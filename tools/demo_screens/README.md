# Plant Room demo checks (17 Nov 2026)

Screenshots from `tools/plant_e2e.mjs` (headless Playwright, 1440×900 @2x), API path (dev server, `/api` → local uvicorn running this branch's `api/main.py`):

- `plant_room_after_event.png` — Plant Room at sim 20:00, all approved steps applied; CHW override to 6.0 °C refused.
- `plant_room_fault.png` / `app_today_alert.png` — fault 1 injected; the alert in the Saffron app (Today) 5.3 s later.
- `plant_room_fixed.png` / `app_today_resolved.png` — Apply fix on the AHU off step; alert gone 4.3 s later.

Logs: `e2e_log_api_path.txt` (plan API /check), `e2e_log_fallback_path.txt` (same run with `/api` → the current Cloud Run build, which predates
the additive `meters` field, so the app used the browser rules: alert 6.8 s, resolved 5.8 s).
`/check` per fault with latency: `check_local_api.txt` (all pass), `check_cloud_run_before_redeploy.txt` (meters ignored until redeployed).

Reproduce:
```
PYTHONPATH=src uv run uvicorn api.main:app --port 8001
cd web && SAFFRON_DEV_FUNCTIONS=1 SAFFRON_MEMORY_STORE=1 SAFFRON_API_URL=http://127.0.0.1:8001 npx vite --port 5173
node tools/plant_e2e.mjs
uv run python tools/plant_cloud_check.py            # against Cloud Run (after redeploy)
```
