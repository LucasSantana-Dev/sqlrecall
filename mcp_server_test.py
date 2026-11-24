#!/usr/bin/env python3
"""Tests for the MCP handshake: version negotiation, ping, tool annotations.
Runs the server as a subprocess against an empty config; no model is loaded
because no query is sent."""

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent


def exchange(*messages: dict) -> list[dict]:
    with tempfile.TemporaryDirectory(prefix="sqlrecall-mcp-") as tmp:
        (Path(tmp) / "sources.yaml").write_text("sources: []\n")
        env = {**os.environ, "RAG_HOME": tmp, "RAG_SOURCES": str(Path(tmp) / "sources.yaml"),
               "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1"}
        stdin = "".join(json.dumps({"jsonrpc": "2.0", **m}) + "\n" for m in messages)
        out = subprocess.run([sys.executable, str(HERE / "mcp_server.py")], input=stdin,
                             capture_output=True, text=True, env=env, cwd=tmp, timeout=120)
    return [json.loads(line) for line in out.stdout.splitlines() if line.strip()]


def init(version: str) -> dict:
    return {"id": 1, "method": "initialize", "params": {"protocolVersion": version}}


def test_version_negotiation():
    (known,), (unknown,) = exchange(init("2025-06-18")), exchange(init("2099-01-01"))
    assert known["result"]["protocolVersion"] == "2025-06-18"
    assert unknown["result"]["protocolVersion"] == "2025-11-25"
    assert known["result"]["serverInfo"]["version"] != "0.1.0"


def test_ping_and_annotations():
    ping, tools = exchange({"id": 2, "method": "ping"}, {"id": 3, "method": "tools/list"})
    assert ping["result"] == {}
    hints = {t["name"]: t["annotations"]["readOnlyHint"] for t in tools["result"]["tools"]}
    assert hints == {"rag_query": True, "search_knowledge": True, "handoff_list": True,
                     "handoff_begin": False, "handoff_accept": False}, hints


if __name__ == "__main__":
    tests = [(k, v) for k, v in globals().items() if k.startswith("test_")]
    for name, fn in tests:
        fn()
        print(f"ok  {name}")
    print(f"\n{len(tests)} passed")
