import os
import time

from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

ENDPOINT = os.environ.get("OTLP_ENDPOINT", "http://otel-collector:4317")

SERVICES = [
    {"service.name": "checkout", "deployment.environment": "prod"},
    {"service.name": "payments", "deployment.environment": "staging"},
]

tracers = []
for svc in SERVICES:
    provider = TracerProvider(resource=Resource.create(svc))
    provider.add_span_processor(
        BatchSpanProcessor(OTLPSpanExporter(endpoint=ENDPOINT, insecure=True))
    )
    tracers.append((svc["service.name"], provider.get_tracer(svc["service.name"])))

print(f"Sending traces to {ENDPOINT} for services: {[s['service.name'] for s in SERVICES]}", flush=True)

while True:
    for name, tracer in tracers:
        with tracer.start_as_current_span(f"{name}.handle_request") as span:
            span.set_attribute("http.method", "GET")
            time.sleep(0.05)
    print("sent batch: checkout + payments", flush=True)
    time.sleep(2)
