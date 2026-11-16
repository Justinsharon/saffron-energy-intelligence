"""The plans log (web/src/planlog.ts, shared by the Netlify plans function and the browser): the duty engineer can mark an APPROVED step
"done" or "can't do" (with a reason), logged with name and time; it never changes the approval, and a step that was not approved is refused.
Bundled with esbuild from web/node_modules and run in Node. Run: uv run pytest tests
"""
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web"
RUNNER = """
import { applyEvent, view } from "./src/planlog";
const act = (group: string, start: string, end: string, setting: string) => ({ kind: "plan", group, start, end, equipment: "X " + group, setting,
  reason: "r", saving_inr: 0, guardrail: "g", id: `${group}|${start}` });
const out: Record<string, unknown> = {};
let e = applyEvent(undefined, { by: "Chief", event: "submit", site: "GGN", inputs: {}, actions: [act("laundry", "00:00", "18:00", "Run batches only 00:00–18:00"),
  act("water", "23:00", "05:00 (next day)", "Heat storage")] }, "2026-11-10 08:00");
e = applyEvent(e, { by: "Chief", event: "approve", action_id: "laundry|00:00" }, "2026-11-10 08:05");
const tryEv = (body: Record<string, unknown>) => { try { e = applyEvent(e, body, "2026-11-10 09:00"); return "ok"; } catch (x) { return String((x as Error).message); } };
out.done = tryEv({ by: "Duty", event: "done", action_id: "laundry|00:00" });
out.not_approved = tryEv({ by: "Duty", event: "done", action_id: "water|23:00" });
out.cant_no_reason = tryEv({ by: "Duty", event: "cant", action_id: "laundry|00:00" });
out.cant = tryEv({ by: "Duty", event: "cant", action_id: "laundry|00:00", reason: "laundry short-staffed" });
out.view = view("2026-11-10", e, "device");
console.log(JSON.stringify(out));
"""


@pytest.mark.skipif(shutil.which("npx") is None or not (WEB / "node_modules").exists(), reason="needs Node and web/node_modules")
def test_duty_done_and_cant(tmp_path):
    src, bundle = WEB / "planlog_duty.tmp.ts", tmp_path / "runner.mjs"
    src.write_text(RUNNER, encoding="utf-8")
    try:
        subprocess.run([shutil.which("npx"), "esbuild", src.name, "--bundle", "--platform=node", "--format=esm", f"--outfile={bundle}", "--log-level=warning"],
                       cwd=WEB, check=True, shell=sys.platform == "win32")
    finally:
        src.unlink(missing_ok=True)
    out = json.loads(subprocess.run(["node", str(bundle)], check=True, capture_output=True, text=True).stdout)
    assert out["done"] == "ok" and out["cant"] == "ok"
    assert "Only approved steps" in out["not_approved"] and "Say why" in out["cant_no_reason"]
    v = out["view"]
    assert v["decisions"]["laundry|00:00"]["event"] == "approve"                       # the approval stays
    d = v["duty"]["laundry|00:00"]
    assert d["event"] == "cant" and d["reason"] == "laundry short-staffed" and d["by"] == "Duty" and d["at"] == "2026-11-10 09:00"
    assert [r["event"] for r in v["log"]] == ["submit", "approve", "done", "cant"]      # appended, nothing removed
