#!/usr/bin/env zsh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

NODE_VERSION="v22.18.0"
ARCH="$(uname -m)"
if [[ "$ARCH" == "arm64" ]]; then
  NODE_DIST="darwin-arm64"
else
  NODE_DIST="darwin-x64"
fi

TOOLS="$ROOT/.tools"
NODE_DIR="$TOOLS/node"
NODE_BIN="$NODE_DIR/bin/node"
NPM_BIN="$NODE_DIR/bin/npm"

if [[ ! -x "$NODE_BIN" ]]; then
  echo "Docker is not installed. Downloading Node.js $NODE_VERSION so the UI can be built..."
  mkdir -p "$TOOLS"
  TARBALL="node-${NODE_VERSION}-${NODE_DIST}.tar.gz"
  curl -fsSL "https://nodejs.org/dist/${NODE_VERSION}/${TARBALL}" -o "$TOOLS/$TARBALL"
  tar -xzf "$TOOLS/$TARBALL" -C "$TOOLS"
  rm -f "$TOOLS/$TARBALL"
  rm -rf "$NODE_DIR"
  mv "$TOOLS/node-${NODE_VERSION}-${NODE_DIST}" "$NODE_DIR"
fi

export PATH="$NODE_DIR/bin:$PATH"

echo "Installing frontend packages..."
cd "$ROOT/frontend"
npm install
npm run build
cd "$ROOT"

UV="${HOME}/.local/bin/uv"
if [[ ! -x "$UV" ]]; then
  echo "uv not found at $UV"
  exit 1
fi

if [[ ! -x "$ROOT/backend/.venv/bin/python" ]]; then
  "$UV" venv "$ROOT/backend/.venv" --python 3.12
fi
"$UV" pip install --python "$ROOT/backend/.venv/bin/python" -r "$ROOT/backend/requirements.txt"

export DATABASE_URL="${DATABASE_URL:-sqlite+aiosqlite:///$ROOT/backend/chat.db}"
export REDIS_URL="${REDIS_URL:-memory://}"
export SECRET_KEY="${SECRET_KEY:-dev-secret-change-me}"
export UPLOAD_DIR="${UPLOAD_DIR:-$ROOT/backend/uploads}"
export CORS_ORIGINS="http://localhost:8000,http://127.0.0.1:8000"

echo
echo "Starting Relay at http://127.0.0.1:8000"
echo "No Docker / Postgres / Redis needed for this local mode."
echo

cd "$ROOT/backend"
exec .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000
