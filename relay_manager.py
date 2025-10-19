import asyncio, json, base64, uuid, logging, websockets, umsgpack
from websockets.protocol import State as WebSocketState

log = logging.getLogger(__name__)


class RelayManager:
    """
    Quản lý kết nối WebSocket tới relay trung gian để forward/nhận datagram UDP.

    - forward_udp_rpc: gửi nguyên datagram UDP tới node đích qua relay.
    - send_udp_response: gửi lại datagram phản hồi cho node đã gửi yêu cầu qua relay.
    - attach_protocol: cho phép relay đẩy trực tiếp datagram vào protocol Kademlia.
    """

    def __init__(self, node_id: str, relay_uri: str):
        self.node_id = node_id
        self.uri = relay_uri
        self.pending = {}
        self.incoming = {}
        self.ws = None
        self.protocol = None
        self._listen_task = None

    def attach_protocol(self, proto):
        self.protocol = proto

    async def connect(self):
        if self.ws:
            return
        self.ws = await websockets.connect(self.uri)
        await self.ws.send(json.dumps({"node_id": self.node_id}))
        self._listen_task = asyncio.create_task(self._listen())
        log.info(f"[RelayManager] Connected as {self.node_id}")

    async def _listen(self):
        try:
            async for message in self.ws:
                data = json.loads(message)
                src = data.get("source")
                rpc_id = data.get("rpc_id")
                payload_b64 = data.get("payload_b64")

                if data.get("rpc") == "udp_forward" and payload_b64:
                    raw = base64.b64decode(payload_b64)
                    msg_id = raw[1:21]
                    if rpc_id:
                        self.incoming[msg_id] = {"rpc_id": rpc_id, "source": src}
                    log.debug(
                        "[%s] received UDP datagram from %s via relay (len=%d)",
                        self.node_id,
                        src,
                        len(raw),
                    )

                    # forward vào RPCProtocol xử lý
                    if self.protocol and hasattr(self.protocol, "datagram_received"):
                        self.protocol.datagram_received(raw, (src, 0))  # (0) = dummy port
                    else:
                        log.warning(
                            "[RelayManager] Protocol not attached or missing datagram_received"
                        )

                elif data.get("rpc") == "udp_response" and payload_b64:
                    fut = self.pending.pop(rpc_id, None)
                    if fut and not fut.done():
                        fut.set_result(base64.b64decode(payload_b64))
                else:
                    log.debug(
                        "[RelayManager] Ignoring unsupported relay message: %s",
                        data.get("rpc"),
                    )
        except websockets.ConnectionClosed:
            log.warning("[RelayManager] Relay connection closed")
        except Exception as exc:
            log.exception("[RelayManager] Error while listening relay: %s", exc)
        finally:
            self._cleanup_after_disconnect()

    def _cleanup_after_disconnect(self):
        if self.ws:
            try:
                asyncio.create_task(self.ws.close())
            except Exception:
                pass
        self.ws = None
        task = self._listen_task
        if task and not task.done() and task is not asyncio.current_task():
            task.cancel()
        self._listen_task = None
        # fail all pending futures
        for rpc_id, fut in list(self.pending.items()):
            if not fut.done():
                fut.set_result(None)
            self.pending.pop(rpc_id, None)
        self.incoming.clear()

    def is_connected(self) -> bool:
        ws = self.ws
        if ws is None:
            return False
        state = getattr(ws, "state", None)
        if state is not None:
            return state is WebSocketState.OPEN
        closed = getattr(ws, "closed", None)
        if isinstance(closed, bool):
            return not closed
        if callable(closed):
            try:
                return not closed()
            except TypeError:
                pass
        open_attr = getattr(ws, "open", None)
        if isinstance(open_attr, bool):
            return open_attr
        if callable(open_attr):
            try:
                return bool(open_attr())
            except TypeError:
                pass
        return True

    async def ensure_connected(self):
        if not self.is_connected():
            await self.connect()

    async def send_udp_response(self, msg_id: bytes, txdata: bytes) -> bool:
        """
        Gửi datagram phản hồi tương ứng với msg_id tới node nguồn qua relay.
        """
        if not self.is_connected():
            raise RuntimeError("RelayManager not connected")

        info = self.incoming.get(msg_id)
        if not info:
            log.debug(
                "[RelayManager] No relay record for msg_id=%s; fallback UDP",
                base64.b64encode(msg_id).decode(),
            )
            return False

        msg = {
            "target": info.get("source"),
            "rpc": "udp_response",
            "rpc_id": info.get("rpc_id"),
            "payload_b64": base64.b64encode(txdata).decode(),
        }
        await self.ws.send(json.dumps(msg))
        # chỉ pop sau khi send thành công
        self.incoming.pop(msg_id, None)
        return True

    async def forward_udp_rpc(self, node, txdata: bytes, timeout: float = 5.0):
        """
        Forward nguyên datagram (txdata) đến node qua relay websocket.
        """
        if not self.ws:
            raise RuntimeError("RelayManager not connected")

        rpc_id = str(uuid.uuid4())
        fut = asyncio.get_event_loop().create_future()
        self.pending[rpc_id] = fut

        msg = {
            "target": node.meta.get("node_id", node.id.hex()[:8]),
            "rpc": "udp_forward",
            "rpc_id": rpc_id,
            "payload_b64": base64.b64encode(txdata).decode(),
        }

        await self.ws.send(json.dumps(msg))
        try:
            data = await asyncio.wait_for(fut, timeout=timeout)
            if data is None:
                raise asyncio.TimeoutError()
            if len(data) < 22 or data[:1] != b"\x01":
                log.warning("[RelayManager] Unexpected relay response format (len=%d)", len(data))
                return (True, data)
            response_payload = umsgpack.unpackb(data[21:])
            return (True, response_payload)
        except asyncio.TimeoutError:
            log.warning(f"[RelayManager] Timeout relay {rpc_id}")
            return None
