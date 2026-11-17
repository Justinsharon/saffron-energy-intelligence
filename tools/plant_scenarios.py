"""Plant Room fault scenarios for the tests and the Cloud Run check: run web/tests/plant.harness.ts in Node (bundled with esbuild from
web/node_modules, as tests/test_plan_parity.py does) on a plan for one date, and return the meter rows the Saffron app would send to /check.
"""
import json
import shutil
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web"
DATE = "2026-11-19"
BOOKINGS = [dict(hall="A", start="09:00", end="18:00", guests=150)]


def available() -> bool:
    return bool(shutil.which("node")) and (WEB / "node_modules" / ".bin" / "esbuild").exists()


def run(plan: dict) -> dict:
    """plan: the /plan response for DATE with BOOKINGS. Returns {unit, scenarios, creep_kva}; raises if a Node assertion fails."""
    with tempfile.TemporaryDirectory() as d:
        d = Path(d)
        js = d / "h.mjs"
        subprocess.run([str(WEB / "node_modules" / ".bin" / "esbuild"), "tests/plant.harness.ts", "--bundle", "--platform=node", "--format=esm",
                        f"--outfile={js}", "--log-level=warning"], cwd=WEB, check=True)
        # the bundle resolves public data relative to the harness file: run it from web/tests via a symlinked copy location
        inp, out = d / "in.json", d / "out.json"
        inp.write_text(json.dumps(dict(date=plan["date"], forecast=plan["forecast"], bookings=plan["inputs_used"]["bookings"], actions=plan["actions"])))
        target = WEB / "tests" / "_harness.mjs"
        shutil.copy(js, target)
        try:
            r = subprocess.run(["node", str(target), str(inp), str(out)], cwd=WEB, capture_output=True, text=True)
        finally:
            target.unlink(missing_ok=True)
        if r.returncode != 0:
            raise AssertionError(r.stderr[-3000:])
        return json.loads(out.read_text())


def check_body(plan: dict, sc: dict) -> dict:
    """The body the Saffron app sends to /check for one scenario (the approved steps, the simulated rows, the sim time)."""
    acts = [dict(a, id=f"{a['group']}|{a['start']}|{a['equipment']}", decision="approve") for a in plan["actions"]]
    return dict(date=plan["date"], site="GGN", as_of=sc["as_of"], actions=acts, plan_source="saved", meters=sc["meters"])
