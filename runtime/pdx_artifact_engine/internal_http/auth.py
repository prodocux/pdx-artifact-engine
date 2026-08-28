"""Engine private façade authentication profile (Phase 1).

Mirrors Kernel sidecar profiles without changing E-05 job contracts:

- unset: opt-in bearer (``PDX_ENGINE_BEARER_TOKENS``)
- ``self_hosted``: bearer required
- ``production_mtls``: bearer + verified client certificate
"""

from __future__ import annotations

import os
import secrets
from collections.abc import Mapping
from typing import Any

PROFILE_SELF_HOSTED = "self_hosted"
PROFILE_PRODUCTION_MTLS = "production_mtls"
_VALID_PROFILES = frozenset({PROFILE_SELF_HOSTED, PROFILE_PRODUCTION_MTLS})


def configured_bearer_tokens() -> frozenset[str]:
    raw = os.environ.get("PDX_ENGINE_BEARER_TOKENS", "").strip()
    if not raw:
        return frozenset()
    return frozenset(part.strip() for part in raw.split(",") if part.strip())


def auth_profile_name() -> str | None:
    raw = os.environ.get("PDX_ENGINE_AUTH_PROFILE", "").strip()
    if not raw:
        return None
    return raw


def mtls_required() -> bool:
    return auth_profile_name() == PROFILE_PRODUCTION_MTLS


def auth_enabled() -> bool:
    profile = auth_profile_name()
    if profile in _VALID_PROFILES:
        return True
    return bool(configured_bearer_tokens())


def auth_profile_ok() -> bool:
    profile = auth_profile_name()
    if profile is None:
        return True
    if profile not in _VALID_PROFILES:
        return False
    return bool(configured_bearer_tokens())


def _mtls_verify_header() -> str:
    return (
        os.environ.get("PDX_ENGINE_MTLS_VERIFY_HEADER", "SSL_CLIENT_VERIFY").strip()
        or "SSL_CLIENT_VERIFY"
    )


def _mtls_verify_value() -> str:
    return (
        os.environ.get("PDX_ENGINE_MTLS_VERIFY_VALUE", "SUCCESS").strip() or "SUCCESS"
    )


def _mtls_trusted_peers() -> frozenset[str]:
    raw = os.environ.get(
        "PDX_ENGINE_MTLS_TRUSTED_PEERS", "127.0.0.1,::1,localhost,testclient"
    ).strip()
    return frozenset(part.strip() for part in raw.split(",") if part.strip())


def client_certificate_verified(
    headers: Mapping[str, str], *, peer: str | None = None
) -> bool:
    """Trust only the configured proxy verify header from a trusted peer.

    Presence of client-certificate forwarding headers is never sufficient.
    """
    if peer is None or peer not in _mtls_trusted_peers():
        return False
    return headers.get(_mtls_verify_header()) == _mtls_verify_value()


def authenticate_request(
    headers: Mapping[str, str], *, peer: str | None = None
) -> dict[str, Any] | None:
    """Return an error document if auth fails; otherwise None."""
    if not auth_enabled():
        return None

    if mtls_required() and not client_certificate_verified(headers, peer=peer):
        return {
            "schema_version": "pdx_internal_error_v1",
            "ok": False,
            "code": "AUTH_MTLS_REQUIRED",
            "message": "verified client certificate required",
            "retryable": False,
            "request_id": "unauthenticated",
            "correlation_id": "unauthenticated",
        }

    tokens = configured_bearer_tokens()
    if not tokens:
        return {
            "schema_version": "pdx_internal_error_v1",
            "ok": False,
            "code": "AUTH_MISCONFIGURED",
            "message": "bearer tokens are not configured for this auth profile",
            "retryable": False,
            "request_id": "unauthenticated",
            "correlation_id": "unauthenticated",
        }

    header = headers.get("Authorization") or headers.get("authorization") or ""
    scheme, _, credential = header.partition(" ")
    if scheme.lower() != "bearer" or not credential:
        return {
            "schema_version": "pdx_internal_error_v1",
            "ok": False,
            "code": "AUTH_REQUIRED",
            "message": "bearer token required",
            "retryable": False,
            "request_id": "unauthenticated",
            "correlation_id": "unauthenticated",
        }
    if not any(secrets.compare_digest(credential, token) for token in tokens):
        return {
            "schema_version": "pdx_internal_error_v1",
            "ok": False,
            "code": "AUTH_INVALID",
            "message": "bearer token rejected",
            "retryable": False,
            "request_id": "unauthenticated",
            "correlation_id": "unauthenticated",
        }
    return None
