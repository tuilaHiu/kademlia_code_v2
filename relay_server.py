# relay_server.py
# Dưới đây là một thiết kế đầy đủ giúp bạn thực hiện RPC qua relay WebSocket, trong đó:
# các Node  sẽ kết nối đến RelayServer qua WebSocket.
# Khi Node A muốn gọi RPC đến Node B, nó gửi yêu cầu qua RelayServer.
# RelayServer chuyển tiếp message cho Node B.
# Node B xử lý RPC và gửi kết quả ngược lại qua RelayServer → Node A.
# Chạy thử nghiệm
# Terminal 1: python relay_server.py
# Trminal 2: python node.py với "node_id": "nodeB"
# Terminal 3: python node.py với "node_id": "nodeA" và thực hiện call_rpc("nodeB", ...)
# Ưu điểm
# RPC từ node A đến B diễn ra qua relay WebSocket mà không cần node B gọi ngược lại.
# Relay không cần xử lý logic RPC, chỉ forward gói tin.
# Kết quả được trả lại đầy đủ thông qua relay.

# 1. Relay Server (chuyển tiếp gói tin)

import asyncio
import json
import websockets

class RelayServer:
    def __init__(self):
        self.connections = {}  # node_id -> websocket

    async def handler(self, websocket):
        node_id = None
        try:
            init = await websocket.recv()
            data = json.loads(init)
            node_id = data.get("node_id")
            if not node_id:
                return await websocket.close()
            self.connections[node_id] = websocket
            print(f"[Relay] {node_id} connected")

            async for message in websocket:
                data = json.loads(message)
                target = data.get("target")
                if target in self.connections:
                    await self.connections[target].send(json.dumps({
                        "source": node_id,
                        "rpc": data["rpc"],
                        "args": data["args"],
                        "rpc_id": data["rpc_id"]
                    }))
        except:
            pass
        finally:
            if node_id:
                self.connections.pop(node_id, None)
                print(f"[Relay] {node_id} disconnected")

    async def run(self):
        print("[Relay] Running...")
        async with websockets.serve(self.handler, "0.0.0.0", 8765):
            await asyncio.Future()

if __name__ == "__main__":
    asyncio.run(RelayServer().run())
