"""
Schema validation of the EvalPort export against the official validators.

Runs only when the ``evalport-sdk`` package is installed (it is not a
project dependency), so the spec conformance claim is reproducible:

    pip install evalport-sdk && pytest tests/unit/evaluation/test_evalport_schema_validation.py
"""

import pytest

validate = pytest.importorskip(
    "openeval.validate", reason="evalport-sdk is not installed"
)

from evaluation.evalport_bridge import (  # noqa: E402
    build_result_set,
    build_suite,
)

from .test_evalport_bridge import FULL_TEST_CASE, MODEL_RESULTS  # noqa: E402


def test_suite_document_conforms_to_the_evalport_schema():
    suite = build_suite(
        suite_id="sam-suite",
        config_name="config.json",
        test_cases=[FULL_TEST_CASE],
        grader_ids=["tool_match", "response_match", "llm_eval"],
        run_count=2,
    )

    result = validate.validate_suite(suite)

    assert result.valid, [str(error) for error in result.errors]


def test_result_set_document_conforms_to_the_evalport_schema():
    result_set = build_result_set(
        MODEL_RESULTS,
        suite_id="sam-suite",
        started_at="2026-09-10T00:00:00+00:00",
        pass_threshold=0.5,
    )

    result = validate.validate_result_set(result_set)

    assert result.valid, [str(error) for error in result.errors]
