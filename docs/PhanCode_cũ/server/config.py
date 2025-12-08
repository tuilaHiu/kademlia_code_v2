
import os
MONGO_URI = "mongodb://localhost:27017"
DB_NAME = "p2p_storage"
COLLECTION_NAME = "peers"
SERVER_PORT = 8000
REPLICATION_FACTOR = 3
DEFAULT_PASSWORD = "123456789"
BOOTSTRAP_NODES_FILE = "bootstrap_nodes.json"
DEFAULT_PORT = 8468
# MONITORING_SERVER_URL = "http://localhost:8001/log/"
# config.py
MONITORING_SERVER_URL = "http://113.185.40.245:8001/monitor"  # Đảm bảo địa chỉ và cổng đúng
