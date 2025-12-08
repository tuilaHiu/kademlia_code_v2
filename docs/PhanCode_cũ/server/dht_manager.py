# dht_manager.py

import asyncio
from kademlia.network import Server
from config import BOOTSTRAP_NODES_FILE, DEFAULT_PORT, REPLICATION_FACTOR, MONGO_URI
from utils import load_bootstrap_nodes_from_file
import logging

# Cấu hình logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def get_bind_ip():
    """Trả về địa chỉ IP và port để bind server."""
    try:
        # Bind lên tất cả các interface để các máy khác có thể kết nối
        bind_ip = '0.0.0.0'  
        bind_port = DEFAULT_PORT
        return bind_ip, bind_port
    except Exception as e:
        logger.error(f"Lỗi khi xác định IP để bind: {e}")
        return None, None

async def create_kademlia_node(bootstrap_nodes, port=DEFAULT_PORT):
    server = Server()
    bind_ip, bind_port = get_bind_ip()
    
    if not bind_ip or not bind_port:
        logger.error("Không thể xác định IP hoặc port để bind. Dừng khởi động node Kademlia.")
        return None, None, None  # Trả về None nếu không lấy được IP và port

    try:
        await server.listen(bind_port, interface=bind_ip)
        logger.info(f"Server Kademlia đang lắng nghe tại {bind_ip}:{bind_port}")
    except Exception as e:
        logger.error(f"Lỗi khi lắng nghe server Kademlia: {e}")
        return None, None, None

    if bootstrap_nodes:
        bootstrap_list = []
        for node in bootstrap_nodes:
            try:
                ip, port_num = node  # Sửa lại dòng này để unpack tuple
                bootstrap_list.append((ip, int(port_num)))
            except (ValueError, TypeError) as e:  # Sửa Exception để bao gồm TypeError
                logger.error(f"Định dạng node bootstrap không hợp lệ: {node}. Lỗi: {e}")
        try:
            await server.bootstrap(bootstrap_list)
            logger.info("Kết nối đến các node bootstrap thành công.")
        except Exception as e:
            logger.error(f"Không thể kết nối đến các node bootstrap: {e}")
    else:
        logger.info("Không có node bootstrap. Đây là một node bootstrap.")

    logger.info(f"Trả về server: {server}, bind_ip: {bind_ip}, bind_port: {bind_port}")
    return server, bind_ip, bind_port
