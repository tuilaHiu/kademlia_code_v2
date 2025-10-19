#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
RelayServer — forward UDP payload giữa các node qua WebSocket.

📌 Chức năng:
- Mỗi Node (A, B, …) kết nối tới RelayServer qua WebSocket và đăng ký `node_id`.
- Khi Node A gửi RPC (dưới dạng datagram base64) đến Node B:
  Relay sẽ forward nguyên gói dữ liệu tới Node B mà không phân tích nội dung.
- Node B xử lý datagram, có thể gửi phản hồi ngược lại (dưới dạng datagram base64).

📌 Cấu trúc message JSON:
- Từ Node gửi đi:
    {
        "node_id": "nodeA",            # chỉ khi connect
        "target": "nodeB",             # node đích
        "rpc": "udp_forward",          # hành động
        "rpc_id": "<uuid>",            # id để match response
        "payload_b64": "<base64>"      # datagram nhị phân (UDP gốc)
    }

- Relay forward nguyên bản cho nodeB:
    {
        "source": "nodeA",
        "rpc": "udp_forward",
        "rpc_id": "<uuid>",
        "payload_b64": "<base64>"
    }

📌 Cách chạy:
Terminal 1: python relay_server.py
Terminal 2: nodeB kết nối tới relay
Terminal 3: nodeA kết nối và gửi gói forward tới nodeB

📌 Lưu ý:
- Relay chỉ giữ vai trò transport trung gian (WebSocket).
- Không giải mã msgpack, không xử lý logic RPC.
"""

import asyncio
import json
import logging
import websockets

# -----------------------------------------------------------------------------
# Logging setup
# -----------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("RelayServer")


# -----------------------------------------------------------------------------
# RelayServer class
# -----------------------------------------------------------------------------
class RelayServer:
    def __init__(self, host: str = "0.0.0.0", port: int = 8765):
        self.host = host
        self.port = port
        self.connections = {}  # node_id -> websocket

    async def _register_node(self, websocket) -> str:
        """
        Nhận message đầu tiên từ client để đăng ký node_id.
        """
        try:
            init = await asyncio.wait_for(websocket.recv(), timeout=10.0)
            data = json.loads(init)
            node_id = data.get("node_id")
            if not node_id:
                await websocket.close()
                return None
            if node_id in self.connections:
                log.warning(f"[Relay] Node {node_id} đã tồn tại, thay thế kết nối cũ.")
                old_ws = self.connections.pop(node_id)
                await old_ws.close()
            self.connections[node_id] = websocket
            log.info(f"[Relay] ✅ Node '{node_id}' connected ({len(self.connections)} total)")
            return node_id
        except asyncio.TimeoutError:
            log.warning("Client không gửi node_id trong 10s → đóng kết nối.")
        except Exception as e:
            log.error(f"Lỗi khi đăng ký node: {e}")
        return None

    async def _forward_message(self, src_id: str, data: dict):
        """
        Forward message từ src_id → target_id.
        """
        target_id = data.get("target")
        if not target_id:
            log.warning(f"[Relay] Bỏ qua message thiếu 'target' từ {src_id}")
            return

        # Tạo message forward
        msg = {
            "source": src_id,
            "rpc": data.get("rpc", "udp_forward"),
            "rpc_id": data.get("rpc_id"),
            "payload_b64": data.get("payload_b64"),
        }

        # Forward cho target nếu online
        target_ws = self.connections.get(target_id)
        if target_ws:
            try:
                await target_ws.send(json.dumps(msg))
                log.debug(f"[Relay] {src_id} → {target_id} ({len(data.get('payload_b64',''))} bytes b64)")
            except Exception as e:
                log.warning(f"[Relay] gửi tới {target_id} lỗi: {e}")
        else:
            log.warning(f"[Relay] ❌ Target '{target_id}' chưa online (từ {src_id})")

    async def handler(self, websocket):
        """
        Xử lý một client WebSocket.
        """
        node_id = await self._register_node(websocket)
        if not node_id:
            return

        try:
            async for message in websocket:
                try:
                    data = json.loads(message)
                    # Loại bỏ echo tự gửi
                    if not isinstance(data, dict):
                        continue
                    # Chuyển tiếp payload
                    await self._forward_message(node_id, data)
                except json.JSONDecodeError:
                    log.warning(f"[Relay] JSON lỗi từ {node_id}")
                except Exception as e:
                    log.exception(f"Lỗi xử lý message từ {node_id}: {e}")

        except websockets.ConnectionClosed:
            pass
        finally:
            # cleanup
            if node_id:
                self.connections.pop(node_id, None)
                log.info(f"[Relay] 🔌 Node '{node_id}' disconnected. ({len(self.connections)} left)")

    async def run(self):
        """
        Chạy relay server (blocking).
        """
        log.info(f"[Relay] Running WebSocket relay on ws://{self.host}:{self.port}")
        async with websockets.serve(self.handler, self.host, self.port):
            await asyncio.Future()  # run forever


# -----------------------------------------------------------------------------
# Entry point
# -----------------------------------------------------------------------------
if __name__ == "__main__":
    try:
        asyncio.run(RelayServer().run())
    except KeyboardInterrupt:
        log.info("Relay server stopped by user.")
