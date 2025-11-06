import os
from kademlia.utils import digest

# Định nghĩa cổng và địa chỉ cho từng node
BOOTSTRAP_HOST = os.getenv("BOOTSTRAP_HOST", "146.190.194.160")
NODE_B_HOST = os.getenv("NODE_B_HOST", "146.190.194.160")
NODE_A_HOST = os.getenv("NODE_A_HOST", "0.0.0.0")

BOOTSTRAP_PORT = 8468
NODE_A_PORT = 8469
NODE_B_PORT = 8470

BOOTSTRAP_ADDR = (BOOTSTRAP_HOST, BOOTSTRAP_PORT)
NODE_A_ADDR = (NODE_A_HOST, NODE_A_PORT)
NODE_B_ADDR = (NODE_B_HOST, NODE_B_PORT)

# Gán trước ID cho từng node để các script biết lẫn nhau
BOOTSTRAP_NODE_ID = digest(b"bootstrap-node")
NODE_A_ID = digest(b"node-a")
NODE_B_ID = digest(b"node-b")

# Cấu hình relay và STUN (có thể override qua biến môi trường)
RELAY_HOST = os.getenv("RELAY_HOST", "146.190.194.160")
RELAY_PORT = int(os.getenv("RELAY_PORT", "8765"))
RELAY_URI = os.getenv("RELAY_URI", f"ws://{RELAY_HOST}:{RELAY_PORT}")

STUN_HOST = os.getenv("STUN_HOST", "stun.l.google.com")
STUN_PORT = int(os.getenv("STUN_PORT", "19302"))

# Metadata tối thiểu cho từng node (sẽ được cập nhật động dựa trên NAT)
BASE_META = {"relay_uri": RELAY_URI} if RELAY_URI else {}

BOOTSTRAP_META = {**BASE_META, "node_id": "bootstrap"}
NODE_A_META = {**BASE_META, "node_id": "nodeA"}
NODE_B_META = {**BASE_META, "node_id": "nodeB"}

if RELAY_URI:
    BOOTSTRAP_META["use_relay"] = True
    NODE_A_META["use_relay"] = True
    NODE_B_META["use_relay"] = True

