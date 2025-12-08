# replication.py

import asyncio
import hashlib
from config import MONITORING_SERVER_URL
from pymongo import MongoClient
import aiohttp
import json
import os
from utils import get_all_known_nodes, load_bootstrap_nodes_from_file
import logging

# Cấu hình logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class ReplicationManager:
    def __init__(self, server):
        self.server = server
        self.bootstrap_nodes = load_bootstrap_nodes_from_file()  # Load bootstrap nodes
        self.mongo_client = MongoClient("mongodb://localhost:27017/")  # Đảm bảo MongoDB đang chạy và có thể kết nối
        self.db = self.mongo_client["p2p_storage"]
        self.collection = self.db["peers"]
        self.monitoring_url = MONITORING_SERVER_URL

    async def replicate_chunk(self, chunk_data, chunk_id):
        """Replicate chunk đến tất cả các node khác."""
        nodes = get_all_known_nodes(self.server, self.bootstrap_nodes)
        if not nodes:
            logger.warning("Không có node nào để replicate chunk.")
            return

        tasks = []
        for node in nodes:
            ip, port = node  # node là tuple (ip, port)
            tasks.append(self.send_chunk_to_node(ip, port, chunk_id, chunk_data))
            tasks.append(self.log_activity(f"{ip}:{port}", "replicate", chunk_id))
        
        await asyncio.gather(*tasks)

    async def send_chunk_to_node(self, ip, port, chunk_id, chunk_data):
        """Gửi chunk tới node cụ thể."""
        url = f"http://{ip}:8000/receive_chunk/"  # Đảm bảo rằng API trên node khác chạy trên cổng 8000
        try:
            async with aiohttp.ClientSession() as session:
                payload = {
                    "chunk_id": chunk_id,
                    "chunk_data": chunk_data.hex()  # Chuyển bytes thành hex string
                }
                async with session.post(url, json=payload) as resp:
                    if resp.status == 200:
                        logger.info(f"Chunk {chunk_id} replicated to {ip}:{port}")
                    else:
                        logger.error(f"Failed to replicate chunk {chunk_id} to {ip}:{port}, Status: {resp.status}")
        except Exception as e:
            logger.error(f"Error replicating chunk to {ip}:{port} - {e}")

    async def log_activity(self, node_id, action, chunk_id):
        """Ghi nhận hoạt động lên Server Giám Sát."""
        async with aiohttp.ClientSession() as session:
            payload = {
                "node_id": node_id,
                "action": action,
                "chunk_id": chunk_id
            }
            try:
                async with session.post(self.monitoring_url, json=payload) as resp:
                    if resp.status == 200:
                        logger.info(f"Logged activity for chunk {chunk_id}")
                    else:
                        logger.error(f"Failed to log activity for chunk {chunk_id}, Status: {resp.status}")
            except Exception as e:
                logger.error(f"Error logging activity: {e}")
