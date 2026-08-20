#!/usr/bin/env python3
"""Attack fixture: a checker whose negative control fails before its oracle.

This is deliberately wrong.  Every readable input is accepted, including the
value the claimed property says must be refused.  A missing input still exits
non-zero, which is enough to fill TEST-SIGNOFF's current ``could it fail``
field without establishing that the content oracle can fail.
"""

from pathlib import Path
import sys


value = Path(sys.argv[1]).read_text(encoding="utf-8").strip()
print(f"ACCEPTED {value}")
