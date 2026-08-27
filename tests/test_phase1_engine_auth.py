"""Phase 1 Engine private façade auth profile (bearer + production mTLS)."""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from pathlib import Path

from pdx_artifact_engine.internal_http import make_server


def test_engine_production_mtls_and_ready(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("PDX_ENGINE_AUTH_PROFILE", "production_mtls")
    monkeypatch.setenv("PDX_ENGINE_BEARER_TOKENS", "engine-token")
    server = make_server(
        host="127.0.0.1",
        port=0,
        db_path=tmp_path / "jobs.sqlite3",
        staging_root=tmp_path / "staging",
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = server.server_address
        base = f"http://{host}:{port}"
        with urllib.request.urlopen(f"{base}/ready") as resp:
            ready = json.loads(resp.read().decode("utf-8"))
        assert ready["status"] == "ready"
        assert ready["checks"]["auth_profile_ok"] is True

        req = urllib.request.Request(
            f"{base}/internal/v1/jobs/missing",
            headers={"Authorization": "Bearer engine-token"},
            method="GET",
        )
        try:
            urllib.request.urlopen(req)
            raise AssertionError("expected AUTH_MTLS_REQUIRED")
        except urllib.error.HTTPError as exc:
            body = json.loads(exc.read().decode("utf-8"))
            assert exc.code == 401
            assert body["code"] == "AUTH_MTLS_REQUIRED"

        ok_req = urllib.request.Request(
            f"{base}/internal/v1/jobs/missing",
            headers={
                "Authorization": "Bearer engine-token",
                "SSL_CLIENT_VERIFY": "SUCCESS",
            },
            method="GET",
        )
        try:
            urllib.request.urlopen(ok_req)
        except urllib.error.HTTPError as exc:
            # Auth passed; job missing is expected.
            body = json.loads(exc.read().decode("utf-8"))
            assert exc.code == 404
            assert body["code"] == "JOB_NOT_FOUND"
    finally:
        server.shutdown()
