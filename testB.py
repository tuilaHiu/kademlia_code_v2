import asyncio
import logging
from pathlib import Path

from relay_manager import RelayManager

from extended_server import ExtendedServer


PORT = 8700
HOST = "0.0.0.0"
RECEIVE_DIR = Path("received_files")
RELAY_URI = None  # đặt URI relay nếu muốn ép dùng relay, mặc định None


class ReceiverServer(ExtendedServer):
    def handle_incoming_data(self, source, payload):
        result = super().handle_incoming_data(source, payload)
        if isinstance(payload, dict):
            payload_type = payload.get("type")
            transfer = payload.get("transfer_id")
            if payload_type == "file_manifest":
                logging.info(
                    "manifest received for transfer %s from %s: %s (%d chunk(s))",
                    transfer,
                    source,
                    payload.get("filename"),
                    payload.get("chunks"),
                )
                return result
            if payload_type == "file_chunk":
                data = payload.get("data")
                size = len(data) if isinstance(data, (bytes, bytearray)) else 0
                logging.debug(
                    "chunk %d/%s (%d bytes) received for transfer %s from %s",
                    payload.get("index"),
                    payload.get("total"),
                    size,
                    transfer,
                    source,
                )
                return result
            if payload_type == "file_complete":
                logging.info(
                    "transfer %s completed signal received from %s",
                    transfer,
                    source,
                )
                return result
        logging.info("payload received từ %s: %r", source, payload)
        return result

    def on_file_received(self, transfer_id, source, manifest, data):
        super().on_file_received(transfer_id, source, manifest, data)
        RECEIVE_DIR.mkdir(parents=True, exist_ok=True)
        filename = manifest.get("filename") or f"transfer_{transfer_id}.bin"
        output_path = RECEIVE_DIR / filename
        if output_path.exists():
            stem = output_path.stem
            suffix = output_path.suffix
            output_path = RECEIVE_DIR / f"{stem}_{transfer_id}{suffix}"
        output_path.write_bytes(data)
        logging.info(
            "saved file '%s' (%d bytes) from %s",
            output_path,
            len(data),
            source,
        )


async def main():
    logging.basicConfig(level=logging.INFO, format="[testB] %(message)s")
    server = ReceiverServer(auto_detect_nat=True)
    await server.listen(PORT, HOST)
    await server.update_local_nat()

    if RELAY_URI:
        manager = RelayManager(RELAY_URI, server.node.id.hex())
        server.attach_relay_manager(manager)
        await manager.connect()
    else:
        manager = None

    print(f"Receiver ready on {HOST}:{PORT}; press Ctrl+C to stop.")
    try:
        while True:
            await asyncio.sleep(3600)
    except asyncio.CancelledError:
        raise
    except KeyboardInterrupt:
        pass
    finally:
        if manager:
            await manager.disconnect()
    finally:
        server.stop()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
