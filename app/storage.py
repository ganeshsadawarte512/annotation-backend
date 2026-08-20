"""Video storage abstraction.

STORAGE_BACKEND=local (default): saves to UPLOAD_DIR on disk, served via /media.
STORAGE_BACKEND=s3: saves to an S3-compatible bucket (e.g. Cloudflare R2, AWS S3).
Swap by changing STORAGE_BACKEND in .env — route code never needs to change.
"""
import os
import shutil
import uuid
from pathlib import Path

from fastapi import UploadFile

from app.config import settings

Path(settings.upload_dir).mkdir(parents=True, exist_ok=True)


class LocalStorage:
    def save(self, file: UploadFile, game_uid: str) -> str:
        ext = os.path.splitext(file.filename)[1] or ".mp4"
        key = f"{game_uid}{ext}"
        dest = Path(settings.upload_dir) / key
        with dest.open("wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
        return f"/media/{key}"


class S3Storage:
    """Requires boto3 (add to requirements.txt) and S3_* env vars set.
    Works as-is for AWS S3 or any S3-compatible endpoint like Cloudflare R2."""

    def __init__(self):
        import boto3  # imported lazily so local dev doesn't need boto3 installed

        self.client = boto3.client(
            "s3",
            endpoint_url=settings.s3_endpoint_url or None,
            aws_access_key_id=settings.s3_access_key,
            aws_secret_access_key=settings.s3_secret_key,
            region_name=settings.s3_region,
        )
        self.bucket = settings.s3_bucket

    def save(self, file: UploadFile, game_uid: str) -> str:
        ext = os.path.splitext(file.filename)[1] or ".mp4"
        key = f"videos/{game_uid}{ext}"
        self.client.upload_fileobj(file.file, self.bucket, key)
        return key  # generate a presigned URL when serving, not stored here


def get_storage():
    if settings.storage_backend == "s3":
        return S3Storage()
    return LocalStorage()
