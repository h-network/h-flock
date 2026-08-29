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
