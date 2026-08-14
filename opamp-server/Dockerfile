FROM golang:1.23-bookworm AS build
WORKDIR /src
RUN git clone --depth 1 https://github.com/open-telemetry/opamp-go.git .
COPY agent.html internal/examples/html/html/agent.html
RUN go build -o /opamp-server ./internal/examples/server

FROM debian:bookworm-slim
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates && rm -rf /var/lib/apt/lists/*
COPY --from=build /opamp-server /opamp-server
WORKDIR /app
EXPOSE 4320 4321
ENTRYPOINT ["/opamp-server", "-no-tls"]
