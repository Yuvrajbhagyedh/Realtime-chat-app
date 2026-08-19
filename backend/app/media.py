import uuid
from pathlib import Path

from fastapi import HTTPException, UploadFile

from app.config import settings

IMAGE_TYPES = {"image/jpeg", "image/png", "image/gif", "image/webp"}


async def save_upload(file: UploadFile, *, images_only: bool = False) -> tuple[str, str, str]:
    if not file.filename:
        raise HTTPException(status_code=400, detail="No file selected")
    data = await file.read()
    if len(data) > settings.max_upload_bytes:
        raise HTTPException(status_code=413, detail="File too large (max 10MB)")
    content_type = file.content_type or ""
    if images_only and content_type not in IMAGE_TYPES:
        raise HTTPException(status_code=400, detail="Use a JPG, PNG, GIF, or WebP image")
    ext = Path(file.filename).suffix[:12] or ".bin"
    stored = f"{uuid.uuid4().hex}{ext}"
    dest_dir = Path(settings.upload_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    (dest_dir / stored).write_bytes(data)
    kind = "image" if content_type in IMAGE_TYPES else "file"
    return f"/uploads/{stored}", Path(file.filename).name, kind
