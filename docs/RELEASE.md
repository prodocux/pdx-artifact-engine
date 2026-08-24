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

The A6-containing coordinated packages are:

```powershell
python -m pip install "pdx-artifact-engine==0.3.0a2"
python -m pip install "pdx-adapter-media==0.2.0a2"
```

`0.2.0a2` for `pdx-adapter-media` is a packaging-only coordinated bump so the
existing dual-publish workflow can attach new files. It must not re-upload
already-published `0.2.0a1`. Asset SHA-256 digests for `v0.3.0a2` are recorded
on the GitHub Release and must match the files promoted to PyPI.

The coordinated release is published at
<https://pypi.org/project/pdx-artifact-engine/0.3.0a2/> and
<https://pypi.org/project/pdx-adapter-media/0.2.0a2/> from GitHub Release
<https://github.com/prodocux/pdx-artifact-engine/releases/tag/v0.3.0a2>.
Workflow run `32692340885` promoted all four approved files unchanged. PyPI
records one matching-digest attestation per file for repository
`prodocux/pdx-artifact-engine` and workflow `release.yml`, using environment
`pypi` for Engine and `pypi-media` for Media.

| Asset | SHA-256 |
|---|---|
| `pdx_artifact_engine-0.3.0a2-py3-none-any.whl` | `e4484a41e3e5622c18e391bfcbe546b41e2ff2b5a2bf947bad1d00e8a8194023` |
| `pdx_artifact_engine-0.3.0a2.tar.gz` | `46f8e5b7ba776a156e2d1d57fbeb2a8daea9ae5c6c883dd15361ab432ae2c093` |
| `pdx_adapter_media-0.2.0a2-py3-none-any.whl` | `df25388589ac855ef193b14d64b6d013ce18798f3aec9fe68d787c4e031ea762` |
| `pdx_adapter_media-0.2.0a2.tar.gz` | `44f315f80a1006388cc12578792a4377c9e96600ad34cc241cf1ac3777d37316` |

Clean PyPI installation/import checks passed for both distributions, including
the Engine `pdx-validate` CLI smoke.

The older coordinated packages remain at
<https://pypi.org/project/pdx-artifact-engine/0.3.0a1/> and
<https://pypi.org/project/pdx-adapter-media/0.2.0a1/>. Those four PyPI file
hashes match GitHub Release `v0.3.0a1` and must not be rebuilt.

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

PDX Artifact Engine and Core `0.3.0a2` form the coordinated prerelease that
distributes the A6 ProDocuX extract/render adapter. The alpha suffix is
intentional and no stable-API claim is made. The earlier execution-plan, tool
request/result, verifier-result, workflow-checkpoint, approval, and
artifact-storage schemas listed in
`compatibility/pdx_prodocux_compatibility_v1.json` remain frozen. The frozen
v2 surface still records `0.3.0a1`; that is the contract pin, not the live
package version. Additive ProDocuX extract/render pins and G1A mapping fixture
digests are recorded in
`compatibility/pdx_prodocux_compatibility_v3.json`. v1, v2, and v3 bytes are
immutable.

The already-published PyPI artifacts for `0.3.0a1` (GitHub Release
`v0.3.0a1`) predate the A6 ProDocuX extract/render adapter freeze. Those
files must not be rebuilt or re-uploaded. Live adapter tools remain pinned by
compatibility v3 at PDX Commit A
`37e89752560b22dc8724d470dce96187f19e3f98`. `0.3.0a2` is the PyPI
distribution of that surface. Do not bump to `0.4.0` for this additive `/v1`
work.

- Breaking schema or public primitive changes require a new prerelease version.
- Security and correctness fixes must preserve existing valid documents or
  explicitly version the affected contract.
- Product state machines, tenant policy, durable databases, cloud adapters, and
  product-specific verification rules remain outside PDX Core.
- Git commit pins remain authoritative until maintainers explicitly create a
  release tag.
