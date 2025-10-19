import asyncio
import logging
import os
from pathlib import Path
from typing import Dict, Optional

from kademliaExtend import ExtendedServer


def _parse_node_id(raw: Optional[str], fallback: str) -> bytes:
    value = (raw or fallback).strip().lower()
    if value.startswith("0x"):
        value = value[2:]
    if len(value) != 40:
        raise ValueError("Node id must be 160-bit (40 hex chars)")
    return bytes.fromhex(value)


class FileReceiverServer(ExtendedServer):
    def __init__(self, *args, download_dir: Optional[str] = None, **kwargs):
        super().__init__(*args, **kwargs)
        base_dir = download_dir or os.getenv("RECEIVE_DIR", "received_files")
        self.download_dir = Path(base_dir).expanduser().resolve()
        self.download_dir.mkdir(parents=True, exist_ok=True)
        self._transfers: Dict[str, Dict[str, object]] = {}

    def _unique_target_path(self, filename: str, transfer_id: str) -> Path:
        base = Path(filename).name or "received.bin"
        final_path = self.download_dir / base
        if not final_path.exists():
            return final_path
        stem = final_path.stem
        suffix = final_path.suffix
        return final_path.with_name(f"{stem}-{transfer_id}{suffix}")

    def handle_incoming_data(self, source, payload):
        if not isinstance(payload, dict):
            logging.debug("Received non-dict payload from %s: %r", source, payload)
            return

        msg_type = payload.get("type")
        if msg_type == "file_manifest":
            self._handle_manifest(source, payload)
        elif msg_type == "file_chunk":
            self._handle_chunk(source, payload)
        elif msg_type == "file_complete":
            self._handle_complete(source, payload)
        else:
            logging.debug("Unhandled payload type %r from %s", msg_type, source)

    def _handle_manifest(self, source, payload: Dict[str, object]) -> None:
        transfer = str(payload.get("transfer_id") or "")
        if not transfer:
            logging.warning("Manifest from %s missing transfer_id", source)
            return

        filename = str(payload.get("filename") or f"{transfer}.bin")
        total_chunks = int(payload.get("chunks") or 0)
        chunk_size = int(payload.get("chunk_size") or 4096)

        target_path = self._unique_target_path(filename, transfer)
        temp_path = target_path.with_suffix(target_path.suffix + ".part")

        if transfer in self._transfers:
            prev = self._transfers.pop(transfer)
            handle = prev.get("handle")
            if handle:
                try:
                    handle.close()
                except Exception:
                    pass

        handle = temp_path.open("wb")
        self._transfers[transfer] = {
            "handle": handle,
            "target": target_path,
            "temp": temp_path,
            "total": total_chunks,
            "chunk_size": chunk_size,
            "received": set(),
            "bytes": 0,
        }
        logging.info(
            "Manifest received from %s: transfer=%s file=%s chunks=%d",
            source,
            transfer,
            target_path.name,
            total_chunks,
        )

    def _handle_chunk(self, source, payload: Dict[str, object]) -> None:
        transfer = str(payload.get("transfer_id") or "")
        if not transfer or transfer not in self._transfers:
            logging.warning("Chunk for unknown transfer %s from %s", transfer, source)
            return

        meta = self._transfers[transfer]
        handle = meta["handle"]
        if handle is None:
            logging.warning("Inactive transfer %s when chunk arrived", transfer)
            return

        index = int(payload.get("index") or 0)
        chunk_data = payload.get("data")
        if isinstance(chunk_data, str):
            # Fallback: interpret as base64/hex? keep simple by encoding raw string.
            chunk_bytes = chunk_data.encode("utf-8")
        else:
            chunk_bytes = bytes(chunk_data or b"")

        if not chunk_bytes:
            logging.debug("Empty chunk %d for transfer %s", index, transfer)
            return

        chunk_size = int(meta.get("chunk_size") or 0)
        try:
            if chunk_size > 0:
                handle.seek(index * chunk_size)
            else:
                handle.seek(0, 2)
        except Exception:
            handle.seek(0, 2)  # append as fallback
        handle.write(chunk_bytes)
        meta["received"].add(index)
        meta["bytes"] = meta.get("bytes", 0) + len(chunk_bytes)
        logging.debug(
            "Chunk %d/%d for transfer %s (%d bytes)",
            index + 1,
            meta.get("total"),
            transfer,
            len(chunk_bytes),
        )

    def _handle_complete(self, source, payload: Dict[str, object]) -> None:
        transfer = str(payload.get("transfer_id") or "")
        meta = self._transfers.get(transfer)
        if not meta:
            logging.warning("Completion for unknown transfer %s from %s", transfer, source)
            return

        handle = meta.get("handle")
        if handle:
            try:
                handle.flush()
                handle.close()
            except Exception:
                logging.exception("Failed closing transfer %s", transfer)
        temp_path = Path(meta.get("temp"))
        target_path = Path(meta.get("target"))
        try:
            temp_path.rename(target_path)
        except FileExistsError:
            temp_path.unlink(missing_ok=True)
            logging.error("Target file %s already exists, dropped transfer %s", target_path, transfer)
            self._transfers.pop(transfer, None)
            return
        except Exception:
            logging.exception("Failed to finalize transfer %s", transfer)
            self._transfers.pop(transfer, None)
            return

        logging.info(
            "Transfer %s from %s completed → %s (%d chunk(s), %d bytes)",
            transfer,
            source,
            target_path,
            len(meta.get("received", [])),
            meta.get("bytes", 0),
        )
        self._transfers.pop(transfer, None)


async def main():
    logging.basicConfig(level=logging.INFO)

    relay_uri = os.getenv("RELAY_URI", "ws://127.0.0.1:8765")
    udp_port = int(os.getenv("UDP_PORT_B", "8471"))
    node_id = _parse_node_id(os.getenv("NODE_ID_B"), "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb")

    server = FileReceiverServer(
        node_id=node_id,
        relay_endpoints=[relay_uri],
        relay_node_id=os.getenv("RELAY_NODE_ID_B", "nodeB"),
        relay_autoconnect=True,
        download_dir=os.getenv("RECEIVE_DIR", "received_files"),
    )

    await server.listen(udp_port)
    logging.info("Node B listening UDP %s and relay %s", udp_port, relay_uri)

    try:
        await asyncio.Event().wait()
    except (KeyboardInterrupt, asyncio.CancelledError):
        logging.info("Node B shutting down...")
    finally:
        await server.disconnect_relay()
        server.stop()


if __name__ == "__main__":
    asyncio.run(main())
