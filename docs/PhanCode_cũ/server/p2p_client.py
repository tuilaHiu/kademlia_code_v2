# p2p_client.py

import asyncio
from kademlia.network import Server
from config import BOOTSTRAP_NODES_FILE, DEFAULT_PORT, MONITORING_SERVER_URL
from utils import load_bootstrap_nodes_from_file
from replication import ReplicationManager
from pymongo import MongoClient
import aiohttp
import json
import os
import aiofiles

class P2PClient:
    def __init__(self):
        self.server = Server()
        self.replication_manager = None
        self.mongo_client = MongoClient()
        self.db = self.mongo_client["p2p_storage"]
        self.collection = self.db["peers"]
        self.monitoring_url = MONITORING_SERVER_URL

    async def start(self):
        bootstrap_nodes = load_bootstrap_nodes_from_file()
        await self.server.listen(DEFAULT_PORT)
        if bootstrap_nodes:
            bootstrap_list = []
            for node in bootstrap_nodes:
                ip, port_str = node.split(":")
                bootstrap_list.append((ip, int(port_str)))
            try:
                await self.server.bootstrap(bootstrap_list)
                print("Connected to bootstrap nodes.")
            except Exception as e:
                print(f"Failed to connect to bootstrap nodes: {e}")
        else:
            print("No bootstrap nodes available. This node is a bootstrap node.")

        self.replication_manager = ReplicationManager(self.server)

    async def send_chunk(self, chunk_id, chunk_data):
        """Gửi chunk tới các node khác."""
        await self.replication_manager.replicate_chunk(chunk_data, chunk_id)

    async def receive_chunk(self, chunk_id, chunk_data):
        """Nhận chunk từ các node khác."""
        received_chunks_dir = 'received_chunks/'
        os.makedirs(received_chunks_dir, exist_ok=True)
        chunk_path = os.path.join(received_chunks_dir, f"{chunk_id}.chunk")
        async with aiofiles.open(chunk_path, 'wb') as f:
            await f.write(bytes.fromhex(chunk_data))
        print(f"Received and saved chunk {chunk_id}")
        # Ghi nhận hoạt động
        await self.log_activity(f"received_chunks/{chunk_id}.chunk", "receive_chunk", chunk_id)

    async def log_activity(self, file_path, action, chunk_id):
        """Ghi nhận hoạt động lên Server Giám Sát."""
        async with aiohttp.ClientSession() as session:
            payload = {
                "node_id": "client",
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
