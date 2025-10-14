"""Extended Kademlia server providing RPC data/file helpers."""

from __future__ import annotations

import logging
import time
from collections import deque
from typing import Any, Deque, Dict, Optional, Tuple

import asyncio

from kademlia.network import Server
from kademliaExtend import KademliaExtend
from nat_utils import detect_nat_info

log = logging.getLogger(__name__)


class ExtendedServer(Server):
    """Server subclass tích hợp các RPC gửi dữ liệu/file."""

    protocol_class = KademliaExtend

    def __init__(self, *args, **kwargs):
        self._auto_detect_nat = kwargs.pop("auto_detect_nat", False)
        self._nat_options = kwargs.pop("nat_options", {}) or {}
        super().__init__(*args, **kwargs)
        self._incoming_transfers: Dict[str, Dict[str, Any]] = {}
        self._completed_transfers: Dict[str, Dict[str, Any]] = {}
        self._recent_payloads: Deque[Tuple[float, Any, Any]] = deque(maxlen=100)
        self._relay_manager = None
        self._nat_task: Optional[asyncio.Task] = None

    def _create_protocol(self):
        protocol = self.protocol_class(self.node, self.storage, self.ksize)
        attach = getattr(protocol, "attach_server", None)
        if callable(attach):
            attach(self)
        if self._relay_manager is not None:
            protocol.attach_relay_manager(self._relay_manager)
        return protocol

    def attach_relay_manager(self, manager):
        """Gắn RelayManager để dùng relay WebSocket."""
        self._relay_manager = manager
        if self.protocol is not None:
            self.protocol.attach_relay_manager(manager)

    async def listen(self, port, interface="0.0.0.0"):
        await super().listen(port, interface)
        if self._auto_detect_nat:
            self.schedule_nat_detection()

    def schedule_nat_detection(self):
        if self._nat_task and not self._nat_task.done():
            return
        loop = asyncio.get_event_loop()
        self._nat_task = loop.create_task(self.update_local_nat(**self._nat_options))

    async def update_local_nat(
        self,
        *,
        stun_host: Optional[str] = None,
        stun_port: Optional[int] = None,
        source_ip: Optional[str] = None,
        source_port: int = 54320,
    ) -> Optional[Dict[str, Any]]:
        try:
            metadata = await detect_nat_info(
                stun_host=stun_host,
                stun_port=stun_port,
                source_ip=source_ip,
                source_port=source_port,
            )
        except Exception:
            log.warning("Không thể xác định NAT cho node hiện tại")
            return None

        self.node.update_meta(meta=metadata)
        if self.protocol:
            self.protocol.source_node.update_meta(meta=metadata)
        log.info("NAT metadata cập nhật: %s", metadata)
        return metadata

    # ------------------------------------------------------------------
    # RPC payload handlers

    def handle_incoming_data(self, source, payload):
        """Được KademliaExtend gọi khi nhận payload từ RPC gửi dữ liệu."""
        if isinstance(payload, dict):
            payload_type = payload.get("type")
            if payload_type == "file_manifest":
                self._handle_file_manifest(source, payload)
                return {"ok": True}
            if payload_type == "file_chunk":
                self._handle_file_chunk(source, payload)
                return {"ok": True}
            if payload_type == "file_complete":
                self._handle_file_complete(source, payload)
                return {"ok": True}

        self._recent_payloads.append((time.time(), source, payload))
        log.info("Received payload from %s: %r", source, payload)
        return {"ok": True}

    def _transfer_entry(self, transfer_id, source):
        entry = self._incoming_transfers.get(transfer_id)
        if entry is None:
            entry = {
                "source": source,
                "manifest": None,
                "chunks": {},
                "received_bytes": 0,
                "created": time.time(),
            }
            self._incoming_transfers[transfer_id] = entry
        else:
            entry["source"] = source
        return entry

    def _handle_file_manifest(self, source, payload):
        transfer_id = payload.get("transfer_id")
        total = payload.get("chunks")
        filename = payload.get("filename")
        if not transfer_id or total is None:
            log.warning("manifest missing fields from %s: %r", source, payload)
            return
        entry = self._transfer_entry(transfer_id, source)
        entry["manifest"] = dict(payload)
        entry["chunks"].clear()
        entry["received_bytes"] = 0
        entry["updated"] = time.time()
        log.info(
            "Manifest received for transfer %s from %s (%s, %d chunk(s))",
            transfer_id,
            source,
            filename,
            total,
        )

    def _handle_file_chunk(self, source, payload):
        transfer_id = payload.get("transfer_id")
        index = payload.get("index")
        data = payload.get("data")
        if transfer_id is None or index is None or data is None:
            log.warning("chunk missing fields from %s: %r", source, payload)
            return
        if isinstance(data, str):
            data = data.encode("utf-8")
        elif isinstance(data, bytearray):
            data = bytes(data)
        elif not isinstance(data, bytes):
            log.warning(
                "unsupported chunk payload type (%s) from %s",
                type(data),
                source,
            )
            return

        entry = self._transfer_entry(transfer_id, source)
        manifest = entry.get("manifest")
        expected_chunks = manifest.get("chunks") if manifest else None
        if expected_chunks is not None and (index < 0 or index >= expected_chunks):
            log.warning(
                "chunk index %d out of range for transfer %s (expected %d)",
                index,
                transfer_id,
                expected_chunks,
            )
            return

        entry["chunks"][index] = data
        entry["received_bytes"] += len(data)
        entry["updated"] = time.time()
        log.debug(
            "Received chunk %d (size %d) for transfer %s from %s",
            index,
            len(data),
            transfer_id,
            source,
        )

    def _handle_file_complete(self, source, payload):
        transfer_id = payload.get("transfer_id")
        if not transfer_id:
            log.warning("completion missing transfer id from %s: %r", source, payload)
            return
        entry = self._incoming_transfers.get(transfer_id)
        if not entry:
            log.warning(
                "completion received for unknown transfer %s from %s",
                transfer_id,
                source,
            )
            return

        manifest = entry.get("manifest")
        if not manifest:
            log.warning(
                "completion received without manifest for transfer %s from %s",
                transfer_id,
                source,
            )
            return

        total_chunks = manifest.get("chunks", 0)
        missing = [i for i in range(total_chunks) if i not in entry["chunks"]]
        if missing:
            log.warning(
                "transfer %s missing %d chunk(s): %s",
                transfer_id,
                len(missing),
                missing[:5],
            )
            return

        data = b"".join(entry["chunks"][i] for i in range(total_chunks))
        record = {
            "source": entry["source"],
            "manifest": manifest,
            "data": data,
            "completed": time.time(),
        }
        self._incoming_transfers.pop(transfer_id, None)
        self._completed_transfers[transfer_id] = record
        log.info(
            "Transfer %s completed from %s: %s (%d bytes)",
            transfer_id,
            source,
            manifest.get("filename"),
            len(data),
        )
        self.on_file_received(transfer_id, record["source"], manifest, data)

    # ------------------------------------------------------------------
    # Hooks và tiện ích cho ứng dụng

    def on_file_received(self, transfer_id, source, manifest, data):
        """Hook để ứng dụng override xử lý file sau khi nhận xong."""
        log.info(
            "File '%s' (transfer %s, %d bytes) received from %s",
            manifest.get("filename"),
            transfer_id,
            manifest.get("size"),
            source,
        )

    def pop_completed_transfer(self, transfer_id):
        """Trả về dữ liệu file đã nhận (và xóa khỏi bộ đệm)."""
        return self._completed_transfers.pop(transfer_id, None)
