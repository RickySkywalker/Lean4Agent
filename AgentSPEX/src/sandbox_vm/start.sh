#!/usr/bin/env bash
set -euo pipefail

# So files/dirs created in the workspace are readable by host (e.g. rsync backup).
# New files: 666, new dirs: 777.
umask 0000

if [ -n "$USER_PASSWORD" ]; then
  echo "$(whoami):${USER_PASSWORD}" | sudo chpasswd
  mkdir -p "$HOME/.vnc"
  x11vnc -storepasswd "$USER_PASSWORD" "$HOME/.vnc/passwd"
  chmod 600 "$HOME/.vnc/passwd"
else
  echo "require \$USER_PASSWORD to run this script"
  exit 1
fi
 
 
export PYTHONPATH="$PWD"

# Visible Chromium
BROWSER_START_URL="https://www.wikipedia.org"


LOGDIR="${VM_WORKSPACE}/logs"
mkdir -p "$LOGDIR/server"  "$LOGDIR/terminal" "$LOGDIR/browser"

ts() { date +%Y%m%d-%H%M%S; }
log() { echo "[$(date +'%F %T')] $*"; }

# -------------------------
# X and desktop
# -------------------------
start_xvfb() {
  log "Setting up X11 authentication..."

  # Create .Xauthority file
  touch "$HOME/.Xauthority"
  chmod 600 "$HOME/.Xauthority"

  # Generate X11 auth cookie
  xauth_cookie=$(openssl rand -hex 16)
  xauth add "$DISPLAY" . "$xauth_cookie"

  log "Starting Xvfb on $DISPLAY ($SCREEN_SIZE) ..."
  Xvfb "$DISPLAY" -screen 0 "$SCREEN_SIZE" -nolisten tcp -auth "$HOME/.Xauthority" \
    >"$LOGDIR/server/xvfb-$(ts).log" 2>&1 &

  # wait for X socket and readiness
  sock="/tmp/.X11-unix/X${DISPLAY#:}"
  for _ in $(seq 1 60); do
    [[ -S "$sock" ]] && break
    sleep 0.2
  done
  if command -v xdpyinfo >/dev/null 2>&1; then
    xdpyinfo -display "$DISPLAY" >/dev/null 2>&1 || { echo "[ERROR] Xvfb not ready"; exit 1; }
  fi

  log "X11 server ready with authentication"
}

start_fluxbox() {
  log "Starting fluxbox ..."
  xsetroot -solid gray &
  fluxbox -display "$DISPLAY" \
    >"$LOGDIR/server/fluxbox-$(ts).log" 2>&1 &
}

start_tmux_xterm() {
  local session="${TMUX_SESSION}"  

  log "Starting tmux + xterm ..."

  tmux has-session -t "$session" 2>/dev/null || tmux new-session -d -s "$session" "/bin/bash -l"

  xterm -display "$DISPLAY" -fa Monospace -fs 10 -geometry 80x40+20+200 -title "$session Terminal" \
    -e tmux attach -t "$session" \
    >"$LOGDIR/server/xterm-$(ts).log" 2>&1 &
}


start_tool_log() {
  log "Starting tool activity log ..."

  export TOOL_LOG_FILE="$LOGDIR/server/tool-activity-$(ts).log"

  # Create the named pipe if not already present
  touch "$TOOL_LOG_FILE"

  # Launch xterm to display contents of the pipe (read-only behavior)
  xterm -display "$DISPLAY" \
    -bg black -fg white -sb -rightbar -sl 500000 \
    -fa Monospace -fs 8 -geometry 100x10+0+0 -title "Tool Activity Log" \
    -e sh -c "stty -echo; exec tail -n 100 -F $TOOL_LOG_FILE" &
}


start_chromium() {
  local prof="$LOGDIR/browser"
  mkdir -p "$prof"

  # Clean up stale Chromium profile locks from previous runs
  rm -f "$prof/Lock" "$prof/SingletonLock"

  log "Starting Chromium: url=${BROWSER_START_URL}  profile=$prof"
  chromium \
    --no-first-run --no-default-browser-check \
    --no-sandbox --disable-setuid-sandbox \
    --disable-dev-shm-usage \
    --disable-gpu --disable-software-rasterizer --disable-features=VizDisplayCompositor \
    --password-store=basic \
    --disable-process-singleton \
    --remote-debugging-address="127.0.0.1" --remote-debugging-port="$CDP_PORT" \
    --user-data-dir="$prof" \
    --window-position=800,20 \
    "${BROWSER_START_URL}" \
    >"$LOGDIR/server/chromium-$(ts).log" 2>&1 &
}

# -------------------------
# VNC 
# -------------------------
start_x11vnc() {
  log "Starting x11vnc on :$RDP_PORT for $DISPLAY ..."
  # Create password file if it doesn't exist
  x11vnc -display "$DISPLAY" -rfbport "$RDP_PORT" -rfbauth "$HOME/.vnc/passwd" -shared -forever -quiet \
    >"$LOGDIR/server/x11vnc-$(ts).log" 2>&1 &
}

start_novnc() {
  log "Starting VNC on :$VNC_PORT ..."
  websockify --web=/usr/share/novnc/ "$VNC_PORT" "localhost:$RDP_PORT" \
    >"$LOGDIR/server/novnc-$(ts).log" 2>&1 &
}

# -------------------------
# MCP server
# -------------------------
start_mcp() {
  # We assume these are defined: MCP_TRANSPORT, MCP_HOST, MCP_PORT, LOGDIR
  logf="$LOGDIR/server/mcp-$(ts).log"

  log "Starting MCP (${MCP_TRANSPORT}) on ${MCP_HOST}:${MCP_PORT}${MCP_BASEPATH}, logging to ${logf}"

  nohup python -m ${VM_PACKAGE}.mcp.server >"$logf" 2>&1 &
}


# -------------------------
# Start all
# -------------------------
start_xvfb
start_fluxbox
start_tmux_xterm
start_tool_log
start_chromium
start_x11vnc
start_novnc
start_mcp

log "Startup complete."
log "VNC:   http://localhost:${VNC_PORT}/vnc_auto.html"

log "MCP:  http://${MCP_HOST}:${MCP_PORT}${MCP_BASEPATH}"
 
log "All services started; waiting for them to exit (or for SIGTERM)…"

# Follow server logs so the container stays in the foreground
tail -F "$LOGDIR"/server/*.log &
wait   # waits for all child processes; keeps the script (and container) alive

