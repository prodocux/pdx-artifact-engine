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

## PyPI trusted publication

GitHub Releases are the publication approval boundary. The
`.github/workflows/release.yml` workflow downloads the already-approved main
and media wheel/source archives, verifies their package metadata and GitHub
SHA-256 digests, and promotes the unchanged files to PyPI. It does not publish
`pdx-artifact-core` separately because the main distribution already owns the
`pdx_artifact_core` import package.

Create pending or existing-project Trusted Publishers with separate environment
identities so first-use project creation cannot mint an ambiguous project-scoped
token:

- `pdx-artifact-engine`: GitHub owner `prodocux`, repository
  `pdx-artifact-engine`, workflow `release.yml`, environment `pypi`;
- `pdx-adapter-media`: GitHub owner `prodocux`, repository
  `pdx-artifact-engine`, workflow `release.yml`, environment `pypi-media`.

Protect both GitHub environments with a required reviewer. No long-lived PyPI
token belongs in repository secrets. Future GitHub Releases start the workflow
automatically; an existing coordinated release can be promoted by manually
running **Publish release assets to PyPI** with its exact tag.

The approved coordinated `v0.3.0a1` assets are:

| Asset | SHA-256 |
|---|---|
| `pdx_artifact_engine-0.3.0a1-py3-none-any.whl` | `30f42c15c2994b5b0f743fa04ecd6ff28abb7ff5a4fc0d73511b74b76f1eb0c3` |
| `pdx_artifact_engine-0.3.0a1.tar.gz` | `e7e012d2405a5700c31ec94afe4a11745099166ff976795da5d088f07bca12a8` |
| `pdx_adapter_media-0.2.0a1-py3-none-any.whl` | `80af3d4426d2986c05ae8b46bb1623c62cabfb7f0606374a16e22490ef73c699` |
| `pdx_adapter_media-0.2.0a1.tar.gz` | `c632adbea2688793a67eac0fab8b7fa30f094b4c20732c82b065dc8242391e39` |

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
