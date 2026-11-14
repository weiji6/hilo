"""Aliyun OSS helpers for knowledge ingestion artifacts."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import oss2


@dataclass(frozen=True)
class OssStorageConfig:
    endpoint: str
    bucket: str
    access_key_id: str
    access_key_secret: str
    public_base_url: str | None
    upload_prefix: str
    security_token: str | None = None


def _normalize_host(value: str) -> str:
    return value.replace("https://", "").replace("http://", "").rstrip("/")


def _normalize_base_url(value: str) -> str:
    return value.rstrip("/")


def _sanitize_path_segment(value: str) -> str:
    normalized = re.sub(r"[^\w.-]+", "-", value.strip(), flags=re.ASCII)
    normalized = re.sub(r"-+", "-", normalized).strip("-")
    return (normalized or "file")[:120]


def get_oss_storage_config() -> OssStorageConfig:
    endpoint = os.getenv("OSS_ENDPOINT")
    bucket = os.getenv("OSS_BUCKET")
    access_key_id = os.getenv("OSS_ACCESS_KEY_ID")
    access_key_secret = os.getenv("OSS_ACCESS_KEY_SECRET")
    if not endpoint or not bucket or not access_key_id or not access_key_secret:
        raise RuntimeError(
            "Missing OSS configuration. Set OSS_ENDPOINT, OSS_BUCKET, OSS_ACCESS_KEY_ID, and OSS_ACCESS_KEY_SECRET."
        )

    endpoint_host = _normalize_host(endpoint)
    configured_public_base = os.getenv("OSS_PUBLIC_BASE_URL")
    public_base_url = _normalize_base_url(configured_public_base) if configured_public_base else None
    upload_prefix = (os.getenv("OSS_UPLOAD_PREFIX") or "uploads").strip("/")
    security_token = os.getenv("OSS_SECURITY_TOKEN") or None

    return OssStorageConfig(
        endpoint=endpoint_host,
        bucket=bucket,
        access_key_id=access_key_id,
        access_key_secret=access_key_secret,
        public_base_url=public_base_url,
        upload_prefix=upload_prefix,
        security_token=security_token,
    )


def _create_bucket(config: OssStorageConfig) -> oss2.Bucket:
    endpoint_url = f"https://{config.endpoint}"
    if config.security_token:
        auth = oss2.StsAuth(config.access_key_id, config.access_key_secret, config.security_token)
    else:
        auth = oss2.Auth(config.access_key_id, config.access_key_secret)
    return oss2.Bucket(auth, endpoint_url, config.bucket)


def upload_file_to_oss(
    file_path: Path,
    *,
    namespace: str,
    content_type: str | None = None,
) -> tuple[str, str | None]:
    """Upload a local file to OSS and return (object_key, public_url)."""
    if not file_path.exists():
        raise FileNotFoundError(file_path)

    config = get_oss_storage_config()
    bucket = _create_bucket(config)
    now = datetime.now(UTC)
    object_key = "/".join(
        [
            config.upload_prefix,
            namespace.strip("/"),
            f"{now.year:04d}",
            f"{now.month:02d}",
            f"{now.day:02d}",
            f"{uuid4()}-{_sanitize_path_segment(file_path.name)}",
        ]
    )

    headers: dict[str, str] = {}
    if content_type:
        headers["Content-Type"] = content_type

    result = bucket.put_object_from_file(object_key, str(file_path), headers=headers or None)
    if result.status // 100 != 2:
        raise RuntimeError(f"OSS upload failed with status {result.status}")

    public_url = f"{config.public_base_url}/{object_key}" if config.public_base_url else None
    return object_key, public_url


def build_oss_download_url(object_key: str, expires_seconds: int = 60 * 60 * 2) -> str:
    """Create a temporary signed GET URL for a stored OSS object."""
    normalized_key = object_key.strip("/")
    if not normalized_key:
        raise ValueError("object_key is required")

    config = get_oss_storage_config()
    bucket = _create_bucket(config)
    return bucket.sign_url("GET", normalized_key, expires_seconds)


def delete_oss_object(object_key: str) -> None:
    """Delete an object from OSS if it exists."""
    normalized_key = object_key.strip("/")
    if not normalized_key:
        raise ValueError("object_key is required")

    config = get_oss_storage_config()
    bucket = _create_bucket(config)
    result = bucket.delete_object(normalized_key)
    if result.status not in {200, 204, 404}:
        raise RuntimeError(f"OSS delete failed with status {result.status}")
