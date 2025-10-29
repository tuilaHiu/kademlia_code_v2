import asyncio
import logging

from kademliaExtend import RelayAwareServer
from node_config import BOOTSTRAP_ADDR, BOOTSTRAP_META, BOOTSTRAP_NODE_ID


async def main():
    logging.basicConfig(level=logging.INFO)

    server = RelayAwareServer(node_id=BOOTSTRAP_NODE_ID)
    server.node.meta = dict(BOOTSTRAP_META)

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
