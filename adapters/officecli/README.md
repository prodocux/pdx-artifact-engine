# PDX OfficeCLI adapter prototype

This is an optional, disabled-by-default executor prototype. It is not included
in `pdx-artifact-engine`, is not registered in `DEFAULT_EXECUTORS`, and does not
install or redistribute the OfficeCLI binary.

The host must explicitly provide an absolute executable path and its expected
SHA-256, enable the adapter, select an allowed runtime mode, and enforce the
required network policy outside this process. The adapter always passes
`--no-publish`, never uses a shell, bounds prompt and output sizes, and accepts
only DOCX, XLSX, or PPTX output candidates from its private output directory.

OfficeCLI output is untrusted. A host must run the resulting file through the
appropriate ProDocuX Kernel structure/template check before Engine records it
as verified. OfficeCLI messages cannot create approval or authority.

The currently documented OfficeCLI interface accepts `--prompt` on argv. That
may expose prompt text to same-host process inspection. This prototype mirrors
the documented interface only for bounded testing; production enablement is
blocked until OfficeCLI offers a reviewed stdin/prompt-file mechanism or the
host provides an isolation profile that explicitly accepts this exposure.

The public OfficeCLI repository is MIT, but it states that the full binary
implementation is not in that repository. Integrators must separately review
the binary/service terms, privacy behavior, telemetry, and hosted/external
runtime configuration. This prototype does not authorize production use.
