# api.py

from fastapi import FastAPI, HTTPException
from database import peers_collection, activities_collection  # Import collection riêng biệt
from pydantic import BaseModel, Field
from datetime import datetime
from ipaddress import IPv4Address  # Import từ thư viện chuẩn

app = FastAPI()

# Mô hình dữ liệu cho endpoint /log/
class Activity(BaseModel):
    node_id: str = Field(..., example="node123")
    action: str = Field(..., example="upload")
    chunk_id: str = Field(..., example="chunk456")

# Mô hình dữ liệu cho endpoint /save_peer/
class SavePeer(BaseModel):
    peer_id: str = Field(..., example="peer789")
    ip: IPv4Address = Field(..., example="192.168.1.1")  # Sử dụng IPv4Address từ ipaddress
    port: int = Field(..., ge=1, le=65535, example=8000)

@app.post("/log/")
async def log_activity(activity: Activity):
    """
    API nhận hoạt động từ các node và lưu vào MongoDB.
    """
    try:
        activity_data = {
            "node_id": activity.node_id,
            "action": activity.action,
            "chunk_id": activity.chunk_id,
            "timestamp": datetime.utcnow()
        }
        activities_collection.insert_one(activity_data)  # Sử dụng collection activities
        return {"status": "success", "message": "Activity logged successfully."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to log activity: {str(e)}")

@app.post("/save_peer/")
async def save_peer(peer: SavePeer):
    """
    API nhận thông tin peer từ các node và lưu vào MongoDB.
    """
    try:
        # Kiểm tra xem peer_id đã tồn tại chưa
        existing_peer = peers_collection.find_one({"peerId": peer.peer_id})
        if existing_peer:
            raise HTTPException(status_code=400, detail="Peer đã tồn tại trong cơ sở dữ liệu.")

        # Tạo dữ liệu để lưu
        peer_data = {
            "peerId": peer.peer_id,
            "ip": str(peer.ip),
            "port": peer.port,
            "registered_at": datetime.utcnow()
        }

        # Lưu vào MongoDB
        peers_collection.insert_one(peer_data)  # Sử dụng collection peers
        return {"status": "success", "message": "Peer đã được lưu thành công."}
    except HTTPException as he:
        raise he
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to save peer: {str(e)}")
