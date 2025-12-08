import hashlib
import base58

def create_peer_id(username):
    """Tạo peerId từ username bằng cách hash và mã hóa base58."""
    hashed = hashlib.sha256(username.encode()).digest()
    return base58.b58encode(hashed).decode()

def verify_auth_code(input_code, expected_code="123456789"):
    """Kiểm tra mã xác thực."""
    return input_code == expected_code
