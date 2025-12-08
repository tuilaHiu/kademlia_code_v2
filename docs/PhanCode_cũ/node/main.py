# main.py

import asyncio
import os
import hashlib
from config import (
    MONGO_URI, DB_NAME, COLLECTION_NAME, DEFAULT_PASSWORD, DEFAULT_PORT, MONITORING_SERVER_URL
)
from authentication import create_peer_id, verify_auth_code
from dht_manager import create_kademlia_node, get_public_ip_and_port
from replication import ReplicationManager
from pymongo import MongoClient
from datetime import datetime
import signal
import sys
import threading
import traceback

from utils import load_bootstrap_nodes_from_file, save_bootstrap_nodes_to_file, save_dht_to_file, load_dht_from_file, debug_routing_table
from file_transfer import app as file_transfer_app

from fastapi import FastAPI
import uvicorn
# from file_manager import load_dht_from_file

import aiohttp  # Thêm thư viện aiohttp để gọi API

# Thông điệp thông báo
BOOTSTRAP_NODE_CREATED = "Bootstrap node created at {ip}:{port}."
BOOTSTRAP_NODE_ADDED = "Bootstrap node mới được thêm vào: {ip}:{port}."
PASSWORD_INCORRECT = "Mật khẩu không chính xác."
NOT_BOOTSTRAP_NODE = "Đây không phải là bootstrap node."
PEER_ID_CREATED = "Peer ID đã được tạo cho {username}: {peer_id}."
PEER_ALREADY_EXISTS = "Peer đã tồn tại trong cơ sở dữ liệu."
PEER_SAVED = "Peer đã được lưu vào cơ sở dữ liệu."
DHT_SAVED = "DHT đã được lưu vào file."
DHT_LOADED = "DHT đã được tải từ file."
ROUTING_TABLE_DEBUG = "Debug routing table."
API_CALL_SUCCESS = "Đã gọi API lưu trữ thành công."
API_CALL_FAILED = "Gọi API lưu trữ thất bại: {error}"

# Khởi tạo biến toàn cục để lưu server
server_instance = None

def get_username():
    """Hàm lấy username từ người dùng."""
    username = input("Nhập Username: ").strip()
    return username

def save_peer_to_mongo(peer_id):
    """Lưu peerId vào MongoDB."""
    try:
        client = MongoClient(MONGO_URI)
        db = client[DB_NAME]
        collection = db[COLLECTION_NAME]

        existing_peer = collection.find_one({"peerId": peer_id})
        if existing_peer:
            print(PEER_ALREADY_EXISTS)
        else:
            peer_data = {
                "peerId": peer_id,
                "lastPingTime": datetime.utcnow()
            }
            collection.insert_one(peer_data)
            print(PEER_SAVED)
    except Exception as e:
        print(f"Failed to save peer to MongoDB: {e}")

async def call_save_peer_api(peer_id, ip, port):
    """Gọi API để lưu peerID và thông tin cơ sở dữ liệu."""
    api_url = f"{MONITORING_SERVER_URL}/save_peer/"  # Đảm bảo đường dẫn đúng
    payload = {
        "peer_id": peer_id,
        "ip": ip,
        "port": port
    }
    headers = {
        "Content-Type": "application/json"
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(api_url, json=payload, headers=headers) as response:
                if response.status == 200:
                    print(API_CALL_SUCCESS)
                else:
                    error_text = await response.text()
                    print(API_CALL_FAILED.format(error=error_text))
    except Exception as e:
        print(API_CALL_FAILED.format(error=e))

async def handle_bootstrap_node_and_create_peer():
    """Xử lý bootstrap node và khởi tạo peer."""
    bootstrap_nodes = load_bootstrap_nodes_from_file()

    if len(bootstrap_nodes) == 0:
        bind_ip, bind_port = get_public_ip_and_port()
        bootstrap_node = f"{bind_ip}:{bind_port}"
        bootstrap_nodes.append(bootstrap_node)
        print(BOOTSTRAP_NODE_CREATED.format(ip=bind_ip, port=bind_port))
        save_bootstrap_nodes_to_file(bootstrap_nodes)
    else:
        is_bootstrap = input("Is this a bootstrap node? (yes/no): ").strip().lower()
        if is_bootstrap == 'yes':
            while True:
                password = input("Enter password to add to bootstrap nodes: ")
                if verify_auth_code(password, DEFAULT_PASSWORD):
                    bind_ip, bind_port = get_public_ip_and_port()
                    new_node = f"{bind_ip}:{bind_port}"
                    if new_node not in bootstrap_nodes:
                        bootstrap_nodes.append(new_node)
                        print(BOOTSTRAP_NODE_ADDED.format(ip=bind_ip, port=bind_port))
                        save_bootstrap_nodes_to_file(bootstrap_nodes)
                    else:
                        print("Bootstrap node đã tồn tại trong danh sách.")
                    break
                else:
                    print(PASSWORD_INCORRECT)
        else:
            print(NOT_BOOTSTRAP_NODE)

    server, bind_ip, bind_port = await create_kademlia_node(bootstrap_nodes, port=DEFAULT_PORT)
    return server, bind_ip, bind_port

async def upload_file(server, file_path, replication_manager):
    """Upload một file lên mạng P2P."""
    from file_manager import split_file, store_file_chunks_in_dht

    file_chunks = split_file(file_path, chunk_size=1024*1024)
    if not file_chunks:
        print("Không thể chia nhỏ file.")
        return None
    file_hash = await store_file_chunks_in_dht(server, file_chunks)
    print(f"File đã được upload với file_hash = {file_hash}")

    for chunk in file_chunks:
        chunk_id = hashlib.sha256(chunk).hexdigest()
        await replication_manager.replicate_chunk(chunk, chunk_id)
    return file_hash

async def download_file(server, file_hash, output_path):
    """Download một file từ mạng P2P."""
    from file_manager import get_file_chunks_from_dht, join_file_chunks

    file_chunks = await get_file_chunks_from_dht(server, file_hash)
    if not file_chunks:
        print("Không thể tải các phần file.")
        return
    join_file_chunks(file_chunks, output_path)
    print(f"File đã được download và lưu tại {output_path}.")

def signal_handler(loop):
    """Hàm xử lý tín hiệu thoát."""
    print("Đang thoát và lưu trạng thái DHT...")
    if server_instance:
        asyncio.run_coroutine_threadsafe(save_dht_to_file(server_instance, "dht_data.json"), loop)
    asyncio.run_coroutine_threadsafe(shutdown(loop), loop)

async def save_dht_on_exit(server):
    """Lưu DHT vào file."""
    from utils import save_dht_to_file

    try:
        await save_dht_to_file(server, "dht_data.json")
        print(DHT_SAVED)
    except Exception as e:
        print(f"Failed to save DHT: {e}")

async def shutdown(loop):
    """Shutdown the event loop."""
    await asyncio.sleep(2)
    loop.stop()
    sys.exit(0)

async def main():
    """Hàm chính."""
    global server_instance
    server, bind_ip, bind_port = await handle_bootstrap_node_and_create_peer()
    server_instance = server

    # Lấy username và tạo peer_id
    username = get_username()
    peer_id = create_peer_id(username)
    print(PEER_ID_CREATED.format(username=username, peer_id=peer_id))

    # Lưu peer_id vào MongoDB
    save_peer_to_mongo(peer_id)

    # Gọi API để lưu peer_id và thông tin node
    await call_save_peer_api(peer_id, bind_ip, bind_port)

    replication_manager = ReplicationManager(server)

    debug_routing_table(server)

    while True:
        action = input("Do you want to upload or download a file? (upload/download/exit): ").strip().lower()
        if action == 'upload':
            file_path = input("Enter the path to the file you want to upload: ").strip()
            if os.path.isfile(file_path):
                await upload_file(server, file_path, replication_manager)
            else:
                print("File không tồn tại.")
        elif action == 'download':
            file_hash = input("Enter the file hash you want to download: ").strip()
            output_path = input("Enter the path to save the downloaded file: ").strip()
            await download_file(server, file_hash, output_path)
        elif action == 'exit':
            await save_dht_on_exit(server)
            print("Đang thoát chương trình.")
            break
        else:
            print("Hành động không hợp lệ. Vui lòng thử lại.")

if __name__ == "__main__":
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        if sys.platform != "win32":
            for sig in (signal.SIGINT, signal.SIGTERM):
                loop.add_signal_handler(sig, lambda: signal_handler(loop))
        else:
            # Trên Windows, không hỗ trợ loop.add_signal_handler
            # Sẽ xử lý qua KeyboardInterrupt
            pass

        loop.run_until_complete(main())

        def run_file_transfer():
            uvicorn.run(file_transfer_app, host="0.0.0.0", port=DEFAULT_PORT + 1) 

        file_transfer_thread = threading.Thread(target=run_file_transfer, daemon=True)
        file_transfer_thread.start()

        loop.run_forever()
    except KeyboardInterrupt:
        print("KeyboardInterrupt received. Shutting down...")
        if server_instance:
            try:
                loop.run_until_complete(save_dht_on_exit(server_instance))
            except Exception as e:
                print(f"Failed to save DHT during shutdown: {e}")
    except Exception as e:
        print(f"An error occurred: {e}")
        traceback.print_exc()
    finally:
        loop.close()
