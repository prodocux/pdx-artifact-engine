# PDX media adapter

Optional product-neutral media identity and technical-probe package.

- MP4, MOV, and MXF: stream SHA-256 identity and optional bounded `ffprobe`
  metadata.
- R3D: identity only; requires a reviewed RED SDK workflow or approved proxy.
- No semantic, scene, schedule, or content interpretation.
- Input paths are local-process inputs. Applications should pass
  `allowed_roots` when the caller is not fully trusted.

The package does not upload, proxy, decode R3D, or claim analysis readiness.
