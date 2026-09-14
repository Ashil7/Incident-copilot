"""Storage contract and local implementation with generated, confined object keys."""

import hashlib
import re
import tempfile
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Protocol
from uuid import uuid4

import boto3

from app.config import PROJECT_ROOT, Settings


@dataclass(frozen=True)
class StoredObject:
    key: str
    size: int
    sha256: str


class Storage(Protocol):
    scope: str

    def put(self, chunks: Iterable[bytes], suffix: str) -> StoredObject: ...
    def open(self, key: str) -> BinaryIO: ...
    def delete(self, key: str) -> None: ...
    def check_ready(self) -> None: ...


class LocalStorage:
    def __init__(self, directory: Path):
        self.root = directory.resolve()
        self.scope = hashlib.sha256(str(self.root).encode("utf-8")).hexdigest()

    def path(self, key: str) -> Path:
        if not re.fullmatch(
            r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}\.(?:log|txt|json|md|pdf)", key
        ):
            raise ValueError("Invalid storage key.")
        path = self.root / key
        if path.is_symlink() or not path.resolve().is_relative_to(self.root):
            raise ValueError("Storage object is outside the upload directory.")
        return path

    def put(self, chunks: Iterable[bytes], suffix: str) -> StoredObject:
        key = f"{uuid4()}{suffix}"
        path = self.path(key)
        self.root.mkdir(parents=True, exist_ok=True)
        digest, size = hashlib.sha256(), 0
        created = False
        try:
            with path.open("xb") as target:
                created = True
                for chunk in chunks:
                    target.write(chunk)
                    digest.update(chunk)
                    size += len(chunk)
            return StoredObject(key, size, digest.hexdigest())
        except BaseException:
            if created:
                path.unlink(missing_ok=True)
            raise

    def open(self, key: str) -> BinaryIO:
        return self.path(key).open("rb")

    def delete(self, key: str) -> None:
        self.path(key).unlink(missing_ok=True)

    def check_ready(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryFile(dir=self.root) as probe:
            probe.write(b"ready")
            probe.flush()
            probe.seek(0)
            if probe.read() != b"ready":
                raise OSError("Storage readiness probe failed.")


class S3Storage:
    """S3-compatible object storage; credentials come from the standard AWS chain."""

    def __init__(self, bucket: str, region: str = "", endpoint_url: str = ""):
        self.bucket = bucket
        self.scope = hashlib.sha256(
            f"s3:{endpoint_url}:{region}:{bucket}".encode("utf-8")
        ).hexdigest()
        self.client = boto3.client(
            "s3", region_name=region or None, endpoint_url=endpoint_url or None
        )

    @staticmethod
    def validate_key(key: str) -> str:
        if not re.fullmatch(
            r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}\.(?:log|txt|json|md|pdf)", key
        ):
            raise ValueError("Invalid storage key.")
        return key

    def put(self, chunks: Iterable[bytes], suffix: str) -> StoredObject:
        key = self.validate_key(f"{uuid4()}{suffix}")
        digest, size = hashlib.sha256(), 0
        with tempfile.SpooledTemporaryFile(max_size=8 * 1024 * 1024) as source:
            for chunk in chunks:
                source.write(chunk)
                digest.update(chunk)
                size += len(chunk)
            source.seek(0)
            self.client.upload_fileobj(source, self.bucket, key)
        return StoredObject(key, size, digest.hexdigest())

    def open(self, key: str) -> BinaryIO:
        return self.client.get_object(Bucket=self.bucket, Key=self.validate_key(key))["Body"]

    def delete(self, key: str) -> None:
        self.client.delete_object(Bucket=self.bucket, Key=self.validate_key(key))

    def check_ready(self) -> None:
        key = self.validate_key(f"{uuid4()}.txt")
        try:
            self.client.put_object(Bucket=self.bucket, Key=key, Body=b"ready")
            body = self.client.get_object(Bucket=self.bucket, Key=key)["Body"]
            try:
                if body.read() != b"ready":
                    raise OSError("S3 readiness probe failed.")
            finally:
                body.close()
        finally:
            self.client.delete_object(Bucket=self.bucket, Key=key)


def get_storage(settings: Settings) -> Storage:
    if settings.storage_backend == "s3":
        settings.validate_storage_configuration()
        return S3Storage(settings.s3_bucket, settings.s3_region, settings.s3_endpoint_url)
    directory = settings.upload_directory
    if not directory.is_absolute():
        directory = PROJECT_ROOT / directory
    return LocalStorage(directory)
