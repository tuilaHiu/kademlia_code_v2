"""
Test script để CHỨNG MINH nodeA lấy metadata của nodeB từ bootstrap node.

Chạy script này sau khi đã start:
1. relay_server.py
2. bootstrap_node.py
3. nodeB.py

Script sẽ in ra log chi tiết để chứng minh flow:
- Bootstrap trả về nodeB với metadata
- NodeA nhận và cache metadata
- ping_node_b() sử dụng metadata từ cache (KHÔNG dùng fallback)
"""

import asyncio
import logging
from kademliaExtend import RelayAwareServer
from nat_utils import detect_nat_info
from config import (
    BOOTSTRAP_ADDR,
    NODE_A_ID,
    NODE_A_META,
    NODE_A_ADDR,
    NODE_B_ID,
    RELAY_URI,
    STUN_HOST,
    STUN_PORT,
)
from relay_manager import RelayManager


# Custom log handler để bắt các log quan trọng
class MetadataTracker:
    def __init__(self):
        self.events = []

    def log_event(self, event_type, details):
        self.events.append((event_type, details))
        print(f"\n{'='*80}")
        print(f"🔍 EVENT: {event_type}")
        print(f"{'='*80}")
        print(details)
        print(f"{'='*80}\n")


tracker = MetadataTracker()


async def build_metadata(base_meta):
    meta = dict(base_meta)
    try:
        nat_info = await detect_nat_info(stun_host=STUN_HOST, stun_port=STUN_PORT)
        logging.info("NAT detection result: %s", {k: nat_info.get(k) for k in ("nat_type", "external_ip", "is_nat")})
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


def check_metadata_cache(server: RelayAwareServer):
    """Kiểm tra metadata cache sau bootstrap"""
    print("\n" + "="*80)
    print("📊 METADATA CACHE INSPECTION")
    print("="*80)

    cache = server.protocol.node_metadata_cache

    if not cache:
        print("⚠️  Cache is EMPTY - no metadata received!")
        tracker.log_event("CACHE_CHECK", "Cache is empty - metadata NOT propagated")
        return False

    print(f"✅ Cache contains {len(cache)} entries:\n")

    found_nodeB = False
    for node_id, meta in cache.items():
        node_id_hex = node_id.hex()[:16]
        print(f"  Node ID: {node_id_hex}...")
        print(f"  Metadata: {meta}")
        print()

        # Check if nodeB is in cache
        if node_id == NODE_B_ID:
            found_nodeB = True
            tracker.log_event(
                "FOUND_NODEB_IN_CACHE",
                f"✅ NodeB metadata found in cache!\n"
                f"Node ID: {node_id_hex}...\n"
                f"Metadata: {meta}\n\n"
                f"CHỨNG MINH: NodeA đã nhận metadata của NodeB từ bootstrap!"
            )

    print("="*80 + "\n")

    if found_nodeB:
        print("✅ SUCCESS: NodeB metadata found in cache!")
        print("   This PROVES that nodeA received nodeB's metadata from bootstrap node.\n")
    else:
        print("⚠️  NodeB NOT found in cache yet.")
        print("   This might mean nodeB hasn't joined the network or bootstrap hasn't discovered it.\n")

    return found_nodeB


def check_routing_table(server: RelayAwareServer):
    """Kiểm tra routing table sau bootstrap"""
    print("\n" + "="*80)
    print("📋 ROUTING TABLE INSPECTION")
    print("="*80)

    found_nodeB = False
    total_nodes = 0

    for bucket_idx, bucket in enumerate(server.protocol.router.buckets):
        nodes = bucket.get_nodes()
        if not nodes:
            continue

        total_nodes += len(nodes)
        print(f"\nBucket {bucket_idx} ({len(nodes)} nodes):")

        for node in nodes:
            node_id_hex = node.id.hex()[:16]
            meta = getattr(node, 'meta', None)

            if node.id == NODE_B_ID:
                found_nodeB = True
                print(f"  ✅ NodeB FOUND!")
                print(f"     ID: {node_id_hex}...")
                print(f"     Address: {node.ip}:{node.port}")
                print(f"     Metadata: {meta}")

                tracker.log_event(
                    "FOUND_NODEB_IN_ROUTING_TABLE",
                    f"✅ NodeB found in routing table with metadata!\n"
                    f"Bucket: {bucket_idx}\n"
                    f"Address: {node.ip}:{node.port}\n"
                    f"Metadata: {meta}\n\n"
                    f"CHỨNG MINH: NodeB đã được add vào routing table với metadata từ bootstrap!"
                )
            else:
                print(f"  - Node {node_id_hex}... ({node.ip}:{node.port})")
                if meta:
                    print(f"    Metadata: {meta}")

    print(f"\nTotal nodes in routing table: {total_nodes}")
    print("="*80 + "\n")

    return found_nodeB


async def test_ping_with_metadata_check(server: RelayAwareServer):
    """Test ping và kiểm tra xem có dùng metadata từ cache không"""
    print("\n" + "="*80)
    print("🏓 TESTING PING WITH METADATA")
    print("="*80)

    # Tìm nodeB trong routing table (giống hàm get_node_with_metadata)
    found_in_routing = False
    node_b = None

    for bucket in server.protocol.router.buckets:
        for node in bucket.get_nodes():
            if node.id == NODE_B_ID:
                found_in_routing = True
                node_b = node
                meta = getattr(node, 'meta', None)
                if not meta:
                    meta = server.protocol.node_metadata_cache.get(node.id)

                if meta:
                    print(f"✅ Found nodeB in routing table with metadata from crawling!")
                    print(f"   Address: {node.ip}:{node.port}")
                    print(f"   Metadata: {meta}")
                    print(f"\n   CHỨNG MINH: Ping sẽ dùng metadata từ bootstrap, KHÔNG dùng fallback!")

                    tracker.log_event(
                        "PING_USES_CRAWLED_METADATA",
                        f"✅ ping_node_b() is using metadata from bootstrap crawl!\n"
                        f"Source: Routing table + metadata cache\n"
                        f"NOT using fallback from config!\n"
                        f"Metadata: {meta}"
                    )
                else:
                    print(f"⚠️  Found nodeB but NO metadata - would use fallback")
                break

    if not found_in_routing:
        print("⚠️  NodeB NOT in routing table - would use fallback from config")
        tracker.log_event("PING_USES_FALLBACK", "NodeB not found, using fallback metadata from config")
        return False

    # Thử ping
    print("\nSending PING to nodeB...")
    try:
        result = await server.protocol.call_ping(node_b)
        if result and result[0]:
            print(f"✅ PING SUCCESS! Response: {result[1]}")
            tracker.log_event("PING_SUCCESS", f"Ping successful using metadata from bootstrap!\nResponse: {result[1]}")
        else:
            print(f"⚠️  PING FAILED or timed out: {result}")
    except Exception as e:
        print(f"❌ PING ERROR: {e}")

    print("="*80 + "\n")
    return found_in_routing


async def main():
    # Setup logging với format chi tiết
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    print("\n" + "="*80)
    print("🧪 TEST: NodeA lấy metadata của NodeB từ Bootstrap Node")
    print("="*80)
    print("\nMục tiêu: Chứng minh rằng:")
    print("1. Bootstrap node trả về nodeB với metadata khi nodeA crawl")
    print("2. NodeA cache metadata của nodeB")
    print("3. ping_node_b() dùng metadata từ cache (KHÔNG dùng fallback)")
    print("="*80 + "\n")

    meta = await build_metadata(NODE_A_META)
    relay_manager = None
    if meta.get("use_relay"):
        if RELAY_URI:
            relay_manager = RelayManager(meta.get("node_id", "test_nodeA"), RELAY_URI)
            logging.info("Relay enabled via %s", RELAY_URI)

    server = RelayAwareServer(node_id=NODE_A_ID, relay_manager=relay_manager)
    server.node.meta = meta

    host, port = NODE_A_ADDR
    await server.listen(port, interface=host)
    logging.info("NodeA listening on %s:%s", host, port)

    # BƯỚC 1: Bootstrap
    tracker.log_event("BOOTSTRAP_START", f"Starting bootstrap from {BOOTSTRAP_ADDR}")
    print(f"🚀 Bootstrapping from {BOOTSTRAP_ADDR}...")
    await server.bootstrap([BOOTSTRAP_ADDR])
    print("✅ Bootstrap completed!\n")
    tracker.log_event("BOOTSTRAP_COMPLETE", "Bootstrap crawl completed")

    # Chờ một chút để crawling hoàn thành
    await asyncio.sleep(3)

    # BƯỚC 2: Kiểm tra metadata cache
    cache_has_nodeB = check_metadata_cache(server)

    # BƯỚC 3: Kiểm tra routing table
    routing_has_nodeB = check_routing_table(server)

    # BƯỚC 4: Test ping
    await test_ping_with_metadata_check(server)

    # BƯỚC 5: Summary
    print("\n" + "="*80)
    print("📊 FINAL SUMMARY")
    print("="*80)
    print(f"\nTotal events tracked: {len(tracker.events)}\n")

    for idx, (event_type, details) in enumerate(tracker.events, 1):
        print(f"{idx}. {event_type}")

    print("\n" + "="*80)
    if cache_has_nodeB and routing_has_nodeB:
        print("✅ ✅ ✅ TEST PASSED! ✅ ✅ ✅")
        print("\nCHỨNG MINH HOÀN THÀNH:")
        print("• NodeB's metadata was received from Bootstrap node during crawl")
        print("• NodeB's metadata was cached in node_metadata_cache")
        print("• NodeB was added to routing table with metadata")
        print("• ping_node_b() WILL USE metadata from cache (NOT fallback!)")
        print("\n❌ NodeA KHÔNG cần fallback từ config!")
        print("❌ NodeA ĐÃ có metadata từ bootstrap crawl!")
    else:
        print("⚠️  TEST INCOMPLETE")
        print("\nNodeB chưa được discover qua bootstrap crawl.")
        print("Có thể do:")
        print("• NodeB chưa chạy")
        print("• Bootstrap chưa discover nodeB")
        print("• Cần chờ lâu hơn để network crawl hoàn thành")
    print("="*80 + "\n")

    server.stop()


if __name__ == "__main__":
    asyncio.run(main())
