# Kaggle Implementation Plan

## Objective

Use Kaggle free GPU resources to develop the early PDX-5B-1B+ model bundle:

- train LoRA/QLoRA adapters for 1B-class experts
- evaluate routing and JSON validity
- export checkpoints for GGUF conversion
- validate low-RAM runtime assumptions locally

Kaggle is a training and experimentation environment, not production
infrastructure.

## Constraints

Assumptions for planning:

- Free GPU availability is quota-limited and may vary by account and region.
- P100/T4-class GPUs are enough for 0.6B-1.7B LoRA experiments.
- Long-running jobs are fragile; notebooks must checkpoint often.
- Datasets and model outputs should be saved to Kaggle Datasets or downloaded.

## Base Model Candidates

Initial candidates:

- Qwen 0.6B/1.7B instruct family for Core and router work.
- Gemma 1B-class instruct models where licensing and tooling fit.
- SmolLM-class models for very low-RAM experiments.

Selection criteria:

- permissive enough for commercial plans
- strong tool-following potential
- multilingual behavior
- stable Hugging Face ecosystem support
- good GGUF conversion path

## Notebook Set

```text
00_build_trace_dataset.ipynb
01_train_pdx_core_router_qlora.ipynb
02_eval_core_router.ipynb
03_train_pdx_doc_expert_qlora.ipynb
04_train_pdx_3d_expert_smoke.ipynb
05_merge_export_checkpoint.ipynb
06_local_gguf_benchmark_instructions.ipynb
```

## Dataset Strategy

Dataset types:

- router traces
- tool-call traces
- artifact-spec traces
- audit-failure repair traces
- refusal and ask-human traces

Trace example:

```json
{
  "input": {
    "user_request": "Create an audit-ready PIF package from these source PDFs.",
    "available_skills": ["pdf_extract", "doc_assemble", "pif_audit"]
  },
  "target": {
    "plan": [
      {"step": "extract_pages", "skill": "pdf_extract"},
      {"step": "draft_sections", "expert": "PDX-Doc-1B"},
      {"step": "assemble_docx", "skill": "doc_assemble"},
      {"step": "audit", "skill": "pif_audit"}
    ],
    "needs_user_input": false
  }
}
```

## Weekly Execution Plan

### Week 1: Dataset Builder

- Convert ProDocuX experiment artifacts into training traces.
- Define negative examples.
- Add JSON validation checks.
- Build a small held-out eval set.

### Week 2: PDX-Core-1B First LoRA

- Train router/tool-call LoRA.
- Evaluate JSON validity and skill selection.
- Inspect failures manually.

### Week 3: Core Repair Loop

- Add audit-failure examples.
- Train on repair actions and missing-input decisions.
- Evaluate failure recovery.

### Week 4: PDX-Doc-1B

- Train document/source-map/review expert.
- Evaluate on PIF workflow tasks.
- Compare Core-only vs Core+Doc.

### Week 5: PDX-3D-1B Smoke Expert

- Build synthetic FreeCAD/Blender spec traces.
- Train a small LoRA or prompt-tuned baseline.
- Evaluate schema validity and engine selection.

### Week 6: Export and Local Benchmark

- Merge LoRA adapters.
- Convert to GGUF.
- Quantize Q4_K_M and Q5_K_M.
- Run local llama.cpp memory and latency tests.

## Success Metrics

Core:

- valid JSON >= 98%
- tool selection accuracy >= 90%
- missing-input detection >= 85%
- unsupported task escalation >= 95%

Doc:

- valid draft/review schema >= 95%
- source hallucination rate <= 2%
- audit-repair usefulness >= 80%

3D:

- engine selection accuracy >= 90%
- valid CAD/scene spec >= 90%
- explicit units/constraints >= 95%

Runtime:

- 8 GB mode can run Core and hot-swap a specialist.
- 16 GB mode can run Core plus one specialist.
- Every artifact has a manifest and verification result.

