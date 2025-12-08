# dht_manager.py

import asyncio
from kademlia.network import Server
from config import BOOTSTRAP_NODES_FILE, DEFAULT_PORT
from utils import load_bootstrap_nodes_from_file
from stun import get_ip_info

def get_public_ip_and_port():
    """Trả về địa chỉ IP công khai và port để bind server sử dụng STUN."""
    try:
        # Gọi hàm get_ip_info và unpack kết quả trả về
        nat_type, external_ip, external_port = get_ip_info()
        public_ip = external_ip
        public_port = DEFAULT_PORT  # Bạn có thể sử dụng external_port nếu cần thiết
        print(f"Đã xác định IP công khai: {public_ip}")
        return public_ip, public_port
    except Exception as e:
        print(f"Lỗi khi lấy IP công khai qua STUN: {e}")
        return None, None

async def create_kademlia_node(bootstrap_nodes, port=DEFAULT_PORT):
    server = Server()
    bind_ip, bind_port = get_public_ip_and_port()
    
    if not bind_ip or not bind_port:
        print("Không thể xác định IP hoặc port để bind. Dừng khởi động node Kademlia.")
        return None, None, None 

    try:
        await server.listen(bind_port, interface=bind_ip)
        print(f"Server Kademlia đang lắng nghe tại {bind_ip}:{bind_port}")
    except Exception as e:
        print(f"Lỗi khi lắng nghe server Kademlia: {e}")
        return None, None, None

    if bootstrap_nodes:
        bootstrap_list = []
        for node in bootstrap_nodes:
            try:
                # Kiểm tra xem node có phải là dictionary hay không
                if isinstance(node, str):
                    # Nếu là chuỗi, chuyển đổi thành dictionary (giả sử định dạng là "ip:port")
                    ip, port = node.split(":")
                    node = {"ip": ip.strip(), "port": int(port.strip())}
                ip, port_num = node['ip'], node['port']
                bootstrap_list.append((ip, int(port_num)))
            except (ValueError, KeyError, AttributeError) as e:
                print(f"Định dạng node bootstrap không hợp lệ: {node}. Lỗi: {e}")
        try:
            await server.bootstrap(bootstrap_list)
            print("Kết nối đến các node bootstrap thành công.")
        except Exception as e:
            print(f"Không thể kết nối đến các node bootstrap: {e}")
    else:
        print("Không có node bootstrap. Đây là một node bootstrap.")
    return server, bind_ip, bind_port
