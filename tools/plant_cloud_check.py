"""Plant Room faults against a running plan API (default: the Cloud Run service): each of the 3 demo faults must make POST /check return a
plan-deviation alert, and fixing / clearing must return none. Prints the latency of every call. The rows come from the same TypeScript
model the Plant Room runs (tools/plant_scenarios.py). An API build without the additive `meters` field is reported as such (the Saffron
app then uses its browser fallback).
Run: uv run python tools/plant_cloud_check.py [base URL]
"""
import json
import sys
import time
import urllib.request

import plant_scenarios as PS

BASE = (sys.argv[1] if len(sys.argv) > 1 else "https://saffron-api-579804303171.asia-south1.run.app").rstrip("/")


def post(path: str, body: dict) -> tuple[dict, float]:
    t0 = time.perf_counter()
    req = urllib.request.Request(BASE + path, data=json.dumps(body).encode(), headers={"content-type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=30) as r:
        out = json.load(r)
    return out, (time.perf_counter() - t0) * 1000


def main() -> int:
    plan, ms = post("/plan", dict(date=PS.DATE, bookings=PS.BOOKINGS))
    print(f"{BASE}\n/plan {PS.DATE}: {len(plan['actions'])} steps, weather: {plan['inputs_used']['weather']} ({ms:.0f} ms)")
    out = PS.run(plan)
    ok = True
    for sc in out["scenarios"]:
        j, ms = post("/check", PS.check_body(plan, sc))
        sim = j.get("meters_source") == "simulated"
        got = bool(j.get("alerts")) if sim else None
        good = sim and got == sc["expect_alert"]
        ok &= good
        what = ("; ".join(a["title"] for a in j["alerts"]) or "no alert") if sim else "meters IGNORED (this API build predates the Plant Room: redeploy)"
        print(f"  {'PASS' if good else 'FAIL'}  {ms:6.0f} ms  {sc['name']}: {what}")
    print("all pass" if ok else "NOT all pass")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
