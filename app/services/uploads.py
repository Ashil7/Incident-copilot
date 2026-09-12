"""Validate and store synthetic UTF-8 logs using generated filenames."""

import codecs
from pathlib import Path
from uuid import uuid4

from fastapi import HTTPException, UploadFile

from app.config import PROJECT_ROOT, Settings

CHUNK_SIZE = 64 * 1024
ALLOWED_CONTENT_TYPES = {"text/plain", "application/octet-stream"}


def save_upload(upload: UploadFile, settings: Settings) -> Path:
    """Stream to a new file, deleting partial data on any validation/write failure."""
    suffix = Path(upload.filename or "").suffix.lower()
    if suffix not in {".log", ".txt"}:
        raise HTTPException(422, "Only .log and .txt files are supported.")
    content_type = (upload.content_type or "").split(";", 1)[0].lower().strip()
    if content_type not in ALLOWED_CONTENT_TYPES:
        raise HTTPException(422, "Upload must have a text/plain or application/octet-stream type.")

    directory = settings.upload_directory
    if not directory.is_absolute():
        directory = PROJECT_ROOT / directory
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{uuid4()}{suffix}"
    size = 0
    decoder = codecs.getincrementaldecoder("utf-8")()
    created = False
    try:
        with path.open("xb") as target:
            created = True
            while chunk := upload.file.read(CHUNK_SIZE):
                size += len(chunk)
                if size > settings.max_upload_size_mb * 1024 * 1024:
                    raise HTTPException(413, "Upload exceeds the configured size limit.")
                # MIME headers are untrusted; also validate the actual text bytes.
                if b"\x00" in chunk:
                    raise HTTPException(422, "Upload must be UTF-8 text without NUL bytes.")
                decoder.decode(chunk)
                target.write(chunk)
            decoder.decode(b"", final=True)
            if size == 0:
                raise HTTPException(422, "Upload must not be empty.")
        return path
    except UnicodeDecodeError:
        if created:
            path.unlink(missing_ok=True)
        raise HTTPException(422, "Upload must contain valid UTF-8 text.") from None
    except BaseException:
        if created:
            path.unlink(missing_ok=True)
        raise
