"""The declared console entry points must resolve in every install layout.

Editable installs used to expose only ``src/`` while the console scripts
declared ``solace_agent_mesh.cli.main:cli`` — a target that only existed
after the wheel build grafted the top-level ``cli/`` directory into the
package. The installed ``sam`` command then died with
``ModuleNotFoundError: No module named 'solace_agent_mesh.cli'`` before
Click ever started (#1645). These checks resolve the exact targets the
installer writes into the launcher scripts, so a layout that breaks them
fails here instead of at the user's first ``sam`` invocation.
"""

import inspect
from importlib.metadata import entry_points

DECLARED_COMMANDS = {"sam", "solace-agent-mesh"}


def test_declared_console_scripts_resolve_and_are_callable():
    installed = {
        ep.name: ep
        for ep in entry_points(group="console_scripts")
        if ep.name in DECLARED_COMMANDS
    }
    missing = DECLARED_COMMANDS - set(installed)
    assert not missing, f"console scripts not installed: {sorted(missing)}"
    for ep in installed.values():
        assert ep.value.startswith("solace_agent_mesh.cli.main"), (
            f"{ep.name} points at {ep.value}; the CLI lives in "
            "solace_agent_mesh.cli.main"
        )
        assert callable(ep.load())


def test_entry_module_imports_without_path_hacks():
    # The old layout only imported because cli/main.py appended its own
    # parent onto sys.path at import time — a hack that only helped wheel
    # installs. The aligned layout must import cleanly, with no path
    # mutation left in the entry module.
    from solace_agent_mesh.cli import main

    assert callable(main.cli)
    assert "sys.path.append" not in inspect.getsource(main)
