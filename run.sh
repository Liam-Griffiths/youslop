#!/usr/bin/env bash
# Start Youslop.
#
#   ./run.sh                        this machine only, http://127.0.0.1:8420
#   HOST=0.0.0.0 HTTPS=1 ./run.sh   reachable from the network, over https
#
# HTTPS matters for more than privacy: browsers refuse to hand a microphone to
# a plain-http page unless it is localhost, so recording from a second machine
# needs either https (this) or an ssh tunnel (see the README).
set -euo pipefail
cd "$(dirname "$0")"

if [ ! -d .venv ]; then
  echo "Creating .venv…"
  python3 -m venv .venv
  ./.venv/bin/pip install -q --upgrade pip
  ./.venv/bin/pip install -q -r requirements.txt
fi

command -v ffmpeg >/dev/null || { echo "ffmpeg not found. brew install ffmpeg"; exit 1; }
# Not fatal: everything downstream of a script already exists — media, voice,
# rendering — works without it. Only writing a new script (from an idea, or by
# importing a pasted one) needs it, and that path reports its own clear error
# the moment it is actually used. See the README's "Running without Claude Code".
command -v claude >/dev/null || echo "Note: claude CLI not found — script writing will be unavailable. See the README."

PORT="${PORT:-8420}"
HOST="${HOST:-127.0.0.1}"

lan_ip() {
  local dev ip
  dev=$(route -n get default 2>/dev/null | awk '/interface:/{print $2}' | head -1)
  for i in "$dev" en0 en1 en2; do
    [ -n "$i" ] || continue
    ip=$(ipconfig getifaddr "$i" 2>/dev/null) || true
    [ -n "$ip" ] && { echo "$ip"; return; }
  done
}
IP="$(lan_ip || true)"

ARGS=()
SCHEME="http"
if [ "${HTTPS:-0}" != "0" ]; then
  CERTS=".certs"; CRT="$CERTS/cert.pem"; KEY="$CERTS/key.pem"
  mkdir -p "$CERTS"
  # Regenerate when this machine's address has changed, or Chrome will reject
  # the certificate outright instead of offering to continue.
  NEED=1
  if [ -s "$CRT" ] && [ -s "$KEY" ]; then
    if [ -z "$IP" ] || openssl x509 -in "$CRT" -noout -text 2>/dev/null | grep -q "IP Address:$IP"; then
      NEED=0
    fi
  fi
  if [ "$NEED" = "1" ]; then
    echo "Making a self-signed certificate for ${IP:-localhost}…"
    SAN="DNS:localhost,IP:127.0.0.1${IP:+,IP:$IP}"
    openssl req -x509 -newkey rsa:2048 -sha256 -days 825 -nodes \
      -keyout "$KEY" -out "$CRT" \
      -subj "/CN=${IP:-localhost}" -addext "subjectAltName=$SAN" >/dev/null 2>&1
    chmod 600 "$KEY"
  fi
  ARGS+=(--ssl-keyfile "$KEY" --ssl-certfile "$CRT")
  SCHEME="https"
fi

# Anything on the network that can reach this port can read, edit and delete
# every project, so leaving loopback turns on a token unless asked not to.
QS=""
case "$HOST" in
  127.0.0.1|localhost|::1) ;;
  *)
    case "${VB_TOKEN:-}" in
      off|none|no) unset VB_TOKEN ;;
      "")
        if [ -s .token ]; then VB_TOKEN=$(cat .token)
        else VB_TOKEN=$(openssl rand -hex 12); printf '%s' "$VB_TOKEN" > .token; chmod 600 .token; fi
        export VB_TOKEN ;;
      *) export VB_TOKEN ;;
    esac
    [ -n "${VB_TOKEN:-}" ] && QS="?t=${VB_TOKEN}"
    ;;
esac

echo "→ ${SCHEME}://127.0.0.1:${PORT}${QS}"
if [ "$HOST" != "127.0.0.1" ] && [ -n "$IP" ]; then
  echo "→ ${SCHEME}://${IP}:${PORT}${QS}   ← open this on the other machine"
  [ "$SCHEME" = "http" ] && echo "   (plain http: that machine's browser will refuse the microphone — use HTTPS=1)"
  [ "$SCHEME" = "https" ] && echo "   (self-signed: accept the certificate warning once)"
fi
exec ./.venv/bin/uvicorn app.main:app --host "$HOST" --port "$PORT" \
  ${ARGS[@]+"${ARGS[@]}"} "$@"
