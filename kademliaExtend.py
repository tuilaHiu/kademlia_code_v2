import asyncio
import json
import logging
import math
import os
import uuid
from base64 import b64encode
from hashlib import sha1
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, Optional, Tuple, Callable

import umsgpack
import websockets
from rpcudp.exceptions import MalformedMessage

from kademlia.network import Server
from kademlia.node import Node
from kademlia.protocol import KademliaProtocol

from relay_manager import RelayManager

MAX_RPC_PAYLOAD = int(os.getenv("KAD_RPC_MAX_PAYLOAD", "4096"))

log = logging.getLogger(__name__)


META_KEYS = {
    "relay",
    "relay_uri",
    "relay_endpoints",
    "use_relay",
    "behind_nat",
    "nat",
    "node_id",
}


class RelayAwareProtocol(KademliaProtocol):
    """
    Mở rộng KademliaProtocol để hỗ trợ gửi/nhận RPC qua WebSocket relay.
    """

    def __init__(
        self,
        source_node: Node,
        storage,
        ksize: int,
        relay_manager: Optional[RelayManager] = None,
    ):
        super().__init__(source_node, storage, ksize)
        self.relay_manager = relay_manager
        self.server = None
        if self.relay_manager:
            self.relay_manager.attach_protocol(self)

    def attach_server(self, server: "RelayAwareServer") -> None:
        self.server = server

    # ------------------------------------------------------------------ #
    # Helpers around metadata and relay detection                        #
    # ------------------------------------------------------------------ #
    def _is_meta(self, value: Any) -> bool:
        return isinstance(value, dict) and any(key in value for key in META_KEYS)

    def _extract_meta(self, args: Tuple[Any, ...]) -> Tuple[Optional[Dict], Optional[Dict]]:
        meta_target = None
        meta_source = None
        if args:
            last = args[-1]
            if self._is_meta(last):
                meta_source = last
            if len(args) >= 2 and self._is_meta(args[-2]):
                meta_target = args[-2]
        return meta_target, meta_source

    def _should_use_relay(self, meta: Optional[Dict]) -> bool:
        if not isinstance(meta, dict):
            return False
        if meta.get("use_relay"):
            return True
        nat_value = meta.get("nat")
        if nat_value and nat_value != "Open Internet":
            return True
        if meta.get("behind_nat"):
            return True
        if meta.get("relay") or meta.get("relay_uri") or meta.get("relay_endpoints"):
            return True
        return False

    def _ensure_node_meta(self, node: Node, meta: Optional[Dict]) -> Node:
        if meta is not None:
            setattr(node, "meta", meta)
        return node

    # ------------------------------------------------------------------ #
    # Relay datagram handling                                            #
    # ------------------------------------------------------------------ #
    def receive_relay_message(self, data: bytes, addr: Tuple[str, int]) -> None:
        """
        Hàm nhận dữ liệu raw từ relay và đẩy vào _solve_datagram như UDP.
        """
        asyncio.ensure_future(self._solve_datagram(data, addr))

    async def send_relay_response(self, msg_id: bytes, txdata: bytes, meta: Optional[Dict]) -> bool:
        if not self.server:
            return False
        if not self._should_use_relay(meta):
            return False
        try:
            return await self.server.send_relay_response(msg_id, txdata)
        except Exception:
            log.exception("[RelayAwareProtocol] send_relay_response failed")
            return False

    # ------------------------------------------------------------------ #
    # Overrides of RPCProtocol                                           #
    # ------------------------------------------------------------------ #
    def __getattr__(self, name):
        if name.startswith("_") or name.startswith("rpc_"):
            return getattr(super(), name)

        try:
            return getattr(super(), name)
        except AttributeError:
            pass

        def func(address, *args):
            msg_id = sha1(os.urandom(32)).digest()
            data = umsgpack.packb([name, args])
            if len(data) > 8192:
                raise MalformedMessage(
                    "Total length of function name and arguments cannot exceed 8K"
                )
            txdata = b"\x00" + msg_id + data

            meta_target, meta_source = self._extract_meta(args)
            if meta_source is not None:
                setattr(self.source_node, "meta", meta_source)

            use_relay = self._should_use_relay(meta_target) and self.server is not None

            if use_relay:
                if not self.server or not self.server.has_relay():
                    log.warning(
                        "[RelayAwareProtocol] Relay requested for %s but no relay manager configured",
                        name,
                    )
                else:
                    loop = asyncio.get_event_loop()
                    if hasattr(loop, "create_future"):
                        outer = loop.create_future()
                    else:
                        outer = asyncio.Future()

                    relay_task = asyncio.ensure_future(
                        self.server.sendto_via_relay(meta_target, txdata)
                    )

                    def _relay_done(task):
                        if outer.done():
                            return
                        if task.cancelled():
                            outer.cancel()
                            return
                        exc = task.exception()
                        if exc:
                            outer.set_exception(exc)
                            return
                        result = task.result()
                        if result is None:
                            outer.set_result((False, None))
                        else:
                            outer.set_result(result)

                    relay_task.add_done_callback(_relay_done)
                    return outer

            loop = asyncio.get_event_loop()
            if hasattr(loop, "create_future"):
                future = loop.create_future()
            else:
                future = asyncio.Future()
            timeout = loop.call_later(self._wait_timeout, self._timeout, msg_id)
            self._outstanding[msg_id] = (future, timeout)
            self.transport.sendto(txdata, address)
            return future

        return func

    async def _accept_request(self, msg_id, data, address):
        if not isinstance(data, list) or len(data) != 2:
            raise MalformedMessage(f"Could not read packet: {data}")
        funcname, args = data
        func = getattr(self, f"rpc_{funcname}", None)
        if func is None or not callable(func):
            msgargs = (self.__class__.__name__, funcname)
            log.warning("%s has no callable method rpc_%s; ignoring request", *msgargs)
            return

        meta_target, meta_source = self._extract_meta(args)

        if not asyncio.iscoroutinefunction(func):
            response = func(address, *args)
        else:
            response = await func(address, *args)
        log.debug(
            "sending response %s for msg id %s to %s",
            response,
            b64encode(msg_id),
            address,
        )
        txdata = b"\x01" + msg_id + umsgpack.packb(response)

        sent = False
        if self.server and self.server.has_relay():
            sent = await self.send_relay_response(msg_id, txdata, meta_source)

        if not sent:
            self.transport.sendto(txdata, address)

    # ------------------------------------------------------------------ #
    # RPC overrides to propagate metadata                                #
    # ------------------------------------------------------------------ #
    def rpc_ping(self, sender, nodeid, meta_target=None, meta_source=None):
        source_meta = meta_source if meta_source is not None else meta_target
        source = self._ensure_node_meta(Node(nodeid, sender[0], sender[1]), source_meta)
        self.welcome_if_new(source)
        return self.source_node.id

    def rpc_store(self, sender, nodeid, key, value, meta_target=None, meta_source=None):
        source_meta = meta_source if meta_source is not None else meta_target
        source = self._ensure_node_meta(Node(nodeid, sender[0], sender[1]), source_meta)
        self.welcome_if_new(source)
        log.debug(
            "got a store request from %s, storing '%s'='%s'", sender, key.hex(), value
        )
        self.storage[key] = value
        return True

    def rpc_find_node(self, sender, nodeid, key, meta_target=None, meta_source=None):
        log.info("finding neighbors of %i in local table", int(nodeid.hex(), 16))
        source_meta = meta_source if meta_source is not None else meta_target
        source = self._ensure_node_meta(Node(nodeid, sender[0], sender[1]), source_meta)
        self.welcome_if_new(source)
        node = Node(key)
        neighbors = self.router.find_neighbors(node, exclude=source)
        return list(map(tuple, neighbors))

    def rpc_find_value(self, sender, nodeid, key, meta_target=None, meta_source=None):
        source_meta = meta_source if meta_source is not None else meta_target
        source = self._ensure_node_meta(Node(nodeid, sender[0], sender[1]), source_meta)
        self.welcome_if_new(source)
        value = self.storage.get(key, None)
        if value is None:
            return self.rpc_find_node(sender, nodeid, key, meta_target, meta_source)
        return {"value": value}

    async def rpc_send_data(self, sender, nodeid, payload, meta_target=None, meta_source=None):
        source_meta = meta_source if meta_source is not None else meta_target
        source = self._ensure_node_meta(Node(nodeid, sender[0], sender[1]), source_meta)
        self.welcome_if_new(source)
        if self.server:
            await self.server.handle_incoming_data(source, payload)
        return {"status": "ok"}

    # ------------------------------------------------------------------ #
    # Call overrides to append metadata                                  #
    # ------------------------------------------------------------------ #
    async def call_find_node(self, node_to_ask, node_to_find):
        address = (node_to_ask.ip, node_to_ask.port)
        meta_target = getattr(node_to_ask, "meta", None)
        meta_source = getattr(self.source_node, "meta", None)
        result = await self.find_node(
            address, self.source_node.id, node_to_find.id, meta_target, meta_source
        )
        return self.handle_call_response(result, node_to_ask)

    async def call_find_value(self, node_to_ask, node_to_find):
        address = (node_to_ask.ip, node_to_ask.port)
        meta_target = getattr(node_to_ask, "meta", None)
        meta_source = getattr(self.source_node, "meta", None)
        result = await self.find_value(
            address, self.source_node.id, node_to_find.id, meta_target, meta_source
        )
        return self.handle_call_response(result, node_to_ask)

    async def call_ping(self, node_to_ask):
        address = (node_to_ask.ip, node_to_ask.port)
        meta_target = getattr(node_to_ask, "meta", None)
        meta_source = getattr(self.source_node, "meta", None)
        result = await self.ping(address, self.source_node.id, meta_target, meta_source)
        return self.handle_call_response(result, node_to_ask)

    async def call_store(self, node_to_ask, key, value):
        address = (node_to_ask.ip, node_to_ask.port)
        meta_target = getattr(node_to_ask, "meta", None)
        meta_source = getattr(self.source_node, "meta", None)
        result = await self.store(
            address, self.source_node.id, key, value, meta_target, meta_source
        )
        return self.handle_call_response(result, node_to_ask)

    async def call_send_data(self, node_to_ask, payload):
        address = (node_to_ask.ip, node_to_ask.port)
        meta_target = getattr(node_to_ask, "meta", None)
        meta_source = getattr(self.source_node, "meta", None)
        result = await self.send_data(
            address, self.source_node.id, payload, meta_target, meta_source
        )
        return self.handle_call_response(result, node_to_ask)


class RelayAwareServer(Server):
    """
    Mở rộng Server để chạy song song listener UDP và listener WebSocket relay.
    """

    protocol_class = RelayAwareProtocol

    def __init__(
        self,
        *args,
        relay_manager: Optional[RelayManager] = None,
        relay_port: Optional[int] = None,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)
        self.relay_manager = relay_manager
        self.relay_port = relay_port or 8765
        self.relay_clients: Dict[Tuple[str, int], websockets.WebSocketServerProtocol] = {}
        self._relay_listener = None
        self.data_handler: Optional[Callable[[Node, Any], Any]] = None
        self.file_handler: Optional[Callable[[Node, str, bytes, str], Any]] = None
        self._incoming_files: Dict[Tuple[int, str], Dict[str, Any]] = {}
        self.received_dir = Path("received_files")
        try:
            self.received_dir.mkdir(exist_ok=True)
        except Exception:
            log.exception("[RelayAwareServer] Could not ensure received_files directory")

    def has_relay(self) -> bool:
        return self.relay_manager is not None

    def _create_protocol(self):
        protocol = self.protocol_class(
            self.node,
            self.storage,
            self.ksize,
            relay_manager=self.relay_manager,
        )
        protocol.attach_server(self)
        return protocol

    async def listen(self, port, interface="0.0.0.0"):
        await super().listen(port, interface)
        if self.relay_manager:
            await self.start_relay_listener()

    async def start_relay_listener(self):
        """
        Lắng nghe WebSocket relay đồng thời với UDP listener.
        """
        if self.relay_manager:
            try:
                await self.relay_manager.connect()
                log.info(
                    "[RelayAwareServer] Relay manager connected for node %s",
                    self.node.long_id,
                )
            except Exception:
                log.exception(
                    "[RelayAwareServer] Failed to connect relay manager for node %s",
                    self.node.long_id,
                )
            # Nếu đã có relay manager kết nối tới server bên ngoài thì không cần
            # mở thêm WebSocket listener cục bộ.
            return

        if self._relay_listener:
            return

        async def handler(ws):
            try:
                init_msg = await ws.recv()
                info = json.loads(init_msg)
                node_id = info.get("node_id")
                log.info("[RelayWS] Node %s connected", node_id)
                async for message in ws:
                    try:
                        pkt = json.loads(message)
                        addr_data = pkt.get("from")
                        payload = pkt.get("data")
                        if not addr_data or payload is None:
                            continue
                        addr = (addr_data[0], int(addr_data[1]))
                        self.relay_clients[addr] = ws
                        if isinstance(payload, str):
                            try:
                                data_bytes = bytes.fromhex(payload)
                            except ValueError:
                                log.warning("[RelayWS] Invalid hex payload from %s", addr)
                                continue
                        else:
                            data_bytes = bytes(payload)
                        self.protocol.receive_relay_message(data_bytes, addr)
                    except Exception as exc:
                        log.exception("[RelayWS] Error processing message: %s", exc)
            finally:
                log.info("[RelayWS] Closed")

        self._relay_listener = await websockets.serve(
            handler, "0.0.0.0", self.relay_port
        )
        log.info(
            "[RelayWS] Listening on %s:%d",
            "0.0.0.0",
            self.relay_port,
        )

    def register_data_handler(self, handler: Callable[[Node, Any], Any]) -> None:
        self.data_handler = handler

    def register_file_handler(self, handler: Callable[[Node, str, bytes, str], Any]) -> None:
        self.file_handler = handler

    async def handle_incoming_data(self, source_node: Node, payload: Any) -> None:
        if isinstance(payload, dict) and payload.get("type") == "file_chunk":
            await self._handle_file_chunk(source_node, payload)
            return
        if self.data_handler is None:
            log.info("[RelayAwareServer] Received data from %s: %r", source_node, payload)
            return
        await self._invoke_handler(self.data_handler, source_node, payload)

    async def _invoke_handler(self, handler: Callable, *args) -> None:
        if handler is None:
            return
        try:
            result = handler(*args)
            if asyncio.iscoroutine(result):
                await result
        except Exception:
            log.exception("[RelayAwareServer] Handler raised an exception")

    async def _handle_file_chunk(self, source_node: Node, payload: Dict[str, Any]) -> None:
        transfer_id = payload.get("transfer_id")
        file_name = payload.get("file_name")
        chunk_index = payload.get("chunk_index")
        total_chunks = payload.get("total_chunks")
        data = payload.get("data")
        if None in (transfer_id, file_name, chunk_index, total_chunks, data):
            log.warning("[RelayAwareServer] Incomplete file chunk metadata: %s", payload)
            return
        try:
            chunk_index = int(chunk_index)
            total_chunks = int(total_chunks)
        except (TypeError, ValueError):
            log.warning("[RelayAwareServer] Invalid chunk indices in payload: %s", payload)
            return
        data_bytes = bytes(data)
        key = (source_node.long_id, str(transfer_id))
        entry = self._incoming_files.setdefault(
            key,
            {
                "file_name": file_name,
                "total": total_chunks,
                "chunks": {},
            },
        )
        entry["chunks"][chunk_index] = data_bytes
        if len(entry["chunks"]) == entry["total"] and all(
            i in entry["chunks"] for i in range(entry["total"])
        ):
            ordered = [entry["chunks"][i] for i in range(entry["total"])]
            file_bytes = b"".join(ordered)
            await self._finalize_file(source_node, file_name, file_bytes, str(transfer_id))
            self._incoming_files.pop(key, None)

    async def _finalize_file(
        self, source_node: Node, file_name: str, file_bytes: bytes, transfer_id: str
    ) -> None:
        if self.file_handler:
            await self._invoke_handler(
                self.file_handler, source_node, file_name, file_bytes, transfer_id
            )
            return
        target_path = self._unique_received_path(file_name)
        try:
            target_path.write_bytes(file_bytes)
            log.info(
                "[RelayAwareServer] Stored file '%s' from %s to %s",
                file_name,
                source_node,
                target_path,
            )
        except Exception:
            log.exception("[RelayAwareServer] Failed saving file chunk result")

    def _unique_received_path(self, file_name: str) -> Path:
        base = self.received_dir / file_name
        if not base.exists():
            return base
        stem = base.stem
        suffix = base.suffix
        counter = 1
        while True:
            candidate = base.with_name(f"{stem}_{counter}{suffix}")
            if not candidate.exists():
                return candidate
            counter += 1

    async def send_data(self, node: Node, payload: Any):
        if not isinstance(node, Node):
            raise TypeError("node must be an instance of kademlia.node.Node")
        return await self.protocol.call_send_data(node, payload)

    async def send_file(
        self,
        node: Node,
        file_path: os.PathLike,
        chunk_size: int = 65536,
        *,
        max_payload: Optional[int] = None,
    ):
        path = Path(file_path)
        if not path.is_file():
            raise FileNotFoundError(f"File not found: {path}")
        payload_cap = max_payload if isinstance(max_payload, int) and max_payload > 0 else MAX_RPC_PAYLOAD
        safe_chunk_size = max(1, min(chunk_size, payload_cap))
        total_chunks = max(1, math.ceil(path.stat().st_size / safe_chunk_size))
        transfer_id = str(uuid.uuid4())
        with path.open("rb") as handle:
            for index in range(total_chunks):
                chunk = handle.read(safe_chunk_size)
                if chunk is None:
                    chunk = b""
                payload = {
                    "type": "file_chunk",
                    "file_name": path.name,
                    "chunk_index": index,
                    "total_chunks": total_chunks,
                    "transfer_id": transfer_id,
                    "data": chunk or b"",
                }
                result = await self.send_data(node, payload)
                if not result or not result[0]:
                    raise RuntimeError(
                        f"Failed to send chunk {index} for file {path.name}: {result}"
                    )
        return transfer_id

    async def sendto_via_relay(self, target_meta: Optional[Dict], txdata: bytes):
        """
        Gửi datagram RPC tới node đích qua relay dựa trên metadata.
        """
        if not self.relay_manager:
            raise RuntimeError("Relay manager not configured")
        await self.relay_manager.ensure_connected()

        target_meta = target_meta or {}
        relay_node = SimpleNamespace(meta=target_meta, id=self.node.id)
        result = await self.relay_manager.forward_udp_rpc(relay_node, txdata)
        if result is None:
            return (False, None)
        return result

    async def send_relay_response(self, msg_id: bytes, txdata: bytes) -> bool:
        """
        Gửi phản hồi RPC trở lại node gọi thông qua relay nếu có bản ghi.
        """
        if not self.relay_manager:
            return False
        await self.relay_manager.ensure_connected()
        return await self.relay_manager.send_udp_response(msg_id, txdata)
