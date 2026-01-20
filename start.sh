#!/bin/bash

# LLM Council - Start script

# Ensure we run from the repo root (important when the script is launched from elsewhere).
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"
export PYTHONPATH="$SCRIPT_DIR${PYTHONPATH:+:$PYTHONPATH}"

echo "Starting LLM Council..."
echo ""

# Select backend port (default 8001, auto-increment if occupied when lsof is available)
BACKEND_PORT="${BACKEND_PORT:-8001}"
if command -v lsof >/dev/null 2>&1; then
  while lsof -iTCP -sTCP:LISTEN -P -n 2>/dev/null | grep -q ":${BACKEND_PORT}"; do
    BACKEND_PORT=$((BACKEND_PORT + 1))
  done
fi
export BACKEND_PORT

# Start backend
echo "Starting backend on http://localhost:${BACKEND_PORT}..."
uv run python -m backend.main &
BACKEND_PID=$!

# Wait a bit for backend to start
sleep 2

# Start frontend
FRONTEND_MODE="${FRONTEND_MODE:-dev}"
if [ "${FRONTEND_MODE}" = "prod" ]; then
  echo "Production mode: building frontend and serving dist from backend..."
  cd frontend
  npm run build
  cd "$SCRIPT_DIR"
  FRONTEND_PID=""
else
  FRONTEND_PORT="${FRONTEND_PORT:-5173}"
  if command -v lsof >/dev/null 2>&1; then
    while lsof -iTCP -sTCP:LISTEN -P -n 2>/dev/null | grep -q ":${FRONTEND_PORT}"; do
      FRONTEND_PORT=$((FRONTEND_PORT + 1))
    done
  fi

  echo "Starting frontend on http://localhost:${FRONTEND_PORT}..."
  cd frontend
  VITE_API_BASE="${VITE_API_BASE:-http://localhost:${BACKEND_PORT}}" npm run dev -- --port "${FRONTEND_PORT}" --strictPort &
  FRONTEND_PID=$!
  cd "$SCRIPT_DIR"
fi

echo ""
echo "✓ LLM Council is running!"
echo "  Backend:  http://localhost:${BACKEND_PORT}"
if [ "${FRONTEND_MODE}" = "prod" ]; then
  echo "  Frontend: http://localhost:${BACKEND_PORT}"
else
  echo "  Frontend: http://localhost:${FRONTEND_PORT}"
fi
echo ""
echo "Press Ctrl+C to stop both servers"

# Wait for Ctrl+C
trap "kill $BACKEND_PID ${FRONTEND_PID:-} 2>/dev/null; exit" SIGINT SIGTERM
wait
