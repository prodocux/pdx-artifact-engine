# adapters/prodocux

Product-neutral ProDocuX HTTP adapter — **no** `prodocux_kernel` / `skills.*`
import.

## Tools

| Tool id | Surface | Status |
|---|---|---|
| `prodocux.validate_structure` | Kernel `POST /v1/validate-structure` | implemented |
| `prodocux.pdf_extract_pages` | PDF skill façade (Kernel has PDF intake primitives; semantic `/v1/extract` remains 501) | implemented |
| `prodocux.pdf_extract` | Legacy registry alias → same executor | supported |
| `prodocux.table_profile` | Kernel `POST /v1/intake/profile-table` | implemented |
| `prodocux.workbook_profile` | Kernel `POST /v1/intake/profile-workbook` | implemented (`.xlsx`) |
| `prodocux.document_profile` | Kernel `POST /v1/intake/profile-document` | implemented (`.docx`) |
| `prodocux.presentation_profile` | Kernel `POST /v1/intake/profile-presentation` | implemented (`.pptx`) |

## Usage

```python
from pdx_adapter_prodocux import (
    make_validate_structure_executor,
    make_pdf_extract_pages_executor,
    make_table_profile_executor,
)

vs = make_validate_structure_executor("http://127.0.0.1:8900/v1")
pdf = make_pdf_extract_pages_executor()  # local pypdf or stub
table = make_table_profile_executor("http://127.0.0.1:8900/v1")
# optional live façade:
# pdf = make_pdf_extract_pages_executor("https://…/extract-pages")
```

### Env

| Var | Meaning |
|---|---|
| `PRODOCUX_V1_BASE_URL` | Kernel `/v1` root (validate-structure) |
| `PRODOCUX_PDF_EXTRACT_URL` | Full URL of PDF skill façade endpoint |
| `PDX_ALLOW_LOCAL_PDF_PATH=1` | Dev-only: allow `pdf_path` / `source_pdf` |

### pdf_extract_pages inputs

- `pdf_b64` + `pdf_filename` (`.pdf`, ≤ 8 MiB decoded) — preferred for small files
- `pdf_uri` — `gs://` object **identity** only (never signed URLs)
- `pdf_path` / `source_pdf` — only with `PDX_ALLOW_LOCAL_PDF_PATH=1`

Local mode uses optional `pypdf` if installed; otherwise it writes a disclosed,
failed stub result that cannot be mistaken for completed extraction.
