"""Import boundaries that must hold in a fresh interpreter."""

import subprocess
import sys


def test_importing_switch_does_not_load_bus_doors():
    check = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; sys.path.insert(0, 'src'); "
            "import flock.switch.service; "
            "assert 'flock.bus.doors' not in sys.modules",
        ],
        capture_output=True,
        text=True,
    )
    assert check.returncode == 0, check.stderr


def test_importing_generic_port_registry_does_not_load_tmux_modules():
    check = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; sys.path.insert(0, 'src'); "
            "import flock.port.registry; "
            "assert not any(name == 'flock.tmux' or name.startswith('flock.tmux.') "
            "for name in sys.modules)",
        ],
        capture_output=True,
        text=True,
    )
    assert check.returncode == 0, check.stderr


def test_legacy_port_tmux_export_is_lazy():
    check = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; sys.path.insert(0, 'src'); import flock.port; "
            "assert 'flock.tmux' not in sys.modules; "
            "assert callable(flock.port.deliver_tmux); "
            "assert 'flock.tmux.deliver' in sys.modules",
        ],
        capture_output=True,
        text=True,
    )
    assert check.returncode == 0, check.stderr
