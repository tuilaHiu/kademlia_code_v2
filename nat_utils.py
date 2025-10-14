import asyncio
import logging
import socket
from typing import Dict, Optional

import stun

log = logging.getLogger(__name__)


def _get_local_ip() -> Optional[str]:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("8.8.8.8", 80))
        return sock.getsockname()[0]
    except OSError:
        log.exception("Không thể xác định địa chỉ IP cục bộ")
        return None
    finally:
        sock.close()


def _detect_nat_sync(
    *,
    stun_host: Optional[str],
    stun_port: Optional[int],
    source_ip: str,
    source_port: int,
) -> Dict[str, Optional[str]]:
    kwargs = {}
    if stun_host:
        kwargs["stun_host"] = stun_host
    if stun_port:
        kwargs["stun_port"] = stun_port
    nat_type, external_ip, external_port = stun.get_ip_info(
        **kwargs, source_ip=source_ip or "0.0.0.0", source_port=source_port
    )
    return {
        "nat_type": nat_type,
        "external_ip": external_ip,
        "external_port": external_port,
    }


async def detect_nat_info(
    *,
    stun_host: Optional[str] = None,
    stun_port: Optional[int] = None,
    source_ip: Optional[str] = None,
    source_port: int = 54320,
) -> Dict[str, Optional[str]]:
    """Chạy STUN để lấy thông tin NAT và trả về dict metadata."""

    loop = asyncio.get_running_loop()
    local_ip = source_ip or _get_local_ip()

    def runner():
        return _detect_nat_sync(
            stun_host=stun_host,
            stun_port=stun_port,
            source_ip=source_ip or local_ip or "0.0.0.0",
            source_port=source_port,
        )

    try:
        nat_data = await loop.run_in_executor(None, runner)
    except Exception:
        log.exception("detect_nat_info thất bại")
        raise

    metadata: Dict[str, Optional[str]] = {
        "nat_type": nat_data.get("nat_type"),
        "external_ip": nat_data.get("external_ip"),
        "external_port": nat_data.get("external_port"),
        "local_ip": local_ip,
        "stun_host": stun_host,
        "stun_port": stun_port,
    }

    if metadata["external_ip"] and metadata["local_ip"]:
        metadata["is_nat"] = metadata["external_ip"] != metadata["local_ip"]
    elif metadata["nat_type"]:
        metadata["is_nat"] = metadata["nat_type"] != "Open Internet"
    else:
        metadata["is_nat"] = None

    if metadata.get("is_nat"):
        metadata["use_relay"] = True

    return metadata
