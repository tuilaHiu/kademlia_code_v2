# database.py

from pymongo import MongoClient
from config import MONGO_URI, DB_NAME

# Kết nối tới MongoDB
client = MongoClient(MONGO_URI)
db = client[DB_NAME]

# Định nghĩa các collection riêng biệt
peers_collection = db["peers_id"]
activities_collection = db["activities"]
