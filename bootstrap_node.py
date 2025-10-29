import asyncio
import logging

from kademliaExtend import RelayAwareServer
from nat_utils import detect_nat_info
from node_config import (
    BOOTSTRAP_ADDR,
    BOOTSTRAP_META,
    BOOTSTRAP_NODE_ID,
    RELAY_URI,
    STUN_HOST,
    STUN_PORT,
)
from relay_manager import RelayManager


async def build_metadata(base_meta):
    meta = dict(base_meta)
    try:
        nat_info = await detect_nat_info(stun_host=STUN_HOST, stun_port=STUN_PORT)
        logging.info(
            "Bootstrap NAT detection: %s",
            {k: nat_info.get(k) for k in ("nat_type", "external_ip", "is_nat")},
        )
    except Exception:
        logging.exception("Bootstrap NAT detection failed")
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

    meta = await build_metadata(BOOTSTRAP_META)
    relay_manager = RelayManager(meta.get("node_id", "bootstrap"), RELAY_URI) if RELAY_URI else None

    server = RelayAwareServer(node_id=BOOTSTRAP_NODE_ID, relay_manager=relay_manager)
    server.node.meta = meta

    host, port = BOOTSTRAP_ADDR
    await server.listen(port, interface=host)

    log = logging.getLogger("bootstrap")
    log.info("Bootstrap node running on %s:%s", host, port)

    try:
        while True:
            await asyncio.sleep(3600)
    except asyncio.CancelledError:
        pass
    except KeyboardInterrupt:
        log.info("Stopping bootstrap node")
    finally:
        server.stop()


if __name__ == "__main__":
    asyncio.run(main())
