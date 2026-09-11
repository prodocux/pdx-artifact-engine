# PDX media adapter

Optional product-neutral media identity and technical-probe package.

- MP4, MOV, and MXF: stream SHA-256 identity and optional bounded `ffprobe`
  metadata.
- R3D: identity only; requires a reviewed RED SDK workflow or approved proxy.
- No semantic, scene, schedule, or content interpretation.
- Input paths are local-process inputs. Applications should pass
  `allowed_roots` when the caller is not fully trusted.

The package does not upload, proxy, decode R3D, or claim analysis readiness.

## Conformance contract proposal

`pdx_adapter_media/schemas` contains the bilaterally frozen v2
technical-profile and v1 conformance request/result contracts. The freeze does
not authorize implementation, and the current executor does not yet claim to
implement them.
`not_evaluated` is a report disposition only; it is never an Engine RunState.
Analyzer or decode failure is `evaluation_failed`, distinct from a measured
`does_not_conform` result.

Consumer mapping is normative for this proposal:

- `not_evaluated`: technical conformance was not requested; create no Engine
  binding and invent no request or expected digest.
- `evaluation_failed`: the check terminal outcome is `failed` with a safe
  error; retryability follows the failure.
- `does_not_conform`: the check terminal outcome is `succeeded` so the verified
  report artifact is retained; the host reads that report and blocks the next
  product step.
- `conforms`: the check terminal outcome is `succeeded` and the host may
  activate the next step.

None maps to `completed_with_review`. Prefer a specific `MEDIA_*_MISMATCH` or
`*_LIMIT_EXCEEDED` issue code. Use `MEDIA_CONFORMANCE_FAILED` only when no
specific code applies.
