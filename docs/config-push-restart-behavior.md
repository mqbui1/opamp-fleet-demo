# Config Push / Restart Behavior

What actually happens to the collector process — and to in-flight trace data —
when the control-plane pushes a new config (block/unblock/auto-block), and
what that implies for production use. Findings below are from live testing
against this demo stack, not documentation guesses.

## Mechanism: full process restart, not a hot reload

Every push (via `opamp-server`'s `/save_config` API) causes the
`opampsupervisor` to write the new config to disk and do a **full stop +
start of the `otelcol-contrib` process** — not an in-place reload.

Confirmed via `/etc/otel/supervisor-data/effective.yaml`'s mtime changing on
every push, and via the collector's own log
(`/etc/otel/supervisor-data/agent.log`) showing a complete cold start on each
config change:

```
"Starting otelcol-contrib..."
"Starting extensions..."
"Starting spanmetrics connector"
"Starting GRPC server" (otlp receiver, :4317)
"Starting HTTP server" (otlp receiver, :4318)
"Everything is ready. Begin running and processing data."
```

## Measured restart gap (this demo's config)

- Startup phase alone (process start → OTLP receivers listening) measured at
  **~27ms** from the log timestamps above (`04:20:33.376` → `04:20:33.403`).
- Probed the OTLP HTTP port (`nc -z localhost 4318`) every 50ms for 15s
  across a real, confirmed restart (config file mtime changed) — **zero
  probes caught the port down**. So total stop+start downtime for this
  demo's config is under 50ms.

This is fast because the demo's pipeline is trivial: one receiver, a couple
of processors, three exporters, no persistent queues or TLS handshakes to
set up. It is a real process restart — just a cheap one for this config.

## What happens to in-flight spans during the gap

- Any span the client tries to send while the receiver port is down gets a
  connection-level failure (gRPC/HTTP connection refused).
- Nothing is buffered by the *collector* in this demo — there's no
  persistent-queue exporter configured. Any recovery is entirely a
  client-side (SDK exporter) behavior.
- The `trace-generator` uses `BatchSpanProcessor` + `OTLPSpanExporter`, which
  has built-in retry-with-backoff on transient (`UNAVAILABLE`-type) errors
  per the OTLP exporter spec. For a gap this short (sub-50ms), a retry
  absorbs it silently — which is why no gaps are visible in the trace data
  around block/unblock actions in this demo.
- The collector's own `filter` processor drop is unrelated to this: blocked
  spans that *do* make it to the collector are dropped intentionally and
  permanently (see main README) — that's a separate mechanism from the
  brief connection gap during restart.

## Production implications

This demo's near-zero-downtime restart is a property of its trivial config
and localhost networking, not something to assume in production:

1. **No redundancy.** This demo runs a single collector instance per
   "agent." In production, pushing a config change to your only collector
   instance means a real (if brief) receive-side outage. A client without
   retry/buffering, or a gap that exceeds the client's retry budget, drops
   data with no recovery path.
2. **Real configs restart slower.** More receivers/processors/exporters —
   especially ones doing connection pooling, TLS handshakes, or disk I/O on
   init (Kafka, file, disk-buffered queues) — take longer to start.
   Seconds, not milliseconds, is common outside of a minimal demo config.
3. **Client retry budgets are finite.** Most SDK exporters retry for a few
   seconds, then give up, log an error, and drop the span. A slower restart
   or a non-localhost network hop can easily exceed that budget.
4. **Volume matters.** At real production span rates, even a 200ms–1s gap
   can mean thousands of spans hitting the retry path simultaneously,
   which also risks a thundering-herd retry spike right as the collector
   comes back up.

**Standard mitigation** (not implemented in this demo, since it's
illustrative rather than a reference HA architecture): run **N+1 collector
replicas behind a load balancer** and roll config changes to one instance at
a time (canary/rolling), so capacity to receive traffic always exists during
any single instance's restart. This demo's single-instance-per-agent model
is meant to make the OpAMP mechanism easy to observe, not to demonstrate a
highly-available production topology.
