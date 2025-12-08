# api.py

from fastapi import APIRouter, UploadFile, File, HTTPException, Request
from pymongo import MongoClient
from config import MONGO_URI, DB_NAME, COLLECTION_NAME
from replication import ReplicationManager
from utils import split_file, store_file_chunks_in_dht
import hashlib
import os
import aiofiles  # Import aiofiles để hỗ trợ I/O bất đồng bộ
from datetime import datetime
import logging

# Cấu hình logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

router = APIRouter()  # Sử dụng APIRouter thay vì FastAPI

# Kết nối tới MongoDB
client = MongoClient(MONGO_URI)
db = client[DB_NAME]
collection = db[COLLECTION_NAME]

@router.post("/uploadfile/")
async def upload_file_api(request: Request, file: UploadFile = File(...)):
    """API nhận file từ người dùng, chia nhỏ và phân phối đến các node."""
    try:
        # Ghi file vào thư mục tạm
        temp_dir = "uploads/"
        os.makedirs(temp_dir, exist_ok=True)
        temp_path = os.path.join(temp_dir, file.filename)
        
        async with aiofiles.open(temp_path, 'wb') as out_file:
            content = await file.read()
            await out_file.write(content)
        logger.info(f"File đã được tải lên: {temp_path}")

        # Chia file thành các phần nhỏ
        file_chunks = list(split_file(temp_path, chunk_size=512))  # 512 bytes mỗi chunk
        logger.info(f"File đã được chia thành {len(file_chunks)} phần.")
        if not file_chunks:
            raise HTTPException(status_code=500, detail="Failed to split file.")

        # Lấy replication_manager từ app.state
        replication_manager = getattr(request.app.state, 'replication_manager', None)
        if not replication_manager:
            logger.error("ReplicationManager không được khởi tạo.")
            raise HTTPException(status_code=500, detail="ReplicationManager không được khởi tạo.")

        # Lưu các chunk vào DHT
        file_hash = await store_file_chunks_in_dht(replication_manager.server, file_chunks)
        if not file_hash:
            raise HTTPException(status_code=500, detail="Failed to store file chunks in DHT.")
        logger.info(f"File đã được lưu vào DHT với file_hash = {file_hash}")

        # Lưu metadata vào MongoDB
        document = {
            "file_hash": file_hash,
            "file_name": file.filename,
            "uploaded_at": datetime.utcnow()
        }
        collection.insert_one(document)
        logger.info(f"File metadata đã được lưu vào MongoDB: {document}")

        # Replicate mỗi chunk
        for chunk in file_chunks:
            logger.debug(f"Processing chunk of size: {len(chunk)} bytes")
            chunk_id = hashlib.sha256(chunk).hexdigest()
            await replication_manager.replicate_chunk(chunk, chunk_id)

        # Xóa file tạm
        os.remove(temp_path)
        logger.info(f"File tạm đã được xóa: {temp_path}")

        return {"file_hash": file_hash}
    except Exception as e:
        logger.error(f"Failed to upload file: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/receive_chunk/")
async def receive_chunk_api(request: Request):
    """Endpoint để nhận chunk từ các node khác."""
    try:
        data = await request.json()
        chunk_id = data.get("chunk_id")
        chunk_data_hex = data.get("chunk_data")

        if not chunk_id or not chunk_data_hex:
            logger.error("Missing chunk_id or chunk_data.")
            raise HTTPException(status_code=400, detail="Missing chunk_id or chunk_data.")

        chunk_data = bytes.fromhex(chunk_data_hex)
        chunk_path = os.path.join("chunks/", f"{chunk_id}.chunk")

        # Lưu chunk vào đĩa
        os.makedirs("chunks/", exist_ok=True)  # Đảm bảo thư mục chunks tồn tại
        async with aiofiles.open(chunk_path, 'wb') as chunk_file:
            await chunk_file.write(chunk_data)
        logger.info(f"Received and saved chunk {chunk_id} vào {chunk_path}")

        # Lưu đường dẫn chunk vào DHT
        replication_manager = getattr(request.app.state, 'replication_manager', None)
        if replication_manager and replication_manager.server:
            await replication_manager.server.set(chunk_id, chunk_path)
            logger.info(f"Chunk {chunk_id} đã được set trong DHT với đường dẫn {chunk_path}")
        else:
            logger.warning("ReplicationManager hoặc server không được khởi tạo, không thể set chunk vào DHT.")

        return {"status": "success", "chunk_id": chunk_id}
    except Exception as e:
        logger.error(f"Failed to receive chunk: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/monitor")
async def monitor_activity(request: Request):
    """Endpoint để nhận log activities từ các node khác."""
    try:
        data = await request.json()
        node_id = data.get("node_id")
        action = data.get("action")
        chunk_id = data.get("chunk_id")

        if not node_id or not action or not chunk_id:
            logger.error("Missing node_id, action, or chunk_id.")
            raise HTTPException(status_code=400, detail="Missing node_id, action, or chunk_id.")

        # Lưu log vào MongoDB
        document = {
            "node_id": node_id,
            "action": action,
            "chunk_id": chunk_id,
            "timestamp": datetime.utcnow()
        }
        collection.insert_one(document)
        logger.info(f"Logged activity: {document}")

        return {"status": "success"}
    except Exception as e:
        logger.error(f"Failed to log activity: {e}")
        raise HTTPException(status_code=500, detail=str(e))
