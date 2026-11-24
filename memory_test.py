#!/usr/bin/env python3
"""Tests for Claude Code auto memory alignment: note freshness from the
frontmatter `modified` stamp, and the MEMORY.md load-limit check."""

import os
import shutil
import sys
import tempfile
import textwrap
from datetime import datetime, timezone
from pathlib import Path

TMP = Path(tempfile.mkdtemp(prefix="sqlrecall-memory-")).resolve()
VAULT, OTHER = TMP / "vault", TMP / "other"
VAULT.mkdir()
OTHER.mkdir()
os.environ["RAG_HOME"] = str(TMP)
os.environ["RAG_SOURCES"] = str(TMP / "sources.yaml")
(TMP / "sources.yaml").write_text(textwrap.dedent(f"""\
    sources:
      - {{type: memory, glob: "{VAULT}/**/*.md"}}
      - {{type: memory, glob: "{VAULT}/*.md"}}
      - {{type: docs, glob: "{OTHER}/*.md"}}
    """))

sys.path.insert(0, str(Path(__file__).resolve().parent))
import indexer  # noqa: E402
import report  # noqa: E402


def stamp(text: str) -> float:
    f = VAULT / "note.md"
    f.write_text(text)
    return indexer.note_time(f, text)


def test_modified_stamp_beats_mtime():
    want = datetime(2026, 10, 2, 1, 45, 16, 128000, tzinfo=timezone.utc).timestamp()
    nested = "---\nname: x\nmetadata:\n  type: user\n  modified: 2026-10-02T01:45:16.128Z\n---\nbody\n"
    assert stamp(nested) == want
    assert stamp("---\nmodified: '2026-10-02T01:45:16.128Z'\n---\n") == want


def test_falls_back_to_mtime():
    for text in ("no frontmatter\n", "---\nmodified: soon\n---\n",
                 "---\nname: y\n---\nmodified: 2020-01-01T00:00:00Z\n"):
        f = VAULT / "note.md"
        f.write_text(text)
        assert indexer.note_time(f, text) == f.stat().st_mtime, text


def test_memory_index_limit():
    index = VAULT / "MEMORY.md"
    index.write_text("".join(f"- [n{i}](n{i}.md) — hook\n" for i in range(150)))
    (OTHER / "MEMORY.md").write_text("x\n" * 500)
    assert report.oversized_memory_indexes() == []
    index.write_text("".join(f"- [n{i}](n{i}.md) — hook\n" for i in range(201)))
    hits = report.oversized_memory_indexes()
    assert [(p, n) for p, n, _ in hits] == [(index, 201)], hits
    index.write_text("- " + "x" * 26 * 1024 + "\n")
    assert len(report.oversized_memory_indexes()) == 1


if __name__ == "__main__":
    tests = [(k, v) for k, v in globals().items() if k.startswith("test_")]
    try:
        for name, fn in tests:
            fn()
            print(f"ok  {name}")
    finally:
        shutil.rmtree(TMP, ignore_errors=True)
    print(f"\n{len(tests)} passed")
