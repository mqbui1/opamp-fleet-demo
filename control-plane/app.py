import logging
import os
import re
import threading
import time

import requests
from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

import storage
from config_builder import build_config

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("control-plane")

OPAMP_SERVER_URL = os.environ.get("OPAMP_SERVER_URL", "http://opamp-server:4321")
METRICS_URL = os.environ.get("METRICS_URL", "http://otel-collector:8889/metrics")
POLL_INTERVAL_SECONDS = float(os.environ.get("POLL_INTERVAL_SECONDS", "15"))

app = FastAPI()
templates = Jinja2Templates(directory="templates")

# "service|environment" -> (last_counter_value, last_scrape_ts)
_last_counts: dict[str, tuple[float, float]] = {}
# "service|environment" -> most recently computed rate (spans/min)
_rates: dict[str, float] = {}

CALLS_RE = re.compile(r'^traces_span_metrics_calls_total\{([^}]*)\}\s+([0-9.eE+-]+)')
LABEL_RE = re.compile(r'(\w+)="([^"]*)"')


def push_config() -> None:
    """Rebuild the collector config from current blocked pairs and push it to every
    connected agent via the opamp-server's HTTP API (the same mechanism the manual
    Quick Action buttons use)."""
    try:
        resp = requests.get(f"{OPAMP_SERVER_URL}/api/agents", timeout=5)
        resp.raise_for_status()
        agents = resp.json()
    except requests.RequestException as e:
        log.warning("Could not list agents from opamp-server: %s", e)
        return

    config = build_config(storage.blocked_pairs())

    for agent in agents:
        if not agent.get("healthy"):
            continue
        try:
            requests.post(
                f"{OPAMP_SERVER_URL}/save_config",
                data={"instanceid": agent["instance_id"], "config": config},
                timeout=10,
            )
        except requests.RequestException as e:
            log.warning("Could not push config to agent %s: %s", agent["instance_id"], e)


def poll_metrics() -> None:
    """Scrape the collector's Prometheus endpoint for spanmetrics `calls_total` and
    turn the cumulative counters into a per-minute rate per (service, environment)."""
    try:
        resp = requests.get(METRICS_URL, timeout=5)
        resp.raise_for_status()
        text = resp.text
    except requests.RequestException as e:
        log.warning("Could not scrape metrics from %s: %s", METRICS_URL, e)
        return

    now = time.time()
    for line in text.splitlines():
        m = CALLS_RE.match(line)
        if not m:
            continue
        labels_str, value_str = m.groups()
        labels = dict(LABEL_RE.findall(labels_str))
        service = labels.get("service_name")
        environment = labels.get("deployment_environment")
        if not service or not environment:
            continue
        storage.ensure_policy_row(service, environment)

        key = f"{service}|{environment}"
        value = float(value_str)
        prev = _last_counts.get(key)
        _last_counts[key] = (value, now)
        if prev is not None:
            prev_value, prev_ts = prev
            dt = now - prev_ts
            if dt > 0 and value >= prev_value:
                _rates[key] = (value - prev_value) / dt * 60.0


def check_triggers() -> None:
    """Compare each policy's cap against the latest measured rate and fire
    notify (log-only/dry-run) and/or auto-block actions as configured."""
    for policy in storage.all_policies():
        key = f"{policy['service']}|{policy['environment']}"
        rate = _rates.get(key, 0.0)
        cap = policy["cap_per_min"]
        if cap is None or rate <= cap:
            continue

        if policy["notify_enabled"]:
            msg = (
                f"[DRY-RUN EMAIL] to={policy['notify_target'] or '(unset)'} "
                f"subject='Ingest cap exceeded: {policy['service']}/{policy['environment']}' "
                f"rate={rate:.1f}/min cap={cap:.1f}/min"
            )
            log.info(msg)
            storage.add_audit(policy["service"], policy["environment"], "notify_dryrun", msg)

        if policy["auto_block_enabled"] and not policy["blocked"]:
            storage.set_blocked(policy["service"], policy["environment"], True)
            push_config()
            detail = f"rate={rate:.1f}/min exceeded cap={cap:.1f}/min"
            storage.add_audit(policy["service"], policy["environment"], "auto_block", detail)
            log.info("Auto-blocked %s/%s: %s", policy["service"], policy["environment"], detail)


def poll_loop() -> None:
    while True:
        poll_metrics()
        check_triggers()
        time.sleep(POLL_INTERVAL_SECONDS)


@app.on_event("startup")
def on_startup() -> None:
    storage.init_db()
    threading.Thread(target=poll_loop, daemon=True).start()


def _row_status(policy) -> str:
    if policy["blocked"]:
        return "BLOCKED"
    cap = policy["cap_per_min"]
    key = f"{policy['service']}|{policy['environment']}"
    rate = _rates.get(key, 0.0)
    if cap is not None and rate > cap:
        return "WARNING"
    return "OK"


@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request):
    rows = []
    for policy in storage.all_policies():
        key = f"{policy['service']}|{policy['environment']}"
        rows.append({
            "service": policy["service"],
            "environment": policy["environment"],
            "rate": _rates.get(key, 0.0),
            "cap": policy["cap_per_min"],
            "notify_enabled": bool(policy["notify_enabled"]),
            "auto_block_enabled": bool(policy["auto_block_enabled"]),
            "notify_target": policy["notify_target"] or "",
            "blocked": bool(policy["blocked"]),
            "status": _row_status(policy),
        })
    audit = [dict(r) for r in storage.recent_audit(30)]
    return templates.TemplateResponse(
        "dashboard.html", {"request": request, "rows": rows, "audit": audit}
    )


@app.post("/policy/update")
def update_policy(
    service: str = Form(...),
    environment: str = Form(...),
    cap_per_min: str = Form(""),
    notify_enabled: bool = Form(False),
    auto_block_enabled: bool = Form(False),
    notify_target: str = Form(""),
):
    cap_val = float(cap_per_min) if cap_per_min.strip() else None
    storage.upsert_policy(service, environment, cap_val, notify_enabled, auto_block_enabled, notify_target)
    storage.add_audit(
        service, environment, "policy_update",
        f"cap={cap_val} notify={notify_enabled} auto_block={auto_block_enabled}",
    )
    return RedirectResponse("/", status_code=303)


@app.post("/policy/block")
def block(service: str = Form(...), environment: str = Form(...)):
    storage.set_blocked(service, environment, True)
    push_config()
    storage.add_audit(service, environment, "manual_block", "blocked via dashboard")
    return RedirectResponse("/", status_code=303)


@app.post("/policy/unblock")
def unblock(service: str = Form(...), environment: str = Form(...)):
    storage.set_blocked(service, environment, False)
    push_config()
    storage.add_audit(service, environment, "manual_unblock", "unblocked via dashboard")
    return RedirectResponse("/", status_code=303)
