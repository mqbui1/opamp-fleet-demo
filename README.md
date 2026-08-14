# OpAMP Fleet Management Demo

Demonstrates dynamic, targeted OTel Collector config push (OpAMP) to block ingestion for a
specific service or environment, entirely outside the Splunk Observability Cloud UI — using
only open source components. The collector still exports to a real Splunk O11y org so the
effect is visible there.

## Architecture

- **opamp-server** — a real, protocol-compliant OpAMP server (OTel's own reference
  implementation, `open-telemetry/opamp-go`), extended with a small "Quick Actions" panel on
  the agent page. Admin UI at http://localhost:4321.
- **otel-collector** — `otelcol-contrib`, managed by the real `opampsupervisor` (from
  `opentelemetry-collector-contrib`). Starts with no config until the admin pushes one; the
  supervisor writes whatever config is pushed to disk and restarts the collector.
- **trace-generator** — a small Python script emitting continuous OTLP traces for two fake
  services (`checkout` / `prod`, `payments` / `staging`).
- Traces are exported from the collector to your real Splunk O11y org via the `sapm` exporter.

## Setup

```
cp .env.example .env
# edit .env: set SPLUNK_ACCESS_TOKEN and SPLUNK_REALM
docker compose up --build
```

## Demo script

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

## Notes

- No pre-built "block service" template exists in any real product today — this repo
  hand-builds the OTel `filter` processor config, which is exactly what an admin would need
  to author via a real Fleet Management Template.
- The OpAMP server/supervisor here are the real upstream OSS implementations, not stubs.
