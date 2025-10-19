import asyncio
import logging
import math
import os
import uuid
from base64 import b64encode
from hashlib import sha1
from pathlib import Path
from typing import Any, Iterable, Optional, Tuple

import umsgpack

from kademlia.protocol import KademliaProtocol
from kademlia.network import Server
from kademlia.node import Node
from rpcudp.exceptions import MalformedMessage

from relay_manager import RelayManager

log = logging.getLogger(__name__)


# ---------------------------
# Enable Node.meta at runtime
# ---------------------------
def _ensure_node_meta_support():
    if getattr(Node, "_meta_support_enabled", False):
        return

    original_init = Node.__init__

    def __init__(self, node_id, ip=None, port=None, meta=None):
        original_init(self, node_id, ip, port)
        self.meta = dict(meta or {})

    def update_meta(self, meta=None, **kwargs):
        if not hasattr(self, "meta") or self.meta is None:
            self.meta = {}
        if isinstance(meta, dict):
            for key, value in meta.items():
                if value is not None:
                    self.meta[key] = value
        for key, value in kwargs.items():
            if value is not None:
                self.meta[key] = value

    Node.__init__ = __init__
    Node.update_meta = update_meta
    Node._meta_support_enabled = True


_ensure_node_meta_support()


class RelayAwareMixin:
    """
    Mixin cho phép chuyển hướng RPC qua RELAY theo hướng FORWARD NGUYÊN DATAGRAM UDP.

    Cơ chế:
    - Chặn __getattr__ để bọc RPC closure gốc.
    - Nếu phát hiện hint dùng relay → tự gói datagram y hệt RPCProtocol:
        txdata = b"\\x00" + msg_id + umsgpack.packb([name, args])
      rồi gửi nguyên txdata qua relay_manager.forward_udp_rpc(...).
    - Nếu relay trả lời None / thất bại → fallback: gọi closure gốc (UDP).
    - Nếu không có hint relay → chạy UDP như bình thường.

    YÊU CẦU relay_manager:
        await relay_manager.forward_udp_rpc(
            node: Node,                   # node đích (có ip/port/meta)
            datagram: bytes,              # datagram UDP đã pack sẵn
            timeout: float,               # timeout giây
        ) -> Tuple[bool, Any]            # (ok, data) tương tự RPC gốc
    """

    _RELAY_HINT_KEY = "__relay_hint__"

    # -------- Helper packing giống hệt RPCProtocol --------
    @staticmethod
    def _pack_rpc_udp_call(name: str, args: tuple) -> Tuple[bytes, bytes]:
        """
        Trả về (msg_id, txdata) theo đúng format UDP của RPCProtocol:
            txdata = b"\\x00" + msg_id + umsgpack.packb([name, args])
        """
        msg_id = sha1(os.urandom(32)).digest()
        data = umsgpack.packb([name, args])
        if len(data) > 8192:
            raise MalformedMessage(
                "Total length of function name and arguments cannot exceed 8K"
            )
        txdata = b"\x00" + msg_id + data
        return msg_id, txdata

    async def _forward_via_relay_raw(self, name: str, node: Node, args: tuple, timeout: float):
        """
        Gửi NGUYÊN DATAGRAM UDP qua relay_manager với timeout.
        Trả về (ok, data) như RPC gốc.
        """
        manager = getattr(self, "_relay_manager", None)
        if manager is None:
            return None

        # Đóng gói y hệt RPCProtocol trước khi chuyển cho relay
        msg_id, txdata = self._pack_rpc_udp_call(name, args)
        log.debug(
            "[RELAY] forward udp rpc '%s' to %s (msgid %s) via relay",
            name,
            node,
            b64encode(msg_id),
        )
        try:
            if hasattr(manager, "ensure_connected"):
                await manager.ensure_connected()
            return await manager.forward_udp_rpc(node, txdata, timeout=timeout)
        except Exception:
            log.exception(
                "relay manager chuyển tiếp %s thất bại, sẽ fallback UDP trực tiếp cho %s",
                name,
                node,
            )
            return None

    def __getattr__(self, name):
        """
        Bọc RPC call:
        - Nếu không có relay hint → gọi RPC closure gốc (UDP).
        - Nếu có relay hint → forward nguyên datagram UDP qua relay_manager.
        - Relay fail → fallback gọi UDP.
        """
        attr = super().__getattr__(name)
        if not callable(attr):
            return attr

        def wrapper(address, *args):
            # Tách hint relay nếu có
            hint = None
            base_args = args
            if args and isinstance(args[-1], dict) and self._RELAY_HINT_KEY in args[-1]:
                hint = args[-1][self._RELAY_HINT_KEY]
                base_args = args[:-1]

            # Không có hint → chạy UDP gốc
            if not hint or not hint.get("use_relay"):
                return attr(address, *base_args)

            # Có hint → cố gắng forward datagram qua relay
            node = hint.get("node")
            if node is None:
                # Thiếu node để forward → quay về UDP
                return attr(address, *base_args)

            # Tính timeout dựa trên _wait_timeout của RPCProtocol nếu có
            timeout = getattr(self, "_wait_timeout", 5.0)

            async def relay_or_udp():
                relay_result = await self._forward_via_relay_raw(
                    name=name, node=node, args=base_args, timeout=timeout
                )
                if relay_result is not None:
                    return relay_result
                # Fallback: UDP gốc
                return await attr(address, *base_args)

            return asyncio.ensure_future(relay_or_udp())

        return wrapper


class KademliaExtend(RelayAwareMixin, KademliaProtocol):
    """Extended protocol with helper RPCs; RELAY = forward nguyên datagram UDP nếu node NAT."""

    def __init__(self, source_node, storage, ksize):
        super().__init__(source_node, storage, ksize)
        if not hasattr(self.source_node, "meta") or self.source_node.meta is None:
            self.source_node.meta = {}
        self._server = None
        self._relay_manager = None

    def attach_server(self, server) -> None:
        self._server = server

    def attach_relay_manager(self, manager) -> None:
        """
        Gắn relay manager từ bên ngoài. Manager phải cung cấp API:
            await forward_udp_rpc(node, datagram: bytes, timeout: float) -> (ok, data)
        """
        self._relay_manager = manager
        if self._relay_manager and hasattr(self._relay_manager, "attach_protocol"):
            self._relay_manager.attach_protocol(self)

    # ---------- Meta helpers ----------
    def _update_local_meta(self, meta):
        if isinstance(meta, dict) and meta:
            self.source_node.update_meta(meta=meta)

    @staticmethod
    def _normalize_sender_meta(_sender, source_meta):
        return dict(source_meta or {})

    @staticmethod
    def _address_for_node(node):
        if node is None:
            return None
        ip = getattr(node, "ip", None)
        port = getattr(node, "port", None)
        if ip is None or port is None:
            return None
        return (ip, port)

    @staticmethod
    def _prefers_relay(node) -> bool:
        meta = getattr(node, "meta", None) or {}
        return bool(meta.get("use_relay") or meta.get("is_nat"))

    @staticmethod
    def _force_relay(node) -> bool:
        meta = getattr(node, "meta", None) or {}
        return bool(meta.get("force_relay"))

    @staticmethod
    def _rpc_result_ok(result) -> bool:
        return isinstance(result, tuple) and len(result) >= 1 and bool(result[0])

    @staticmethod
    def _meta_payload(node):
        if hasattr(node, "meta") and isinstance(node.meta, dict):
            return dict(node.meta)
        return {}

    @staticmethod
    def _senddata_successful(result):
        return (
            isinstance(result, tuple)
            and len(result) >= 2
            and result[0]
            and isinstance(result[1], dict)
            and result[1].get("ok", False)
        )

    # ---------- RPC overrides with meta ----------
    def rpc_ping(self, sender, nodeid, target_meta=None, source_meta=None):
        self._update_local_meta(target_meta)
        source = Node(
            nodeid,
            sender[0],
            sender[1],
            self._normalize_sender_meta(sender, source_meta),
        )
        self.welcome_if_new(source)
        return {
            "node_id": self.source_node.id,
            "meta": self._meta_payload(self.source_node),
        }

    async def _send_rpc(self, method, node, *args):
        """
        Gọi RPC theo cơ chế:
        - Nếu node nên dùng relay → chèn relay hint để __getattr__ ở mixin forward datagram.
        - Nếu không → gọi trực tiếp UDP như mặc định.
        """
        address = self._address_for_node(node)
        if address is None:
            raise ValueError("Cannot resolve address for node")

        rpc = getattr(self, method)
        prefers_relay = self._prefers_relay(node)
        force_relay = self._force_relay(node)

        async def call_via_relay():
            relay_args = list(args)
            relay_args.append(
                {self._RELAY_HINT_KEY: {"use_relay": True, "node": node}}
            )
            return await rpc(address, *relay_args)

        # Force relay -> skip UDP attempt
        if force_relay:
            return await call_via_relay()

        # Try UDP first
        udp_exception = None
        try:
            result = await rpc(address, *args)
        except Exception as exc:  # pragma: no cover - defensive
            udp_exception = exc
            result = None
        if self._rpc_result_ok(result):
            return result
        if not prefers_relay or self._relay_manager is None:
            if udp_exception:
                raise udp_exception
            return result

        # UDP failed; fall back to relay if available
        try:
            relay_result = await call_via_relay()
        except Exception:
            if udp_exception:
                raise udp_exception
            raise
        if relay_result is not None:
            return relay_result
        if udp_exception:
            raise udp_exception
        return result

    async def call_ping(self, node_to_ask):
        target_meta = self._meta_payload(node_to_ask)
        source_meta = self._meta_payload(self.source_node)
        result = await self._send_rpc(
            "ping",
            node_to_ask,
            self.source_node.id,
            target_meta,
            source_meta,
        )
        if result[0] and isinstance(result[1], dict):
            payload = result[1]
            if hasattr(node_to_ask, "update_meta"):
                node_to_ask.update_meta(meta=payload.get("meta"))
            node_id = payload.get("node_id", node_to_ask.id)
            result = (result[0], node_id)
        return self.handle_call_response(result, node_to_ask)

    def rpc_store(self, sender, nodeid, key, value, target_meta=None, source_meta=None):
        self._update_local_meta(target_meta)
        source = Node(
            nodeid,
            sender[0],
            sender[1],
            self._normalize_sender_meta(sender, source_meta),
        )
        self.welcome_if_new(source)
        log.debug(
            "got a store request from %s, storing '%s'='%s'", sender, key.hex(), value
        )
        self.storage[key] = value
        return {"ok": True, "meta": self._meta_payload(self.source_node)}

    async def call_store(self, node_to_ask, key, value):
        result = await self._send_rpc(
            "store",
            node_to_ask,
            self.source_node.id,
            key,
            value,
            self._meta_payload(node_to_ask),
            self._meta_payload(self.source_node),
        )
        if result[0] and isinstance(result[1], dict):
            payload = result[1]
            if hasattr(node_to_ask, "update_meta"):
                node_to_ask.update_meta(meta=payload.get("meta"))
            result = (result[0], payload.get("ok", True))
        return self.handle_call_response(result, node_to_ask)

    def rpc_find_node(self, sender, nodeid, key, target_meta=None, source_meta=None):
        log.info("finding neighbors of %i in local table", int(nodeid.hex(), 16))
        self._update_local_meta(target_meta)
        source = Node(
            nodeid,
            sender[0],
            sender[1],
            self._normalize_sender_meta(sender, source_meta),
        )
        self.welcome_if_new(source)
        node = Node(key)
        neighbors_payload = []
        for neighbor in self.router.find_neighbors(node, exclude=source):
            entry = {
                "node_id": neighbor.id,
                "address": tuple(neighbor),
            }
            meta = getattr(neighbor, "meta", None)
            if isinstance(meta, dict) and meta:
                entry["meta"] = dict(meta)
            neighbors_payload.append(entry)
        return {"nodes": neighbors_payload, "meta": self._meta_payload(self.source_node)}

    async def call_find_node(self, node_to_ask, node_to_find):
        result = await self._send_rpc(
            "find_node",
            node_to_ask,
            self.source_node.id,
            node_to_find.id,
            self._meta_payload(node_to_ask),
            self._meta_payload(self.source_node),
        )
        if result[0] and isinstance(result[1], dict):
            payload = result[1]
            meta = payload.get("meta")
            if meta and hasattr(node_to_ask, "update_meta"):
                node_to_ask.update_meta(meta=meta)
            neighbors_payload = payload.get("nodes")
            if neighbors_payload is not None:
                normalized_neighbors = []
                if isinstance(neighbors_payload, list):
                    for entry in neighbors_payload:
                        if isinstance(entry, dict):
                            address = entry.get("address")
                            if isinstance(address, (list, tuple)) and len(address) >= 3:
                                normalized_neighbors.append(tuple(address))
                            elif "node_id" in entry:
                                normalized_neighbors.append(
                                    (entry["node_id"], entry.get("ip"), entry.get("port"))
                                )
                        else:
                            normalized_neighbors.append(entry)
                else:
                    normalized_neighbors = neighbors_payload
                result = (result[0], normalized_neighbors)
        return self.handle_call_response(result, node_to_ask)

    def rpc_find_value(self, sender, nodeid, key, target_meta=None, source_meta=None):
        self._update_local_meta(target_meta)
        source = Node(
            nodeid,
            sender[0],
            sender[1],
            self._normalize_sender_meta(sender, source_meta),
        )
        self.welcome_if_new(source)
        value = self.storage.get(key, None)
        if value is None:
            result = self.rpc_find_node(
                sender, nodeid, key, target_meta=target_meta, source_meta=source_meta
            )
            if isinstance(result, dict):
                result.setdefault("requested_key", key)
            return result
        return {"value": value, "meta": self._meta_payload(self.source_node)}

    async def call_find_value(self, node_to_ask, node_to_find):
        result = await self._send_rpc(
            "find_value",
            node_to_ask,
            self.source_node.id,
            node_to_find.id,
            self._meta_payload(node_to_ask),
            self._meta_payload(self.source_node),
        )
        if result[0] and isinstance(result[1], dict):
            payload = result[1]
            if hasattr(node_to_ask, "update_meta"):
                node_to_ask.update_meta(meta=payload.get("meta"))
            if "nodes" in payload:
                neighbors_payload = payload.get("nodes") or []
                normalized = []
                if isinstance(neighbors_payload, list):
                    for entry in neighbors_payload:
                        if isinstance(entry, dict):
                            address = entry.get("address")
                            if isinstance(address, (list, tuple)) and len(address) >= 3:
                                normalized.append(tuple(address))
                            elif "node_id" in entry:
                                normalized.append(
                                    (entry["node_id"], entry.get("ip"), entry.get("port"))
                                )
                        else:
                            normalized.append(entry)
                else:
                    normalized = neighbors_payload
                payload = {"nodes": normalized, "meta": payload.get("meta")}
                result = (result[0], payload)
        return self.handle_call_response(result, node_to_ask)

    # ---------- Arbitrary payload push ----------
    def rpc_senddata(
        self,
        sender,
        nodeid,
        payload,
        target_meta=None,
        source_meta=None,
    ):
        self._update_local_meta(target_meta)
        source = Node(
            nodeid,
            sender[0],
            sender[1],
            self._normalize_sender_meta(sender, source_meta),
        )
        self.welcome_if_new(source)
        if self._server and hasattr(self._server, "handle_incoming_data"):
            handler = getattr(self._server, "handle_incoming_data")
            try:
                result = handler(source, payload)
                if asyncio.iscoroutine(result):
                    asyncio.ensure_future(result)
            except Exception:  # defensive
                log.exception("error while handling payload from %s", sender)
        else:
            log.debug("received payload from %s: %r", sender, payload)
        return {"ok": True, "meta": self._meta_payload(self.source_node)}

    async def call_senddata(self, node_to_ask, payload):
        result = await self._send_rpc(
            "senddata",
            node_to_ask,
            self.source_node.id,
            payload,
            self._meta_payload(node_to_ask),
            self._meta_payload(self.source_node),
        )
        if result[0] and isinstance(result[1], dict):
            response = result[1]
            if hasattr(node_to_ask, "update_meta"):
                node_to_ask.update_meta(meta=response.get("meta"))
            result = (result[0], response.get("ok", True))
        return self.handle_call_response(result, node_to_ask)

    async def _accept_request(self, msg_id, data, address):
        """
        Ghi đè RPCProtocol._accept_request để hỗ trợ gửi phản hồi qua relay nếu cần.
        """
        if not isinstance(data, list) or len(data) != 2:
            raise MalformedMessage(f"Could not read packet: {data}")
        funcname, args = data
        func = getattr(self, f"rpc_{funcname}", None)
        if func is None or not callable(func):
            log.warning(
                "%s has no callable method rpc_%s; ignoring request",
                self.__class__.__name__,
                funcname,
            )
            return

        try:
            if asyncio.iscoroutinefunction(func):
                response = await func(address, *args)
            else:
                response = func(address, *args)
                if asyncio.iscoroutine(response):
                    response = await response
        except Exception:
            log.exception("Error while handling rpc_%s from %s", funcname, address)
            response = {"ok": False, "error": "internal_error"}

        log.debug(
            "sending response %s for msg id %s to %s",
            response,
            b64encode(msg_id),
            address,
        )
        txdata = b"\x01" + msg_id + umsgpack.packb(response)

        sent_via_relay = False
        if self._relay_manager:
            try:
                sent_via_relay = await self._relay_manager.send_udp_response(msg_id, txdata)
            except Exception:
                log.exception("Failed sending rpc_%s response via relay", funcname)
                sent_via_relay = False

        if not sent_via_relay:
            if not self.transport:
                log.warning("Missing transport to send response for rpc_%s", funcname)
                return
            self.transport.sendto(txdata, address)

    # ---------- File transfer via senddata ----------
    async def rpc_sendfile(
        self,
        sender,
        nodeid,
        file_path,
        chunk_size=4096,
        transfer_id=None,
        target_meta=None,
        source_meta=None,
    ):
        self._update_local_meta(target_meta)
        source = Node(
            nodeid,
            sender[0],
            sender[1],
            self._normalize_sender_meta(sender, source_meta),
        )
        self.welcome_if_new(source)

        try:
            path = Path(file_path).expanduser().resolve()
        except Exception as exc:
            log.warning("rpc_sendfile invalid path from %s: %s", sender, exc)
            return {
                "ok": False,
                "error": "invalid file path",
                "meta": self._meta_payload(self.source_node),
            }

        if not path.is_file():
            log.warning("rpc_sendfile missing file %s from %s", path, sender)
            return {
                "ok": False,
                "error": "file not found",
                "meta": self._meta_payload(self.source_node),
            }

        if chunk_size <= 0:
            log.debug("rpc_sendfile chunk_size <= 0, defaulting to 4096")
            chunk_size = 4096

        # Giữ payload nhỏ để không vượt ~8K khi pack RPC
        max_chunk = 4096
        if chunk_size > max_chunk:
            log.debug(
                "rpc_sendfile reducing chunk_size from %d to %d bytes",
                chunk_size,
                max_chunk,
            )
            chunk_size = max_chunk

        total_size = path.stat().st_size
        total_chunks = max(1, math.ceil(total_size / chunk_size))
        transfer_id = transfer_id or f"sendfile-{uuid.uuid4().hex}"

        destination = self._address_for_node(source) or sender
        if destination is None:
            log.warning("rpc_sendfile cannot resolve destination for %s", source)
            return {
                "ok": False,
                "error": "cannot resolve destination",
                "meta": self._meta_payload(self.source_node),
            }

        sender_meta = self._meta_payload(self.source_node)
        target_payload = self._meta_payload(source)

        manifest = {
            "type": "file_manifest",
            "transfer_id": transfer_id,
            "filename": path.name,
            "size": total_size,
            "chunks": total_chunks,
            "chunk_size": chunk_size,
        }

        manifest_result = await self.senddata(
            destination,
            self.source_node.id,
            manifest,
            target_payload,
            sender_meta,
        )
        if self._senddata_successful(manifest_result):
            response = manifest_result[1]
            if isinstance(response, dict) and "meta" in response:
                source.update_meta(meta=response["meta"])
                target_payload = self._meta_payload(source)
        else:
            log.warning("rpc_sendfile failed to deliver manifest for %s", transfer_id)
            return {
                "ok": False,
                "error": "manifest delivery failed",
                "meta": sender_meta,
            }

        with path.open("rb") as fh:
            for index in range(total_chunks):
                chunk = fh.read(chunk_size)
                if not chunk:
                    break
                payload = {
                    "type": "file_chunk",
                    "transfer_id": transfer_id,
                    "index": index,
                    "total": total_chunks,
                    "data": chunk,
                }
                result = await self.senddata(
                    destination,
                    self.source_node.id,
                    payload,
                    self._meta_payload(source),
                    sender_meta,
                )
                if self._senddata_successful(result):
                    response = result[1]
                    if isinstance(response, dict) and "meta" in response:
                        source.update_meta(meta=response["meta"])
                else:
                    log.warning(
                        "rpc_sendfile failed on chunk %d/%d for %s",
                        index + 1,
                        total_chunks,
                        transfer_id,
                    )
                    return {
                        "ok": False,
                        "error": f"chunk {index} delivery failed",
                        "meta": sender_meta,
                    }

        completion = {
            "type": "file_complete",
            "transfer_id": transfer_id,
        }
        completion_result = await self.senddata(
            destination,
            self.source_node.id,
            completion,
            self._meta_payload(source),
            sender_meta,
        )
        if self._senddata_successful(completion_result):
            response = completion_result[1]
            if isinstance(response, dict) and "meta" in response:
                source.update_meta(meta=response["meta"])
        else:
            log.warning("rpc_sendfile failed to send completion for %s", transfer_id)
            return {
                "ok": False,
                "error": "completion delivery failed",
                "meta": sender_meta,
            }

        log.info(
            "rpc_sendfile sent %d chunk(s) (%d bytes) to %s as transfer %s",
            total_chunks,
            total_size,
            source,
            transfer_id,
        )

        return {
            "ok": True,
            "transfer_id": transfer_id,
            "chunks": total_chunks,
            "size": total_size,
            "meta": sender_meta,
        }

    async def call_sendfile(
        self,
        node_to_ask,
        file_path,
        *,
        chunk_size: int = 4096,
        transfer_id: Optional[str] = None,
    ):
        address = self._address_for_node(node_to_ask)
        if address is None:
            raise ValueError("Cannot resolve address for node")

        try:
            path = Path(file_path).expanduser().resolve()
        except Exception as exc:
            raise ValueError(f"Invalid file path {file_path!r}: {exc}") from exc

        if not path.is_file():
            raise FileNotFoundError(f"File not found: {path}")

        if chunk_size <= 0:
            log.debug("call_sendfile chunk_size <= 0, defaulting to 4096")
            chunk_size = 4096

        max_chunk = 4096
        if chunk_size > max_chunk:
            log.debug(
                "call_sendfile reducing chunk_size from %d to %d bytes",
                chunk_size,
                max_chunk,
            )
            chunk_size = max_chunk

        total_size = path.stat().st_size
        total_chunks = max(1, math.ceil(total_size / chunk_size))
        transfer = transfer_id or f"sendfile-{uuid.uuid4().hex}"

        sender_meta = self._meta_payload(self.source_node)
        target_payload = self._meta_payload(node_to_ask)

        manifest = {
            "type": "file_manifest",
            "transfer_id": transfer,
            "filename": path.name,
            "size": total_size,
            "chunks": total_chunks,
            "chunk_size": chunk_size,
        }

        manifest_result = await self._send_rpc(
            "senddata",
            node_to_ask,
            self.source_node.id,
            manifest,
            target_payload,
            sender_meta,
        )
        if self._senddata_successful(manifest_result):
            response = manifest_result[1]
            if isinstance(response, dict) and "meta" in response:
                if hasattr(node_to_ask, "update_meta"):
                    node_to_ask.update_meta(meta=response["meta"])
                target_payload = self._meta_payload(node_to_ask)
        else:
            log.warning("call_sendfile failed to deliver manifest for %s", transfer)
            result = (
                False,
                {
                    "ok": False,
                    "error": "manifest delivery failed",
                    "meta": sender_meta,
                },
            )
            return self.handle_call_response(result, node_to_ask)

        with path.open("rb") as fh:
            for index in range(total_chunks):
                chunk = fh.read(chunk_size)
                if not chunk:
                    break
                payload = {
                    "type": "file_chunk",
                    "transfer_id": transfer,
                    "index": index,
                    "total": total_chunks,
                    "data": chunk,
                }
                result = await self._send_rpc(
                    "senddata",
                    node_to_ask,
                    self.source_node.id,
                    payload,
                    target_payload,
                    sender_meta,
                )
                if self._senddata_successful(result):
                    response = result[1]
                    if isinstance(response, dict) and "meta" in response:
                        if hasattr(node_to_ask, "update_meta"):
                            node_to_ask.update_meta(meta=response["meta"])
                        target_payload = self._meta_payload(node_to_ask)
                else:
                    log.warning(
                        "call_sendfile failed on chunk %d/%d for %s",
                        index + 1,
                        total_chunks,
                        transfer,
                    )
                    result = (
                        False,
                        {
                            "ok": False,
                            "error": f"chunk {index} delivery failed",
                            "meta": sender_meta,
                        },
                    )
                    return self.handle_call_response(result, node_to_ask)

        completion = {
            "type": "file_complete",
            "transfer_id": transfer,
        }
        completion_result = await self._send_rpc(
            "senddata",
            node_to_ask,
            self.source_node.id,
            completion,
            target_payload,
            sender_meta,
        )
        if self._senddata_successful(completion_result):
            response = completion_result[1]
            if isinstance(response, dict) and "meta" in response:
                if hasattr(node_to_ask, "update_meta"):
                    node_to_ask.update_meta(meta=response["meta"])
        else:
            log.warning(
                "call_sendfile failed to send completion for %s",
                transfer,
            )
            result = (
                False,
                {
                    "ok": False,
                    "error": "completion delivery failed",
                    "meta": sender_meta,
                },
            )
            return self.handle_call_response(result, node_to_ask)

        log.info(
            "call_sendfile sent %d chunk(s) (%d bytes) to %s as transfer %s",
            total_chunks,
            total_size,
            node_to_ask,
            transfer,
        )

        result = (
            True,
            {
                "ok": True,
                "transfer_id": transfer,
                "chunks": total_chunks,
                "size": total_size,
                "meta": sender_meta,
            },
        )
        return self.handle_call_response(result, node_to_ask)


class ExtendedServer(Server):
    """
    Server mở rộng cho phép lắng nghe UDP mặc định của Kademlia đồng thời
    kết nối tới các relay endpoint (WebSocket) để forward gói tin cho node sau NAT.
    """

    protocol_class = KademliaExtend

    def __init__(
        self,
        *args,
        relay_endpoints: Optional[Iterable[str]] = None,
        relay_node_id: Optional[str] = None,
        relay_autoconnect: bool = True,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)
        self.relay_autoconnect = relay_autoconnect
        self.relay_endpoints = self._normalize_relay_endpoints(relay_endpoints)
        self.relay_node_id = relay_node_id or self.node.id.hex()
        self.relay_manager: Optional[RelayManager] = None
        self._relay_lock: Optional[asyncio.Lock] = None
        self._active_relay_uri: Optional[str] = None

    @staticmethod
    def _normalize_relay_endpoints(
        endpoints: Optional[Iterable[str]],
    ) -> list[str]:
        if not endpoints:
            return []
        if isinstance(endpoints, str):
            endpoints_iter = [endpoints]
        else:
            endpoints_iter = list(endpoints)
        normalized = []
        for endpoint in endpoints_iter:
            if isinstance(endpoint, str):
                trimmed = endpoint.strip()
                if trimmed and trimmed not in normalized:
                    normalized.append(trimmed)
        return normalized

    def _create_protocol(self):
        proto = self.protocol_class(self.node, self.storage, self.ksize)
        if isinstance(proto, KademliaExtend):
            proto.attach_server(self)
            if self.relay_manager:
                proto.attach_relay_manager(self.relay_manager)
        return proto

    async def listen(self, port, interface="0.0.0.0"):
        await super().listen(port, interface)
        if isinstance(self.protocol, KademliaExtend):
            self.protocol.attach_server(self)
            if self.relay_manager:
                self.protocol.attach_relay_manager(self.relay_manager)
        if self.relay_autoconnect and self.relay_endpoints:
            await self.connect_relay()

    def _ensure_relay_lock(self) -> asyncio.Lock:
        if self._relay_lock is None:
            self._relay_lock = asyncio.Lock()
        return self._relay_lock

    async def connect_relay(self) -> Optional[RelayManager]:
        """
        Thử kết nối tới một trong các relay endpoint theo thứ tự ưu tiên.
        Thành công → trả về RelayManager, thất bại → None.
        """
        async with self._ensure_relay_lock():
            # Nếu đã kết nối và còn sống → dùng lại.
            if self.relay_manager and getattr(self.relay_manager, "is_connected", lambda: False)():
                return self.relay_manager

            last_error = None
            for uri in self.relay_endpoints:
                manager = RelayManager(self.relay_node_id, uri)
                if isinstance(self.protocol, KademliaExtend):
                    manager.attach_protocol(self.protocol)
                try:
                    await manager.connect()
                except Exception as exc:
                    log.warning("Failed to connect relay endpoint %s: %s", uri, exc)
                    last_error = exc
                    continue

                self.relay_manager = manager
                self._active_relay_uri = uri
                if isinstance(self.protocol, KademliaExtend):
                    self.protocol.attach_relay_manager(manager)
                    self.protocol._update_local_meta(
                        {
                            "use_relay": True,
                            "relay_uri": uri,
                            "node_id": self.relay_node_id,
                        }
                    )
                if hasattr(self.node, "update_meta"):
                    self.node.update_meta(
                        meta={
                            "use_relay": True,
                            "relay_uri": uri,
                            "node_id": self.relay_node_id,
                        }
                    )
                log.info(
                    "ExtendedServer connected to relay %s as %s",
                    uri,
                    self.relay_node_id,
                )
                return manager

            if last_error:
                log.error(
                    "Unable to connect to any relay endpoints %s: %s",
                    self.relay_endpoints,
                    last_error,
                )
            else:
                log.error(
                    "Unable to connect to any relay endpoints %s (no attempt made)",
                    self.relay_endpoints,
                )
            return None

    async def disconnect_relay(self):
        async with self._ensure_relay_lock():
            manager = self.relay_manager
            self.relay_manager = None
            self._active_relay_uri = None
            if isinstance(self.protocol, KademliaExtend):
                self.protocol.attach_relay_manager(None)
                self.protocol._update_local_meta({"use_relay": False})
            if hasattr(self.node, "update_meta"):
                self.node.update_meta(meta={"use_relay": False})
            if manager and getattr(manager, "ws", None):
                try:
                    await manager.ws.close()
                except Exception:
                    pass

    @property
    def active_relay_uri(self) -> Optional[str]:
        return self._active_relay_uri
