"""
Unit tests for evaluation/evalport_bridge.py

Tests the EvalPort export bridge including:
- Test case mapping to the EvalPort TestCase document
- Grader selection from evaluation settings
- ResultSet mapping (attempts, grader results, pass threshold, errors)
- Summary aggregation
- End-to-end export of a results directory
"""

import json
from types import SimpleNamespace

import pytest

from evaluation.evalport_bridge import (
    EVALPORT_VERSION,
    build_result_set,
    build_suite,
    enabled_grader_ids,
    export_results,
    to_evalport_test_case,
)

FULL_TEST_CASE = {
    "test_case_id": "hello_world",
    "category": "Content Generation",
    "description": "A simple greeting test.",
    "query": "Hello, world!",
    "target_agent": "OrchestratorAgent",
    "wait_time": 30,
    "artifacts": [{"type": "url", "path": "https://example.com/doc"}],
    "evaluation": {
        "expected_tools": ["web_request"],
        "expected_response": "Hello! How can I help you today?",
        "criterion": "Evaluate if the agent greets the user.",
    },
}

MODEL_RESULTS = {
    "model_name": "test-model",
    "total_execution_time": 12.5,
    "test_cases": [
        {
            "test_case_id": "case_a",
            "category": "Content Generation",
            "runs": [
                {
                    "run": 1,
                    "test_case_id": "case_a",
                    "test_case_path": "/tmp/a.test.json",
                    "duration_seconds": 2.0,
                    "tool_match": 1.0,
                    "response_match": 0.8,
                    "llm_eval": {"score": 0.9, "reasoning": "Good answer."},
                },
                {
                    "run": 2,
                    "test_case_id": "case_a",
                    "test_case_path": "/tmp/a.test.json",
                    "duration_seconds": 1.5,
                    "tool_match": 1.0,
                    "response_match": 0.4,
                },
            ],
        },
        {
            "test_case_id": "case_b",
            "category": "Other",
            "runs": [
                {
                    "run": 1,
                    "test_case_id": "case_b",
                    "test_case_path": "/tmp/b.test.json",
                    "duration_seconds": None,
                    "errors": ["agent timed out"],
                },
            ],
        },
    ],
}


def options(tool=True, response=True, llm=False):
    return SimpleNamespace(
        tool_matching_enabled=tool,
        response_matching_enabled=response,
        llm_evaluation_enabled=llm,
    )


class TestGraderSelection:
    def test_reflects_the_enabled_evaluators(self):
        assert enabled_grader_ids(options(llm=True)) == [
            "tool_match",
            "response_match",
            "llm_eval",
        ]
        assert enabled_grader_ids(options(tool=False)) == ["response_match"]

    def test_no_evaluators_means_no_graders(self):
        assert enabled_grader_ids(options(False, False, False)) == []


class TestTestCaseMapping:
    def test_maps_every_field_of_a_full_test_case(self):
        doc = to_evalport_test_case(FULL_TEST_CASE, ["tool_match", "llm_eval"])

        assert doc == {
            "id": "hello_world",
            "input": "Hello, world!",
            "graders": ["tool_match", "llm_eval"],
            "expected_output": "Hello! How can I help you today?",
            "expected_tools": ["web_request"],
            "timeout_ms": 30000,
            "tags": ["Content Generation"],
            "metadata": {
                "sam.target_agent": "OrchestratorAgent",
                "sam.description": "A simple greeting test.",
                "sam.criterion": "Evaluate if the agent greets the user.",
                "sam.artifacts": [
                    {"type": "url", "path": "https://example.com/doc"}
                ],
            },
        }

    def test_omits_empty_optional_fields(self):
        doc = to_evalport_test_case(
            {
                "test_case_id": "minimal",
                "query": "Hi",
                "target_agent": "Agent",
                "evaluation": {"expected_tools": [], "expected_response": ""},
            },
            ["response_match"],
        )

        assert doc["id"] == "minimal"
        assert doc["graders"] == ["response_match"]
        assert "expected_output" not in doc
        assert "expected_tools" not in doc
        assert "timeout_ms" not in doc
        assert "tags" not in doc


class TestSuiteDocument:
    def test_builds_a_suite_with_grader_definitions(self):
        suite = build_suite(
            suite_id="my-suite",
            config_name="config.json",
            test_cases=[FULL_TEST_CASE],
            grader_ids=["tool_match", "response_match"],
            run_count=3,
        )

        assert suite["version"] == EVALPORT_VERSION
        assert suite["id"] == "my-suite"
        assert [grader["id"] for grader in suite["graders"]] == [
            "tool_match",
            "response_match",
        ]
        # Framework-specific grader types must declare params.handler so
        # consumers that cannot execute them can skip gracefully.
        assert all("handler" in grader["params"] for grader in suite["graders"])
        assert suite["test_cases"][0]["id"] == "hello_world"
        assert suite["metadata"]["sam.run_count"] == 3


class TestResultSetMapping:
    def build(self, pass_threshold=0.5):
        return build_result_set(
            MODEL_RESULTS,
            suite_id="my-suite",
            started_at="2026-08-31T00:00:00+00:00",
            pass_threshold=pass_threshold,
        )

    def test_maps_runs_to_attempts(self):
        result_set = self.build()

        assert result_set["version"] == EVALPORT_VERSION
        assert result_set["suite_id"] == "my-suite"
        assert result_set["run_id"] == "my-suite-test-model"
        assert result_set["provider"] == {"model": "test-model"}
        assert [
            (result["test_case_id"], result["attempt"])
            for result in result_set["results"]
        ] == [("case_a", 1), ("case_a", 2), ("case_b", 1)]

    def test_applies_the_pass_threshold_per_grader(self):
        first, second, _ = self.build()["results"]

        assert first["passed"] is True
        assert {g["grader_id"]: g["passed"] for g in first["grader_results"]} == {
            "tool_match": True,
            "response_match": True,
            "llm_eval": True,
        }
        llm = next(
            g for g in first["grader_results"] if g["grader_id"] == "llm_eval"
        )
        assert llm["reason"] == "Good answer."
        assert first["duration_ms"] == 2000

        assert second["passed"] is False, "response_match 0.4 is below 0.5"

    def test_a_stricter_threshold_flips_results(self):
        first = self.build(pass_threshold=0.85)["results"][0]

        assert first["passed"] is False, "response_match 0.8 is below 0.85"

    def test_errors_become_a_runner_error(self):
        errored = self.build()["results"][2]

        assert errored["passed"] is False
        assert errored["grader_results"] == []
        assert errored["error"] == {
            "type": "runner_error",
            "message": "agent timed out",
        }
        assert "duration_ms" not in errored

    def test_summary_aggregates_results_and_graders(self):
        summary = self.build()["summary"]

        assert summary["total"] == 3
        assert summary["passed"] == 1
        assert summary["failed"] == 2
        assert summary["pass_rate"] == pytest.approx(1 / 3)
        assert summary["avg_score"] == pytest.approx(0.82)
        assert summary["duration_ms"] == 12500
        assert summary["by_grader"]["response_match"] == {
            "passed": 1,
            "failed": 1,
            "avg_score": pytest.approx(0.6),
        }

    def test_rejects_results_without_runs(self):
        with pytest.raises(ValueError, match="no runs to export"):
            build_result_set(
                {"model_name": "empty", "test_cases": []},
                suite_id="s",
                started_at="2026-08-31T00:00:00+00:00",
                pass_threshold=0.5,
            )


class TestExportResults:
    @pytest.fixture
    def suite_tree(self, tmp_path, mocker):
        """A fake config loader plus test case files and a results tree."""
        cases_dir = tmp_path / "cases"
        cases_dir.mkdir()
        case_paths = []
        for case_id in ("case_a", "case_b"):
            path = cases_dir / f"{case_id}.test.json"
            path.write_text(
                json.dumps(
                    {
                        "test_case_id": case_id,
                        "query": f"Query for {case_id}",
                        "target_agent": "OrchestratorAgent",
                    }
                )
            )
            case_paths.append(str(path))

        results_dir = tmp_path / "results" / "my-suite"
        model_dir = results_dir / "test-model"
        model_dir.mkdir(parents=True)
        (model_dir / "results.json").write_text(json.dumps(MODEL_RESULTS))

        loader = mocker.patch(
            "evaluation.evalport_bridge.EvaluationConfigLoader"
        )
        loader.return_value.load_configuration.return_value = SimpleNamespace(
            results_directory="my-suite",
            test_case_files=case_paths,
            run_count=2,
            evaluation_options=options(llm=True),
        )
        return results_dir

    def test_writes_the_suite_and_one_result_set_per_model(
        self, suite_tree, tmp_path
    ):
        written = export_results(
            str(tmp_path / "config.json"), results_dir=suite_tree
        )

        assert [path.name for path in written] == [
            "my-suite.suite.json",
            "test-model.resultset.json",
        ]
        assert all(path.parent == suite_tree / "evalport" for path in written)

        suite_doc = json.loads(written[0].read_text())
        assert [case["id"] for case in suite_doc["test_cases"]] == [
            "case_a",
            "case_b",
        ]

        result_set = json.loads(written[1].read_text())
        assert result_set["suite_id"] == "my-suite"
        assert result_set["metadata"]["sam.pass_threshold"] == 0.5
        assert result_set["started_at"].endswith("+00:00")

    def test_refuses_to_export_without_enabled_graders(
        self, suite_tree, tmp_path, mocker
    ):
        loader = mocker.patch(
            "evaluation.evalport_bridge.EvaluationConfigLoader"
        )
        loader.return_value.load_configuration.return_value = SimpleNamespace(
            results_directory="my-suite",
            test_case_files=[],
            run_count=1,
            evaluation_options=options(False, False, False),
        )

        with pytest.raises(ValueError, match="no evaluators are enabled"):
            export_results(
                str(tmp_path / "config.json"), results_dir=suite_tree
            )

    def test_rejects_a_suite_id_that_escapes_the_output_dir(
        self, suite_tree, tmp_path, mocker
    ):
        loader = mocker.patch(
            "evaluation.evalport_bridge.EvaluationConfigLoader"
        )
        loader.return_value.load_configuration.return_value = SimpleNamespace(
            results_directory="../evil",
            test_case_files=[],
            run_count=1,
            evaluation_options=options(llm=True),
        )

        with pytest.raises(ValueError, match="not a safe filename component"):
            export_results(
                str(tmp_path / "config.json"), results_dir=suite_tree
            )

    def test_model_filename_comes_from_the_directory_not_the_json(
        self, suite_tree, tmp_path
    ):
        crafted = dict(MODEL_RESULTS, model_name="../../escape")
        results_file = suite_tree / "test-model" / "results.json"
        results_file.write_text(json.dumps(crafted))

        written = export_results(
            str(tmp_path / "config.json"), results_dir=suite_tree
        )

        result_set_path = written[1]
        assert result_set_path.name == "test-model.resultset.json"
        assert result_set_path.parent == suite_tree / "evalport"

    @pytest.mark.parametrize("threshold", [-0.1, 1.5])
    def test_rejects_an_out_of_range_pass_threshold(
        self, suite_tree, tmp_path, threshold
    ):
        with pytest.raises(ValueError, match="pass_threshold"):
            export_results(
                str(tmp_path / "config.json"),
                results_dir=suite_tree,
                pass_threshold=threshold,
            )
