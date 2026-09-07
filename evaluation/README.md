# Solace Agent Mesh - Evaluation Framework

This directory contains the evaluation framework for the Solace Agent Mesh. It is designed to test the functionality and performance of Solace Agent Mesh.

## How to Run Evaluations

The evaluations are run using the `sam` command-line interface after installing the project.

### Quick Start with Make

If you prefer an automated setup, you can use the provided Make command which handles environment setup and runs the evaluation. Run the command in the root of the project:

```bash
make test-eval-local
```

This command will:
- Create a Python 3.12 virtual environment
- Install the project and its dependencies
- Run the local evaluation tests

**Note:** Ensure your environment variables are exported before running this command (see [Environment Variables](#environment-variables) section below).

### Manual Setup (alternative)

Install the project and its dependencies by running the following command from the root of the project:

```bash
pip install .
```

Install the rest gateway:

```bash
pip install sam-rest-gateway
```

To run an evaluation test suite, use the `sam eval` command followed by the path to the test suite's JSON configuration file. For example, to run the full remote evaluation suite, execute the following command:

```bash
sam eval tests/evaluation/local_example.json
```

## Environment Variables

To run the evaluations successfully, you must configure the following environment variables. These are defined in `sam eval tests/evaluation/local_example.json` and must be exported to your environment.

### Solace Broker Connection

These variables are required to connect to the Solace message broker during the tests.

```bash
export SOLACE_BROKER_URL=<enter the URL of the Solace broker>
export SOLACE_BROKER_USERNAME=<enter the username for the broker connection>
export SOLACE_BROKER_PASSWORD=<enter the password for the broker connection>
export SOLACE_BROKER_VPN=<enter the Message VPN to connect to on the broker>
```

### LLM Evaluator Settings

For evaluations that use an LLM to judge the response, the following variables are needed:

```bash
export LLM_SERVICE_ENDPOINT=<enter the endpoint for the LLM service>
export LLM_SERVICE_API_KEY=<enter the API key for the LLM service>
```

## Exporting to EvalPort

The evaluation results can be exported to [EvalPort](https://github.com/adhabnr-ux/evalport),
an open JSON-Schema specification for portable LLM evaluation documents, so
suites and results can be consumed by other evaluation tools without bespoke
glue code.

Export as part of a run:

```bash
sam eval <test_suite_config.json> --export-evalport
```

Or convert the results of a previous run without re-executing anything:

```bash
python -m evaluation.evalport_bridge <test_suite_config.json>
```

This writes one `<suite>.suite.json` (the test cases plus grader
definitions) and one `<model>.resultset.json` per evaluated model into
`results/<results_dir_name>/evalport/`. Each SAM run maps to an EvalPort
result with the run number as its `attempt`, and the three evaluators map to
the framework-specific grader types `tool_match`, `response_match` and
`llm_eval`.

SAM scores are continuous values in [0, 1] with no pass/fail notion, while
EvalPort requires a boolean per grader result. The export derives it as
`score >= threshold` with a configurable `--pass-threshold` (default `0.5`),
and records the threshold in the ResultSet metadata.
