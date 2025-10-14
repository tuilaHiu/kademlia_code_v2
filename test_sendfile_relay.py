import asyncio
import logging
from pathlib import Path

import websockets

from extended_server import ExtendedServer
from kademlia.node import Node
from relay_manager import RelayManager
from relay_server import handler as relay_handler


HOST = "127.0.0.1"
RELAY_PORT = 9999
PORT_RECEIVER = 8820
PORT_SENDER = 8821
SAMPLE_FILE = Path("test.png")


async def start_relay():
    server = await websockets.serve(relay_handler, HOST, RELAY_PORT)
    sockets = server.sockets or []
    if not sockets:
        raise RuntimeError("relay failed to bind")
    _, port = sockets[0].getsockname()[:2]
    uri = f"ws://{HOST}:{port}"
    return server, uri


async def setup_server(port: int, relay_uri: str, *, auto_nat: bool):
    server = ExtendedServer(auto_detect_nat=auto_nat)
    await server.listen(port, HOST)
    manager = RelayManager(relay_uri, server.node.id.hex())
    server.attach_relay_manager(manager)
    await manager.connect()
    await server.update_local_nat(stun_host="stun.l.google.com", stun_port=19302)
    return server, manager


async def main():
    logging.basicConfig(level=logging.INFO, format="[test-sendfile] %(message)s")
    relay_server, relay_uri = await start_relay()

    receiver, receiver_manager = await setup_server(PORT_RECEIVER, relay_uri, auto_nat=True)
    sender, sender_manager = await setup_server(PORT_SENDER, relay_uri, auto_nat=True)

    node_receiver = Node(
        receiver.node.id,
        HOST,
        PORT_RECEIVER,
        receiver.node.meta,
    )

    await asyncio.sleep(1)

    try:
        logging.info("Sending greeting payload via relay")
        payload = {"type": "greeting", "message": "hello over relay"}
        result = await sender.protocol.call_senddata(node_receiver, payload)
        logging.info("call_senddata result: %s", result)

        if not SAMPLE_FILE.is_file():
            raise FileNotFoundError(f"Sample file not found: {SAMPLE_FILE}")

        logging.info("Sending file via relay: %s", SAMPLE_FILE)
        send_result = await sender.protocol.call_sendfile(
            node_receiver,
            SAMPLE_FILE,
            chunk_size=2048,
        )
        logging.info("call_sendfile result: %s", send_result)

        await asyncio.sleep(1.0)
    finally:
        sender.stop()
        receiver.stop()
        await sender_manager.disconnect()
        await receiver_manager.disconnect()
        relay_server.close()
        await relay_server.wait_closed()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
