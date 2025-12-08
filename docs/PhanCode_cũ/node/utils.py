import json
from config import BOOTSTRAP_NODES_FILE

async def find_nearest_nodes(server, key, count):
    """Tìm các node gần nhất dựa trên key."""
    closest = await server.getClosestNodes(key)
    return closest[:count]

def save_bootstrap_nodes_to_file(bootstrap_nodes):
    """Lưu danh sách bootstrap nodes vào file."""
    try:
        unique_nodes = list(set(bootstrap_nodes))
        with open(BOOTSTRAP_NODES_FILE, "w") as file:
            json.dump(unique_nodes, file, indent=4)
        print("Bootstrap nodes đã được lưu.")
    except Exception as e:
        print(f"Failed to save bootstrap nodes: {e}")

def load_bootstrap_nodes_from_file():
    """Lấy danh sách bootstrap nodes từ file."""
    try:
        with open(BOOTSTRAP_NODES_FILE, "r") as file:
            bootstrap_nodes = json.load(file)
            print(f"Đã tải bootstrap nodes: {bootstrap_nodes}")
            return bootstrap_nodes
    except FileNotFoundError:
        print("Không tìm thấy tệp bootstrap_nodes.json.")
        return []
    except Exception as e:
        print(f"Failed to load bootstrap nodes: {e}")
        return []

async def save_dht_to_file(server, fname):
    """Lưu DHT vào file."""
    try:
        keys = await server.storage.get_all_keys()
        dht_data = {}
        for key in keys:
            value = await server.get(key)
            dht_data[key] = value
        with open(fname, "w") as file:
            json.dump(dht_data, file, indent=4)
        print("DHT đã được lưu vào file.")
    except Exception as e:
        print(f"Failed to save DHT: {e}")

async def load_dht_from_file(server, fname):
    """Tải DHT từ file."""
    try:
        with open(fname, "r") as file:
            dht_data = json.load(file)
        for key, value in dht_data.items():
            await server.set(key, value)
        print("DHT đã được tải từ file.")
    except FileNotFoundError:
        print("Không tìm thấy tệp DHT để tải. Đang tạo DHT mới.")
    except Exception as e:
        print(f"Failed to load DHT: {e}")

def debug_routing_table(server):
    """Debug routing table của Kademlia."""
    try:
        routing_table = server.protocol.routing_table
        known_nodes = []
        for bucket in routing_table.buckets:
            for contact in bucket.contacts:
                known_nodes.append(contact)

        if known_nodes:
            print("Known nodes in routing table:")
            for node in known_nodes:
                print(f"Node: {node}")
        else:
            print("No known nodes in routing table.")
    except AttributeError as ae:
        print(f"AttributeError: {ae}")
    except Exception as e:
        print(f"Failed to debug routing table: {e}")
