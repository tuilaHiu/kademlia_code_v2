import asyncio
import hashlib
from utils import find_nearest_nodes
from config import REPLICATION_FACTOR, MONITORING_SERVER_URL
from pymongo import MongoClient
import aiohttp
import json

class ReplicationManager:
    def __init__(self, server):
        self.server = server
        self.mongo_client = MongoClient()
        self.db = self.mongo_client["p2p_storage"]
        self.collection = self.db["peers"]
        self.monitoring_url = MONITORING_SERVER_URL

    async def replicate_chunk(self, chunk_data, chunk_id):
        """Replicate chunk đến các node khác."""
        nearest_nodes = await find_nearest_nodes(self.server, chunk_id, REPLICATION_FACTOR)
        for node in nearest_nodes:
            ip, port = node
            await self.send_chunk_to_node(ip, port, chunk_id, chunk_data)
            await self.log_activity(f"{ip}:{port}", "replicate", chunk_id)

    async def send_chunk_to_node(self, ip, port, chunk_id, chunk_data):
        """Gửi chunk tới node cụ thể."""
        url = f"http://{ip}:{port}/receive_chunk/"
        try:
            async with aiohttp.ClientSession() as session:
                payload = {
                    "chunk_id": chunk_id,
                    "chunk_data": chunk_data.hex()
                }
                async with session.post(url, json=payload) as resp:
                    if resp.status == 200:
                        print(f"Chunk {chunk_id} replicated to {ip}:{port}")
                    else:
                        print(f"Failed to replicate chunk {chunk_id} to {ip}:{port}")
        except Exception as e:
            print(f"Error replicating chunk to {ip}:{port} - {e}")

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
                        print(f"Logged activity for chunk {chunk_id}")
                    else:
                        print(f"Failed to log activity for chunk {chunk_id}")
            except Exception as e:
                print(f"Error logging activity: {e}")
