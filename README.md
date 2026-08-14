# OpAMP Fleet Management Demo

Demonstrates dynamic, targeted OTel Collector config push (OpAMP) to block ingestion for a
specific service or environment, entirely outside the Splunk Observability Cloud UI — using
only open source components. The collector still exports to a real Splunk O11y org so the
effect is visible there.

Includes a **Fleet Ingest Control Plane** dashboard on top: per-service/environment
utilization, manual block/unblock, ingest caps, and cap-breach triggers (notify + optional
auto-block). Notifications are log-only/dry-run for now.

## Architecture

- **opamp-server** — a real, protocol-compliant OpAMP server (OTel's own reference
  implementation, `open-telemetry/opamp-go`), extended with a small "Quick Actions" panel on
  the agent page and a `/api/agents` JSON endpoint. Admin UI at http://localhost:4321.
- **otel-collector** — `otelcol-contrib`, managed by the real `opampsupervisor` (from
  `opentelemetry-collector-contrib`). Starts with no config until a config is pushed; the
  supervisor writes whatever config is pushed to disk and restarts the collector. Also runs a
  `spanmetrics` connector exposed via a Prometheus endpoint (`:8889/metrics`) for utilization.
- **trace-generator** — a small Python script emitting continuous OTLP traces for two fake
  services (`checkout` / `prod`, `payments` / `staging`).
- **control-plane** — a FastAPI app (http://localhost:8080) that:
  - scrapes the collector's `calls_total` spanmetrics every `POLL_INTERVAL_SECONDS` to compute
    a live spans/min rate per (service, environment)
  - lets you set a cap, and independently toggle notify / auto-block, per (service, environment)
  - on cap breach: logs a dry-run "would email X" line (and records it in the audit log), and if
    auto-block is enabled, rebuilds and pushes a new collector config via the opamp-server API —
    same mechanism as the manual Quick Action buttons
  - persists policies + audit log in SQLite (`control-plane-data` volume)
- Traces are exported from the collector to your real Splunk O11y org via the `otlphttp` exporter,
  pointed at Splunk's OTLP trace ingest endpoint. (Not the `signalfx` exporter: its trace path
  silently drops all spans in otelcol-contrib v0.158.0 with no errors logged, even at debug level
  — confirmed via live testing. `otlphttp` works correctly.)

## Setup

```
cp .env.example .env
# edit .env: set SPLUNK_ACCESS_TOKEN and SPLUNK_REALM
docker compose up --build
```

## Demo script

### Part 1 — raw OpAMP mechanism (opamp-server UI)

1. Open http://localhost:4321, click the connected agent.
2. Click **"Push Base Config (unblocked)"**. The collector picks up the config over OpAMP and
   restarts. Traces for both `checkout` and `payments` should now be flowing.
3. Confirm both services show up in Splunk O11y APM (may take ~30-60s).
4. Click **"Block Service: payments"**. This pushes a new config containing an OTel `filter`
   processor that drops spans where `service.name == "payments"`, over the same OpAMP
   connection — no redeploy, no restart of the demo stack.
5. Watch Splunk O11y: `payments` traces stop arriving within roughly one polling interval;
   `checkout` keeps flowing the whole time.
6. Click **"Block Environment: staging"** to show the same mechanism scoped by
   `deployment.environment` instead of `service.name`.
7. Click **"Push Base Config (unblocked)"** again to restore full ingestion.

### Part 2 — Fleet Ingest Control Plane (control-plane UI)

1. Make sure a base (unblocked) config is active (Part 1, steps 1-2) so the collector has a
   `spanmetrics` pipeline running and there's traffic to measure.
2. Open http://localhost:8080. After the first `POLL_INTERVAL_SECONDS`, `checkout`/`prod` and
   `payments`/`staging` rows appear with a live spans/min rate.
3. Click **Block** on a row — pushes a filter config for just that (service, environment) pair
   via the opamp-server API; confirm it disappears from Splunk O11y. Click **Unblock** to restore.
4. Set a low **Cap** on a row (e.g. below its current rate), check **notify**, add a
   **Notify target** email, click **Save**. Within one poll interval, check the Audit Log at the
   bottom of the page for a `notify_dryrun` entry (also logged to the container's stdout) —
   nothing is actually emailed.
5. Check **auto-block** on the same row and click **Save**. On the next poll interval that finds
   the rate still over cap, the row auto-flips to **BLOCKED** and an `auto_block` audit entry
   appears — no manual click needed.

## Notes

- No pre-built "block service" template exists in any real product today — this repo
  hand-builds the OTel `filter` processor config, which is exactly what an admin would need
  to author via a real Fleet Management Template.
- The OpAMP server/supervisor here are the real upstream OSS implementations, not stubs.
