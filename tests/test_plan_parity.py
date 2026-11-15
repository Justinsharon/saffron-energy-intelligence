"""Python (src/operating_plan.py) vs TypeScript (web/src/plan.ts): same actions and ₹ within 1 % on 10 sample days with bookings.

The browser recomputes the plan when bookings change, so the two must not drift. The TS side is bundled with esbuild (from web/node_modules)
and run in Node on the same inputs. Run: uv run pytest tests
"""
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web"
sys.path.insert(0, str(ROOT / "src"))
import operating_plan as OP  # noqa: E402

PLAN = WEB / "public" / "data" / "plan"
SCENARIOS = [
    dict(),
    dict(bookings=[dict(hall="A", start="09:00", end="18:00", guests=300)]),
    dict(tmax_shift=8, bookings=[dict(hall="B", start="10:00", end="16:30", guests=150)]),
    dict(rooms=215, covers=850, bookings=[dict(hall="A+B", start="19:00", end="23:59", guests=550)]),
    dict(tmax_shift=-6, rooms=90),
    dict(tmax_shift=16, bookings=[dict(hall="A", start="09:00", end="18:00", guests=600), dict(hall="B", start="09:00", end="18:00", guests=600)]),
    dict(covers=200, bookings=[dict(hall="A", start="13:00", end="15:00", guests=50)]),
    dict(tmax_shift=12, rooms=220, bookings=[dict(hall="A+B", start="18:00", end="23:59", guests=600)]),
    dict(tmax_shift=4, bookings=[dict(hall="B", start="08:00", end="20:00", guests=250)]),
    dict(tmax_shift=20, rooms=220, covers=900),
]
RUNNER = """
import { planFor } from "./src/plan";
import { readFileSync, writeFileSync } from "node:fs";
const cases = JSON.parse(readFileSync(process.argv[2], "utf8"));
const out = cases.map((c: any) => planFor(c.day, c.inputs).actions.map((a: any) => ({ group: a.group, start: a.start, end: a.end, equipment: a.equipment, setting: a.setting, saving_inr: a.saving_inr })));
writeFileSync(process.argv[3], JSON.stringify(out));
"""


def cases():
    idx = sorted(json.loads((PLAN / "index.json").read_text(encoding="utf-8"))["days"])
    picks = idx[:: max(1, len(idx) // 10)][:10]
    out = []
    for d, sc in zip(picks, SCENARIOS):
        day = json.loads((PLAN / f"{d}.json").read_text(encoding="utf-8"))
        inp = dict(bookings=sc.get("bookings", []))
        for k in ("rooms", "covers"):
            if k in sc:
                inp[k] = sc[k]
        if "tmax_shift" in sc:
            inp["tmax"] = day["template_tmax"] + sc["tmax_shift"]
        out.append(dict(day=day, inputs=inp))
    return out


def python_plan(c):
    i = c["inputs"]
    f = OP.compose_day(c["day"], rooms=i.get("rooms"), covers=i.get("covers"), tmax=i.get("tmax"), bookings=i["bookings"])
    acts = OP.plan_day(f["tr"], f["kva"], f["temp"], i["bookings"], c["day"]["pf"], c["day"]["ref"], c["day"]["tariff"])
    return [dict(group=a["group"], start=a["start"], end=a["end"], equipment=a["equipment"], setting=a["setting"], saving_inr=a["saving_inr"]) for a in acts]


@pytest.mark.skipif(shutil.which("npx") is None or not (WEB / "node_modules").exists(), reason="needs Node and web/node_modules")
def test_python_and_typescript_plans_match(tmp_path):
    cs = cases()
    assert len(cs) == 10
    src, inp, outp = WEB / "plan_parity.tmp.ts", tmp_path / "cases.json", tmp_path / "ts.json"
    bundle = tmp_path / "runner.mjs"
    src.write_text(RUNNER, encoding="utf-8")
    try:
        npx = shutil.which("npx")
        subprocess.run([npx, "esbuild", src.name, "--bundle", "--platform=node", "--format=esm", f"--outfile={bundle}", "--log-level=warning"],
                       cwd=WEB, check=True, shell=sys.platform == "win32")
    finally:
        src.unlink(missing_ok=True)
    inp.write_text(json.dumps(cs), encoding="utf-8")
    subprocess.run(["node", str(bundle), str(inp), str(outp)], check=True)
    ts = json.loads(outp.read_text(encoding="utf-8"))
    n_actions = 0
    for c, py, t in zip(cs, map(python_plan, cs), ts):
        key = lambda xs: [(a["group"], a["start"], a["end"], a["equipment"], a["setting"]) for a in xs]
        assert key(py) == key(t), c["day"]["date"]
        for a, b in zip(py, t):
            assert abs(a["saving_inr"] - b["saving_inr"]) <= max(0.01 * abs(a["saving_inr"]), 0.5), (c["day"]["date"], a, b)
        n_actions += len(py)
    assert n_actions > 50
