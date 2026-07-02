#!/bin/bash

if [[ "$1" == "-h" || "$1" == "--help" ]]; then
  echo "Usage: $0 [WORKFLOW_PATH] [WORKFLOW_ENV_PATH] [options] [-- <extra python args>]"
  echo ""
  echo "Arguments:"
  echo "  WORKFLOW_PATH   Path to workflow. (default to WORKFLOW_PATH"
  echo "      workflow file: WORKFLOW_PATH.json "
  echo "  WORKFLOW_ENV_PATH   Path to workflow env. (default to WORKFLOW_PATH)"
  echo "      workflow environment variable file: WORKFLOW_ENV_PATH.env"
  echo ""
  echo "Options:"
  echo "  --output_dir DIR        Override output directory (default: outputs/<workflow_name>)"
  echo "  --mcp_url URL           Override MCP URL (default: http://localhost:<MCP_PORT><MCP_BASEPATH> from config/vm.env)"
  echo "  --resume                Resume from checkpoint.json (skips completed steps)"
  echo "  --checkpoint_path PATH  Override checkpoint path (default: <output_dir>/checkpoint.json)"
  echo "  --trace_path PATH       Override trace path (default: <output_dir>/trace.jsonl)"
  echo "  --replay_trace PATH     Replay tool outputs from trace.jsonl (no real tool calls)"
  echo "  --no_dashboard          Do not start dashboard (script exits when agent finishes)"
  echo ""
  echo "Description:"
  echo " Agent to perform task based on workflow."
  echo " Reproducibility snapshots (config, workflow, env, git state, submodules) are created"
  echo " by the Python agent under <output_dir>/reproducibility/."
  exit 0
fi


SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

color() {
  # color <ansi_code> <text>
  #
  # By default, we try to colorize even when stdout isn't detected as a TTY
  # (some IDE terminals/proxies break `-t`), unless NO_COLOR is set.
  # Controls:
  # - CS_SCRIPT_COLOR=1  force enable
  # - CS_SCRIPT_COLOR=0  force disable
  # - NO_COLOR=1         disable (standard)
  local code="$1"; shift
  local mode="${CS_SCRIPT_COLOR:-auto}"
  local term="${TERM:-}"

  # Force-enable always wins.
  if [[ "$mode" == "1" ]]; then
    printf "\033[%sm%s\033[0m" "$code" "$*"
    return 0
  fi

  if [[ -n "${NO_COLOR:-}" || "$mode" == "0" || "$term" == "dumb" ]]; then
    printf "%s" "$*"
    return 0
  fi

  # Still emit ANSI by default; many terminals support it even if -t fails.
  printf "\033[%sm%s\033[0m" "$code" "$*"
}

log_info() { echo "$(color '36' '[info]') $*"; }   # cyan
log_ok()   { echo "$(color '32' '[ok]')   $*"; }  # green
log_warn() { echo "$(color '33' '[warn]') $*"; }  # yellow
log_err()  { echo "$(color '31' '[err]')  $*"; }  # red

workflow_path="./workflows/tool_test_workflow_creation"
workflow_env_path=""
OUTPUT_DIR=""
MCP_URL_OVERRIDE=""
RESUME_FLAG=""
CHECKPOINT_PATH=""
TRACE_PATH=""
REPLAY_TRACE=""
NO_DASHBOARD="false"
EXTRA_PY_ARGS=()

while [[ $# -gt 0 ]]; do
  case "$1" in
    --output_dir|--output-dir)
      OUTPUT_DIR="$2"
      shift 2
      ;;
    --mcp_url|--mcp-url)
      MCP_URL_OVERRIDE="$2"
      shift 2
      ;;
    --resume)
      RESUME_FLAG="--resume"
      shift
      ;;
    --checkpoint_path|--checkpoint-path)
      CHECKPOINT_PATH="$2"
      shift 2
      ;;
    --trace_path|--trace-path)
      TRACE_PATH="$2"
      shift 2
      ;;
    --replay_trace|--replay-trace)
      REPLAY_TRACE="$2"
      shift 2
      ;;
    --no_dashboard|--no-dashboard)
      NO_DASHBOARD="true"
      shift
      ;;
    --)
      shift
      while [[ $# -gt 0 ]]; do
        EXTRA_PY_ARGS+=("$1")
        shift
      done
      ;;
    -*)
      # Forward unknown flags to python. If your flag takes a value, prefer using:
      #   -- --flag value
      EXTRA_PY_ARGS+=("$1")
      shift
      ;;
    *)
      if [[ -z "$workflow_env_path" && "$workflow_path" == "./workflows/tool_test_workflow_creation" ]]; then
        workflow_path="$1"
      elif [[ -z "$workflow_env_path" ]]; then
        workflow_env_path="$1"
      else
        echo "Unexpected argument: $1"
        exit 1
      fi
      shift
      ;;
  esac
done

if [[ -z "$workflow_env_path" ]]; then
  workflow_env_path="$workflow_path"
fi

# Resolve plan file (prefer explicit extension, otherwise prefer YAML if present)
if [[ "$workflow_path" == *.yaml || "$workflow_path" == *.yml || "$workflow_path" == *.json ]]; then
  workflow_file="$workflow_path"
else
  if [[ -f ${workflow_path}.yaml ]]; then
    workflow_file=${workflow_path}.yaml
  elif [[ -f ${workflow_path}.yml ]]; then
    workflow_file=${workflow_path}.yml
  else
    workflow_file=${workflow_path}.json
  fi
fi

# Validate that workflow file exists otherwise exit
if [[ ! -f "$workflow_file" ]]; then
  echo "Error: Workflow file not found: $workflow_file"
  exit 1
fi

workflow_env_file=${workflow_env_path}.env
if [[ "$workflow_env_path" == "$workflow_path" ]]; then
  case "$workflow_file" in
    *.yaml|*.yml|*.json)
      workflow_env_file="${workflow_file%.*}.env"
      ;;
  esac
fi

### Initialize variables as empty (will be set from .env or left for YAML config fallback)
max_tokens_per_step=""
max_tool_calls_per_step=""
plan_revision_max_steps=""
openai_model=""

### Load environment files
set -a
# Only source workflow_env_file if it exists
if [[ -f "${workflow_env_file}" ]]; then
    log_info "Loading env: ${workflow_env_file}"
    source ${workflow_env_file}
else
    log_warn "No env file: ${workflow_env_file} (will use YAML config)"
fi
# Always load VM and host configs for API keys and paths
source config/vm.env
source config/host.env
set +a

log_info "Workflow: ${workflow_file}"

### MCP URL (prefer explicit MCP_URL env, else derive from vm.env)
if [[ -z "${MCP_URL:-}" ]]; then
  MCP_URL="http://localhost:${MCP_PORT}${MCP_BASEPATH}"
fi
log_info "MCP URL: ${MCP_URL}"

### Determine MCP URL (prefer CLI override; otherwise derive from vm.env)
mcp_url=""
if [[ -n "${MCP_URL_OVERRIDE}" ]]; then
  mcp_url="${MCP_URL_OVERRIDE}"
else
  if [[ -n "${MCP_PORT:-}" ]]; then
    basepath="${MCP_BASEPATH:-/mcp}"
    mcp_url="http://localhost:${MCP_PORT}${basepath}"
  fi
fi

TASK_NAME=""
if [[ "$workflow_file" == *.yaml || "$workflow_file" == *.yml ]]; then
  TASK_NAME=$(python - "$workflow_file" <<'PY' 2>/dev/null
import sys
import os
path = sys.argv[1]
name = ""
try:
    import yaml  # type: ignore
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    name = data.get("name", "") or ""
except Exception:
    pass
if not name:
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            if stripped.lower().startswith("name:"):
                name = stripped.split(":", 1)[1].strip().strip('"').strip("'")
                break
if name:
    name = os.path.expandvars(name)
print(name)
PY
  )
fi

if [[ -z "$TASK_NAME" ]]; then
  TASK_NAME=$(basename "$workflow_file")
  TASK_NAME="${TASK_NAME%.*}"
fi

if [[ -n "$OUTPUT_DIR" ]]; then
  LOG_DIR="$OUTPUT_DIR"
else
  DEFAULT_OUTPUT_ROOT="${WORKSPACE_PERSISTENT:-$PROJECT_ROOT/workspace_persistent}/outputs"
  LOG_DIR="$DEFAULT_OUTPUT_ROOT/$TASK_NAME"
fi
LOG_FILE="$LOG_DIR/agent_run.log"
EVENT_LOG_FILE="$LOG_DIR/agent_events.log"
mkdir -p "$LOG_DIR"

# On resume, keep existing logs so the dashboard can continue tailing them.
# The Python agent already appends to the existing event log on resume.
if [[ -z "$RESUME_FLAG" ]]; then
  # Don't silently destroy previous logs; rotate them with a timestamp suffix.
  timestamp="$(date +%Y%m%d-%H%M%S)"
  if [[ -f "$LOG_FILE" ]]; then
    mv "$LOG_FILE" "$LOG_DIR/agent_run-prev-${timestamp}.log" 2>/dev/null || true
  fi
  if [[ -f "$EVENT_LOG_FILE" ]]; then
    mv "$EVENT_LOG_FILE" "$LOG_DIR/agent_events-prev-${timestamp}.log" 2>/dev/null || true
  fi
fi

# Resolve absolute path so user can find outputs regardless of cwd
OUTPUT_DIR_ABS="$(cd "$LOG_DIR" 2>/dev/null && pwd)" || OUTPUT_DIR_ABS="$LOG_DIR"
log_info "Output directory: $OUTPUT_DIR_ABS"

cleanup_dashboard() {
  if [[ -n "${DASHBOARD_PID:-}" ]]; then
    if kill -0 "$DASHBOARD_PID" 2>/dev/null; then
      kill "$DASHBOARD_PID" 2>/dev/null || true
      wait "$DASHBOARD_PID" 2>/dev/null || true
    fi
  fi
}

ui_no_wait() {
  [[ "${CS_DASHBOARD_NO_WAIT:-}" == "1" || "${CS_DASHBOARD_NO_WAIT:-}" == "true" ]]
}

# In UI mode we don't want the dashboard to be killed when the agent exits,
# so users can inspect logs after completion. Still cleanup on explicit stop.
if ui_no_wait; then
  trap 'cleanup_dashboard; exit 130' INT
  trap 'cleanup_dashboard; exit 143' TERM
  trap ':' EXIT
else
  trap cleanup_dashboard EXIT INT TERM
fi

if [[ "$NO_DASHBOARD" != "true" ]]; then
  # UI runs: only one dashboard at a time. Kill previous dashboard(s) if any.
  UI_RUNS_DIR="$PROJECT_ROOT/outputs/_ui_runs"
  UI_DASHBOARD_PID_FILE="$UI_RUNS_DIR/.dashboard_pid"
  IS_UI_RUN=false
  if [[ "$workflow_file" == *"/_ui_runs/"* || "$workflow_file" == *"_ui_runs"* ]]; then
    IS_UI_RUN=true
    mkdir -p "$UI_RUNS_DIR"
    # Kill dashboard recorded in PID file (from previous UI run)
    if [[ -f "$UI_DASHBOARD_PID_FILE" ]]; then
      OLD_PID=$(cat "$UI_DASHBOARD_PID_FILE" 2>/dev/null)
      if [[ -n "$OLD_PID" ]] && kill -0 "$OLD_PID" 2>/dev/null; then
        log_info "Stopping previous dashboard (PID $OLD_PID)."
        kill "$OLD_PID" 2>/dev/null || true
        for _ in 1 2 3 4 5 6 7 8 9 10; do
          kill -0 "$OLD_PID" 2>/dev/null || break
          sleep 0.5
        done
        kill -9 "$OLD_PID" 2>/dev/null || true
      fi
      rm -f "$UI_DASHBOARD_PID_FILE"
    fi
    # Kill any other dashboard.py from this project (e.g. import-then-run leaves old one running)
    for pid in $(pgrep -f "dashboard.py" 2>/dev/null); do
      [[ -z "$pid" ]] && continue
      if [[ -f "/proc/$pid/cmdline" ]]; then
        cmd=$(tr '\0' ' ' <"/proc/$pid/cmdline" 2>/dev/null)
        if [[ "$cmd" == *"$SCRIPT_DIR/dashboard.py"* && "$cmd" == *"agent_events"* ]]; then
          kill "$pid" 2>/dev/null || true
          log_info "Stopping other dashboard (PID $pid)."
        fi
      fi
    done
    sleep 0.5
  fi

  # Find available port for dashboard
  DASHBOARD_PORT=5050
  if command -v ss &>/dev/null; then
    while ss -tlnH "sport = :$DASHBOARD_PORT" | grep -q .; do
      DASHBOARD_PORT=$((DASHBOARD_PORT + 1))
    done
  elif command -v lsof &>/dev/null; then
    while lsof -iTCP:"$DASHBOARD_PORT" -sTCP:LISTEN -P -n &>/dev/null; do
      DASHBOARD_PORT=$((DASHBOARD_PORT + 1))
    done
  fi

  # Silence dashboard's own logs; keep a local log file for debugging if needed.
  DASHBOARD_LOG_FILE="$LOG_DIR/dashboard.log"
  DASHBOARD_BROWSER_ARGS=()
  if [[ "${CS_DASHBOARD_NO_BROWSER:-}" == "1" || "${CS_DASHBOARD_NO_BROWSER:-}" == "true" ]]; then
    DASHBOARD_BROWSER_ARGS+=(--no-browser)
  fi
  if ui_no_wait; then
    nohup python "$SCRIPT_DIR/dashboard.py" "$EVENT_LOG_FILE" --port $DASHBOARD_PORT "${DASHBOARD_BROWSER_ARGS[@]}" --no-auto-close >"$DASHBOARD_LOG_FILE" 2>&1 &
  else
    python "$SCRIPT_DIR/dashboard.py" "$EVENT_LOG_FILE" --port $DASHBOARD_PORT "${DASHBOARD_BROWSER_ARGS[@]}" --no-auto-close >"$DASHBOARD_LOG_FILE" 2>&1 &
  fi
  DASHBOARD_PID=$!
  if [[ "$IS_UI_RUN" == "true" ]]; then
    echo "$DASHBOARD_PID" >"$UI_DASHBOARD_PID_FILE" 2>/dev/null || true
  fi
  sleep 1

  if ! kill -0 "$DASHBOARD_PID" 2>/dev/null; then
    log_err "Failed to start dashboard (see $DASHBOARD_LOG_FILE)"
    exit 1
  fi

  log_ok "Dashboard: http://127.0.0.1:$DASHBOARD_PORT"
fi

cd "$PROJECT_ROOT"

python -m harness.run \
    --workflow_file="${workflow_file}" \
    --mcp_url="${MCP_URL}" \
    ${max_tokens_per_step:+--max_tokens_per_step=${max_tokens_per_step}} \
    ${max_tool_calls_per_step:+--max_tool_calls_per_step=${max_tool_calls_per_step}} \
    ${plan_revision_max_steps:+--plan_revision_max_steps=${plan_revision_max_steps}} \
    ${openai_model:+--model=${openai_model}} \
    --output_dir="$LOG_DIR" \
    ${mcp_url:+--mcp_url="$mcp_url"} \
    ${CHECKPOINT_PATH:+--checkpoint_path="$CHECKPOINT_PATH"} \
    ${TRACE_PATH:+--trace_path="$TRACE_PATH"} \
    ${REPLAY_TRACE:+--replay_trace="$REPLAY_TRACE"} \
    ${RESUME_FLAG:+$RESUME_FLAG} \
    "${EXTRA_PY_ARGS[@]}"

if [[ "$NO_DASHBOARD" != "true" ]]; then
  echo ""
  log_info "Dashboard is still running. Press Ctrl+C to stop when done."
  if [[ "${CS_DASHBOARD_NO_WAIT:-}" == "1" || "${CS_DASHBOARD_NO_WAIT:-}" == "true" ]]; then
    log_info "CS_DASHBOARD_NO_WAIT is set; not waiting for dashboard."
  else
    wait "$DASHBOARD_PID"
  fi
fi
