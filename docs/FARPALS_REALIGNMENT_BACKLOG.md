# Farpals and PDX realignment backlog

Status: coordination backlog only. No Farpals or PDX production work is
authorized by this document.

## Package and capability alignment

- record the currently published Kernel, Engine, and Media pins independently;
- keep release pins distinct from contract-freeze provenance commits;
- decide whether Farpals installations need the optional
  `prodocux[pdf-mupdf]` rasterizer; default installations must not acquire it;
- add license/SBOM evidence when the optional AGPL/commercial backend is used;
- consume `pdx_provenance_bundle_v1` only as a derived export; Engine receipts
  remain authoritative and graph inference remains recommendation evidence;
- agree on any future Semantica adapter without making Semantica a runtime
  dependency of Hub or Engine.

## OfficeCLI boundary

- OfficeCLI remains an optional provider/executor, disabled by default;
- Farpals Host owns binary provisioning, terms acceptance, executable digest,
  credentials, runtime selection, network enforcement, process-tree
  termination, and user approval;
- Engine receives no hosted key and must not treat OfficeCLI messages as
  authority;
- every OfficeCLI artifact is a candidate until Kernel template/structure
  checks and Engine check-report binding succeed;
- hosted publishing remains forbidden unless a separate approved external
  operation explicitly authorizes it;
- close the documented `--prompt` argv disclosure before production use by
  adopting a reviewed stdin/prompt-file interface or an explicitly accepted
  same-host isolation profile;
- perform clean-machine, binary-upgrade, response-bound, cancellation, and
  egress-negative tests before production enablement.

## Existing cross-line items

- revisit the durable Host Gate only after Farpals proves its supervisor and
  installable workflow loop; retain the existing no-secret Engine boundary;
- verify a5/a6/a8 workflow and step-projection consumer parity after each pin
  update;
- preserve agent-message-is-not-authorization, aggregate workflow budgets,
  artifact-mediated communication, and post-cancel rejection invariants;
- update compatibility manifests only after implementation candidates and
  bilateral evidence pass; do not reuse historical release or freeze pins.
