# test_stun.py

from stun import get_ip_info

def test_stun():
    try:
        nat_type, external_ip, external_port = get_ip_info(
            source_port=3478,
            stun_host='stun.l.google.com',
            stun_port=19302
        )
        print(f"NAT Type: {nat_type}")
        print(f"External IP: {external_ip}")
        print(f"External Port: {external_port}")
    except Exception as e:
        print(f"Lỗi: {e}")

if __name__ == "__main__":
    test_stun()
