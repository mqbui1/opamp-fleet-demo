FROM python:3.12-slim
WORKDIR /app
RUN pip install --no-cache-dir opentelemetry-sdk opentelemetry-exporter-otlp-proto-grpc
COPY gen.py .
CMD ["python", "gen.py"]
