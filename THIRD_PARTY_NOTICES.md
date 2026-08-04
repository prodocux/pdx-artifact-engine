# Third-party components

This repository does not vendor third-party source, model weights, media
binaries, or executable tool builds.

Runtime and optional integrations may use separately installed dependencies,
including `jsonschema`, `pypdf`, and `ffprobe`. Those components retain their
own licenses and notices. In particular, `ffprobe` is not bundled; distributors
that add an FFmpeg build must review the license and configuration of that
specific build.

Generated wheels must be inspected before publication to confirm that they do
not accidentally bundle external executables, credentials, fixtures, or build
environment files.
