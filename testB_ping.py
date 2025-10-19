import asyncio
import logging
import os
from typing import Optional

from kademliaExtend import ExtendedServer


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
    udp_port = int(os.getenv("UDP_PORT_B", "8471"))
    node_id = _parse_node_id(os.getenv("NODE_ID_B"), "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb")

    server = ExtendedServer(
        node_id=node_id,
        relay_endpoints=[relay_uri],
        relay_node_id=os.getenv("RELAY_NODE_ID_B", "nodeB"),
        relay_autoconnect=True,
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
