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
  implementation, `open-telemetry/opamp-go`), extended with a `/api/agents` JSON endpoint so
  the control-plane can discover connected agents. Admin UI at http://localhost:4321 — useful
  for inspecting agent status/effective config and for raw protocol debugging via its manual
  "Additional Configuration" form, but **blocking should be done via the control-plane**, not
  here, to avoid two tools racing to push config to the same agent.
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
    auto-block is enabled, rebuilds and pushes a new collector config via the opamp-server API
  - persists policies + audit log in SQLite (`control-plane-data` volume)
  - displays the exact YAML config currently pushed to the agent, rebuilt live from policy state,
    at the bottom of the dashboard — useful for showing exactly what OpAMP is enforcing
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

All blocking/unblocking is done from the **Fleet Ingest Control Plane** (http://localhost:8080)
— it's the single source of truth for which (service, environment) pairs are blocked, and every
push it makes rebuilds the full desired-state config from its own database, so there's no drift.

1. `docker compose up --build` and wait for the stack to come up. Open http://localhost:8080.
   After the first `POLL_INTERVAL_SECONDS`, `checkout`/`prod` and `payments`/`staging` rows
   appear with a live spans/min rate.
2. Confirm both services show up in Splunk O11y APM (may take a few minutes to index).
3. Click **Block** on the `checkout`/`prod` row — pushes a filter config for just that pair via
   the opamp-server API; confirm it disappears from Splunk O11y while `payments` keeps flowing.
   Click **Unblock** to restore.
4. Set a low **Cap** on a row (e.g. below its current rate), check **notify**, add a
   **Notify target** email, click **Save**. Within one poll interval, check the Audit Log at the
   bottom of the page for a `notify_dryrun` entry (also logged to the container's stdout) —
   nothing is actually emailed.
5. Check **auto-block** on the same row and click **Save**. On the next poll interval that finds
   the rate still over cap, the row auto-flips to **BLOCKED** and an `auto_block` audit entry
   appears — no manual click needed.

The opamp-server admin UI (http://localhost:4321) is still useful to inspect an agent's raw
status/effective config, or for one-off raw OpAMP protocol debugging via its manual
"Additional Configuration" form — but avoid using it to push blocking config in parallel with
the control-plane, since neither tool is aware of the other's desired state.

## Notes

- No pre-built "block service" template exists in any real product today — this repo
  hand-builds the OTel `filter` processor config, which is exactly what an admin would need
  to author via a real Fleet Management Template.
- The OpAMP server/supervisor here are the real upstream OSS implementations, not stubs.
- **Always use `docker compose up --build`**, not plain `up`, after editing any service's code.
  A plain `up` keeps running stale container images even when the source files on disk have
  changed — this caused a real bug during testing where the control-plane kept pushing an old,
  broken config after a fix had already been made to `config_builder.py` (see git history).
- Every config push is a **full restart** of the `otelcol-contrib` process (not a hot reload),
  so there's a brief receiver-down window on every block/unblock/auto-block. In this demo it's
  imperceptible (measured under 50ms) and absorbed by the trace-generator's SDK-level retry —
  but this is not a production HA pattern. See
  [`docs/config-push-restart-behavior.md`](docs/config-push-restart-behavior.md) for the full
  measured behavior and production implications (no redundancy, larger real configs restart
  slower, finite client retry budgets).
