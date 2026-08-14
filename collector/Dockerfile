FROM debian:bookworm-slim

ARG OTELCOL_VERSION=0.158.0
ARG SUPERVISOR_VERSION=0.158.0

RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates && rm -rf /var/lib/apt/lists/*

RUN curl -fL -o /tmp/otelcol.tar.gz \
      "https://github.com/open-telemetry/opentelemetry-collector-releases/releases/download/v${OTELCOL_VERSION}/otelcol-contrib_${OTELCOL_VERSION}_linux_amd64.tar.gz" \
    && tar -xzf /tmp/otelcol.tar.gz -C /usr/local/bin otelcol-contrib \
    && rm /tmp/otelcol.tar.gz \
    && curl -fL -o /usr/local/bin/opampsupervisor \
      "https://github.com/open-telemetry/opentelemetry-collector-releases/releases/download/cmd/opampsupervisor/v${SUPERVISOR_VERSION}/opampsupervisor_${SUPERVISOR_VERSION}_linux_amd64" \
    && chmod +x /usr/local/bin/otelcol-contrib /usr/local/bin/opampsupervisor

COPY supervisor.yaml /etc/otel/supervisor.yaml
RUN mkdir -p /etc/otel/supervisor-data

WORKDIR /etc/otel
EXPOSE 4317 4318
ENTRYPOINT ["/usr/local/bin/opampsupervisor", "--config=/etc/otel/supervisor.yaml"]
