import asyncio
import logging

import websockets

from extended_server import ExtendedServer
from kademlia.node import Node
from relay_manager import RelayManager
from relay_server import handler as relay_handler


HOST = "127.0.0.1"
PORT_A = 8810
PORT_B = 8811
RELAY_PORT = 9900


async def start_relay():
    server = await websockets.serve(relay_handler, HOST, RELAY_PORT)
    sockets = server.sockets or []
    if not sockets:
        raise RuntimeError("relay server failed to bind to socket")
    _, port = sockets[0].getsockname()[:2]
    uri = f"ws://{HOST}:{port}"
    return server, uri


async def setup_server(port: int, relay_uri: str):
    server = ExtendedServer()
    await server.listen(port, HOST)
    manager = RelayManager(relay_uri, server.node.id.hex())
    server.attach_relay_manager(manager)
    await manager.connect()
    await server.update_local_nat(stun_host="stun.l.google.com", stun_port=19302)
    # buộc node sử dụng relay để test
    server.protocol.source_node.update_meta(meta={"force_relay": True})
    return server, manager


async def main():
    logging.basicConfig(level=logging.INFO, format="[test-relay] %(message)s")
    relay_server, relay_uri = await start_relay()
    server_b, manager_b = await setup_server(PORT_B, relay_uri)
    server_a, manager_a = await setup_server(PORT_A, relay_uri)

    node_b = Node(
        server_b.node.id,
        HOST,
        PORT_B,
        {"force_relay": True},
    )

    # Gửi ping qua relay
    try:
        result = await server_a.protocol.call_ping(node_b)
        logging.info("call_ping via relay -> %s", result)
    finally:
        server_a.stop()
        server_b.stop()
        await manager_a.disconnect()
        await manager_b.disconnect()
        relay_server.close()
        await relay_server.wait_closed()


if __name__ == "__main__":
    asyncio.run(main())
