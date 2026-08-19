# Relay — realtime chat

Async Python chat stack: **FastAPI → Redis pub/sub → WebSocket hub → PostgreSQL**, with a React client and Docker Compose.

## Features

- Registration / login with JWT
- 1-to-1 DMs and group chats
- WebSocket events for new messages, presence, typing, and read receipts
- Message history with unread counts
- Image / file sharing (10MB)
- Redis presence + typing TTLs and cross-process fan-out
- PostgreSQL persistence
- Offline notifications stored for when a user comes back
- Docker deployment

## Architecture

```
React  --HTTP-->  FastAPI  --SQL-->  PostgreSQL
  |                  |
  |               Redis (presence, typing, pub/sub)
  |                  |
  +----WebSocket-----+
```

FastAPI workers keep local sockets. Every event is published on Redis `chat:events` so other workers can deliver it. Presence keys expire unless the client heartbeats.

## Run without Docker (this Mac)

`docker` is not installed. Use the local starter instead — it builds the React UI, uses SQLite, and an in-memory presence broker:

```bash
cd /Users/balrajkrishnappa/Projects/realtime-chat
chmod +x start.sh
./start.sh
```

Then open [http://127.0.0.1:8000](http://127.0.0.1:8000).

Register two accounts (Safari + a private window) to try DMs.

To use Docker later, install [Docker Desktop](https://www.docker.com/products/docker-desktop/) and run `docker compose up --build`.

## Host online (Render)

Render now charges for Postgres and Redis. This repo deploys as **one web service** (SQLite + in-memory presence) so you do not need to buy a database.

If a card is still required, that is Render’s Hobby account check. You can skip adding Postgres / Key Value.

1. **+ New → Web Service** (or Blueprint; it only creates `relay-web` now).
2. Connect **Yuvrajbhagyedh/Realtime-chat-app**, branch **main**.
3. Runtime: **Docker**. Dockerfile path: `./Dockerfile`.
4. Do **not** create Postgres or Key Value.
5. Wait until the service is **Live**, then open the `.onrender.com` URL.

Chat data can reset when Render restarts the free/hobby instance. For a permanent database you would add paid Postgres later.

## Run with Docker

```bash
docker compose up --build
```

Open [http://localhost:8080](http://localhost:8080). API docs: [http://localhost:8000/docs](http://localhost:8000/docs).

Register two accounts (use two browsers or a private window) to try DMs, typing, and online status.

## Local development

You need PostgreSQL and Redis. From the repo root:

```bash
# terminals: postgres + redis, or:
docker compose up postgres redis

cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
export DATABASE_URL=postgresql+asyncpg://chat:chat@localhost:5432/chat
export REDIS_URL=redis://localhost:6379/0
export SECRET_KEY=dev-secret
uvicorn app.main:app --reload --port 8000

cd ../frontend
npm install
npm run dev
```

Vite proxies `/api`, `/uploads`, and `/ws` to the backend. Open [http://localhost:5173](http://localhost:5173).

## API sketch

| Method | Path | Purpose |
| --- | --- | --- |
| POST | `/api/auth/register` | JSON register, returns JWT |
| POST | `/api/auth/login` | OAuth2 form login |
| GET | `/api/users/search?q=` | Find users |
| GET | `/api/conversations` | Inbox |
| POST | `/api/conversations/direct` | `{ "user_id": n }` |
| POST | `/api/conversations/group` | `{ "name", "member_ids" }` |
| GET | `/api/conversations/{id}/messages` | History |
| POST | `/api/conversations/{id}/messages` | multipart `content` + optional `file` |
| POST | `/api/conversations/{id}/read` | Mark read |
| GET | `/api/notifications` | Offline notification log |
| WS | `/ws?token=` | Realtime channel |

WebSocket JSON: `ping`, `typing` `{ conversation_id, is_typing }`. Server emits `message`, `presence`, `typing`, `read`, `notification`, `conversation.upsert`.

## Notes for interviews

This is a portfolio-style implementation, not a production messenger. Tokens live in `localStorage`, files sit on a local volume, and there is no E2E encryption. The interesting parts to walk through are the async SQLAlchemy session, Redis pub/sub hub, and presence TTLs.
