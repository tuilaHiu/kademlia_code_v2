import asyncio
import json
import logging
from typing import Dict

import websockets

logging.basicConfig(level=logging.INFO, format="[relay] %(message)s")
log = logging.getLogger("relay")


class RelayHub:
    def __init__(self):
        self._clients: Dict[str, websockets.WebSocketServerProtocol] = {}
        self._lock = asyncio.Lock()

    async def register(self, node_id: str, ws: websockets.WebSocketServerProtocol):
        async with self._lock:
            self._clients[node_id] = ws
            log.info("Node %s connected", node_id)

    async def unregister(self, node_id: str):
        async with self._lock:
            existing = self._clients.pop(node_id, None)
            if existing:
                log.info("Node %s disconnected", node_id)

    async def forward(self, target_id: str, payload: str):
        async with self._lock:
            ws = self._clients.get(target_id)
        if ws is None:
            log.warning("Target %s not connected; dropping message", target_id)
            return
        await ws.send(payload)


hub = RelayHub()


async def handler(ws: websockets.WebSocketServerProtocol):
    node_id = None
    try:
        greeting = await ws.recv()
        data = json.loads(greeting)
        if data.get("type") != "register":
            await ws.close(code=4001, reason="expected register")
            return
        node_id = data.get("node_id")
        if not node_id:
            await ws.close(code=4002, reason="missing node_id")
            return
        await hub.register(node_id, ws)
        async for message in ws:
            try:
                payload = json.loads(message)
            except json.JSONDecodeError:
                log.warning("Invalid JSON from %s", node_id)
                continue
            target = payload.get("to")
            if not target:
                log.warning("Message from %s missing target: %s", node_id, payload)
                continue
            await hub.forward(target, message)
    except websockets.ConnectionClosed:
        pass
    finally:
        if node_id:
            await hub.unregister(node_id)


async def main(host="0.0.0.0", port=8765):
    async with websockets.serve(handler, host, port):
        log.info("Relay server listening on %s:%d", host, port)
        await asyncio.Future()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
