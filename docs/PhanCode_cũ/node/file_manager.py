import os
import hashlib
import json
from kademlia.network import Server
from utils import find_nearest_nodes
import sys
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from node.main import ROUTING_TABLE_DEBUG

def split_file(file_path, chunk_size=1024*1024):
    """
    Chia nhỏ file thành các phần nhỏ.

    :param file_path: Đường dẫn tới file gốc.
    :param chunk_size: Kích thước mỗi phần (byte).
    :return: Danh sách các phần file.
    """
    chunks = []
    try:
        with open(file_path, 'rb') as f:
            while True:
                chunk = f.read(chunk_size)
                if not chunk:
                    break
                chunks.append(chunk)
        print(f"File {file_path} đã được chia thành {len(chunks)} phần.")
    except Exception as e:
        print(f"Failed to split file: {e}")
    return chunks

async def store_file_chunks_in_dht(server: Server, file_chunks):
    """
    Lưu các phần file vào DHT.

    :param server: Kademlia server instance.
    :param file_chunks: Danh sách các phần file.
    :return: Hash của file đã upload.
    """
    chunk_hashes = []
    for idx, chunk in enumerate(file_chunks):
        chunk_hash = hashlib.sha256(chunk).hexdigest()
        key = f"file_chunk_{chunk_hash}"
        await server.set(key, chunk.hex()) 
        chunk_hashes.append(chunk_hash)
        print(f"Lưu phần {idx+1}: Hash = {chunk_hash}")
    file_hash = hashlib.sha256("".join(chunk_hashes).encode()).hexdigest()
    await server.set("file_hash", file_hash)
    await server.set(f"file_chunks_{file_hash}", json.dumps(chunk_hashes))
    print(f"Đã lưu danh sách các hash file với file_hash = {file_hash}")
    return file_hash

async def get_file_chunks_from_dht(server: Server, file_hash):
    """
    Lấy các phần file từ DHT.

    :param server: Kademlia server instance.
    :param file_hash: Hash của file gốc.
    :return: Danh sách các phần file.
    """
    try:
        chunks_json = await server.get(f"file_chunks_{file_hash}")
        if not chunks_json:
            print("Không tìm thấy danh sách các phần file trong DHT.")
            return []
        chunk_hashes = json.loads(chunks_json)
        file_chunks = []
        for chunk_hash in chunk_hashes:
            chunk_hex = await server.get(f"file_chunk_{chunk_hash}")
            if chunk_hex:
                file_chunks.append(bytes.fromhex(chunk_hex))
                print(f"Đã tải phần file với hash = {chunk_hash}")
            else:
                print(f"Không tìm thấy phần file với hash = {chunk_hash}")
        return file_chunks
    except Exception as e:
        print(f"Failed to get file chunks from DHT: {e}")
        return []

def join_file_chunks(file_chunks, output_path):
    """
    Ghép lại các phần file thành file gốc.

    :param file_chunks: Danh sách các phần file.
    :param output_path: Đường dẫn tới file đầu ra.
    """
    try:
        with open(output_path, 'wb') as f:
            for chunk in file_chunks:
                f.write(chunk)
        print(f"Đã ghép lại file thành công tại {output_path}.")
    except Exception as e:
        print(f"Failed to join file chunks: {e}")

def debug_routing_table(server: Server):
    """Debug routing table của Kademlia."""
    try:
        routing_table = server.protocol.routing_table
        known_nodes = []
        for bucket in routing_table.buckets:
            for contact in bucket.contacts:
                known_nodes.append(contact)

        if known_nodes:
            print(ROUTING_TABLE_DEBUG)
            for node in known_nodes:
                print(f"Node: {node}")
        else:
            print("No known nodes in routing table.")
    except AttributeError as ae:
        print(f"AttributeError: {ae}")
    except Exception as e:
        print(f"Failed to debug routing table: {e}")

def load_dht_from_file(server, filename):
    # Kiểm tra nếu file không tồn tại
    if not os.path.exists(filename):
        print(f"File {filename} không tồn tại. Tạo file mới.")
        with open(filename, 'w') as file:
            json.dump({}, file)  # Tạo file rỗng
    
    # Đọc nội dung từ file
    with open(filename, 'r') as file:
        dht_data = json.load(file)
    
    # Cập nhật server nếu cần
    if server:
        server.update_routing_table(dht_data)
    
    return dht_data

