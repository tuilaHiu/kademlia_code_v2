import asyncio
import logging
from pathlib import Path

from kademlia.node import Node

from kademliaExtend import RelayAwareServer
from nat_utils import detect_nat_info
from node_config import (
    BOOTSTRAP_ADDR,
    NODE_A_ADDR,
    NODE_A_ID,
    NODE_A_META,
    NODE_B_ADDR,
    NODE_B_ID,
    NODE_B_META,
    RELAY_URI,
    STUN_HOST,
    STUN_PORT,
)
from relay_manager import RelayManager


async def ping_node_b(server: RelayAwareServer):
    """
    Gửi RPC ping từ nodeA tới nodeB để kiểm tra đường truyền.
    """
    logging.info("Waiting 2 seconds before sending ping to nodeB...")
    await asyncio.sleep(2)

    node_b = Node(NODE_B_ID, NODE_B_ADDR[0], NODE_B_ADDR[1])
    node_b.meta = dict(NODE_B_META)

    try:
        result = await server.protocol.call_ping(node_b)
    except Exception:
        logging.exception("Ping RPC raised an exception")
        return

    if result and result[0]:
        logging.info("Ping success, response: %s", result[1])
    else:
        logging.warning("Ping failed or timed out, result=%s", result)


async def send_sample_data(server: RelayAwareServer):
    """
    Gửi dữ liệu JSON đơn giản tới nodeB qua send_data.
    """
    await asyncio.sleep(3)
    node_b = Node(NODE_B_ID, NODE_B_ADDR[0], NODE_B_ADDR[1])
    node_b.meta = dict(NODE_B_META)
    payload = {"type": "text", "message": "Hello from nodeA"}

    try:
        result = await server.send_data(node_b, payload)
    except Exception:
        logging.exception("send_data raised an exception")
        return

    if result and result[0]:
        logging.info("send_data acknowledged with payload: %s", result[1])
    else:
        logging.warning("send_data failed, result=%s", result)


async def send_sample_file(server: RelayAwareServer):
    """
    Gửi file mẫu tới nodeB bằng cách chia thành nhiều chunk send_data.
    """
    await asyncio.sleep(4)
    node_b = Node(NODE_B_ID, NODE_B_ADDR[0], NODE_B_ADDR[1])
    node_b.meta = dict(NODE_B_META)
    sample_path = Path("test.png")
    if not sample_path.exists():
        logging.warning("Sample file %s not found, skipping send_file test", sample_path)
        return
    try:
        transfer_id = await server.send_file(node_b, sample_path)
        logging.info("send_file completed with transfer_id=%s", transfer_id)
    except Exception:
        logging.exception("send_file raised an exception")


async def build_metadata(base_meta):
    meta = dict(base_meta)
    try:
        nat_info = await detect_nat_info(stun_host=STUN_HOST, stun_port=STUN_PORT)
        logging.info(
            "NAT detection result: %s", {k: nat_info.get(k) for k in ("nat_type", "external_ip", "is_nat")}
        )
    except Exception:
        logging.exception("Failed to detect NAT info")
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

    meta = await build_metadata(NODE_A_META)
    relay_manager = None
    if meta.get("use_relay"):
        if not RELAY_URI:
            logging.warning("Relay URI not configured; cannot enable relay despite NAT")
        else:
            relay_manager = RelayManager(meta.get("node_id", "nodeA"), RELAY_URI)
            logging.info("Relay enabled for nodeA via %s", RELAY_URI)

    server = RelayAwareServer(node_id=NODE_A_ID, relay_manager=relay_manager)
    server.node.meta = meta

    host, port = NODE_A_ADDR
    await server.listen(port, interface=host)
    logging.info("nodeA listening on %s:%s", host, port)

    await server.bootstrap([BOOTSTRAP_ADDR])
    logging.info("nodeA bootstrapped via %s:%s", *BOOTSTRAP_ADDR)

    asyncio.create_task(ping_node_b(server))
    asyncio.create_task(send_sample_data(server))
    asyncio.create_task(send_sample_file(server))

    try:
        while True:
            await asyncio.sleep(3600)
    except asyncio.CancelledError:
        pass
    except KeyboardInterrupt:
        logging.info("Stopping nodeA")
    finally:
        server.stop()


if __name__ == "__main__":
    asyncio.run(main())
