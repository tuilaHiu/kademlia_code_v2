# utils.py

import json
from config import BOOTSTRAP_NODES_FILE
import hashlib
import os
import aiofiles

import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
# utils.py
# utils.py

def get_all_known_nodes(server, bootstrap_nodes=[]):
    """Lấy danh sách tất cả các node đang kết nối. Nếu không có, dùng bootstrap_nodes."""
    try:
        # Truy cập router từ server
        router = getattr(server, 'router', None)
        if not router:
            logger.warning("Cannot find 'router' attribute in server.")
            return bootstrap_nodes  # Fallback to bootstrap_nodes nếu không có router

        logger.info(f"Type of router: {type(router)}")

        known_nodes = []
        for bucket in router.buckets:
            logger.debug(f"Inspecting bucket: {bucket}")
            for contact in bucket.contacts:
                known_nodes.append((contact.host, contact.port))

        logger.info(f"Total known nodes: {len(known_nodes)}")
        return known_nodes

    except Exception as e:
        logger.error(f"Failed to get known nodes: {e}")
        return bootstrap_nodes 



def save_bootstrap_nodes_to_file(bootstrap_nodes):
    """Lưu danh sách bootstrap nodes vào file."""
    try:
        with open(BOOTSTRAP_NODES_FILE, "w") as file:
            json.dump(bootstrap_nodes, file, indent=4)
        print("Bootstrap nodes đã được lưu.")
    except Exception as e:
        print(f"Failed to save bootstrap nodes: {e}")

def load_bootstrap_nodes_from_file():
    """Lấy danh sách bootstrap nodes từ file."""
    try:
        with open(BOOTSTRAP_NODES_FILE, "r") as file:
            bootstrap_nodes = json.load(file)
            logger.info(f"Đã tải bootstrap nodes: {bootstrap_nodes}")
            return [(node['ip'], node['port']) for node in bootstrap_nodes]
    except FileNotFoundError:
        logger.warning("Không tìm thấy tệp bootstrap_nodes.json.")
        return []
    except Exception as e:
        logger.error(f"Failed to load bootstrap nodes: {e}")
        return []


def split_file(file_path, chunk_size=512):
    """Chia file thành các phần nhỏ."""
    try:
        with open(file_path, 'rb') as f:
            while True:
                chunk = f.read(chunk_size)
                if not chunk:
                    break
                yield chunk
    except Exception as e:
        print(f"Failed to split file: {e}")
        return []

async def store_file_chunks_in_dht(server, file_chunks):
    """Lưu các chunk vào DHT và lưu chunk trên đĩa."""
    try:
        file_hash = hashlib.sha256()
        os.makedirs("chunks/", exist_ok=True)  # Tạo thư mục chunks nếu chưa có
        for chunk in file_chunks:
            chunk_id = hashlib.sha256(chunk).hexdigest()
            chunk_path = os.path.join("chunks/", f"{chunk_id}.chunk")
            
            # Lưu chunk vào đĩa
            async with aiofiles.open(chunk_path, 'wb') as chunk_file:
                await chunk_file.write(chunk)
            print(f"Chunk {chunk_id} saved to {chunk_path}")
            
            # Lưu đường dẫn chunk vào DHT
            await server.set(chunk_id, chunk_path)
            print(f"Chunk {chunk_id} set in DHT với đường dẫn {chunk_path}")
            file_hash.update(chunk)
        return file_hash.hexdigest()
    except Exception as e:
        print(f"Failed to store file chunks in DHT: {e}")
        return None

async def save_dht_to_file(server, fname):
    """Lưu DHT vào file."""
    try:
        keys = await server.storage.get_all_keys()
        dht_data = {}
        for key in keys:
            value = await server.get(key)
            dht_data[key] = value
        with open(fname, "w") as file:
            json.dump(dht_data, file, indent=4)
        print("DHT đã được lưu vào file.")
    except Exception as e:
        print(f"Failed to save DHT: {e}")

async def load_dht_from_file(server, fname):
    """Tải DHT từ file."""
    try:
        with open(fname, "r") as file:
            dht_data = json.load(file)
        for key, value in dht_data.items():
            await server.set(key, value)
        print("DHT đã được tải từ file.")
    except FileNotFoundError:
        print("Không tìm thấy tệp DHT để tải. Đang tạo DHT mới.")
    except Exception as e:
        print(f"Failed to load DHT: {e}")

# utils.py

def debug_routing_table(server):
    """Debug routing table của Kademlia."""
    try:
        router = getattr(server, 'router', None)
        if not router:
            router = getattr(server.protocol, 'routing_table', None)
            if callable(router):
                router = router()  # Gọi hàm nếu 'routing_table' là một hàm

        if not router:
            print("Cannot find routing_table in server.")
            return

        known_nodes = []
        for bucket in router.buckets:
            for contact in bucket.contacts:
                known_nodes.append(contact)

        if known_nodes:
            print("Known nodes in routing table:")
            for node in known_nodes:
                print(f"Node: {node.host}:{node.port}")
        else:
            print("No known nodes in routing table.")
    except AttributeError as ae:
        print(f"AttributeError: {ae}")
    except Exception as e:
        print(f"Failed to debug routing table: {e}")

