#!/usr/bin/env sh
# Concurrent-stream load test for the Mycelium streaming path.
#
# Opens N slow concurrent streams against one token and measures API latency
# while they run - the point is not stream throughput but whether the rest of
# the app stays responsive under streaming load, which is exactly what the Go
# streaming front exists for.
#
# Usage:
#   scripts/loadtest-streams.sh <base-url> <token> [streams] [seconds]
#   scripts/loadtest-streams.sh https://mycelium.example.com a1b2c3d4e5f60718 40 60
#
# Pick a token of something ALREADY PLAYED (admin > Maintenance or
# /ui/api/virtual-items): a warm token costs no TorBox createtorrent budget.
# Bandwidth still flows from the TorBox CDN: N x 500KB/s x seconds
# (the defaults pull roughly 1.2 GB total).
#
# Reading the result: healthy is p95 under ~100ms with every stream open.
# For a before/after comparison, run once, set STREAM_FRONT_ENABLED=false,
# restart, and run again - and try raising streams until the fallback
# degrades while the front does not.
set -eu

BASE="${1:?usage: loadtest-streams.sh <base-url> <token> [streams] [seconds]}"
TOKEN="${2:?need a virtual-item token (use one that has already been played)}"
STREAMS="${3:-40}"
SECONDS_TOTAL="${4:-60}"
# Per-stream rate. Lower it when running from a client whose own downlink
# would saturate before the server does (N x rate must fit YOUR connection,
# or the health probes measure your congestion, not the server's).
RATE="${RATE:-500k}"
BASE="${BASE%/}"

TMP="$(mktemp -d)"
# The || true matters: set -e is live inside the trap, and kill returns
# nonzero once the streams have already exited, which made the whole script
# report failure after a successful run.
trap 'kill $(cat "$TMP"/pids 2>/dev/null) 2>/dev/null || true; rm -rf "$TMP"' EXIT INT TERM

echo "== baseline: /health latency, idle (10 samples) =="
i=0
while [ "$i" -lt 10 ]; do
  curl -s -o /dev/null -w '%{time_total}\n' "$BASE/health" >> "$TMP/base" || echo failed >> "$TMP/base"
  i=$((i + 1))
done
sort -n "$TMP/base" | awk '{a[NR]=$1} END {printf "  min=%.3fs median=%.3fs max=%.3fs\n", a[1], a[int(NR/2)+1], a[NR]}'

echo "== opening $STREAMS streams for ${SECONDS_TOTAL}s (each rate-limited to $RATE/s) =="
i=0
: > "$TMP/pids"
while [ "$i" -lt "$STREAMS" ]; do
  curl -s -o /dev/null -m "$SECONDS_TOTAL" --limit-rate "$RATE" \
    -H "Range: bytes=0-" "$BASE/spore-stream/$TOKEN" \
    -w '%{http_code}\n' >> "$TMP/codes" &
  echo $! >> "$TMP/pids"
  i=$((i + 1))
done
sleep 5  # let every stream get past resolve and start pulling bytes

echo "== /health latency with $STREAMS streams open (one sample per second) =="
i=0
budget=$((SECONDS_TOTAL - 10))
while [ "$i" -lt "$budget" ]; do
  curl -s -o /dev/null -m 10 -w '%{time_total}\n' "$BASE/health" >> "$TMP/loaded" || echo timeout >> "$TMP/loaded"
  sleep 1
  i=$((i + 1))
done

wait $(cat "$TMP/pids") 2>/dev/null || true

echo
echo "== results =="
timeouts=$(grep -c timeout "$TMP/loaded" 2>/dev/null || true)
grep -v timeout "$TMP/loaded" | sort -n | awk -v to="${timeouts:-0}" '
  {a[NR]=$1}
  END {
    if (NR == 0) { print "  every health probe timed out"; exit }
    printf "  health under load: samples=%d timeouts=%d\n", NR, to
    printf "  min=%.3fs median=%.3fs p95=%.3fs max=%.3fs\n",
           a[1], a[int(NR/2)+1], a[int(NR*0.95)+ (NR*0.95==int(NR*0.95)?0:1)], a[NR]
  }'
echo "  stream HTTP codes:"
sort "$TMP/codes" 2>/dev/null | uniq -c | sed 's/^/   /'
echo
echo "Verdict guide: p95 < 0.1s and zero timeouts = the API is unaffected by"
echo "streaming load. Rising medians or timeouts = the serving path is"
echo "saturating; check 'docker stats mycelium' and the container logs."
