"""Exercise failures and UTF-8 decoding across streaming boundaries."""

from io import BytesIO

import pytest
from fastapi import HTTPException, UploadFile
from starlette.datastructures import Headers

from app.config import Settings
from app.services.uploads import CHUNK_SIZE, save_upload


def upload(stream):
    return UploadFile(
        filename="synthetic.log", file=stream, headers=Headers({"content-type": "text/plain"})
    )


def test_multibyte_character_across_chunks(tmp_path) -> None:
    data = b"a" * (CHUNK_SIZE - 1) + "€".encode()
    with BytesIO(data) as stream:
        saved = save_upload(upload(stream), Settings(_env_file=None, upload_directory=tmp_path))
    assert saved.read_bytes() == data


def test_truncated_utf8_removes_partial_file(tmp_path) -> None:
    with BytesIO(b"a" * CHUNK_SIZE + b"\xe2") as stream:
        with pytest.raises(HTTPException) as error:
            save_upload(upload(stream), Settings(_env_file=None, upload_directory=tmp_path))
    assert error.value.status_code == 422
    assert list(tmp_path.iterdir()) == []


def test_read_failure_removes_partial_file(tmp_path) -> None:
    class BrokenStream(BytesIO):
        def read(self, size=-1):
            if self.tell():
                raise OSError("synthetic read failure")
            return super().read(size)

    with BrokenStream(b"a" * CHUNK_SIZE) as stream:
        with pytest.raises(OSError, match="synthetic read failure"):
            save_upload(upload(stream), Settings(_env_file=None, upload_directory=tmp_path))
    assert list(tmp_path.iterdir()) == []
