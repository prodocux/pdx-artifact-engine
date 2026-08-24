"""Tests for ProDocuX HTTP adapter (mocked Kernel)."""

from __future__ import annotations

import base64
import hashlib
import io
import json
from pathlib import Path

import pytest

from pdx_adapter_prodocux import (
    ProDocuXHttpClient,
    ProDocuXHttpError,
    ValidateStructureExecutor,
    PdfExtractPagesExecutor,
    TableProfileExecutor,
    WorkbookProfileExecutor,
    DocumentProfileExecutor,
    PresentationProfileExecutor,
    ExtractContentBlocksExecutor,
    RenderArtifactExecutor,
)
from pdx_adapter_prodocux.pdf_extract_pages import resolve_pdf_bytes
from pdx_adapter_prodocux.validate_structure import resolve_document_path_for_kernel


class _FakeResp:
    def __init__(self, payload: dict, status: int = 200) -> None:
        self._raw = json.dumps(payload).encode("utf-8")
        self.status = status

    def read(self) -> bytes:
        return self._raw

    def getcode(self) -> int:
        return self.status

    def __enter__(self) -> "_FakeResp":
        return self

    def __exit__(self, *args: object) -> None:
        return None


def test_validate_structure_writes_report(tmp_path: Path) -> None:
    payload = {
        "kernel_version": "0.0-test",
        "passed": True,
        "invariants": [
            {"id": "valid_docx", "passed": True, "status": "checked", "code": ""},
        ],
    }

    def opener(req: object, timeout: float = 0) -> _FakeResp:
        return _FakeResp(payload)

    client = ProDocuXHttpClient("http://example.test/v1", opener=opener)
    executor = ValidateStructureExecutor(client)
    result = executor(
        {"document_path": str(tmp_path / "doc.docx")},
        tmp_path / "out",
    )
    assert result["result"]["passed"] is True
    report = tmp_path / "out" / "validate_structure.json"
    assert report.is_file()
    assert json.loads(report.read_text(encoding="utf-8"))["passed"] is True


def test_rejects_signed_document_uri(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="forbidden|signed"):
        resolve_document_path_for_kernel(
            {
                "document_uri": (
                    "gs://bucket/obj?X-Goog-Signature=abc&X-Goog-Credential=x"
                )
            },
            tmp_path,
        )


def test_document_b64_writes_under_output(tmp_path: Path) -> None:
    raw = b"PK\x03\x04fake-docx"
    path, _ = resolve_document_path_for_kernel(
        {
            "document_b64": base64.b64encode(raw).decode("ascii"),
            "document_filename": "tiny.docx",
        },
        tmp_path / "step",
    )
    assert Path(path).read_bytes() == raw
    assert Path(path).name == "tiny.docx"


def test_http_error_surfaces_status() -> None:
    import urllib.error

    def opener(req: object, timeout: float = 0) -> None:
        raise urllib.error.HTTPError(
            url="http://example.test/v1/validate-structure",
            code=503,
            msg="unavailable",
            hdrs=None,  # type: ignore[arg-type]
            fp=io.BytesIO(b'{"detail":"down"}'),
        )

    client = ProDocuXHttpClient("http://example.test/v1", opener=opener)
    with pytest.raises(ProDocuXHttpError, match="503") as excinfo:
        client.validate_structure(document_path="/tmp/x.docx")
    assert excinfo.value.status == 503


def test_http_client_calls_frozen_pdf_intake_contract() -> None:
    observed = {}

    def opener(req: object, timeout: float = 0) -> _FakeResp:
        observed["url"] = req.full_url
        observed["payload"] = json.loads(req.data.decode("utf-8"))
        return _FakeResp(
            {
                "status": "ocr_required",
                "source_sha256": "a" * 64,
                "page_count": 1,
                "pages": [{"page_number": 1, "text": "", "ocr_required": True}],
                "truncation": {"truncated": False, "total_characters": 0},
            }
        )

    result = ProDocuXHttpClient("http://example.test/v1", opener=opener).extract_pages(
        document_b64="JVBERg==",
        document_filename="sample.pdf",
        max_pages=10,
    )
    assert observed["url"].endswith("/v1/intake/extract-pages")
    assert observed["payload"]["max_pages"] == 10
    assert result["status"] == "ocr_required"


def test_http_error_does_not_expose_response_body() -> None:
    import urllib.error

    secret = "access_token=do-not-leak"

    def opener(req: object, timeout: float = 0) -> None:
        raise urllib.error.HTTPError(
            url="http://example.test/v1/validate-structure",
            code=500,
            msg="error",
            hdrs=None,  # type: ignore[arg-type]
            fp=io.BytesIO(secret.encode("utf-8")),
        )

    client = ProDocuXHttpClient("http://example.test/v1", opener=opener)
    with pytest.raises(ProDocuXHttpError) as excinfo:
        client.validate_structure(document_path="document.docx")
    assert secret not in str(excinfo.value)
    assert not hasattr(excinfo.value, "body")


@pytest.mark.parametrize(
    "base_url",
    [
        "ftp://example.test/v1",
        "https://token@example.test/v1",
        "https://example.test/v1?token=secret",
    ],
)
def test_http_client_rejects_unsafe_base_url(base_url: str) -> None:
    with pytest.raises(ValueError):
        ProDocuXHttpClient(base_url)


@pytest.mark.parametrize(
    "facade_url",
    [
        "file:///tmp/extract-pages",
        "https://token@example.test/extract-pages",
        "https://example.test/extract-pages?token=secret",
        "https://example.test/extract-pages#fragment",
    ],
)
def test_pdf_extract_rejects_unsafe_facade_url(facade_url: str) -> None:
    with pytest.raises(ValueError, match="facade_url"):
        PdfExtractPagesExecutor(facade_url=facade_url)


def test_pdf_extract_validates_facade_url_from_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PRODOCUX_PDF_EXTRACT_URL", "file:///tmp/extract-pages")
    with pytest.raises(ValueError, match="facade_url"):
        PdfExtractPagesExecutor()


@pytest.mark.parametrize("timeout", [0, -1, float("inf"), float("nan")])
def test_http_client_rejects_invalid_timeout(timeout: float) -> None:
    with pytest.raises(ValueError, match="timeout"):
        ProDocuXHttpClient("http://example.test/v1", timeout_s=timeout)


def test_pdf_extract_rejects_path_without_allow(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PDX_ALLOW_LOCAL_PDF_PATH", raising=False)
    with pytest.raises(ValueError, match="PDX_ALLOW_LOCAL_PDF_PATH"):
        resolve_pdf_bytes({"pdf_path": str(tmp_path / "a.pdf")}, tmp_path)


def test_pdf_extract_allows_existing_local_path_only_when_enabled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "source.pdf"
    source.write_bytes(b"%PDF-1.1\n%%EOF\n")
    monkeypatch.setenv("PDX_ALLOW_LOCAL_PDF_PATH", "1")
    raw, filename, uri = resolve_pdf_bytes(
        {"pdf_path": str(source)}, tmp_path / "output"
    )
    assert raw == source.read_bytes()
    assert filename == "source.pdf"
    assert uri is None


def test_pdf_extract_stub_from_b64(tmp_path: Path) -> None:
    raw = b"%PDF-1.1\ntrailer\n%%EOF\n"
    executor = PdfExtractPagesExecutor(facade_url="")
    result = executor(
        {
            "pdf_b64": base64.b64encode(raw).decode("ascii"),
            "pdf_filename": "tiny.pdf",
        },
        tmp_path / "pdf_out",
    )
    pages = tmp_path / "pdf_out" / "pages.json"
    assert pages.is_file()
    doc = json.loads(pages.read_text(encoding="utf-8"))
    assert doc["schema"] == "pdx_pages_facade_v0"
    assert result["result"]["tool"] == "prodocux.pdf_extract_pages"
    # stub or pypdf — both acceptable without live façade
    assert result["result"]["mode"] in {"stub", "pypdf", "pypdf_error"}
    if result["result"]["mode"] == "stub":
        assert result["result"]["ok"] is False
        assert result["result"]["status"] == "failed"


def test_pdf_extract_rejects_signed_uri(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="forbidden|signed|gs://"):
        resolve_pdf_bytes(
            {
                "pdf_uri": "gs://b/o?X-Goog-Signature=deadbeef",
            },
            tmp_path,
        )


def test_pdf_extract_http_facade(tmp_path: Path) -> None:
    payload = {
        "document": {
            "schema": "pdx_pages_facade_v0",
            "engine": "remote_facade",
            "page_count": 1,
            "pages": [{"file": "x.pdf", "page": 1, "text": "hi", "char_count": 2}],
            "errors": {},
        }
    }

    def opener(req: object, timeout: float = 0) -> _FakeResp:
        return _FakeResp(payload)

    client = ProDocuXHttpClient("http://example.test/v1", opener=opener)
    executor = PdfExtractPagesExecutor(
        facade_url="http://example.test/extract-pages",
        http_client=client,
    )
    result = executor(
        {
            "pdf_b64": base64.b64encode(b"%PDF-1.1").decode("ascii"),
            "pdf_filename": "x.pdf",
        },
        tmp_path / "http_out",
    )
    assert result["result"]["mode"] == "http_facade"
    assert result["result"]["ok"] is True
    assert result["result"]["page_count"] == 1


def test_table_profile_calls_kernel_and_writes_artifact(tmp_path: Path) -> None:
    payload = {
        "kernel_version": "0.1-test",
        "profile": {
            "schema_version": "prodocux_table_profile_v1",
            "source": {"name": "schedule.csv", "sha256": "a" * 64},
            "columns": ["date", "unit"],
            "row_count": 1,
            "preview": [{"date": "2026-08-02", "unit": "A"}],
            "interpretation": "none",
        },
    }

    def opener(req: object, timeout: float = 0) -> _FakeResp:
        assert getattr(req, "full_url").endswith("/v1/intake/profile-table")
        return _FakeResp(payload)

    source = tmp_path / "schedule.csv"
    source.write_text("date,unit\n2026-08-02,A\n", encoding="utf-8")
    executor = TableProfileExecutor(
        ProDocuXHttpClient("http://example.test/v1", opener=opener)
    )
    result = executor({"table_path": str(source)}, tmp_path / "out")
    assert result["result"]["kernel_version"] == "0.1-test"
    assert result["outputs"]["profile"]["interpretation"] == "none"
    assert (tmp_path / "out" / "table_profile.json").is_file()


def test_workbook_profile_calls_kernel_and_writes_artifact(tmp_path: Path) -> None:
    payload = {
        "kernel_version": "0.1-test",
        "profile": {
            "schema_version": "prodocux_workbook_profile_v1",
            "source": {"name": "schedule.xlsx", "sha256": "b" * 64},
            "sheet_count": 1,
            "sheets": [{"name": "Unit A", "preview": []}],
            "interpretation": "none",
        },
    }

    def opener(req: object, timeout: float = 0) -> _FakeResp:
        assert getattr(req, "full_url").endswith("/v1/intake/profile-workbook")
        return _FakeResp(payload)

    source = tmp_path / "schedule.xlsx"
    source.write_bytes(b"PK\x03\x04fixture")
    executor = WorkbookProfileExecutor(
        ProDocuXHttpClient("http://example.test/v1", opener=opener)
    )
    result = executor({"workbook_path": str(source)}, tmp_path / "workbook-out")
    assert result["result"]["sheet_count"] == 1
    assert result["outputs"]["profile"]["interpretation"] == "none"
    assert (tmp_path / "workbook-out" / "workbook_profile.json").is_file()


def test_document_profile_calls_kernel_and_writes_artifact(tmp_path: Path) -> None:
    payload = {
        "kernel_version": "0.1-test",
        "profile": {
            "schema_version": "prodocux_docx_profile_v1",
            "source": {"name": "brief.docx", "sha256": "c" * 64},
            "paragraph_count": 2,
            "table_count": 1,
            "paragraphs": [],
            "interpretation": "none",
        },
    }

    def opener(req: object, timeout: float = 0) -> _FakeResp:
        assert getattr(req, "full_url").endswith("/v1/intake/profile-document")
        return _FakeResp(payload)

    source = tmp_path / "brief.docx"
    source.write_bytes(b"PK\x03\x04fixture")
    executor = DocumentProfileExecutor(
        ProDocuXHttpClient("http://example.test/v1", opener=opener)
    )
    result = executor({"document_path": str(source)}, tmp_path / "document-out")
    assert result["result"]["paragraph_count"] == 2
    assert result["outputs"]["profile"]["interpretation"] == "none"
    assert (tmp_path / "document-out" / "document_profile.json").is_file()


def test_presentation_profile_calls_kernel_and_writes_artifact(tmp_path: Path) -> None:
    payload = {
        "kernel_version": "0.1-test",
        "profile": {
            "schema_version": "prodocux_presentation_profile_v1",
            "source": {"name": "plan.pptx", "sha256": "d" * 64},
            "slide_count": 1,
            "slides": [{"slide_number": 1, "title": "Plan"}],
            "interpretation": "none",
        },
    }

    def opener(req: object, timeout: float = 0) -> _FakeResp:
        assert getattr(req, "full_url").endswith("/v1/intake/profile-presentation")
        return _FakeResp(payload)

    source = tmp_path / "plan.pptx"
    source.write_bytes(b"PK\x03\x04fixture")
    executor = PresentationProfileExecutor(
        ProDocuXHttpClient("http://example.test/v1", opener=opener)
    )
    result = executor({"presentation_path": str(source)}, tmp_path / "presentation-out")
    assert result["result"]["slide_count"] == 1
    assert result["outputs"]["profile"]["interpretation"] == "none"
    assert (tmp_path / "presentation-out" / "presentation_profile.json").is_file()


def test_extract_content_blocks_calls_kernel_and_writes_artifact(tmp_path: Path) -> None:
    payload = {
        "kernel_version": "0.1-test",
        "format": "csv",
        "source_sha256": "e" * 64,
        "truncated": False,
        "content": {
            "schema_version": "prodocux_content_blocks_v1",
            "blocks": [{"id": "s1", "type": "sheet", "name": "Sheet", "table": {"rows": [["a"]]}}],
        },
        "text_items": [{"id": "s1.r1", "type": "sheet_row", "text": "a", "source_locator": "sheet:Sheet/r1"}],
    }

    def opener(req: object, timeout: float = 0) -> _FakeResp:
        assert getattr(req, "full_url").endswith("/v1/intake/extract-blocks")
        return _FakeResp(payload)

    source = tmp_path / "rows.csv"
    source.write_text("a\n", encoding="utf-8")
    executor = ExtractContentBlocksExecutor(
        ProDocuXHttpClient("http://example.test/v1", opener=opener)
    )
    result = executor({"document_path": str(source)}, tmp_path / "blocks-out")
    assert result["result"]["format"] == "csv"
    assert result["outputs"]["content"]["schema_version"] == "prodocux_content_blocks_v1"
    assert (tmp_path / "blocks-out" / "content_blocks.json").is_file()


def test_render_artifact_executor_writes_inline_file_and_rejects_gs(tmp_path: Path) -> None:
    payload = {
        "schema_version": "prodocux_render_result_v1",
        "status": "completed",
        "kernel_version": "0.1-test",
        "renderer_id": "prodocux.blocks.csv",
        "renderer_version": "0.1-test",
        "target_format": "csv",
        "validation": {"passed": True, "reasons": []},
        "media_type": "text/csv",
        "output_sha256": hashlib.sha256(b"id,label\n1,alpha\n").hexdigest(),
        "content_b64": base64.b64encode(b"id,label\n1,alpha\n").decode("ascii"),
    }

    def opener(req: object, timeout: float = 0) -> _FakeResp:
        assert getattr(req, "full_url").endswith("/v1/render/artifact")
        return _FakeResp(payload)

    executor = RenderArtifactExecutor(
        ProDocuXHttpClient("http://example.test/v1", opener=opener)
    )
    kernel_request = {
        "schema_version": "prodocux_render_request_v1",
        "request_id": "t1",
        "target_format": "csv",
        "content": {
            "schema_version": "prodocux_content_blocks_v1",
            "blocks": [{"id": "s1", "type": "sheet", "name": "Sheet", "table": {"rows": [["id"]]}}],
        },
        "output": {"output_name": "out.csv", "delivery_mode": "inline"},
    }
    result = executor({"kernel_request": kernel_request}, tmp_path / "render-out")
    assert result["result"]["status"] == "completed"
    assert (tmp_path / "render-out" / "out.csv").read_bytes().startswith(b"id,label")
    with pytest.raises(ValueError, match="storage URLs"):
        executor(
            {
                "kernel_request": {
                    **kernel_request,
                    "template": {"artifact": {"uri": "gs://bucket/obj"}},
                }
            },
            tmp_path / "render-bad",
        )


def test_render_artifact_executor_rejects_output_digest_mismatch(tmp_path: Path) -> None:
    payload = {
        "schema_version": "prodocux_render_result_v1",
        "status": "completed",
        "kernel_version": "0.1-test",
        "renderer_id": "prodocux.blocks.csv",
        "renderer_version": "0.1-test",
        "target_format": "csv",
        "validation": {"passed": True, "reasons": []},
        "media_type": "text/csv",
        "output_sha256": "0" * 64,
        "content_b64": base64.b64encode(b"id,label\n1,alpha\n").decode("ascii"),
    }

    def opener(req: object, timeout: float = 0) -> _FakeResp:
        return _FakeResp(payload)

    executor = RenderArtifactExecutor(
        ProDocuXHttpClient("http://example.test/v1", opener=opener)
    )
    kernel_request = {
        "schema_version": "prodocux_render_request_v1",
        "request_id": "t-mismatch",
        "target_format": "csv",
        "content": {
            "schema_version": "prodocux_content_blocks_v1",
            "blocks": [{"id": "s1", "type": "sheet", "name": "Sheet", "table": {"rows": [["id"]]}}],
        },
        "output": {"output_name": "out.csv", "delivery_mode": "inline"},
    }
    with pytest.raises(ValueError, match="output_sha256"):
        executor({"kernel_request": kernel_request}, tmp_path / "render-mismatch")


class _FakeBytesResp:
    def __init__(self, raw: bytes, status: int = 200) -> None:
        self._raw = raw
        self.status = status

    def read(self) -> bytes:
        return self._raw

    def getcode(self) -> int:
        return self.status

    def __enter__(self) -> "_FakeBytesResp":
        return self

    def __exit__(self, *args: object) -> None:
        return None


def test_render_artifact_executor_retrieves_kernel_identity(tmp_path: Path) -> None:
    raw = b"PK\x03\x04synthetic-docx"
    digest = hashlib.sha256(raw).hexdigest()
    payload = {
        "schema_version": "prodocux_render_result_v1",
        "status": "completed",
        "kernel_version": "0.3.0rc1",
        "renderer_id": "prodocux.blocks.docx",
        "renderer_version": "0.3.0rc1",
        "target_format": "docx",
        "validation": {"passed": True, "reasons": []},
        "media_type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "output_sha256": digest,
        "artifact": {
            "schema_version": "prodocux_opaque_artifact_v1",
            "artifact_id": "out-docx",
            "uri": "artifact://render/out.docx",
            "sha256": digest,
            "size_bytes": len(raw),
            "media_type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        },
    }

    def opener(req: object, timeout: float = 0) -> object:
        url = getattr(req, "full_url")
        if url.endswith("/v1/render/artifact"):
            return _FakeResp(payload)
        if url.endswith("/v1/render/artifacts/out-docx"):
            return _FakeBytesResp(raw)
        raise AssertionError(url)

    executor = RenderArtifactExecutor(
        ProDocuXHttpClient("http://example.test/v1", opener=opener)
    )
    kernel_request = {
        "schema_version": "prodocux_render_request_v1",
        "request_id": "t-artifact",
        "target_format": "docx",
        "content": {
            "schema_version": "prodocux_content_blocks_v1",
            "blocks": [{"id": "h1", "type": "heading", "level": 1, "text": "T"}],
        },
        "output": {"output_name": "out.docx", "delivery_mode": "artifact"},
    }
    mapped = executor.execute(
        {"tool": "prodocux.render_artifact", "inputs": {"kernel_request": kernel_request}},
        {"output_dir": str(tmp_path / "render-artifact")},
    )
    assert mapped["status"] == "completed"
    assert mapped["artifacts"][0]["uri"] == "artifact://render/out.docx"
    assert mapped["artifacts"][0]["checksum"] == f"sha256:{digest}"
    written = tmp_path / "render-artifact" / "out.docx"
    assert written.read_bytes() == raw
    assert hashlib.sha256(written.read_bytes()).hexdigest() == digest


def test_render_artifact_executor_rejects_retrieved_digest_mismatch(tmp_path: Path) -> None:
    declared = "0" * 64
    payload = {
        "schema_version": "prodocux_render_result_v1",
        "status": "completed",
        "kernel_version": "0.1-test",
        "renderer_id": "prodocux.blocks.docx",
        "renderer_version": "0.1-test",
        "target_format": "docx",
        "validation": {"passed": True, "reasons": []},
        "media_type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "output_sha256": declared,
        "artifact": {
            "schema_version": "prodocux_opaque_artifact_v1",
            "artifact_id": "out-docx",
            "uri": "artifact://render/out.docx",
            "sha256": declared,
            "size_bytes": 4,
            "media_type": "application/octet-stream",
        },
    }

    def opener(req: object, timeout: float = 0) -> object:
        url = getattr(req, "full_url")
        if url.endswith("/v1/render/artifact"):
            return _FakeResp(payload)
        return _FakeBytesResp(b"real")

    executor = RenderArtifactExecutor(
        ProDocuXHttpClient("http://example.test/v1", opener=opener)
    )
    kernel_request = {
        "schema_version": "prodocux_render_request_v1",
        "request_id": "t-artifact-mismatch",
        "target_format": "docx",
        "content": {
            "schema_version": "prodocux_content_blocks_v1",
            "blocks": [{"id": "h1", "type": "heading", "level": 1, "text": "T"}],
        },
        "output": {"output_name": "out.docx", "delivery_mode": "artifact"},
    }
    with pytest.raises(ValueError, match="output_sha256"):
        executor({"kernel_request": kernel_request}, tmp_path / "render-get-mismatch")
