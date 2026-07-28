from __future__ import annotations

import argparse
import json
from pathlib import Path

from pdx_artifact_engine.dispatcher import Dispatcher
from pdx_artifact_engine.errors import PDXError
from pdx_artifact_engine.plan import load_plan
from pdx_artifact_engine.planners import ManualPlanner, RulePlanner
from pdx_artifact_engine.registry import SkillRegistry


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run a PDX plan (model-optional; no LLM weights required)."
    )
    parser.add_argument("--plan", type=Path, help="Path to a plan.json (ManualPlanner).")
    parser.add_argument(
        "--rule-request",
        type=Path,
        help="JSON request for RulePlanner (deterministic, no model).",
    )
    parser.add_argument("--schema", default=Path("schemas/plan.schema.json"), type=Path)
    parser.add_argument(
        "--registry",
        default=Path("skills/registry.sample.json"),
        type=Path,
    )
    parser.add_argument(
        "--registry-schema",
        default=Path("schemas/skill_registry.schema.json"),
        type=Path,
    )
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument(
        "--mock",
        action="store_true",
        help="Mock skills without registered executors; also mocks expert steps.",
    )
    args = parser.parse_args()

    if bool(args.plan) == bool(args.rule_request):
        parser.error("Provide exactly one of --plan or --rule-request")

    try:
        if args.plan:
            planner = ManualPlanner(args.plan, args.schema)
            plan = planner.create_plan()
            planner_name = planner.name
        else:
            request = json.loads(args.rule_request.read_text(encoding="utf-8"))
            planner = RulePlanner()
            plan = planner.create_plan(request)
            # Validate generated plan against schema via round-trip file helper
            tmp = args.output_dir / "_generated_plan.json"
            args.output_dir.mkdir(parents=True, exist_ok=True)
            tmp.write_text(json.dumps(plan, indent=2) + "\n", encoding="utf-8")
            plan = load_plan(tmp, args.schema)
            planner_name = planner.name

        registry = SkillRegistry.load(args.registry, schema_path=args.registry_schema)
        result = Dispatcher(
            registry,
            allow_mock=args.mock,
            planner_name=planner_name,
        ).run(plan, args.output_dir)
    except PDXError as exc:
        print(f"ERROR {exc}")
        return 2
    except (OSError, json.JSONDecodeError) as exc:
        print(f"ERROR {exc}")
        return 2

    run_manifest = result["run_manifest"]
    print(args.output_dir / "run_manifest.json")
    print(args.output_dir / "artifact_manifest.json")
    print(f"status={run_manifest['status']}")
    if run_manifest["status"] in {"failed", "blocked"}:
        for error in run_manifest.get("errors", []):
            print(f"error: {error}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
