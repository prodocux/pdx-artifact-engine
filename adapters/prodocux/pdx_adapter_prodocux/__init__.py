"""Product-neutral ProDocuX HTTP adapter.

- Kernel ``/v1`` tools (e.g. validate-structure)
- Skill façades (e.g. pdf_extract_pages) — **not** automatically Kernel routes

Never imports ``prodocux_kernel`` or ``skills.*``.
"""

from .http_client import ProDocuXHttpClient, ProDocuXHttpError
from .pdf_extract_pages import (
    LEGACY_TOOL_ID as PDF_EXTRACT_LEGACY_ID,
    TOOL_ID as PDF_EXTRACT_PAGES_TOOL_ID,
    PdfExtractPagesExecutor,
    make_pdf_extract_pages_executor,
)
from .validate_structure import ValidateStructureExecutor, make_validate_structure_executor
from .table_profile import TableProfileExecutor, make_table_profile_executor
from .workbook_profile import WorkbookProfileExecutor, make_workbook_profile_executor
from .document_profile import DocumentProfileExecutor, make_document_profile_executor
from .presentation_profile import (
    PresentationProfileExecutor,
    make_presentation_profile_executor,
)

__all__ = [
    "ProDocuXHttpClient",
    "ProDocuXHttpError",
    "ValidateStructureExecutor",
    "make_validate_structure_executor",
    "PdfExtractPagesExecutor",
    "make_pdf_extract_pages_executor",
    "PDF_EXTRACT_PAGES_TOOL_ID",
    "PDF_EXTRACT_LEGACY_ID",
    "TableProfileExecutor",
    "make_table_profile_executor",
    "WorkbookProfileExecutor",
    "make_workbook_profile_executor",
    "DocumentProfileExecutor",
    "make_document_profile_executor",
    "PresentationProfileExecutor",
    "make_presentation_profile_executor",
]
