#!/bin/bash
cd "$(dirname "$0")"

# Precheck: API already running?
if python -m pdp strategy list &>/dev/null; then
  echo "✓ API already running"
  STATUS=$(python -m pdp strategy list)
  echo "$STATUS"

  # Start any STOPPED strategies
  STOPPED=$(echo "$STATUS" | grep '^STOPPED' | awk '{print $2}')
  if [ -z "$STOPPED" ]; then
    echo "✓ All strategies already running"
    exit 0
  fi

  echo "$STOPPED" | while read -r strat; do
    echo "Starting $strat..."
    python -m pdp strategy start "$strat"
  done
  echo "✓ Done"
  exit 0
fi

# Precheck: Port 8000 already in use? Kill the stale process.
STALE_PID=$(netstat -ano 2>/dev/null | grep '0.0.0.0:8000.*LISTENING' | awk '{print $NF}' | head -1)
if [ -n "$STALE_PID" ]; then
  echo "Port 8000 held by PID $STALE_PID — killing..."
  taskkill //PID "$STALE_PID" //F >/dev/null 2>&1 || true
  sleep 1
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

echo "Starting all strategies..."
python -m pdp strategy list | grep '^STOPPED' | awk '{print $2}' | while read -r strat; do
  echo "  Starting $strat..."
  python -m pdp strategy start "$strat"
done

echo ""
echo "✓ Strategies running"
python -m pdp strategy list
echo ""
echo "API server running at http://localhost:8000"
echo "Press Ctrl+C to stop."

trap "kill $SERVER_PID 2>/dev/null || true" EXIT
wait $SERVER_PID
