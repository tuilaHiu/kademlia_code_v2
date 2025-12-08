# Deployment Guide

## Two Deployment Modes

### 1. Local Testing (All services on same machine)
- Use: `run_local_test.sh`
- Config: Automatically sets `SERVER_PUBLIC_IP=127.0.0.1`
- Purpose: Test before deploying to production

### 2. Production (Distributed: Server + Client)
- Use: `run_full_test.sh` or manual commands
- Config: Default `SERVER_PUBLIC_IP=146.190.94.139`
- Purpose: Actual deployment

## Architecture (Production)

```
SERVER (146.190.94.139)          CLIENT (Local Machine)
├── relay_server.py              ├── nodeA.py
├── bootstrap_node.py            └── test_metadata_propagation.py
└── nodeB.py
```

## Configuration

The system uses `config.py` with the following key settings:

- **SERVER_PUBLIC_IP**: Public IP of server (default: `146.190.94.139`)
- **BOOTSTRAP_HOST**: Where to connect to bootstrap node (default: `SERVER_PUBLIC_IP`)
- **RELAY_HOST**: Where to connect to relay server (default: `SERVER_PUBLIC_IP`)

### Server Side (146.190.94.139)

All server components listen on `0.0.0.0` (all interfaces) but advertise the public IP for clients to connect.

### Client Side (Local Machine)

Client components connect to server using `SERVER_PUBLIC_IP`.

## Deployment Steps

### Option A: Local Testing First (Recommended)

```bash
# Test everything on one machine first
chmod +x run_local_test.sh
./run_local_test.sh
```

This will:
- Override `SERVER_PUBLIC_IP=127.0.0.1` via environment variable
- Start relay, bootstrap, nodeB locally
- Run metadata propagation test
- Test file transfer with nodeA
- Verify everything works before deploying to server

### Option B: Production Deployment

#### 1. On Server (146.190.94.139)

```bash
# Ensure config.py has correct SERVER_PUBLIC_IP
# Default is already set to 146.190.94.139

# Start relay server (listens on 0.0.0.0:8760)
venv/bin/python relay_server.py &

# Start bootstrap node (listens on 0.0.0.0:8468)
venv/bin/python bootstrap_node.py &

# Start nodeB (listens on 0.0.0.0:8470)
venv/bin/python nodeB.py &
```

#### 2. On Client (Local Machine)

```bash
# Default config already points to SERVER_PUBLIC_IP=146.190.94.139
# No config changes needed

# Run test to verify metadata propagation
venv/bin/python test_metadata_propagation.py

# Or run nodeA for file transfer
venv/bin/python nodeA.py

# If your server IP is different, override it:
export SERVER_PUBLIC_IP="your.server.ip"
venv/bin/python nodeA.py
```

## Firewall Configuration

Ensure the following ports are open on server **146.190.94.139**:

- **8468/udp**: Bootstrap node (Kademlia)
- **8470/udp**: NodeB (Kademlia)
- **8760/tcp**: Relay server (WebSocket)

## Environment Variables (Optional)

You can override configuration using environment variables:

```bash
# On server
export SERVER_PUBLIC_IP="your.server.ip"
export RELAY_PORT="8765"

# On client
export BOOTSTRAP_HOST="your.server.ip"
export RELAY_HOST="your.server.ip"
```

## Verification

### Check Server Services

```bash
# On server
netstat -tulpn | grep -E '8468|8470|8765'

# Should show:
# udp 0.0.0.0:8468 (bootstrap)
# udp 0.0.0.0:8470 (nodeB)
# tcp 0.0.0.0:8760 (relay)
```

### Check Client Connection

```bash
# On client
venv/bin/python test_metadata_propagation.py

# Should output:
# ✅ SUCCESS: X/Y nodes have metadata!
# Metadata IS being propagated correctly through crawling.
```

## Troubleshooting

### Connection Refused

- Check firewall rules on server
- Verify services are running: `ps aux | grep python`
- Check server logs: `tail -f /tmp/*.log`

### Metadata Not Propagating

- Ensure bootstrap node is running first
- Wait 5-10 seconds after bootstrap for crawling to complete
- Check routing table in test output

### File Transfer Fails

- Verify relay server is accessible
- Check NAT detection results in logs
- Ensure both nodes have `relay_uri` in metadata

## Log Files

When using provided scripts:
- `/tmp/relay_server.log`
- `/tmp/bootstrap.log`
- `/tmp/nodeB.log`
- `/tmp/nodeA.log`
