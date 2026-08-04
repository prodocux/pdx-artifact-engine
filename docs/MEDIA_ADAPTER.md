# Product-neutral media adapter

`pdx_adapter_media` owns deterministic media identity and optional technical
probing. It is separate from the ProDocuX document Kernel and product
applications.

## Contract

- Always: basename, extension, byte size, SHA-256, immutable source identity.
- MP4/MOV/MXF: call injected `ffprobe` when available; otherwise return
  `review` with `technical_metadata: null` and an explicit error.
- R3D: never send the camera original through generic ffprobe in this adapter.
  Record identity and require RED SDK/DIT sidecars or an approved proxy.
- Always: `interpretation: none`. Scene/content understanding belongs upstream.

The adapter is packaged independently from PDX Artifact Engine. Without
`ffprobe`, it returns identity evidence with `completed_with_review`; camera
original upload, storage, proxy generation, and semantic analysis remain the
responsibility of the product application.
