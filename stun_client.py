import stun
import socket
# Tạo một STUN client
nat_type, external_ip, external_port = stun.get_ip_info()


print(f"Type of NAT: {nat_type}")
print(f"Public IP: {external_ip}")
print(f"External Port: {external_port}")

# them doan sau de kiem tra xem có phai Open Internet
# kiem tra neu local_Ip = External_IP thi la IP cong cong


def get_local_ip():
    """Lấy IP local (từ interface thực sự đang online)"""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        # Không cần kết nối thực sự, chỉ để lấy IP local
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    finally:
        s.close()

def check_nat_type():
    nat_type, external_ip, external_port = stun.get_ip_info()
    local_ip = get_local_ip()

    print("Local IP     :", local_ip)
    print("STUN IP      :", external_ip)
    print("STUN Port    :", external_port)
    print("STUN Result  :", nat_type)

    if external_ip == local_ip:
        print("✅ Bạn đang ở Open Internet (IP công cộng, không NAT)")
        return "Open Internet", external_ip, external_port
    else:
        print("❗ NAT type: ", nat_type)
        return nat_type, external_ip, external_port

# Gọi kiểm tra
check_nat_type()