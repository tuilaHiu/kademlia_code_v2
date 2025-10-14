import asyncio
import contextlib
import json
import logging
import uuid
from typing import Any, Dict, Iterable, Optional

import websockets

log = logging.getLogger(__name__)


def _encode_value(value: Any) -> Any:
    if isinstance(value, bytes):
        return {"__type": "bytes", "data": value.hex()}
    if isinstance(value, tuple):
        return {"__type": "tuple", "data": [_encode_value(v) for v in value]}
    if isinstance(value, list):
        return [_encode_value(v) for v in value]
    if isinstance(value, dict):
        return {str(k): _encode_value(v) for k, v in value.items()}
    return value


def _decode_value(value: Any) -> Any:
    if isinstance(value, dict):
        vtype = value.get("__type")
        if vtype == "bytes":
            return bytes.fromhex(value["data"])
        if vtype == "tuple":
            return tuple(_decode_value(item) for item in value["data"])
        # regular dict: decode nested values
        return {k: _decode_value(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_decode_value(v) for v in value]
    return value


class RelayManager:
    """Đơn giản hóa việc gửi RPC qua WebSocket relay."""

    def __init__(self, uri: str, node_id_hex: str):
        self._uri = uri
        self._node_id_hex = node_id_hex
        self._protocol = None
        self._ws: Optional[websockets.WebSocketClientProtocol] = None
        self._listener: Optional[asyncio.Task] = None
        self._pending: Dict[str, asyncio.Future] = {}
        self._lock = asyncio.Lock()
        self._connected_event = asyncio.Event()

    def attach_protocol(self, protocol) -> None:
        self._protocol = protocol

    async def connect(self) -> None:
        async with self._lock:
            if self._ws and not self._ws.close:
                return
            log.info("RelayManager connecting to %s", self._uri)
            self._ws = await websockets.connect(self._uri)
            await self._ws.send(
                json.dumps({"type": "register", "node_id": self._node_id_hex})
            )
            self._connected_event.set()
            if self._listener is None or self._listener.done():
                self._listener = asyncio.create_task(self._listen_loop())

    async def disconnect(self) -> None:
        async with self._lock:
            if self._ws and not self._ws.close:
                await self._ws.close()
            self._connected_event.clear()
        if self._listener:
            self._listener.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._listener
            self._listener = None

    async def ensure_connected(self) -> None:
        if self._ws and not self._ws.close:
            return
        await self.connect()

    async def _listen_loop(self) -> None:
        assert self._ws is not None
        try:
            async for message in self._ws:
                await self._handle_message(message)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("RelayManager listen loop terminated unexpectedly")
        finally:
            self._connected_event.clear()
            # fail pending futures
            while self._pending:
                _, future = self._pending.popitem()
                if not future.done():
                    future.set_result((False, {"error": "relay disconnected"}))

    async def _handle_message(self, message: str) -> None:
        try:
            payload = json.loads(message)
        except json.JSONDecodeError:
            log.warning("RelayManager received invalid JSON: %s", message)
            return
        mtype = payload.get("type")
        if mtype == "rpc_response":
            await self._handle_response(payload)
        elif mtype == "rpc_request":
            await self._handle_request(payload)
        else:
            log.debug("RelayManager ignoring message type %s", mtype)

    async def _handle_response(self, payload: Dict[str, Any]) -> None:
        msg_id = payload.get("id")
        future = self._pending.pop(msg_id, None)
        if not future:
            log.debug("RelayManager unknown response id %s", msg_id)
            return
        ok = bool(payload.get("ok"))
        result = _decode_value(payload.get("result"))
        if not future.done():
            future.set_result((ok, result))

    async def _handle_request(self, payload: Dict[str, Any]) -> None:
        if not self._protocol:
            log.debug("RelayManager has no protocol attached; dropping request")
            return
        rpc_name = payload.get("rpc")
        request_id = payload.get("id")
        sender_hex = payload.get("from")
        args = _decode_value(payload.get("args", []))
        handler = getattr(self._protocol, f"rpc_{rpc_name}", None)
        ok = False
        result: Any = {"error": "unknown rpc"}
        if handler is not None:
            address = ("relay", 0)
            try:
                maybe_coro = handler(address, *args)
                if asyncio.iscoroutine(maybe_coro):
                    result = await maybe_coro
                else:
                    result = maybe_coro
                ok = True
            except Exception:
                log.exception("RelayManager error in rpc_%s", rpc_name)
                ok = False
                result = {"error": "exception"}
        response = {
            "type": "rpc_response",
            "id": request_id,
            "rpc": rpc_name,
            "from": self._node_id_hex,
            "to": sender_hex,
            "ok": ok,
            "result": _encode_value(result),
        }
        await self._send_json(response)

    async def _send_json(self, payload: Dict[str, Any]) -> bool:
        try:
            await self.ensure_connected()
        except Exception:
            log.exception("RelayManager failed to connect before sending")
            return False
        if not self._ws or self._ws.close:
            return False
        try:
            await self._ws.send(json.dumps(payload))
            return True
        except Exception:
            log.exception("RelayManager failed to send payload")
            return False

    async def send_rpc(self, method: str, node, args: Iterable[Any]):
        """Gửi một RPC tới node qua relay."""
        await self.ensure_connected()
        if not self._ws or self._ws.close:
            return None
        msg_id = uuid.uuid4().hex
        loop = asyncio.get_event_loop()
        future = loop.create_future()
        self._pending[msg_id] = future
        payload = {
            "type": "rpc_request",
            "id": msg_id,
            "rpc": method,
            "from": self._node_id_hex,
            "to": getattr(node, "id", None).hex() if getattr(node, "id", None) else None,
            "args": _encode_value(list(args)),
        }
        if payload["to"] is None:
            future.cancel()
            self._pending.pop(msg_id, None)
            raise ValueError("Target node is missing id for relay RPC")
        sent = await self._send_json(payload)
        if not sent:
            self._pending.pop(msg_id, None)
            future.cancel()
            return None
        return await future
