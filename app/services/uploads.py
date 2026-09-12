"""Streaming validation shared by local and future storage adapters."""

import codecs
from pathlib import Path

from fastapi import HTTPException, UploadFile

from app.config import Settings
from app.services.storage import Storage, StoredObject, get_storage

CHUNK_SIZE = 64 * 1024
ALLOWED_CONTENT_TYPES = {"text/plain", "application/octet-stream", "application/json"}


def store_upload(upload: UploadFile, settings: Settings, storage: Storage) -> StoredObject:
    suffix = Path(upload.filename or "").suffix.lower()
    if suffix not in {".log", ".txt", ".json"}:
        raise HTTPException(422, "Only .log, .txt and .json logs are supported.")
    content_type = (upload.content_type or "").split(";", 1)[0].lower().strip()
    if content_type not in ALLOWED_CONTENT_TYPES:
        raise HTTPException(422, "Unsupported log content type.")

    def chunks():
        size = 0
        decoder = codecs.getincrementaldecoder("utf-8")()
        try:
            while chunk := upload.file.read(CHUNK_SIZE):
                size += len(chunk)
                if size > settings.max_upload_size_mb * 1024 * 1024:
                    raise HTTPException(413, "Upload exceeds the configured size limit.")
                if b"\x00" in chunk:
                    raise HTTPException(422, "Upload must be UTF-8 text without NUL bytes.")
                decoder.decode(chunk)
                yield chunk
            decoder.decode(b"", final=True)
            if size == 0:
                raise HTTPException(422, "Upload must not be empty.")
        except UnicodeDecodeError:
            raise HTTPException(422, "Upload must contain valid UTF-8 text.") from None

    return storage.put(chunks(), suffix)


def save_upload(upload: UploadFile, settings: Settings) -> Path:
    """Compatibility wrapper; application services use opaque keys."""
    storage = get_storage(settings)
    return storage.path(store_upload(upload, settings, storage).key)
