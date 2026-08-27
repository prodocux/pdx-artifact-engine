"""Engine-owned TTL filesystem staging for private job payloads."""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import time
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class StagingHandle:
    handle: str
    sha256: str
    size_bytes: int
    media_type: str
    expires_at: str  # RFC3339 Zulu

    def as_wire(self) -> dict:
        return {
            "schema_version": "pdx_staging_handle_v1",
            "handle": self.handle,
            "sha256": self.sha256,
            "size_bytes": self.size_bytes,
            "media_type": self.media_type,
            "expires_at": self.expires_at,
        }


class StagingStore:
    """Permission-restricted TTL staging root (Engine-owned)."""

    def __init__(
        self,
        root: Path | None = None,
        *,
        ttl_seconds: int | None = None,
        max_decoded_bytes: int | None = None,
    ) -> None:
        self.root = (root or Path(os.environ.get("PDX_ENGINE_STAGING_ROOT", "/var/lib/pdx-engine/staging"))).resolve()
        self.ttl_seconds = int(
            ttl_seconds
            if ttl_seconds is not None
            else os.environ.get("PDX_ENGINE_STAGING_TTL_SECONDS", "3600")
        )
        self.max_decoded_bytes = int(
            max_decoded_bytes
            if max_decoded_bytes is not None
            else os.environ.get("PDX_ENGINE_MAX_DECODED_BYTES", "33554432")
        )
        self.root.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(self.root, 0o700)
        except OSError:
            # Windows may ignore POSIX mode bits; fail open for local dev.
            pass

    def stage(
        self,
        *,
        payload: bytes,
        media_type: str,
        expected_sha256: str | None = None,
    ) -> StagingHandle:
        if len(payload) < 1 or len(payload) > self.max_decoded_bytes:
            raise ValueError("PAYLOAD_SIZE")
        digest = hashlib.sha256(payload).hexdigest()
        if expected_sha256 is not None and digest != expected_sha256:
            raise ValueError("DIGEST_MISMATCH")
        handle = f"stg_{secrets.token_hex(16)}"
        expires = int(time.time()) + self.ttl_seconds
        expires_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(expires))
        meta = {
            "handle": handle,
            "sha256": digest,
            "size_bytes": len(payload),
            "media_type": media_type,
            "expires_at": expires_at,
            "expires_unix": expires,
        }
        payload_path = self.root / f"{handle}.bin"
        meta_path = self.root / f"{handle}.json"
        tmp_payload = Path(str(payload_path) + ".tmp")
        tmp_meta = Path(str(meta_path) + ".tmp")
        tmp_payload.write_bytes(payload)
        tmp_meta.write_text(json.dumps(meta, ensure_ascii=True) + "\n", encoding="utf-8")
        os.replace(tmp_payload, payload_path)
        os.replace(tmp_meta, meta_path)
        try:
            os.chmod(payload_path, 0o600)
            os.chmod(meta_path, 0o600)
        except OSError:
            pass
        return StagingHandle(
            handle=handle,
            sha256=digest,
            size_bytes=len(payload),
            media_type=media_type,
            expires_at=expires_at,
        )

    def read_bytes(self, handle: str) -> bytes | None:
        meta = self._load_meta(handle)
        if meta is None:
            return None
        if int(meta["expires_unix"]) < int(time.time()):
            self.delete(handle)
            return None
        path = self.root / f"{handle}.bin"
        if not path.exists():
            return None
        return path.read_bytes()

    def get_handle(self, handle: str) -> StagingHandle | None:
        meta = self._load_meta(handle)
        if meta is None:
            return None
        if int(meta["expires_unix"]) < int(time.time()):
            self.delete(handle)
            return None
        return StagingHandle(
            handle=meta["handle"],
            sha256=meta["sha256"],
            size_bytes=int(meta["size_bytes"]),
            media_type=meta["media_type"],
            expires_at=meta["expires_at"],
        )

    def delete(self, handle: str) -> None:
        for path in (self.root / f"{handle}.bin", self.root / f"{handle}.json"):
            if path.exists():
                path.unlink()

    def _load_meta(self, handle: str) -> dict | None:
        if not handle.startswith("stg_"):
            return None
        path = self.root / f"{handle}.json"
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))
