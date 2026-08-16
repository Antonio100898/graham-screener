#!/usr/bin/env bash
# Serve the screener through an ngrok tunnel so it can be opened from a phone.
#
# The tunnel is public: anyone with the URL reaches this machine. Reading is
# harmless (public SEC data), but the load jobs download gigabytes onto this
# disk, so writes are locked behind a token generated fresh on each run.
set -euo pipefail

cd "$(dirname "$0")"
PORT="${PORT:-8000}"
export SCREENER_TOKEN="${SCREENER_TOKEN:-$(python3 -c 'import secrets; print(secrets.token_urlsafe(12))')}"

command -v ngrok >/dev/null || { echo "ngrok not installed: brew install ngrok"; exit 1; }
[ -f api/screener/static/ui/index.html ] || { echo "UI not built — run: make build"; exit 1; }

pkill -f "uvicorn screener.api:app.*--port ${PORT}" 2>/dev/null || true
( cd api && .venv/bin/uvicorn screener.api:app --host 127.0.0.1 --port "$PORT" >/tmp/screener-api.log 2>&1 & )

for _ in $(seq 30); do
  curl -sf "http://127.0.0.1:${PORT}/health" >/dev/null && break
  sleep 0.5
done

ngrok http "$PORT" --log stdout --log-format json >/tmp/screener-ngrok.log 2>&1 &
NGROK_PID=$!
trap 'kill $NGROK_PID 2>/dev/null || true' EXIT

URL=""
for _ in $(seq 40); do
  URL=$(curl -s http://127.0.0.1:4040/api/tunnels 2>/dev/null \
        | python3 -c 'import json,sys; t=json.load(sys.stdin)["tunnels"]; print(t[0]["public_url"] if t else "")' 2>/dev/null || true)
  [ -n "$URL" ] && break
  sleep 0.5
done
[ -n "$URL" ] || { echo "ngrok did not report a URL — see /tmp/screener-ngrok.log"; exit 1; }

cat <<EOF

  Screener is live.

  Open on any device:   ${URL}/?token=${SCREENER_TOKEN}

  That link stores the token in the browser, so later visits to ${URL}
  work without it. Reading needs nothing; loading data needs the token.

  Ctrl-C stops the tunnel. The API keeps running locally on :${PORT}.

EOF
wait $NGROK_PID
