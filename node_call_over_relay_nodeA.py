# Chạy thử nghiệm
# Terminal 1: python relay_server.py
# Terminal 2: python node.py với "node_id": "nodeB"
# Terminal 3: python node.py với "node_id": "nodeA" và thực hiện call_rpc("nodeB", ...)
# Ưu điểm
# RPC từ node A đến B diễn ra qua relay WebSocket mà không cần node B gọi ngược lại.
# Relay không cần xử lý logic RPC, chỉ forward gói tin.
# Kết quả được trả lại đầy đủ thông qua relay.

import asyncio
import json
import websockets
import uuid

class RelayClient:
    def __init__(self, node_id, uri):
        self.node_id = node_id
        self.uri = uri
        self.pending = {}

    async def connect(self):
        self.ws = await websockets.connect(self.uri)
        await self.ws.send(json.dumps({"node_id": self.node_id}))
        asyncio.create_task(self.listen())

    async def listen(self):
        async for message in self.ws:
            data = json.loads(message)
            print(f"[{self.node_id}] Received_1:", data)
            if "rpc" in data:
                result = await self.handle_rpc(data["rpc"], data["args"])
                print("[nodeA] Got result:", result)
                await self.ws.send(json.dumps({
                    "target": data["source"],
                    "rpc": "rpc_result",
                    "args": [data["rpc_id"], result],
                    "rpc_id": str(uuid.uuid4())  # new ID
                }))
            elif data["rpc"] == "rpc_result":
                rpc_id, result = data["args"]
                fut = self.pending.pop(rpc_id, None)
                if fut:
                    fut.set_result(result)

    async def handle_rpc(self, name, args):
        if name == "ping":
            return f"Pong from {self.node_id}"
        # thêm các RPC khác tại đây
        return "rpc_result"

    async def call_rpc(self, target, name, args):
        rpc_id = str(uuid.uuid4())
        fut = asyncio.get_event_loop().create_future()
        self.pending[rpc_id] = fut
        await self.ws.send(json.dumps({
            "target": target,
            "rpc": name,
            "args": args,
            "rpc_id": rpc_id
        }))
        return await fut

# Test sample
async def main():
    client = RelayClient("nodeA", "ws://localhost:8765")
    # client = RelayClient("nodeA", "ws://42.96.12.119:8765")
    await client.connect()

    await asyncio.sleep(2)  # chờ nodeB kết nối relay
    result = await client.call_rpc("nodeB", "ping", [])
    print("[nodeA] Got result:", result)

asyncio.run(main())
