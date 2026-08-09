import os

# The paste sequence sleeps PASTE_ENTER_DELAY seconds between the paste and the
# Enter, and the default is 0.5 — a margin chosen for real TUIs, which is the
# right call in a container and pure cost in a test suite that mocks tmux
# entirely. Four adapter tests were paying it, two seconds of a 2.3 second run,
# and it grows with every delivery test anyone adds.
#
# ⚠ Set here rather than in a fixture because `flock.tmux.ops` reads it at
# import time into a module constant. A fixture runs too late — the value is
# already bound by the time the first test executes.
os.environ.setdefault("PASTE_ENTER_DELAY", "0")
