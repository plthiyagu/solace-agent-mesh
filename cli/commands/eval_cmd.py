import os
from pathlib import Path
import click
from cli.utils import error_exit


@click.command(name="eval")
@click.argument(
    "test_suite_config_path",
    type=click.Path(exists=True, dir_okay=False, resolve_path=True),
    required=True,
    metavar="<PATH>",
)
@click.option(
    "-v",
    "--verbose",
    is_flag=True,
    help="Enable verbose output.",
)
@click.option(
    "--export-evalport",
    is_flag=True,
    help="After the run, export the test cases and results to the EvalPort "
    "open format (https://github.com/adhabnr-ux/evalport) under "
    "<results dir>/evalport.",
)
@click.option(
    "--pass-threshold",
    type=click.FloatRange(0.0, 1.0),
    default=0.5,
    show_default=True,
    help="Score at or above which an exported grader result counts as "
    "passed (only used with --export-evalport).",
)
def eval_cmd(test_suite_config_path, verbose, export_evalport, pass_threshold):
    """
    Run an evaluation suite using a specified configuration file. Such as path/to/file.yaml.

    <PATH>: The path to the evaluation test suite config file.
    """
    from evaluation.run import main as run_evaluation_main

    click.echo(
        click.style(
            f"Starting evaluation with test_suite_config: {test_suite_config_path}",
            fg="blue",
        )
    )

    # Set logging config path for evaluation
    project_root = Path.cwd()
    logging_config_path = project_root / "configs" / "logging_config.yaml"
    if logging_config_path.exists():
        os.environ["LOGGING_CONFIG_PATH"] = str(logging_config_path.resolve())

    try:
        run_evaluation_main(test_suite_config_path, verbose=verbose)
        click.echo(click.style("Evaluation completed successfully.", fg="green"))
    except Exception as e:
        error_exit(f"An error occurred during evaluation: {e}")

    if export_evalport:
        from evaluation.evalport_bridge import export_results

        try:
            written = export_results(
                test_suite_config_path, pass_threshold=pass_threshold
            )
            for path in written:
                click.echo(click.style(f"Wrote {path}", fg="green"))
        except Exception as e:
            error_exit(f"An error occurred during the EvalPort export: {e}")
