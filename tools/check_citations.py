#!/usr/bin/env python3
"""Check path:line citations in Markdown documentation."""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
# ⚠ IGNORECASE is load-bearing, not tidiness. Without it a citation written
# `path.MD:1` matched NOTHING — so a dead path produced zero findings and the
# run reported "0 hard failures". The checker was not lenient about the file, it
# was blind to the citation, which is the worse failure: silence reads as clean.
# Constructed by `bus` while attacking the sign-off form (build 78) and
# reproduced here: `does-not-exist.md:1` exits 1, `does-not-exist.MD:1` exits 0.
CITATION = re.compile(
    r"(?<![\w./-])"
    r"((?:[A-Za-z0-9_.-]+/)*[A-Za-z0-9_.-]+\."
    r"(?:py|sh|md|yaml|yml|toml|json|html|js|css))"
    r":(\d+)(?:-(\d+))?",
    re.IGNORECASE,
)
QUOTED = re.compile(r"`([^`]+)`")
SYMBOL = re.compile(r"^[A-Za-z_][A-Za-z0-9_.]*(?:\(\))?$")


@dataclass(frozen=True)
class Citation:
    document: Path
    document_line: int
    path: str
    first_line: int
    last_line: int
    symbol: str | None


def _nearest_symbol(line: str, match: re.Match[str]) -> str | None:
    candidates: list[tuple[int, str]] = []
    for quoted in QUOTED.finditer(line):
        value = quoted.group(1)
        if value == match.group(0) or not SYMBOL.fullmatch(value):
            continue
        distance = min(abs(quoted.start() - match.end()), abs(match.start() - quoted.end()))
        candidates.append((distance, value.removesuffix("()")))
    if not candidates:
        return None
    distance, symbol = min(candidates)
    return symbol if distance <= 12 else None


def collect(documents: list[Path]) -> list[Citation]:
    citations = []
    for document in documents:
        for line_number, line in enumerate(document.read_text(encoding="utf-8").splitlines(), 1):
            for match in CITATION.finditer(line):
                first = int(match.group(2))
                citations.append(
                    Citation(
                        document=document,
                        document_line=line_number,
                        path=match.group(1),
                        first_line=first,
                        last_line=int(match.group(3) or first),
                        symbol=_nearest_symbol(line, match),
                    )
                )
    return citations


def resolve(path: str, root: Path, document: Path, last_line: int, symbol: str | None) -> Path:
    direct = root / path
    if direct.exists():
        return direct
    documented = root / "docs" / path
    if documented.exists():
        return documented
    # Docs often cite from a package or container boundary (bus/keys.py,
    # entrypoint.sh) rather than spelling the repository prefix. Accept that
    # only when the suffix identifies exactly one file; ambiguity is a failure.
    matches = [
        candidate
        for candidate in root.rglob(Path(path).name)
        if ".git" not in candidate.parts
        and candidate.is_file()
        and candidate.relative_to(root).as_posix().endswith(path)
    ]
    if len(matches) == 1:
        return matches[0]
    in_range = [
        candidate
        for candidate in matches
        if len(candidate.read_text(encoding="utf-8").splitlines()) >= last_line
    ]
    if len(in_range) == 1:
        return in_range[0]
    if symbol:
        plausible = []
        for candidate in in_range:
            lines = candidate.read_text(encoding="utf-8").splitlines()
            low = max(0, last_line - 4)
            high = min(len(lines), last_line + 3)
            if symbol in "\n".join(lines[low:high]):
                plausible.append(candidate)
        if len(plausible) == 1:
            return plausible[0]
    document_name = document.stem.lower()
    contextual = [
        candidate
        for candidate in in_range
        if candidate.parent.name.lower() in document_name
    ]
    return contextual[0] if len(contextual) == 1 else direct


def check(citations: list[Citation], root: Path) -> tuple[list[str], list[str]]:
    hard: list[str] = []
    near: list[str] = []
    cache: dict[Path, list[str]] = {}
    for citation in citations:
        location = f"{citation.document.relative_to(root)}:{citation.document_line}"
        target = resolve(
            citation.path,
            root,
            citation.document,
            citation.last_line,
            citation.symbol,
        )
        rendered = f"{citation.path}:{citation.first_line}"
        if citation.last_line != citation.first_line:
            rendered += f"-{citation.last_line}"
        if not target.is_file():
            hard.append(f"{location}: {rendered}: path does not exist")
            continue
        lines = cache.setdefault(target, target.read_text(encoding="utf-8").splitlines())
        if citation.first_line < 1 or citation.last_line > len(lines):
            hard.append(
                f"{location}: {rendered}: line outside file (1-{len(lines)})"
            )
            continue
        if citation.symbol:
            low = max(0, citation.first_line - 4)
            high = min(len(lines), citation.last_line + 3)
            if citation.symbol not in "\n".join(lines[low:high]):
                near.append(
                    f"{location}: {rendered}: symbol {citation.symbol!r} not within 3 lines"
                )
    return hard, near


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("paths", nargs="*", type=Path, default=[Path("docs")])
    parser.add_argument("--root", type=Path, default=REPO_ROOT)
    args = parser.parse_args(argv)
    root = args.root.resolve()
    documents: list[Path] = []
    for supplied in args.paths:
        path = supplied if supplied.is_absolute() else root / supplied
        if path.is_dir():
            documents.extend(path.rglob("*.md"))
        elif path.is_file():
            documents.append(path)
    citations = collect(sorted(set(documents)))
    hard, near = check(citations, root)
    unique = {
        (citation.path, citation.first_line, citation.last_line) for citation in citations
    }
    print(f"citations checked: {len(citations)} ({len(unique)} unique)")
    for finding in hard:
        print(f"HARD {finding}")
    for finding in near:
        print(f"NEAR {finding}")
    print(f"hard failures: {len(hard)}")
    print(f"near misses: {len(near)}")
    return 1 if hard else 0


if __name__ == "__main__":
    sys.exit(main())
