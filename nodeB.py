import asyncio
import logging
from pathlib import Path

from kademliaExtend import RelayAwareServer
from node_config import (
    BOOTSTRAP_ADDR,
    NODE_B_ADDR,
    NODE_B_ID,
    NODE_B_META,
)


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


async def main():
    logging.basicConfig(level=logging.INFO)

    server = RelayAwareServer(node_id=NODE_B_ID)
    server.node.meta = dict(NODE_B_META)
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
