import argparse
import asyncio
import json
import logging
from typing import Dict

import websockets


log = logging.getLogger("relay_server")

CONNECTED: Dict[str, websockets.WebSocketServerProtocol] = {}
CONNECTED_LOCK = asyncio.Lock()


async def register(node_id: str, ws: websockets.WebSocketServerProtocol):
    async with CONNECTED_LOCK:
        old = CONNECTED.get(node_id)
        if old and old is not ws:
            try:
                await old.close(code=1012, reason="Replaced by new connection")
            except Exception:
                pass
        CONNECTED[node_id] = ws
        log.info("Node %s connected (total=%d)", node_id, len(CONNECTED))


async def unregister(node_id: str, ws: websockets.WebSocketServerProtocol):
    async with CONNECTED_LOCK:
        current = CONNECTED.get(node_id)
        if current is ws:
            CONNECTED.pop(node_id, None)
            log.info("Node %s disconnected (total=%d)", node_id, len(CONNECTED))


async def forward_message(sender: str, payload: dict):
    target = payload.get("target")
    rpc = payload.get("rpc")
    if not target or not rpc:
        log.debug("Ignoring message missing target/rpc: %s", payload)
        return
    message = {
        "rpc": rpc,
        "rpc_id": payload.get("rpc_id"),
        "payload_b64": payload.get("payload_b64"),
        "source": sender,
    }
    async with CONNECTED_LOCK:
        target_ws = CONNECTED.get(target)
    if target_ws is None:
        log.info("Target %s not connected; cannot deliver rpc=%s", target, rpc)
        return
    try:
        await target_ws.send(json.dumps(message))
    except Exception:
        log.exception("Failed to forward message from %s to %s", sender, target)


async def relay_handler(ws: websockets.WebSocketServerProtocol):
    node_id = None
    try:
        init_message = await ws.recv()
        try:
            init = json.loads(init_message)
        except json.JSONDecodeError:
            await ws.close(code=1002, reason="Invalid JSON during init")
            return
        node_id = init.get("node_id")
        if not node_id:
            await ws.close(code=1008, reason="node_id required")
            return
        await register(node_id, ws)
        async for message in ws:
            try:
                data = json.loads(message)
            except json.JSONDecodeError:
                log.debug("Ignoring non-JSON message from %s", node_id)
                continue
            await forward_message(node_id, data)
    except websockets.ConnectionClosed:
        pass
    except Exception:
        log.exception("Unexpected error in relay handler for %s", node_id)
    finally:
        if node_id:
            await unregister(node_id, ws)


async def serve(host: str, port: int):
    async with websockets.serve(relay_handler, host, port):
        log.info("Relay server listening on %s:%d", host, port)
        await asyncio.Future()


def main():
    parser = argparse.ArgumentParser(description="WebSocket relay for Kademlia nodes")
    parser.add_argument("--host", default="0.0.0.0", help="Host to bind relay server")
    parser.add_argument("--port", type=int, default=8765, help="Port to bind relay server")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    try:
        asyncio.run(serve(args.host, args.port))
    except KeyboardInterrupt:
        log.info("Relay server stopped by user")


if __name__ == "__main__":
    main()
