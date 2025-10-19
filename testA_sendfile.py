import asyncio
import logging
import os
from pathlib import Path
from typing import Optional

from kademliaExtend import ExtendedServer
from kademlia.node import Node


def _parse_node_id(raw: Optional[str], fallback: str) -> bytes:
    value = (raw or fallback).strip().lower()
    if value.startswith("0x"):
        value = value[2:]
    if len(value) != 40:
        raise ValueError("Node id must be 160-bit (40 hex chars)")
    return bytes.fromhex(value)


async def main():
    logging.basicConfig(level=logging.INFO)

    relay_uri = os.getenv("RELAY_URI", "ws://127.0.0.1:8765")
    node_a_id = _parse_node_id(os.getenv("NODE_ID_A"), "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa")
    node_b_id = _parse_node_id(os.getenv("NODE_ID_B"), "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb")
    relay_node_a = os.getenv("RELAY_NODE_ID_A", "nodeA")
    relay_node_b = os.getenv("RELAY_NODE_ID_B", "nodeB")
    udp_port_a = int(os.getenv("UDP_PORT_A", "8470"))
    udp_port_b = int(os.getenv("UDP_PORT_B", "8471"))
    node_b_ip = os.getenv("NODE_B_IP", "127.0.0.1")
    chunk_size = int(os.getenv("CHUNK_SIZE", "4096"))

    file_path = Path(os.getenv("FILE_PATH", "test.png")).expanduser().resolve()
    if not file_path.is_file():
        raise FileNotFoundError(f"File to send not found: {file_path}")

    server = ExtendedServer(
        node_id=node_a_id,
        relay_endpoints=[relay_uri],
        relay_node_id=relay_node_a,
        relay_autoconnect=True,
    )

    await server.listen(udp_port_a)
    logging.info("Node A listening UDP %s and relay %s", udp_port_a, relay_uri)

    # Allow relay connection to settle
    await asyncio.sleep(1.0)

    node_b = Node(
        node_b_id,
        node_b_ip,
        udp_port_b,
        meta={
            "use_relay": True,
            "relay_uri": relay_uri,
            "node_id": relay_node_b,
        },
    )

    try:
        logging.info("Ping node B before sending file")
        await server.protocol.call_ping(node_b)
    except Exception as exc:
        logging.warning("Initial ping failed (continuing anyway): %s", exc)

    try:
        logging.info("Sending file %s (%d bytes) to node B", file_path, file_path.stat().st_size)
        result = await server.protocol.call_sendfile(
            node_b,
            str(file_path),
            chunk_size=chunk_size,
        )
        logging.info("Sendfile result: %s", result)
    finally:
        await asyncio.sleep(0.5)
        await server.disconnect_relay()
        server.stop()


if __name__ == "__main__":
    asyncio.run(main())
