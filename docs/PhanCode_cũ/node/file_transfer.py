from fastapi import FastAPI, UploadFile, File
import aiofiles
import os

app = FastAPI()

received_chunks_dir = "received_chunks/"
os.makedirs(received_chunks_dir, exist_ok=True)

@app.post("/receive_chunk/")
async def receive_chunk(chunk_id: str = File(...), chunk_data: str = File(...)):
    """API nhận chunk từ các node khác."""
    try:
        chunk_bytes = bytes.fromhex(chunk_data)
        chunk_path = os.path.join(received_chunks_dir, f"{chunk_id}.chunk")
        async with aiofiles.open(chunk_path, 'wb') as f:
            await f.write(chunk_bytes)
        print(f"Received and saved chunk {chunk_id}")
        return {"status": "success"}
    except Exception as e:
        print(f"Failed to receive chunk {chunk_id}: {e}")
        return {"status": "failure", "error": str(e)}
