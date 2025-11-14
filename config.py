"""
Shared configuration for Kademlia nodes.

Metadata is now automatically propagated through network crawling,
so most metadata here serves as FALLBACK only (when node not yet discovered).
"""

import os
from kademlia.utils import digest

# ============================================================================
# Network Configuration
# ============================================================================

# Node addresses (can override via environment variables)
BOOTSTRAP_HOST = os.getenv("BOOTSTRAP_HOST", "146.190.93.139")
BOOTSTRAP_PORT = 8468

NODE_A_HOST = os.getenv("NODE_A_HOST", "0.0.0.0")
NODE_A_PORT = 8469

NODE_B_HOST = os.getenv("NODE_B_HOST", "146.190.93.139")
NODE_B_PORT = 8470

# Addresses
BOOTSTRAP_ADDR = (BOOTSTRAP_HOST, BOOTSTRAP_PORT)
NODE_A_ADDR = (NODE_A_HOST, NODE_A_PORT)
NODE_B_ADDR = (NODE_B_HOST, NODE_B_PORT)

# ============================================================================
# Node IDs (deterministic)
# ============================================================================

BOOTSTRAP_NODE_ID = digest(b"bootstrap-node")
NODE_A_ID = digest(b"node-a")
NODE_B_ID = digest(b"node-b")

# ============================================================================
# Relay & STUN Configuration
# ============================================================================

RELAY_HOST = os.getenv("RELAY_HOST", "146.190.93.139")
RELAY_PORT = int(os.getenv("RELAY_PORT", "8760"))
RELAY_URI = os.getenv("RELAY_URI", f"ws://{RELAY_HOST}:{RELAY_PORT}")

STUN_HOST = os.getenv("STUN_HOST", "stun.l.google.com")
STUN_PORT = int(os.getenv("STUN_PORT", "19302"))

# ============================================================================
# Metadata (FALLBACK - will be overridden by crawled metadata)
# ============================================================================
# NOTE: This metadata is only used when:
# 1. Node hasn't been discovered via crawling yet
# 2. Node doesn't exist in routing table
# 3. As initial metadata before NAT detection

BOOTSTRAP_META = {
    "node_id": "bootstrap",
    "relay_uri": RELAY_URI,
}

NODE_A_META = {
    "node_id": "nodeA",
    "relay_uri": RELAY_URI,
}

NODE_B_META = {
    "node_id": "nodeB",
    "relay_uri": RELAY_URI,
}
