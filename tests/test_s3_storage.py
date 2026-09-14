from io import BytesIO

import pytest

from app.config import Settings
from app.services.storage import S3Storage, get_storage


class Body(BytesIO):
    pass


class FakeS3:
    def __init__(self):
        self.objects = {}

    def upload_fileobj(self, source, bucket, key):
        self.objects[(bucket, key)] = source.read()

    def put_object(self, Bucket, Key, Body):
        self.objects[(Bucket, Key)] = Body

    def get_object(self, Bucket, Key):
        return {"Body": Body(self.objects[(Bucket, Key)])}

    def delete_object(self, Bucket, Key):
        self.objects.pop((Bucket, Key), None)


def test_s3_contract_and_readiness(monkeypatch):
    fake = FakeS3()
    monkeypatch.setattr("app.services.storage.boto3.client", lambda *args, **kwargs: fake)
    storage = S3Storage("synthetic-bucket", "test-region", "http://storage.invalid")

    stored = storage.put([b"synthetic", b" data"], ".txt")

    assert stored.size == 14
    assert len(stored.sha256) == 64
    with storage.open(stored.key) as source:
        assert source.read() == b"synthetic data"
    storage.check_ready()
    storage.delete(stored.key)
    assert fake.objects == {}
    with pytest.raises(ValueError):
        storage.open("../private")


def test_storage_selection_and_required_bucket(monkeypatch):
    fake = FakeS3()
    monkeypatch.setattr("app.services.storage.boto3.client", lambda *args, **kwargs: fake)
    settings = Settings(_env_file=None, storage_backend="s3", s3_bucket="synthetic")
    assert isinstance(get_storage(settings), S3Storage)
    with pytest.raises(RuntimeError, match="S3_BUCKET"):
        Settings(_env_file=None, storage_backend="s3").validate_storage_configuration()
