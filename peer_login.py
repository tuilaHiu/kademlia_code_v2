"""Legacy-style temporary login helpers for node registration."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Mapping

import aiohttp
from pymongo import MongoClient
from pymongo.errors import PyMongoError

from authentication import create_peer_id
from config import COLLECTION_NAME, DB_NAME, MONGO_URI, MONITORING_SERVER_URL

log = logging.getLogger(__name__)

PEER_ALREADY_EXISTS = "Peer đã tồn tại trong cơ sở dữ liệu."
PEER_ID_CREATED = "Peer ID đã được tạo cho {username}: {peer_id}."
PEER_SAVED = "Peer đã được lưu vào cơ sở dữ liệu."
API_CALL_SUCCESS = "Đã gọi API lưu trữ thành công."
API_CALL_FAILED = "Gọi API lưu trữ thất bại: {error}"


def prompt_username(prompt: str = "Nhập Username: ") -> str:
    """Prompt for a username on stdin.

    Args:
        prompt: Prompt string shown to the user.

    Returns:
        Stripped username string.
    """
    return input(prompt).strip()


def resolve_advertised_ip(meta: Mapping[str, object], fallback_ip: str) -> str:
    """Resolve the IP address to report for monitoring.

    Args:
        meta: Metadata dictionary that may contain external/local IPs.
        fallback_ip: Fallback IP address if metadata is missing.

    Returns:
        The resolved IP address string.
    """
    external_ip = meta.get("external_ip")
    if isinstance(external_ip, str) and external_ip:
        return external_ip
    local_ip = meta.get("local_ip")
    if isinstance(local_ip, str) and local_ip:
        return local_ip
    return fallback_ip


def save_peer_to_mongo(peer_id: str) -> None:
    """Save a peer ID to MongoDB if it does not exist.

    Args:
        peer_id: Peer ID to store.
    """
    client = MongoClient(MONGO_URI)
    try:
        db = client[DB_NAME]
        collection = db[COLLECTION_NAME]

        existing_peer = collection.find_one({"peerId": peer_id})
        if existing_peer:
            log.info(PEER_ALREADY_EXISTS)
            return

        peer_data = {"peerId": peer_id, "lastPingTime": datetime.utcnow()}
        collection.insert_one(peer_data)
        log.info(PEER_SAVED)
    except PyMongoError as exc:
        log.error("Failed to save peer to MongoDB: %s", exc)
    finally:
        client.close()


async def call_save_peer_api(peer_id: str, ip: str, port: int) -> None:
    """Call the monitoring API to save peer registration data.

    Args:
        peer_id: Peer ID to report.
        ip: IP address to report.
        port: Port to report.
    """
    api_url = f"{MONITORING_SERVER_URL}/save_peer/"
    payload = {"peer_id": peer_id, "ip": ip, "port": port}
    headers = {"Content-Type": "application/json"}

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(api_url, json=payload, headers=headers) as response:
                if response.status == 200:
                    log.info(API_CALL_SUCCESS)
                else:
                    error_text = await response.text()
                    log.warning(API_CALL_FAILED.format(error=error_text))
    except aiohttp.ClientError as exc:
        log.warning(API_CALL_FAILED.format(error=exc))


async def login_and_register_peer(ip: str, port: int) -> str:
    """Prompt for username, create peer ID, and register it externally.

    Args:
        ip: IP address to report.
        port: Port to report.

    Returns:
        The generated peer ID.
    """
    username = prompt_username()
    peer_id = create_peer_id(username)
    log.info(PEER_ID_CREATED.format(username=username, peer_id=peer_id))
    save_peer_to_mongo(peer_id)
    await call_save_peer_api(peer_id, ip, port)
    return peer_id
