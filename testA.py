import asyncio
import logging
from pathlib import Path

from extended_server import ExtendedServer
from kademlia.node import Node


HOST = "127.0.0.1"
LOCAL_PORT = 8701
REMOTE_PORT = 8700


async def bootstrap_with_retry(server, addr, retries=10, delay=1.0):
    for attempt in range(1, retries + 1):
        try:
            await server.bootstrap([addr])
            logging.info("bootstrap succeeded on attempt %d", attempt)
            return
        except Exception as exc:  # pragma: no cover - interactive script
            logging.warning("bootstrap attempt %d failed: %s", attempt, exc)
            await asyncio.sleep(delay)
    raise RuntimeError("could not bootstrap to remote node")


async def resolve_remote_node(protocol, address):
    result = await protocol.ping(address, protocol.source_node.id, {}, protocol.source_node.meta)
    if not result[0] or not isinstance(result[1], dict):
        raise RuntimeError("ping failed; is receiver running?")
    payload = result[1]
    remote_id = payload.get("node_id")
    if not remote_id:
        raise RuntimeError("receiver did not return node id")
    remote_meta = payload.get("meta")
    node = Node(remote_id, address[0], address[1], remote_meta)
    protocol.welcome_if_new(node)
    return node


async def main():
    logging.basicConfig(level=logging.INFO, format="[testA] %(message)s")
    server = ExtendedServer()
    await server.listen(LOCAL_PORT, HOST)
    logging.info("sender listening on %s:%d", HOST, LOCAL_PORT)

    address = (HOST, REMOTE_PORT)
    await bootstrap_with_retry(server, address)

    node_b = await resolve_remote_node(server.protocol, address)

    # send simple payload
    payload = {"type": "greeting", "message": "hello from testA"}
    result = await server.protocol.call_senddata(node_b, payload)
    logging.info("call_senddata result: %s", result)

    # prepare file to send
    sample_path = Path("test.png").resolve()
    if not sample_path.is_file():
        raise FileNotFoundError(f"Không tìm thấy file để gửi: {sample_path}")

    # send file via RPC
    file_result = await server.protocol.call_sendfile(
        node_b,
        sample_path,
        chunk_size=2048,
    )
    logging.info("call_sendfile result: %s", file_result)

    await asyncio.sleep(0.5)
    server.stop()


if __name__ == "__main__":
    asyncio.run(main())
