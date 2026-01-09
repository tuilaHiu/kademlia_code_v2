# Project Context Documentation

## 1. Project Overview
- Purpose: Demo a NAT-aware Kademlia DHT with WebSocket relay support, metadata propagation across crawls, and chunked file transfer.
- Primary users: Developers testing P2P/Kademlia networking behind NATs; operators running a small bootstrap/relay testbed.
- Source of truth: Root-level scripts are the active code; `docs/` contains reference/archived material only.
- Main features:
  - Relay-aware Kademlia RPC (UDP + WebSocket relay)
  - NAT detection via STUN and metadata propagation in routing table
  - Simple data and file transfer over DHT RPC
  - Scripts/tests to validate metadata propagation and file transfer

## 2. Tech Stack
- Language: Python 3
- Framework: None (asyncio-based scripts)
- Database: None in current root demo; legacy subproject uses MongoDB (under `docs/PhanCode_cũ`)
- Infra/Runtime (Docker, k8s, etc.): None; standalone scripts plus WebSocket relay server
- Key libraries:
  - `kademlia`, `rpcudp` (DHT + RPC)
  - `websockets` (relay)
  - `u-msgpack-python` (message serialization)
  - `pystun3`/`stun` (NAT discovery)
  - Legacy subproject: `fastapi`, `uvicorn`, `pymongo`, `aiohttp`, `aiofiles`

## 3. Directory Structure
- Tree (depth 3–4, pruned for brevity)
```
.
├── bootstrap_node.py
├── config.py
├── kademliaExtend.py
├── nat_utils.py
├── nodeA.py
├── nodeB.py
├── relay_manager.py
├── relay_server.py
├── requirements.txt
├── run_full_test.sh
├── test_bootstrap_metadata.py
├── test_metadata_propagation.py
├── METADATA_PROPAGATION.md
├── DEPLOYMENT.md
├── docs/
│   └── PhanCode_cũ/
│       ├── docs/
│       │   └── architecture.md
│       ├── node/
│       │   ├── main.py
│       │   ├── dht_manager.py
│       │   ├── file_manager.py
│       │   ├── file_transfer.py
│       │   ├── replication.py
│       │   ├── config.py
│       │   └── requirements.txt
│       ├── server/
│       │   ├── main.py
│       │   ├── api.py
│       │   ├── dht_manager.py
│       │   ├── file_manager.py
│       │   ├── replication.py
│       │   ├── config.py
│       │   └── requirements.txt
│       ├── monitoring_server/
│       │   ├── main.py
│       │   ├── api.py
│       │   ├── database.py
│       │   ├── config.py
│       │   └── requirements.txt
│       ├── scripts/
│       │   └── setup.sh
│       ├── chunks/  # many .chunk files
│       ├── bootstrap_nodes.json
│       └── geoip2.py
├── node_call_over_relay_nodeA.py
├── node_call_over_relay_nodeB.py
├── stun_client.py
├── test.png
├── *.docx
└── __pycache__/
```
- Key folders explained
  - `docs/`: Reference/archived material only; not part of the active source code.
  - `docs/PhanCode_cũ/`: Legacy/archived multi-service implementation (node/server/monitoring_server) with its own requirements and FastAPI + MongoDB usage.
  - `docs/PhanCode_cũ/chunks/`: Sample chunk files from earlier file-splitting experiments.
  - Root scripts: current demo for NAT-aware Kademlia + relay.

## 4. Architecture & Data Flow
- High-level diagram (text)
```
NodeA (NAT) --WebSocket--> Relay Server <--WebSocket-- Bootstrap/NodeB
NodeA/NodeB/Bootstrap --UDP Kademlia RPC--> (direct when possible)
```
- Request/data flow steps
  1. Each node builds metadata via STUN (`nat_utils.detect_nat_info`) and sets `node.meta` (NAT info, `relay_uri`, `use_relay`, `node_id`).
  2. `RelayAwareServer` starts UDP listener and (if configured) connects to the relay via `RelayManager`.
  3. Bootstrapping: `nodeA.py`/`nodeB.py` call `server.bootstrap([BOOTSTRAP_ADDR])` to crawl the network.
  4. `RelayAwareProtocol.rpc_find_node` returns neighbors including metadata; `handle_call_response` deserializes and caches metadata so future calls know whether relay is required.
  5. For RPCs (`ping`, `store`, `find_node`, `send_data`), `RelayAwareProtocol.__getattr__` decides to send via relay when metadata indicates NAT/relay usage.
  6. File transfer: `RelayAwareServer.send_file` chunks a file into `send_data` payloads; receiver reassembles and stores in `received_files/` or uses a custom file handler.
- Key modules (entrypoints, services, persistence)
  - Entrypoints: `relay_server.py`, `bootstrap_node.py`, `nodeA.py`, `nodeB.py`.
  - Core logic: `kademliaExtend.py` (RelayAwareProtocol/Server + metadata propagation + file chunk handling), `relay_manager.py` (relay client), `nat_utils.py` (STUN).
  - Tests/utilities: `test_metadata_propagation.py`, `test_bootstrap_metadata.py`, `run_full_test.sh`.
  - Legacy services (reference only): `docs/PhanCode_cũ/node/main.py`, `docs/PhanCode_cũ/server/main.py`, `docs/PhanCode_cũ/monitoring_server/main.py`.

## 5. How to Run & Test
- Local run commands (from README/DEPLOYMENT)
  - Create venv + install: `python3 -m venv venv && source venv/bin/activate && pip install -r requirements.txt`
  - Start relay: `python3 relay_server.py`
  - Start bootstrap: `python3 bootstrap_node.py`
  - Start nodeB: `python3 nodeB.py`
  - Start nodeA (client side): `python3 nodeA.py`
- Tests
  - Metadata propagation: `python3 test_metadata_propagation.py`
  - Bootstrap metadata check: `python3 test_bootstrap_metadata.py`
  - Full flow script: `./run_full_test.sh` (kills all `python` processes and uses `venv/bin/python`).
- Notes / known mismatches
  - `config.py` defaults `RELAY_PORT=8768` while `relay_server.py` defaults to `8765`; set `RELAY_PORT`/`RELAY_URI` env vars accordingly.
  - `test_metadata_propagation.py` and `test_bootstrap_metadata.py` import `NODE_A_META`, which is not defined in `config.py`.
  - `DEPLOYMENT.md` references `SERVER_PUBLIC_IP` and `run_local_test.sh`, neither exists in current root config/files.

## 6. Recent Changes (Auto)
- No git changes detected (`git status --porcelain` clean).
