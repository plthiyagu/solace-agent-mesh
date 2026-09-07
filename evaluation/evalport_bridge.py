"""Bridge SAM evaluation test cases and results to the EvalPort open format.

EvalPort (https://github.com/adhabnr-ux/evalport) is an open JSON-Schema
specification for portable LLM evaluation documents, so eval data is not
locked to one framework's format. This module exports:

- the suite's test cases as an EvalPort ``EvalSuite`` document
  (``spec/schemas/suite.json`` / ``testcase.json``), and
- each model's ``results.json`` as an EvalPort ``ResultSet`` document
  (``spec/schemas/resultset.json``), one result per run with the run number
  carried as the spec's ``attempt`` field.

SAM's evaluators map to framework-specific grader types (``tool_match``,
``response_match``, ``llm_eval``). Per the EvalPort spec, unknown grader
types declare ``params.handler`` so consumers that cannot execute them skip
gracefully instead of guessing.

SAM scores are continuous values in [0, 1] with no pass/fail notion, while
EvalPort requires a boolean ``passed`` per grader result. The bridge applies
a configurable threshold (``--pass-threshold``, default 0.5) and records it
in the ResultSet metadata so consumers know how the booleans were derived.

Usage:
    sam eval <config.json> --export-evalport
    python -m evaluation.evalport_bridge <config.json> [--results-dir DIR]
        [--output-dir DIR] [--pass-threshold 0.5]
"""

import argparse
import json
import logging
from datetime import datetime, timezone
from importlib import metadata as importlib_metadata
from pathlib import Path

from .shared import EvaluationConfigLoader, load_test_case

log = logging.getLogger(__name__)

EVALPORT_VERSION = "1.0.0-rc.5"
DEFAULT_PASS_THRESHOLD = 0.5

GRADER_DEFINITIONS = {
    "tool_match": {
        "id": "tool_match",
        "type": "tool_match",
        "params": {"handler": "evaluation.evaluator.ToolMatchEvaluator"},
        "description": (
            "Recall of the expected tools over the tools the agent "
            "actually called (1.0 when no tools are expected)."
        ),
    },
    "response_match": {
        "id": "response_match",
        "type": "response_match",
        "params": {"handler": "evaluation.evaluator.ResponseMatchEvaluator"},
        "description": (
            "Weighted ROUGE F-score (0.2 rouge-1 + 0.3 rouge-2 + "
            "0.5 rouge-l) between the final response and the expected "
            "response."
        ),
    },
    "llm_eval": {
        "id": "llm_eval",
        "type": "llm_eval",
        "params": {"handler": "evaluation.evaluator.LLMEvaluator"},
        "description": (
            "LLM judge scoring the response against the test case "
            "criterion on a 0.0-1.0 rubric, with reasoning."
        ),
    },
}


def enabled_grader_ids(evaluation_options) -> list[str]:
    """The grader ids enabled by the suite's evaluation settings."""
    graders = []
    if evaluation_options.tool_matching_enabled:
        graders.append("tool_match")
    if evaluation_options.response_matching_enabled:
        graders.append("response_match")
    if evaluation_options.llm_evaluation_enabled:
        graders.append("llm_eval")
    return graders


def to_evalport_test_case(test_case: dict, grader_ids: list[str]) -> dict:
    """Map one SAM test case dict to an EvalPort TestCase document."""
    evaluation = test_case.get("evaluation", {})

    evalport_case = {
        "id": test_case["test_case_id"],
        "input": test_case["query"],
        "graders": list(grader_ids),
    }

    if evaluation.get("expected_response"):
        evalport_case["expected_output"] = evaluation["expected_response"]
    if evaluation.get("expected_tools"):
        evalport_case["expected_tools"] = list(evaluation["expected_tools"])
    if test_case.get("wait_time"):
        evalport_case["timeout_ms"] = int(test_case["wait_time"] * 1000)
    if test_case.get("category"):
        evalport_case["tags"] = [test_case["category"]]

    metadata = {"sam.target_agent": test_case["target_agent"]}
    if test_case.get("description"):
        metadata["sam.description"] = test_case["description"]
    if evaluation.get("criterion"):
        metadata["sam.criterion"] = evaluation["criterion"]
    if test_case.get("artifacts"):
        metadata["sam.artifacts"] = test_case["artifacts"]
    evalport_case["metadata"] = metadata

    return evalport_case


def build_suite(
    *,
    suite_id: str,
    config_name: str,
    test_cases: list[dict],
    grader_ids: list[str],
    run_count: int,
) -> dict:
    """Build the EvalPort EvalSuite document for the SAM test suite."""
    return {
        "version": EVALPORT_VERSION,
        "id": suite_id,
        "name": suite_id,
        "description": (
            f"Exported from the Solace Agent Mesh test suite '{config_name}'."
        ),
        "graders": [GRADER_DEFINITIONS[grader_id] for grader_id in grader_ids],
        "test_cases": [
            to_evalport_test_case(test_case, grader_ids)
            for test_case in test_cases
        ],
        "metadata": {
            "sam.source_config": config_name,
            "sam.run_count": run_count,
        },
    }


def _grader_results(run: dict, pass_threshold: float) -> list[dict]:
    """The EvalPort grader results present in one SAM run record."""
    graders = []

    for grader_id in ("tool_match", "response_match"):
        if grader_id in run:
            score = float(run[grader_id])
            graders.append(
                {
                    "grader_id": grader_id,
                    "type": grader_id,
                    "score": score,
                    "passed": score >= pass_threshold,
                }
            )

    llm_eval = run.get("llm_eval")
    if llm_eval is not None:
        score = float(llm_eval["score"])
        grader = {
            "grader_id": "llm_eval",
            "type": "llm_eval",
            "score": score,
            "passed": score >= pass_threshold,
        }
        if llm_eval.get("reasoning"):
            grader["reason"] = llm_eval["reasoning"]
        graders.append(grader)

    return graders


def _run_to_result(run: dict, pass_threshold: float) -> dict:
    """Map one SAM run record to an EvalPort result item."""
    grader_results = _grader_results(run, pass_threshold)
    errors = run.get("errors") or []

    result = {
        "test_case_id": run["test_case_id"],
        "attempt": int(run["run"]),
        "grader_results": grader_results,
        "passed": (
            bool(grader_results)
            and not errors
            and all(grader["passed"] for grader in grader_results)
        ),
    }

    if run.get("duration_seconds") is not None:
        result["duration_ms"] = max(0, round(run["duration_seconds"] * 1000))
    if errors:
        result["error"] = {
            "type": "runner_error",
            "message": "; ".join(str(error) for error in errors),
        }

    return result


def _summary(results: list[dict], total_execution_time: float | None) -> dict:
    """Aggregate statistics over the mapped results."""
    passed = sum(1 for result in results if result["passed"])
    scores = [
        grader["score"]
        for result in results
        for grader in result["grader_results"]
        if grader["score"] is not None
    ]

    by_grader: dict[str, dict] = {}
    for result in results:
        for grader in result["grader_results"]:
            stats = by_grader.setdefault(
                grader["grader_id"], {"passed": 0, "failed": 0, "scores": []}
            )
            stats["passed" if grader["passed"] else "failed"] += 1
            if grader["score"] is not None:
                stats["scores"].append(grader["score"])

    summary = {
        "total": len(results),
        "passed": passed,
        "failed": len(results) - passed,
        "pass_rate": (passed / len(results)) if results else 0.0,
        "avg_score": (sum(scores) / len(scores)) if scores else 0.0,
        "by_grader": {
            grader_id: {
                "passed": stats["passed"],
                "failed": stats["failed"],
                "avg_score": (
                    sum(stats["scores"]) / len(stats["scores"])
                    if stats["scores"]
                    else 0.0
                ),
            }
            for grader_id, stats in by_grader.items()
        },
    }
    if total_execution_time is not None:
        summary["duration_ms"] = max(0, round(total_execution_time * 1000))
    return summary


def _runner_info() -> dict:
    runner = {"name": "solace-agent-mesh"}
    try:
        runner["version"] = importlib_metadata.version("solace-agent-mesh")
    except importlib_metadata.PackageNotFoundError:
        log.debug("solace-agent-mesh is not installed; omitting runner version")
    return runner


def build_result_set(
    model_results: dict,
    *,
    suite_id: str,
    started_at: str,
    pass_threshold: float,
) -> dict:
    """Map one model's results.json content to an EvalPort ResultSet."""
    model_name = model_results["model_name"]
    results = [
        _run_to_result(run, pass_threshold)
        for test_case in model_results.get("test_cases", [])
        for run in test_case.get("runs", [])
    ]
    if not results:
        raise ValueError(
            f"results for model '{model_name}' contain no runs to export"
        )

    return {
        "version": EVALPORT_VERSION,
        "suite_id": suite_id,
        "run_id": f"{suite_id}-{model_name}",
        "started_at": started_at,
        "provider": {"model": model_name},
        "runner": _runner_info(),
        "results": results,
        "summary": _summary(results, model_results.get("total_execution_time")),
        "metadata": {
            "sam.pass_threshold": pass_threshold,
            "sam.started_at_source": "results.json modification time",
        },
    }


def export_results(
    config_path: str,
    results_dir: Path | None = None,
    output_dir: Path | None = None,
    pass_threshold: float = DEFAULT_PASS_THRESHOLD,
) -> list[Path]:
    """Export a suite's test cases and per-model results to EvalPort files.

    Reads the suite configuration and the results directory a previous
    ``sam eval`` run produced, and writes one ``<suite>.suite.json`` plus one
    ``<model>.resultset.json`` per model into ``output_dir`` (defaults to
    ``<results_dir>/evalport``). Returns the written paths.
    """
    config = EvaluationConfigLoader(config_path).load_configuration()
    suite_id = config.results_directory
    grader_ids = enabled_grader_ids(config.evaluation_options)
    if not grader_ids:
        raise ValueError(
            "no evaluators are enabled in evaluation_settings; "
            "there are no graders to export"
        )

    if results_dir is None:
        results_dir = Path.cwd() / "results" / suite_id
    if output_dir is None:
        output_dir = results_dir / "evalport"
    output_dir.mkdir(parents=True, exist_ok=True)

    written: list[Path] = []

    test_cases = [load_test_case(path) for path in config.test_case_files]
    suite_doc = build_suite(
        suite_id=suite_id,
        config_name=Path(config_path).name,
        test_cases=test_cases,
        grader_ids=grader_ids,
        run_count=config.run_count,
    )
    suite_path = output_dir / f"{suite_id}.suite.json"
    _write_json(suite_doc, suite_path)
    written.append(suite_path)

    for results_file in sorted(results_dir.glob("*/results.json")):
        model_results = json.loads(results_file.read_text())
        started_at = datetime.fromtimestamp(
            results_file.stat().st_mtime, tz=timezone.utc
        ).isoformat()
        result_set = build_result_set(
            model_results,
            suite_id=suite_id,
            started_at=started_at,
            pass_threshold=pass_threshold,
        )
        result_set_path = (
            output_dir / f"{model_results['model_name']}.resultset.json"
        )
        _write_json(result_set, result_set_path)
        written.append(result_set_path)

    if len(written) == 1:
        log.warning(
            "No <model>/results.json files found under %s; only the suite "
            "document was exported. Run `sam eval` first.",
            results_dir,
        )

    return written


def _write_json(data: dict, filepath: Path) -> None:
    filepath.parent.mkdir(parents=True, exist_ok=True)
    with filepath.open("w") as f:
        json.dump(data, f, indent=4)


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Export SAM evaluation test cases and results to the EvalPort "
            "open format."
        )
    )
    parser.add_argument(
        "config_path", help="Path to the evaluation test suite config file."
    )
    parser.add_argument(
        "--results-dir",
        type=Path,
        default=None,
        help="Results directory of a previous run "
        "(default: ./results/<results_dir_name>).",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Where to write the EvalPort documents "
        "(default: <results-dir>/evalport).",
    )
    parser.add_argument(
        "--pass-threshold",
        type=float,
        default=DEFAULT_PASS_THRESHOLD,
        help="Score at or above which a grader result counts as passed "
        f"(default: {DEFAULT_PASS_THRESHOLD}).",
    )
    args = parser.parse_args()

    written = export_results(
        args.config_path,
        results_dir=args.results_dir,
        output_dir=args.output_dir,
        pass_threshold=args.pass_threshold,
    )
    for path in written:
        print(f"Wrote {path}")


if __name__ == "__main__":
    main()
