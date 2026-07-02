set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

function usage {
  cat <<EOF
Usage: $0 {start|stop} [options]

Commands:
  start   Launch the sandbox container (detached)
  stop    Stop and remove the running sandbox container

Options for 'start':
  --profile <name>   Install tools after starting. Profiles: chemistry
                     Container will persist (no --rm) when using a profile.

Examples:
  $0 start                         # Base container only
  $0 start --profile chemistry     # Base + chemistry tools (ka_gat, ka_gnn)
  $0 stop
EOF
  exit 1
}

if [ $# -lt 1 ]; then
  usage
fi

ACTION="$1"
shift

PROFILE=""
while [ $# -gt 0 ]; do
  case "$1" in
    --profile)
      PROFILE="$2"
      shift 2
      ;;
    *)
      echo "Unknown option: $1"
      usage
      ;;
  esac
done

IMAGE="${IMAGE:-agentspex-sandbox:latest}"
CONTAINER_NAME="${CONTAINER_NAME:-sandbox}"

if grep -q '[[:space:]]$' config/vm.env 2>/dev/null; then
    echo "Cleaning trailing spaces in config/vm.env"
    sed -i '' 's/[[:space:]]*$//' config/vm.env 2>/dev/null || sed -i 's/[[:space:]]*$//' config/vm.env
fi

source config/vm.env
source config/host.env

# Forward all keys defined in .env into the container
API_KEY_ARGS=()
if [ -f .env ]; then
  while IFS= read -r line || [ -n "$line" ]; do
    # Skip comments and blank lines
    [[ "$line" =~ ^[[:space:]]*# ]] && continue
    [[ -z "${line// }" ]] && continue
    key="${line%%=*}"
    value="${line#*=}"
    if [ -n "$value" ]; then
      API_KEY_ARGS+=(-e "${key}=${value}")
    fi
  done < .env
fi

case "$ACTION" in
  start)
    echo "[$(date +%T)] Preparing workspace at $HOST_WORKSPACE"
    mkdir -p "$HOST_WORKSPACE"

    RM_FLAG=""
    if [ -z "$PROFILE" ]; then
      RM_FLAG="--rm"
    fi

    echo "[$(date +%T)] Launching container '$CONTAINER_NAME' from image '$IMAGE'"
    docker run -d --name "$CONTAINER_NAME" --hostname "$VM_HOSTNAME" $RM_FLAG \
      -v "$HOST_WORKSPACE":"$VM_WORKSPACE":rw \
      --env-file config/vm.env \
      "${API_KEY_ARGS[@]}" \
      -p ${MCP_PORT}:${MCP_PORT} \
      -p ${VNC_PORT}:${VNC_PORT} \
      "$IMAGE"

    echo "[$(date +%T)] Container ${CONTAINER_NAME} started (detached)."
    echo "VNC:  http://localhost:${VNC_PORT}/vnc_auto.html"
    echo "MCP:  http://localhost:${MCP_PORT}${MCP_BASEPATH}"

    if [ -n "$PROFILE" ]; then
      echo ""
      echo "[$(date +%T)] Installing tools for profile: $PROFILE"
      echo "This may take several minutes..."
      echo ""

      cat "$SCRIPT_DIR/setup_tools.sh" | docker exec -i -u root "$CONTAINER_NAME" bash -s "$PROFILE"

      echo ""
      echo "[$(date +%T)] Tools installed. Container will persist until 'stop' is called."
      echo "Note: Use '$0 stop' to stop. Container won't auto-remove."
    fi
    ;;
  stop)
    if docker inspect "$CONTAINER_NAME" &>/dev/null; then
      echo "[$(date +%T)] Stopping container '$CONTAINER_NAME'..."
      docker stop "$CONTAINER_NAME" &>/dev/null || true
      docker rm "$CONTAINER_NAME" &>/dev/null || true
      echo "[$(date +%T)] Container stopped and removed."
    else
      echo "[$(date +%T)] Container '$CONTAINER_NAME' is not running."
    fi
    ;;
  *)
    usage
    ;;
esac
