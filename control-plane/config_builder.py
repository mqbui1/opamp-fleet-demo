"""Builds the OTel Collector YAML config pushed over OpAMP.

Kept intentionally simple/string-based (not a YAML library round-trip) so the
generated config is easy to eyeball during a demo. Mirrors the config built
client-side in opamp-server/agent.html's quick-action buttons, but supports
blocking an arbitrary set of (service, environment) pairs at once.

Uses the otlphttp exporter (not the signalfx exporter) to send traces to
Splunk O11y: the signalfx exporter's trace path silently drops all spans in
otelcol-contrib v0.158.0 (no errors logged even at debug level) - confirmed
via live testing. otlphttp against Splunk's OTLP trace ingest endpoint works.
"""

RECEIVERS_CONNECTORS = """receivers:
  otlp:
    protocols:
      grpc:
        endpoint: 0.0.0.0:4317
      http:
        endpoint: 0.0.0.0:4318
connectors:
  spanmetrics:
    dimensions:
      - name: deployment.environment
    histogram:
      disable: true
    metrics_flush_interval: 15s
"""

EXPORTERS = """exporters:
  otlphttp/splunk:
    traces_endpoint: https://ingest.${env:SPLUNK_REALM}.signalfx.com/v2/trace/otlp
    headers:
      X-SF-Token: ${env:SPLUNK_ACCESS_TOKEN}
  debug:
    verbosity: normal
  prometheus:
    endpoint: 0.0.0.0:8889
"""


def build_config(blocked_pairs: list[tuple[str, str]]) -> str:
    """blocked_pairs: list of (service_name, environment) to drop before export."""
    processors = "processors:\n  batch:\n"
    trace_processors = ["batch"]

    if blocked_pairs:
        conditions = "\n".join(
            "        - 'resource.attributes[\"service.name\"] == \"{}\" and "
            "resource.attributes[\"deployment.environment\"] == \"{}\"'".format(s, e)
            for s, e in blocked_pairs
        )
        processors += f"  filter/blocked:\n    traces:\n      span:\n{conditions}\n"
        trace_processors = ["filter/blocked", "batch"]

    pipelines = f"""service:
  pipelines:
    traces:
      receivers: [otlp]
      processors: [{', '.join(trace_processors)}]
      exporters: [otlphttp/splunk, debug, spanmetrics]
    metrics:
      receivers: [spanmetrics]
      exporters: [prometheus]
"""
    return RECEIVERS_CONNECTORS + processors + EXPORTERS + pipelines
