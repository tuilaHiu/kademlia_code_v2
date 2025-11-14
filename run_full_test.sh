#!/bin/bash
# Script để test metadata propagation và file transfer
set -e

echo "🧹 Cleaning up old processes..."
killall -9 python 2>/dev/null || true
sleep 1

echo ""
echo "🚀 Starting services..."
echo "  1/3 Starting relay server..."
venv/bin/python relay_server.py > /tmp/relay_server.log 2>&1 &
sleep 2

echo "  2/3 Starting bootstrap node..."
venv/bin/python bootstrap_node.py > /tmp/bootstrap.log 2>&1 &
sleep 2

echo "  3/3 Starting nodeB..."
venv/bin/python nodeB.py > /tmp/nodeB.log 2>&1 &
sleep 3

echo ""
echo "✅ All services started!"
echo ""
echo "📊 Running metadata propagation test..."
venv/bin/python test_metadata_propagation.py 2>&1 | tail -25

echo ""
echo "🔄 Now testing file transfer with nodeA..."
echo ""
venv/bin/python nodeA.py > /tmp/nodeA.log 2>&1 &
NODEA_PID=$!

# Wait and show logs
sleep 10

echo "📝 NodeA logs:"
tail -20 /tmp/nodeA.log | grep -E "(Found node|Ping|send_data|send_file|metadata|success|failed)" || echo "No relevant logs yet"

echo ""
echo "📝 NodeB logs:"
tail -20 /tmp/nodeB.log | grep -E "(received|stored|file)" || echo "No file received yet"

echo ""
echo "🎉 Test completed! Services are still running."
echo "   Kill with: killall -9 python"
