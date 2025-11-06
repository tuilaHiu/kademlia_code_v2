import asyncio
import logging
from pathlib import Path

from kademliaExtend import RelayAwareServer
from nat_utils import detect_nat_info
from nodeB_config import (
    BOOTSTRAP_ADDR,
    NODE_B_ADDR,
    NODE_B_ID,
    NODE_B_META,
    RELAY_URI,
    STUN_HOST,
    STUN_PORT,
)
from relay_manager import RelayManager


def handle_incoming_data(source, payload):
    logging.info("nodeB received data from %s: %r", source, payload)


def handle_incoming_file(source, file_name, file_bytes, transfer_id):
    target_dir = Path("received_files")
    target_dir.mkdir(exist_ok=True)
    target_path = target_dir / f"{transfer_id}_{file_name}"
    try:
        target_path.write_bytes(file_bytes)
        logging.info(
            "nodeB stored file '%s' from %s to %s", file_name, source, target_path
        )
    except Exception:
        logging.exception("nodeB failed to store file '%s'", file_name)


async def build_metadata(base_meta):
    meta = dict(base_meta)
    try:
        nat_info = await detect_nat_info(stun_host=STUN_HOST, stun_port=STUN_PORT)
        logging.info(
            "nodeB NAT detection: %s",
            {k: nat_info.get(k) for k in ("nat_type", "external_ip", "is_nat")},
        )
    except Exception:
        logging.exception("nodeB NAT detection failed")
        nat_info = {}

    nat_type = nat_info.get("nat_type")
    if nat_type:
        meta["nat"] = nat_type
        meta["nat_type"] = nat_type
    if nat_info.get("external_ip"):
        meta["external_ip"] = nat_info["external_ip"]
    if nat_info.get("local_ip"):
        meta["local_ip"] = nat_info["local_ip"]

    if nat_info.get("is_nat"):
        meta["use_relay"] = True
    if RELAY_URI:
        meta["relay_uri"] = RELAY_URI
    return meta


async def main():
    logging.basicConfig(level=logging.INFO)

    meta = await build_metadata(NODE_B_META)
    relay_manager = RelayManager(meta.get("node_id", "nodeB"), RELAY_URI) if RELAY_URI else None

    server = RelayAwareServer(node_id=NODE_B_ID, relay_manager=relay_manager)
    server.node.meta = meta
    server.register_data_handler(handle_incoming_data)
    server.register_file_handler(handle_incoming_file)

    host, port = NODE_B_ADDR
    await server.listen(port, interface=host)
    logging.info("nodeB listening on %s:%s", host, port)

    await server.bootstrap([BOOTSTRAP_ADDR])
    logging.info("nodeB bootstrapped via %s:%s", *BOOTSTRAP_ADDR)

    try:
        while True:
            await asyncio.sleep(3600)
    except asyncio.CancelledError:
        pass
    except KeyboardInterrupt:
        logging.info("Stopping nodeB")
    finally:
        server.stop()


if __name__ == "__main__":
    asyncio.run(main())
