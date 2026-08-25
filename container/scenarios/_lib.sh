#!/usr/bin/env bash
# _lib.sh — the shape every scenario script shares. Source it; do not run it.
#
#   . "$(dirname "$0")/_lib.sh"
#   check "what it is" <expected> <curl args...>
#   expect "what it is" <expected> <actual>
#   finish <name>
#
# ⚠ WHY THIS EXISTS. Three api-* scripts made HTTP calls, printed the status they
# got, and compared nothing. They always exited 0, so `accept.sh` could have run
# them forever and never learned anything. A script that records instead of
# judging is not a test, and the only way to tell the difference from outside is
# whether it can go red.
#
# ⚠ EXIT CODES ARE THE CONTRACT — a caller reads the code, never the prose:
#   0    every check passed
#   1+   that many checks FAILED
#   100  could not run: no tenant, no token, nothing to test against.
#        ⚠ NOT a pass and NOT a failure. Collapsing it into either is how a
#        gate starts lying about a run that never happened.

_FAILED=0

# Bail out before running anything, when there is nothing to run against.
incomplete() {                       # incomplete <name> <reason>
  [ "$#" -eq 2 ] || { echo "RESULT scenario incomplete reason=invalid_incomplete_arguments" >&2; exit 100; }
  echo "RESULT $1 incomplete reason=$2" >&2
  exit 100
}

# Compare two values that are already in hand.
expect() {                           # expect <what> <want> <got>
  [ "$#" -eq 3 ] || incomplete scenario invalid_expect_arguments
  if [ "$2" = "$3" ]; then
    echo "  ✓ $1 → $3"
  else
    echo "  ✗ $1 → $3, expected $2" >&2
    _FAILED=$((_FAILED+1))
  fi
}

# One HTTP call, compared against the status it should return.
# ⚠ One call, not two. The scripts this replaces issued each request twice —
# once for the body, once for the status — so the two could describe different
# responses and nobody would know.
check() {                            # check <what> <want-status> <curl args...>
  [ "$#" -ge 3 ] || incomplete scenario invalid_check_arguments
  local what="$1" want="$2"; shift 2
  local out status
  out="$(curl -s -w '\n%{http_code}' "$@" 2>/dev/null)" || true
  status="${out##*$'\n'}"
  expect "$what" "$want" "${status:-000}"
}

# One line a caller can grep, then the count as the exit code.
finish() {                           # finish <name>
  [ "$#" -eq 1 ] || incomplete scenario invalid_finish_arguments
  if [ "$_FAILED" = 0 ]; then
    echo "RESULT $1 pass"
  else
    echo "RESULT $1 fail failed=$_FAILED" >&2
  fi
  exit "$_FAILED"
}
