# Metadata Propagation Through Network Crawling

## Vấn Đề

Trước đây, metadata (thông tin NAT, relay URI, node_id, etc.) của các nodes **KHÔNG được propagate** qua network crawling. Khi node bootstrap và "cào" (crawl) các node khác từ bootstrap node, các node nhận được chỉ có thông tin cơ bản `(id, ip, port)`, không bao gồm metadata cần thiết để sử dụng relay.

### Nguyên nhân:

1. **Thư viện Kademlia gốc** chỉ serialize Node thành tuple `(id, ip, port)` (xem `/venv/lib/python3.12/site-packages/kademlia/node.py:36-40`)
2. **RPC `find_node`** trả về `list(map(tuple, neighbors))` - mất metadata
3. **Crawling logic** deserialize từ tuple thành Node objects - không có metadata

### Hậu quả:

Code hiện tại **CHỈ GỬI FILE THÀNH CÔNG** vì hardcode metadata trong config:

```python
# nodeA.py - HARDCODE metadata
node_b = Node(NODE_B_ID, NODE_B_ADDR[0], NODE_B_ADDR[1])
node_b.meta = dict(NODE_B_META)  # ❌ Thông tin này KHÔNG đến từ network!
```

Nếu không hardcode, node sẽ không biết node đích cần relay hay không.

---

## Giải Pháp Đã Implement

### 1. Sửa `rpc_find_node` để serialize metadata ([kademliaExtend.py:241-264](kademliaExtend.py#L241-L264))

```python
def rpc_find_node(self, sender, nodeid, key, meta_target=None, meta_source=None):
    # ... existing code ...
    neighbors = self.router.find_neighbors(node, exclude=source)

    # ✅ Serialize neighbors VỚI metadata
    result = []
    for n in neighbors:
        node_meta = getattr(n, 'meta', None)
        if node_meta:
            # Format mới: dict chứa đầy đủ thông tin
            result.append({
                'id': n.id,
                'ip': n.ip,
                'port': n.port,
                'meta': node_meta
            })
        else:
            # Backward compatible: tuple cho nodes không có metadata
            result.append(tuple(n))
    return result
```

**Điểm quan trọng:**
- Mixed format: dict (có meta) hoặc tuple (không có meta)
- Backward compatible với thư viện Kademlia gốc
- `rpc_find_value` cũng sử dụng `rpc_find_node` nên tự động được fix

### 2. Thêm `_deserialize_nodes` helper ([kademliaExtend.py:96-117](kademliaExtend.py#L96-L117))

```python
def _deserialize_nodes(self, nodelist: list) -> list:
    """Deserialize mixed format (dict hoặc tuple) thành Node objects với metadata"""
    result = []
    for item in nodelist:
        if isinstance(item, dict):
            # Format mới với metadata
            node = Node(item['id'], item['ip'], item['port'])
            if 'meta' in item and item['meta']:
                setattr(node, 'meta', item['meta'])
            result.append(node)
        elif isinstance(item, (tuple, list)) and len(item) >= 3:
            # Format cũ: tuple (id, ip, port)
            node = Node(item[0], item[1], item[2])
            result.append(node)
    return result
```

### 3. Override `handle_call_response` ([kademliaExtend.py:352-376](kademliaExtend.py#L352-L376))

```python
def handle_call_response(self, result, node):
    """Override để deserialize metadata từ node list trong response"""
    if not result[0]:
        log.warning("no response from %s, removing from router", node)
        self.router.remove_contact(node)
        return result

    log.info("got successful response from %s", node)
    self.welcome_if_new(node)

    # ✅ Deserialize node list với metadata
    response_data = result[1]
    if isinstance(response_data, list) and response_data:
        deserialized_nodes = self._deserialize_nodes(response_data)
        return (result[0], deserialized_nodes)

    return result
```

---

## Flow Hoạt Động

### Before (Metadata KHÔNG propagate):

```
Bootstrap Node (có meta)
    ↓ rpc_find_node returns [(id,ip,port), ...]
NodeA receives → crawling → NodeHeap
    ↓ Tạo Node objects từ tuples
NodeA Routing Table: [Node(id,ip,port)] ← ❌ KHÔNG CÓ META
    ↓
Khi gửi file tới NodeB → KHÔNG BIẾT cần relay
```

### After (Metadata ĐƯỢC propagate):

```
Bootstrap Node (có meta)
    ↓ rpc_find_node returns [{'id':..., 'ip':..., 'port':..., 'meta':{...}}]
NodeA receives → handle_call_response → _deserialize_nodes
    ↓ Tạo Node objects VỚI metadata
NodeA Routing Table: [Node(id,ip,port, meta={...})] ← ✅ CÓ META
    ↓
Khi gửi file tới NodeB → BIẾT cần relay từ metadata!
```

---

## Cách Test

### 1. Chạy test script:

```bash
# Terminal 1: Relay server
python relay_server.py

# Terminal 2: Bootstrap node
python bootstrap_node.py

# Terminal 3: NodeB
python nodeB.py

# Terminal 4: Test metadata propagation
python test_metadata_propagation.py
```

### 2. Kết quả mong đợi:

```
================================================================================
ROUTING TABLE METADATA CHECK
================================================================================

✓ Node 67735440992921214740318711745797151624247505998 (42.96.12.119:8468)
  Metadata: {'node_id': 'bootstrap', 'relay_uri': 'ws://...', 'nat': '...', ...}

✓ Node 113190136722469850215798338346789569742 (0.0.0.0:8470)
  Metadata: {'node_id': 'nodeB', 'relay_uri': 'ws://...', 'use_relay': True, ...}

--------------------------------------------------------------------------------
Summary:
  Total nodes in routing table: 2
  Nodes WITH metadata: 2
  Nodes WITHOUT metadata: 0
================================================================================

✅ SUCCESS: All nodes have metadata!
   Metadata IS being propagated correctly through crawling.

🎉 Test PASSED: Metadata propagation is working!
```

### 3. Test thực tế với file transfer:

Sau khi fix, bạn có thể **XÓA HARDCODE** trong nodeA.py:

```python
# BEFORE (hardcode):
node_b = Node(NODE_B_ID, NODE_B_ADDR[0], NODE_B_ADDR[1])
node_b.meta = dict(NODE_B_META)  # ❌ Hardcode

# AFTER (lấy từ routing table):
# Tìm node trong routing table (đã có metadata từ crawling)
node_b = None
for bucket in server.protocol.router.buckets:
    for n in bucket.get_nodes():
        if n.id == NODE_B_ID:
            node_b = n  # ✅ Node này ĐÃ CÓ metadata từ crawling!
            break
    if node_b:
        break

if not node_b:
    # Fallback: tạo mới nếu chưa có trong routing table
    node_b = Node(NODE_B_ID, NODE_B_ADDR[0], NODE_B_ADDR[1])
    # Có thể thử ping trước để lấy metadata
```

---

## Lưu Ý

### Backward Compatibility

Giải pháp này **HOÀN TOÀN tương thích ngược**:
- Nodes cũ (không có metadata) vẫn hoạt động bình thường
- Nodes mới (có metadata) sẽ propagate metadata
- Mixed network (cũ + mới) hoạt động ổn định

### Không Sửa Thư Viện Gốc

Tất cả thay đổi chỉ trong `kademliaExtend.py`:
- Override RPC methods
- Override `handle_call_response`
- Thêm helper methods
- **KHÔNG động** vào `/venv/lib/python3.12/site-packages/kademlia/`

---

## Tóm Tắt

| Aspect | Before | After |
|--------|--------|-------|
| **RPC Response Format** | `[(id,ip,port), ...]` | `[{'id':...,'meta':{...}}, ...]` |
| **Metadata trong Router** | ❌ Không có | ✅ Có đầy đủ |
| **Relay Detection** | ❌ Phải hardcode | ✅ Tự động từ metadata |
| **File Transfer** | ❌ Chỉ khi hardcode | ✅ Hoạt động tự động |
| **Backward Compatible** | N/A | ✅ Đầy đủ |

---

**Kết luận:** Giờ đây metadata được propagate đầy đủ qua network crawling, node có thể tự động phát hiện nodes khác cần relay mà không cần hardcode thông tin!
