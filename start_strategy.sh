#!/bin/bash
cd "$(dirname "$0")"

# Precheck: API already running?
if python -m pdp strategy list &>/dev/null; then
  echo "✓ API already running"
  STATUS=$(python -m pdp strategy list)
  echo "$STATUS"

  # Check if strategy is already running
  if echo "$STATUS" | grep -q "RUNNING.*supertrend_short"; then
    echo "✓ Strategy already running"
    exit 0
  fi

  # Strategy is stopped, start it
  echo "Starting supertrend_short strategy..."
  python -m pdp strategy start supertrend_short
  echo "✓ Strategy started"
  exit 0
fi

# Precheck: Port 8000 already in use?
if lsof -Pi :8000 -sTCP:LISTEN -t >/dev/null 2>&1; then
  echo "✗ Port 8000 already in use (API may be running elsewhere)"
  exit 1
fi

echo "Starting PDP API server..."
python -m pdp serve &
SERVER_PID=$!

echo "Waiting for server to initialize..."
for i in {1..30}; do
  if python -m pdp strategy list &>/dev/null; then
    echo "✓ Server ready"
    break
  fi
  if [ $i -eq 30 ]; then
    echo "✗ Server failed to start"
    kill $SERVER_PID 2>/dev/null || true
    exit 1
  fi
  sleep 1
done

echo "Starting supertrend_short strategy..."
python -m pdp strategy start supertrend_short

echo ""
echo "✓ Strategy running"
python -m pdp strategy list
echo ""
echo "API server running at http://localhost:8000"
echo "Press Ctrl+C to stop."

trap "kill $SERVER_PID 2>/dev/null || true" EXIT
wait $SERVER_PID
