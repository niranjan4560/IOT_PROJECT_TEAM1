"""Run the Node-RED "Decision rules" code (from nodered/flows.json) from Python via tools/run_rules.js.

run_rules(records)  - batch mode (open loop: decisions do not change the inputs)
RulesSession        - step-by-step mode for closed-loop simulation (the next input depends on this decision)
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
FLOWS = ROOT / "nodered" / "flows.json"


def _node() -> str:
    node = shutil.which("node")
    if not node:
        raise SystemExit("Node.js is needed to run the Node-RED decision rules (install Node.js 22 LTS).")
    return node


def run_rules(records: list[dict[str, Any]], config: dict | None = None, flows: str | Path = FLOWS) -> list[dict | None]:
    lines = ([json.dumps({"_config": config})] if config else []) + [json.dumps(r) for r in records]
    done = subprocess.run([_node(), str(ROOT / "tools" / "run_rules.js"), str(flows)], input="\n".join(lines) + "\n",
                          capture_output=True, text=True, check=True)
    return [json.loads(line) for line in done.stdout.splitlines() if line.strip()]


class RulesSession:
    def __init__(self, config: dict | None = None, flows: str | Path = FLOWS):
        self.proc = subprocess.Popen([_node(), str(ROOT / "tools" / "run_rules.js"), str(flows)], stdin=subprocess.PIPE,
                                     stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, bufsize=1)
        if config:
            self.proc.stdin.write(json.dumps({"_config": config}) + "\n")

    def decide(self, record: dict) -> dict:
        self.proc.stdin.write(json.dumps(record) + "\n")
        self.proc.stdin.flush()
        return json.loads(self.proc.stdout.readline())

    def close(self) -> None:
        if self.proc.poll() is None:
            self.proc.stdin.close()
            self.proc.wait(timeout=10)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
