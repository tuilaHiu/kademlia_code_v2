from kademlia.utils import digest

# Định nghĩa cổng và địa chỉ cho từng node
BOOTSTRAP_HOST = "127.0.0.1"
NODE_A_HOST = "127.0.0.1"
NODE_B_HOST = "127.0.0.1"

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

# Metadata tối thiểu cho từng node (có thể mở rộng khi cần NAT/Relay)
BOOTSTRAP_META = {"node_id": "bootstrap", "nat": "Open Internet"}
NODE_A_META = {"node_id": "nodeA", "nat": "Open Internet"}
NODE_B_META = {"node_id": "nodeB", "nat": "Open Internet"}
