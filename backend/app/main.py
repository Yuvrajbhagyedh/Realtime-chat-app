from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.config import settings
from app.database import engine
from app.hub import hub
from app.migrate import init_db
from app.redis_client import close_redis, init_redis
from app.routers import auth, conversations, messages, users
from app.ws import router as ws_router

REPO_ROOT = Path(__file__).resolve().parents[2]
FRONTEND_DIST = Path(settings.frontend_dist) if settings.frontend_dist else REPO_ROOT / "frontend" / "dist"


@asynccontextmanager
async def lifespan(_: FastAPI):
    Path(settings.upload_dir).mkdir(parents=True, exist_ok=True)
    await init_db()
    await init_redis()
    await hub.start()
    yield
    await hub.stop()
    await close_redis()
    await engine.dispose()


app = FastAPI(title="Realtime Chat", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(users.router)
app.include_router(users.notify_router)
app.include_router(conversations.router)
app.include_router(messages.router)
app.include_router(ws_router)

uploads = Path(settings.upload_dir)
uploads.mkdir(parents=True, exist_ok=True)
app.mount("/uploads", StaticFiles(directory=str(uploads)), name="uploads")


@app.get("/api/health")
async def health():
    return {"status": "ok"}


if FRONTEND_DIST.exists():
    assets = FRONTEND_DIST / "assets"
    if assets.exists():
        app.mount("/assets", StaticFiles(directory=str(assets)), name="frontend-assets")

    @app.get("/{full_path:path}")
    async def spa(full_path: str):
        candidate = FRONTEND_DIST / full_path
        if full_path and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(FRONTEND_DIST / "index.html")
