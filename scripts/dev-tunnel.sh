#!/usr/bin/env bash
# Run the dev stack with a public https address, so publishing to Instagram
# works from a laptop.
#
#   scripts/dev-tunnel.sh
#
# Starts an ngrok tunnel to :8000, waits for its URL, and brings the stack up
# with PUBLIC_BASE_URL pointing at it. Ctrl+C stops both. If PUBLIC_BASE_URL
# is already exported (a cloudflared tunnel, a reserved ngrok domain, ...),
# that value is used as-is and no tunnel is started.
set -euo pipefail
cd "$(dirname "$0")/.."

compose=(docker compose -f docker-compose.yml -f docker-compose.tunnel.yml)
started_ngrok=""

cleanup() {
  [ -n "$started_ngrok" ] && kill "$started_ngrok" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

if [ -z "${PUBLIC_BASE_URL:-}" ]; then
  command -v ngrok >/dev/null || {
    echo "ngrok not found. Install it, or export PUBLIC_BASE_URL from another tunnel." >&2
    exit 1
  }

  # Reuse a tunnel that is already up (the agent API only answers when one is).
  PUBLIC_BASE_URL=$(curl -fsS --max-time 2 http://127.0.0.1:4040/api/tunnels 2>/dev/null \
    | python3 -c 'import json,sys;print(next((t["public_url"] for t in json.load(sys.stdin).get("tunnels",[]) if t["public_url"].startswith("https")),""))' 2>/dev/null || true)

  if [ -z "$PUBLIC_BASE_URL" ]; then
    echo "starting ngrok on :8000 ..."
    ngrok http 8000 --log=stdout >/tmp/diffus-ngrok.log 2>&1 &
    started_ngrok=$!
    for _ in $(seq 1 30); do
      PUBLIC_BASE_URL=$(curl -fsS --max-time 2 http://127.0.0.1:4040/api/tunnels 2>/dev/null \
        | python3 -c 'import json,sys;print(next((t["public_url"] for t in json.load(sys.stdin).get("tunnels",[]) if t["public_url"].startswith("https")),""))' 2>/dev/null || true)
      [ -n "$PUBLIC_BASE_URL" ] && break
      sleep 1
    done
    [ -n "$PUBLIC_BASE_URL" ] || { echo "ngrok did not report a URL; see /tmp/diffus-ngrok.log" >&2; exit 1; }
  else
    echo "reusing the ngrok tunnel that is already running"
  fi
fi

export PUBLIC_BASE_URL
echo
echo "  public address : $PUBLIC_BASE_URL"
echo "  app            : http://localhost:8000"
echo "  ngrok inspector: http://127.0.0.1:4040"
echo
echo "Instagram fetches draft images from the public address above. It changes"
echo "every time a free ngrok tunnel restarts, which is why the stack is started"
echo "with it rather than reading it from .env."
echo

"${compose[@]}" up --build --remove-orphans
