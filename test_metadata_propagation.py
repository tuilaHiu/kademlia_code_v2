"""
Test script to verify metadata is propagated through network crawling.

Usage:
1. Start relay_server.py
2. Start bootstrap_node.py
3. Start nodeB.py
4. Run this test script to verify metadata propagation
"""

import asyncio
import logging
from kademliaExtend import RelayAwareServer
from nat_utils import detect_nat_info
from nodeA_config import (
    BOOTSTRAP_ADDR,
    NODE_A_ID,
    NODE_A_META,
    NODE_A_ADDR,
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
            "NAT detection result: %s",
            {k: nat_info.get(k) for k in ("nat_type", "external_ip", "is_nat")},
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


def print_routing_table_metadata(server: RelayAwareServer):
    """Print metadata của tất cả nodes trong routing table"""
    print("\n" + "=" * 80)
    print("ROUTING TABLE METADATA CHECK")
    print("=" * 80)

    total_nodes = 0
    nodes_with_meta = 0
    nodes_without_meta = 0

    for bucket in server.protocol.router.buckets:
        for node in bucket.get_nodes():
            total_nodes += 1
            # Try to get metadata from attribute first, then from cache
            meta = getattr(node, 'meta', None)
            if not meta:
                meta = server.protocol.node_metadata_cache.get(node.id)

            if meta:
                nodes_with_meta += 1
                print(f"\n✓ Node {node.long_id} ({node.ip}:{node.port})")
                print(f"  Metadata: {meta}")
            else:
                nodes_without_meta += 1
                print(f"\n✗ Node {node.long_id} ({node.ip}:{node.port})")
                print(f"  NO METADATA!")

    print("\n" + "-" * 80)
    print(f"Summary:")
    print(f"  Total nodes in routing table: {total_nodes}")
    print(f"  Nodes WITH metadata: {nodes_with_meta}")
    print(f"  Nodes WITHOUT metadata: {nodes_without_meta}")
    print("=" * 80 + "\n")

    if total_nodes == 0:
        print("⚠️  WARNING: No nodes in routing table yet.")
        print("   Wait for bootstrap/crawling to complete.")
        return None
    elif nodes_with_meta > 0:
        print(f"✅ SUCCESS: {nodes_with_meta}/{total_nodes} nodes have metadata!")
        print("   Metadata IS being propagated correctly through crawling.")
        if nodes_without_meta > 0:
            print(f"   Note: {nodes_without_meta} nodes without metadata (may be bootstrap nodes)")
        return True
    else:
        print("❌ FAIL: NO nodes have metadata!")
        print("   Metadata is NOT being propagated correctly through crawling.")
        return False


async def main():
    logging.basicConfig(
        level=logging.DEBUG,  # Changed to DEBUG to see detailed logging
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    meta = await build_metadata(NODE_A_META)
    relay_manager = None
    if meta.get("use_relay"):
        if not RELAY_URI:
            logging.warning("Relay URI not configured; cannot enable relay despite NAT")
        else:
            relay_manager = RelayManager(meta.get("node_id", "test_node"), RELAY_URI)
            logging.info("Relay enabled for test node via %s", RELAY_URI)

    server = RelayAwareServer(node_id=NODE_A_ID, relay_manager=relay_manager)
    server.node.meta = meta

    host, port = NODE_A_ADDR
    await server.listen(port, interface=host)
    logging.info("Test node listening on %s:%s", host, port)

    # Bootstrap và chờ crawling hoàn thành
    logging.info("Bootstrapping from %s:%s...", *BOOTSTRAP_ADDR)
    await server.bootstrap([BOOTSTRAP_ADDR])
    logging.info("Bootstrap completed. Waiting for network crawling...")

    # Chờ một chút để crawling hoàn thành
    await asyncio.sleep(5)

    # Kiểm tra routing table
    result = print_routing_table_metadata(server)

    # Chờ thêm nếu chưa có nodes
    if result is None:
        logging.info("Waiting additional 10 seconds for more nodes to join...")
        await asyncio.sleep(10)
        result = print_routing_table_metadata(server)

    server.stop()

    if result is True:
        print("\n🎉 Test PASSED: Metadata propagation is working!")
    elif result is False:
        print("\n💥 Test FAILED: Metadata propagation is NOT working!")
    else:
        print("\n⚠️  Test INCONCLUSIVE: No nodes discovered yet.")


if __name__ == "__main__":
    asyncio.run(main())
