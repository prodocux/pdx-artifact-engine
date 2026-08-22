# Release boundary and verification

PDX Artifact Engine is released as small, explicit package surfaces.

| Distribution | Import package | Contents |
|---|---|---|
| `pdx-artifact-engine` | `pdx_artifact_engine` | Runtime, dispatcher, manifests, CLI |
| `pdx-artifact-engine` | `pdx_artifact_core` | Schemas, validators, protocols, state |
| `pdx-artifact-engine` | `pdx_adapter_prodocux` | Product-neutral ProDocuX HTTP adapter |
| `pdx-adapter-media` | `pdx_adapter_media` | Optional media identity and technical probe |

The main distribution does not include the optional media package. Neither
distribution includes product workflows, private decision records, model
weights, credentials, signed URLs, generated outputs, or external tool
binaries.

## Release checks

Before creating a tag:

1. Run the full test suite.
2. Run `tests/test_release_hygiene.py` explicitly.
3. Build the main wheel and the media wheel independently.
4. Inspect both archive listings; reject foreign packages or private files.
5. Install each wheel into an empty environment and run import smoke tests.
6. Run `git diff --check` and review every staged path against the intended
   batch manifest.
7. Keep credentials, model weights, build output, and local decision records
   outside the release tree.

The wheel build, temporary-environment install, and import smoke can be run as:

```powershell
python scripts/verify_clean_install.py
```

Release hashes are evidence for one build, not reproducibility claims unless a
separate reproducible-build process verifies them.

## Release-candidate freeze

PDX Artifact Engine and Core `0.3.0a1` form the coordinated prerelease surface;
the alpha suffix is intentional and no stable-API claim is made. The earlier
execution-plan, tool request/result, verifier-result, workflow-checkpoint,
approval, and artifact-storage schemas listed in
`compatibility/pdx_prodocux_compatibility_v1.json` remain frozen. The active
additive surface is recorded in
`compatibility/pdx_prodocux_compatibility_v2.json`.

- Breaking schema or public primitive changes require a new prerelease version.
- Security and correctness fixes must preserve existing valid documents or
  explicitly version the affected contract.
- Product state machines, tenant policy, durable databases, cloud adapters, and
  product-specific verification rules remain outside PDX Core.
- Git commit pins remain authoritative until maintainers explicitly create a
  release tag.
