import asyncio
import logging
import math
import uuid
from pathlib import Path
from typing import Any, Optional

from kademlia.protocol import KademliaProtocol
from kademlia.node import Node

log = logging.getLogger(__name__)


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


class KademliaExtend(KademliaProtocol):
    """Extended protocol with helper RPCs to push arbitrary payloads."""

    def __init__(self, source_node, storage, ksize):
        super().__init__(source_node, storage, ksize)
        if not hasattr(self.source_node, "meta") or self.source_node.meta is None:
            self.source_node.meta = {}
        self._server = None

    def attach_server(self, server) -> None:
        self._server = server

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

    async def call_ping(self, node_to_ask):
        address = self._address_for_node(node_to_ask)
        result = await self.ping(
            address,
            self.source_node.id,
            self._meta_payload(node_to_ask),
            self._meta_payload(self.source_node),
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
        address = self._address_for_node(node_to_ask)
        result = await self.store(
            address,
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
        neighbors = self.router.find_neighbors(node, exclude=source)
        return list(map(tuple, neighbors))

    async def call_find_node(self, node_to_ask, node_to_find):
        address = self._address_for_node(node_to_ask)
        result = await self.find_node(
            address,
            self.source_node.id,
            node_to_find.id,
            self._meta_payload(node_to_ask),
            self._meta_payload(self.source_node),
        )
        if result[0] and isinstance(result[1], dict) and "meta" in result[1]:
            if hasattr(node_to_ask, "update_meta"):
                node_to_ask.update_meta(meta=result[1]["meta"])
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
            return self.rpc_find_node(sender, nodeid, key)
        return {"value": value, "meta": self._meta_payload(self.source_node)}

    async def call_find_value(self, node_to_ask, node_to_find):
        address = self._address_for_node(node_to_ask)
        result = await self.find_value(
            address,
            self.source_node.id,
            node_to_find.id,
            self._meta_payload(node_to_ask),
            self._meta_payload(self.source_node),
        )
        if result[0] and isinstance(result[1], dict):
            payload = result[1]
            if hasattr(node_to_ask, "update_meta"):
                node_to_ask.update_meta(meta=payload.get("meta"))
        return self.handle_call_response(result, node_to_ask)

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
            except Exception:  # pragma: no cover - defensive
                log.exception("error while handling payload from %s", sender)
        else:
            log.debug("received payload from %s: %r", sender, payload)
        return {"ok": True, "meta": self._meta_payload(self.source_node)}

    async def call_senddata(self, node_to_ask, payload):
        address = self._address_for_node(node_to_ask)
        if address is None:
            raise ValueError("Cannot resolve address for node")
        result = await self.senddata(
            address,
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
        except Exception as exc:  # pragma: no cover - invalid input
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

        # keep chunks small so packed RPC payload stays within ~8K limit
        max_chunk = 4096
        if chunk_size > max_chunk:
            log.debug(
                "rpc_sendfile reducing chunk_size from %d to %d bytes", chunk_size, max_chunk
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

        manifest_result = await self.senddata(
            address,
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
                result = await self.senddata(
                    address,
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
        completion_result = await self.senddata(
            address,
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
