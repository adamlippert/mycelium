# -- Stage 1: build the React + Vite frontend -----------------------------------------
FROM node:22-alpine AS frontend
WORKDIR /build
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm install --no-audit --no-fund
COPY frontend/ ./
COPY plugins/ /plugins/
RUN npm run build

# -- Stage 2: build spore-nfs (Go) ------------------------------------------------------
FROM golang:1.25-alpine AS spore-nfs
WORKDIR /src
COPY spore-nfs/go.mod spore-nfs/go.sum* ./
RUN go mod download
COPY spore-nfs/main.go ./
RUN CGO_ENABLED=0 go build -o /spore-nfs .

# -- Stage 2b: build spore-stream, the Go streaming front ------------------------------
FROM golang:1.25-alpine AS spore-stream
WORKDIR /src
COPY spore-stream/go.mod spore-stream/go.sum* ./
COPY spore-stream/*.go ./
RUN CGO_ENABLED=0 go build -o /spore-stream .

# -- Stage 3: build spore-smb (Rust) ---------------------------------------------------
FROM rust:slim AS spore-smb
RUN apt-get update -qq && apt-get install -y -qq pkg-config libssl-dev && rm -rf /var/lib/apt/lists/*
WORKDIR /src
COPY spore-smb/ ./
RUN cargo build --release && cp target/release/spore-smb /spore-smb

# -- Stage 4: Python runtime ----------------------------------------------------------
FROM python:3.12-slim

ARG BUILD_VERSION=dev
LABEL org.opencontainers.image.title="mycelium" \
      org.opencontainers.image.description="Self-hosted media pipeline: watchlist to .strm via TorBox" \
      org.opencontainers.image.version="${BUILD_VERSION}" \
      org.opencontainers.image.source="https://github.com/adamlippert/mycelium"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    LISTEN_HOST=0.0.0.0 \
    LISTEN_PORT=8088 \
    LIBVA_DRIVER_NAME=iHD

WORKDIR /app

ARG TARGETARCH
# Add non-free repo for Intel VA-API driver (iHD = Gen8+, includes J3455/J4125)
# intel-media-va-driver is x86-only; skip on arm64
RUN echo "deb http://deb.debian.org/debian bookworm contrib non-free non-free-firmware" \
        > /etc/apt/sources.list.d/non-free.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends \
        ffmpeg \
        libva2 \
        libva-drm2 \
        gosu \
        libcap2-bin \
    && if [ "$TARGETARCH" = "amd64" ]; then \
        apt-get install -y --no-install-recommends intel-media-va-driver; \
    fi \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY *.py ./
COPY releases.json ./
COPY plugins/ ./plugins/
COPY templates/ ./templates/
COPY docs/ ./docs/
# Built SPA from stage 1 (Vite writes to ../static/app relative to frontend/)
COPY --from=frontend /static/app/ ./static/app/
# Also copy pre-built SPA if present (skips npm build when static/app/ is tracked)
COPY static/ ./static/
COPY --from=spore-nfs /spore-nfs /usr/local/bin/spore-nfs
COPY --from=spore-smb /spore-smb /usr/local/bin/spore-smb
COPY --from=spore-stream /spore-stream /usr/local/bin/spore-stream

# SMB's port 445 is below 1024, so opening it normally requires root. Marking
# the binary itself lets it bind that port at any user id, which keeps the
# share working when PUID is set. Capabilities live in the file's extended
# attributes, so this has to happen after the COPY, not in the build stage.
RUN setcap cap_net_bind_service=+ep /usr/local/bin/spore-smb

COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN chmod +x /usr/local/bin/docker-entrypoint.sh
ENTRYPOINT ["docker-entrypoint.sh"]

ENV MYCELIUM_BASE=http://127.0.0.1:8088

EXPOSE 8088 2049 445

HEALTHCHECK --interval=60s --timeout=10s --start-period=30s --retries=3 \
  CMD python -c "import urllib.request,os,sys; \
port=os.environ.get('LISTEN_PORT','8088'); \
r=urllib.request.urlopen(f'http://127.0.0.1:{port}/health',timeout=5); \
sys.exit(0 if r.status==200 else 1)" || exit 1

# --workers MUST stay 1: catbox's single-flight token locks, the scan-burst
# detector, mp4_faststart's build locks, Flask-Limiter's memory:// login
# counters and several caches all live in process memory and are only correct
# in a single process. Streaming concurrency comes from the Go front
# (spore-stream) instead: it owns /spore-stream/* where each open stream is a
# goroutine, and reverse-proxies everything else to gunicorn, whose threads
# then only serve short-lived requests. STREAM_FRONT_ENABLED=false reverts to
# gunicorn on the exposed port with its own (complete) /spore-stream route,
# where --threads is once again the ceiling on simultaneous open streams.
CMD ["sh", "-c", "\
( LISTEN_ADDR=:2049 spore-nfs; echo \"[mycelium] spore-nfs exited (status $?); the NFS share is now unavailable\" >&2 ) & \
( LISTEN_ADDR=0.0.0.0:445 spore-smb; echo \"[mycelium] spore-smb exited (status $?); the SMB share is now unavailable\" >&2 ) & \
if [ \"${STREAM_FRONT_ENABLED:-true}\" = \"true\" ]; then \
  ( while true; do STREAM_LISTEN=${LISTEN_HOST}:${LISTEN_PORT} STREAM_UPSTREAM=http://127.0.0.1:${GUNICORN_PORT:-8090} spore-stream; \
      echo \"[mycelium] spore-stream exited (status $?); restarting in 1s\" >&2; sleep 1; done ) & \
  exec gunicorn --bind 127.0.0.1:${GUNICORN_PORT:-8090} --workers 1 --threads ${GUNICORN_THREADS:-64} --access-logfile - app:app; \
else \
  exec gunicorn --bind ${LISTEN_HOST}:${LISTEN_PORT} --workers 1 --threads ${GUNICORN_THREADS:-64} --access-logfile - app:app; \
fi"]
