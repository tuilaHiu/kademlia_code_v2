# main.py

import asyncio
from fastapi import FastAPI
import uvicorn
from dht_manager import create_kademlia_node
from replication import ReplicationManager
from utils import (
    load_bootstrap_nodes_from_file,
    save_bootstrap_nodes_to_file,
    load_dht_from_file,
    save_dht_to_file,
    debug_routing_table
)
from api import router as file_api
from config import DEFAULT_PORT, MONITORING_SERVER_URL
import signal
import sys
from contextlib import asynccontextmanager
import logging

# Cấu hình logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Context manager để quản lý các sự kiện khởi động và tắt ứng dụng."""
    try:
        # Sự kiện khởi động
        await startup_event(app)
        yield
    finally:
        # Sự kiện tắt
        await shutdown_event(app)

async def startup_event(app: FastAPI):
    """Sự kiện khởi động khi FastAPI bắt đầu."""
    try:
        bootstrap_nodes = load_bootstrap_nodes_from_file()
        logger.info(f"Đã tải bootstrap nodes: {bootstrap_nodes}")
        server, bind_ip, bind_port = await create_kademlia_node(bootstrap_nodes, port=DEFAULT_PORT)
        
        logger.info(f"Type of server: {type(server)}")
        logger.debug(f"Server attributes: {dir(server)}")
        
        if server is None:
            logger.error("Không thể khởi tạo node Kademlia. Dừng khởi động ứng dụng.")
            sys.exit(1)  # Kết thúc ứng dụng nếu không khởi tạo được node Kademlia

        # Lưu trữ server và replication_manager vào app.state
        app.state.server = server
        app.state.replication_manager = ReplicationManager(server)

        # Debug: Kiểm tra nội dung app.state
        logger.debug(f"app.state: {app.state}, type: {type(app.state)}")

        await load_dht_from_file(server, "dht_data.json")
        debug_routing_table(server)
        logger.info(f"Kademlia node started tại {bind_ip}:{bind_port}")
    except Exception as e:
        logger.error(f"Lỗi trong sự kiện khởi động: {e}")
        sys.exit(1)  # Kết thúc ứng dụng nếu có lỗi trong quá trình khởi động

async def shutdown_event(app: FastAPI):
    """Sự kiện đóng khi FastAPI tắt."""
    try:
        server = getattr(app.state, 'server', None)
        if server:
            await save_dht_to_file(server, "dht_data.json")
            logger.info("DHT đã được lưu vào file.")
        else:
            logger.warning("Không có server để lưu DHT.")
    except Exception as e:
        logger.error(f"Lỗi trong sự kiện tắt: {e}")

if __name__ == "__main__":
    # Tạo một FastAPI instance mới với lifespan context manager
    app = FastAPI(lifespan=lifespan)

    # Kết hợp các routes từ file_api vào app chính
    app.include_router(file_api)

    # Nếu bạn muốn giới hạn truy cập chỉ từ địa chỉ IP nội bộ, hãy sử dụng '127.0.0.1'
    # Nếu bạn muốn truy cập từ mọi địa chỉ, sử dụng '0.0.0.0'
    uvicorn.run(app, host="0.0.0.0", port=8000)
