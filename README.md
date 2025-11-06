# Kademlia NAT-Aware Demo

Hướng dẫn từng bước giúp bạn dựng thử nghiệm gồm **bootstrap node**, **nodeB** (trên máy chủ) và **nodeA** (trên máy cá nhân sau NAT) với hỗ trợ relay WebSocket và chia nhỏ file.

> Toàn bộ lệnh dưới đây giả định bạn dùng hệ điều hành Linux/WSL. Nếu dùng Windows, hãy chuyển sang PowerShell với các lệnh tương đương.

---

## 1. Chuẩn bị mã nguồn & môi trường Python

```bash
git clone <repository-url> kademlia-demo
cd kademlia-demo

python3 -m venv venv
source venv/bin/activate

pip install --upgrade pip
pip install -r requirements.txt
```

Thư viện chính cần có:
- `kademlia`, `rpcudp` – core DHT & RPC
- `websockets`, `umsgpack`
- `pystun3` (`stun`) để kiểm tra NAT

---

## 2. Cấu hình chung qua biến môi trường

Các script đọc cấu hình từ `node_config.py`, nhưng bạn có thể override bằng biến môi trường. Dưới đây là hai bộ cấu hình mẫu: **Server** (chạy relay + bootstrap + nodeB) và **Local** (chạy nodeA).

### 2.1 Trên máy chủ (có IP công cộng, ví dụ `146.190.x.x`)

```bash
BOOTSTRAP_HOST=0.0.0.0
NODE_B_HOST=0.0.0.0
NODE_A_HOST=146.190.x.x
RELAY_HOST=146.190.x.x
RELAY_PORT=8765
RELAY_URI=ws://146.190.x.x:8765

STUN_HOST=stun.l.google.com
STUN_PORT=19302
```

Giải thích:
- `0.0.0.0` giúp listener nghe mọi interface.
- `NODE_A_HOST` đại diện cho IP của nodeA khi dùng trên server (nodeA sẽ override bằng NAT info thực tế).
- Relay chạy cùng server, nên URI trỏ về chính nó.

### 2.2 Trên máy local (đằng sau NAT)

```bash
BOOTSTRAP_HOST=146.190.x.x
NODE_B_HOST=146.190.x.x
NODE_A_HOST=0.0.0.0
RELAY_HOST=146.190.x.x
RELAY_PORT=8765
RELAY_URI=ws://146.190.x.x:8765

STUN_HOST=stun.l.google.com
STUN_PORT=19302
```

---

## 3. Khởi chạy trên máy chủ

Luôn kích hoạt virtualenv (`source venv/bin/activate`) trước khi chạy.

1. **Relay WebSocket**
   ```bash
   python3 relay_server.py --host 0.0.0.0 --port 8765
   ```
   Giữ cửa sổ này mở (có thể dùng `tmux`/`screen`).

2. **Bootstrap node**
   ```bash
   python3 bootstrap_node.py
   ```
   Script sẽ:
   - Chạy STUN → log `nat_type`, `external_ip`.
   - Nếu không ở “Open Internet”, tự bật relay với `RelayManager`.
   - Bắt đầu nghe UDP trên `BOOTSTRAP_HOST:BOOTSTRAP_PORT` (mặc định 0.0.0.0:8468).

3. **nodeB**
   ```bash
   python3 nodeB.py
   ```
   nodeB cũng tự kiểm tra NAT và đăng ký handler:
   - Nhận dữ liệu thường: log ra console.
   - Nhận file: ghép các chunk, lưu vào `received_files/<transfer_id>_<tên_file>`.

*Lưu ý:* Nếu chạy nhiều script cùng máy, hãy dùng các terminal riêng và xác thực log để chắc chắn từng dịch vụ đang chạy.

---

## 4. Khởi chạy nodeA trên máy local

Trên máy cá nhân (sau NAT), trong thư mục project đã copy/clone:

```bash
source venv/bin/activate
python3 nodeA.py
```

Hành vi:
- Tự STUN → log `nat_type`. Nếu không phải “Open Internet” sẽ tự bật relay (vì metadata luôn chứa `relay_uri` & `use_relay`).
- Ping nodeB → log kết quả.
- Gửi một payload JSON → nodeB log dữ liệu nhận.
- Chia file `test.png` thành nhiều chunk → nodeB nhận & lưu.

Nếu file `test.png` không tồn tại, script sẽ bỏ qua bước gửi file (log cảnh báo).

---

## 5. Kiểm tra kết quả

- **nodeA.log**: xác nhận ping thành công, `send_data` và `send_file` không bị timeout.
- **nodeB.log**: nhận dữ liệu JSON và báo đường dẫn file lưu (`received_files/...`).
- **Thư mục server**: kiểm tra `received_files` chứa file nhận đúng dung lượng.

Nếu có timeout ở nodeA:
- Đảm bảo relay đã chạy, nodeB/Bootstrap có `RelayManager`.
- Xem nodeB log “Connected as …” từ relay_manager.
- Kiểm tra firewall: mở UDP 8468–8470 và TCP 8765.

---

## 6. Tuỳ chỉnh thêm

- **Relay ở máy khác:** đổi `RELAY_HOST`, `RELAY_URI` ở cả hai phía.
- **Cổng khác:** sửa `BOOTSTRAP_PORT`, `NODE_A_PORT`, `NODE_B_PORT` trong `node_config.py` hoặc biến môi trường tương ứng.
- **STUN server dự phòng:** thay `STUN_HOST` nếu mặc định bị chặn.
- **Gửi file khác:** chỉnh `sample_path` trong `nodeA.py` hoặc viết script riêng gọi `RelayAwareServer.send_file(node, path)`.

---

## 7. Dọn dẹp

```bash
deactivate
```

Tắt relay/Bootstrap/nodeA/nodeB bằng `Ctrl+C` trong từng terminal. Nếu chạy bằng `tmux`/`screen` hãy detach/kill session sau khi hoàn tất.

---

Chúc bạn thử nghiệm thành công! Nếu gặp vấn đề, kiểm tra lại biến môi trường, log của từng tiến trình và chắc chắn relay hoạt động trước khi khởi chạy các node. 
