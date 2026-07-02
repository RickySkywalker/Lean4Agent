# AgentSPEX: An Agent SPecification and EXecution Language

A declarative workflow language for LLM-agent pipelines with explicit control flow, modular structure, and a customizable execution harness.

See the [Workflow Language Guide](docs/workflow-language.md) for full syntax, step types, and examples.

## Quick start

### 1. Install dependencies

Using `uv`:
```bash
uv venv --python 3.11
source .venv/bin/activate
uv pip install -r requirements.txt
uv pip install -e .
```

Using `conda`:
```bash
conda create -n AgentSPEX_env python=3.11
conda activate AgentSPEX_env
pip install -r requirements.txt
pip install -e .
```

### 2. Set up API keys

```bash
cp example.env .env
```

### 3. Quickstart

Run:
```bash
agentspex
```

Arrow-key navigation lets you run workflows, write task plans, browse docs, manage integrations, and control the sandbox VM — all without remembering CLI flags.

Or run directly:

```bash
agentspex run workflows/quickstart.yaml
agentspex run workflows/quickstart.yaml --model claude-opus-4-6
agentspex run --help
```

Each `agentspex run` spins up an isolated container for the duration of the workflow and tears it down on exit.

For repeated runs or a **persistent VM**:

```bash
docker build -t agentspex-sandbox:latest -f config/Dockerfile .
cp config/vm.env.example config/vm.env       # container-side: ports, MCP, VNC
cp config/host.env.example config/host.env   # host-side: workspace paths
bash ./scripts/run_vm.sh start
# wait until the MCP server is ready (prints 406; takes ~10-30 s after start)
curl -s -o /dev/null -w '%{http_code}\n' http://localhost:7002/mcp
source .env   # the credentials file created in Step 2
bash ./scripts/run_agent.sh workflows/quickstart.yaml
```

Default VNC and MCP endpoints are printed on start. Stop with `bash ./scripts/run_vm.sh stop`. If the agent fails to connect, see [Troubleshooting the persistent VM](#troubleshooting-the-persistent-vm).

## Writing workflows

Workflows are YAML files that define a sequence of steps. A minimal example:

```yaml
name: "hello_world"
goal: "A simple task to demonstrate the basics"

workflow:
  - step:
      name: "greet"
      instruction: "Say hello in a friendly way"
```

Workflows support parameters, template variables, loops, conditionals, parallel execution, sub-workflows, and more. See the [Workflow Language Guide](docs/workflow-language.md) for the complete reference. Example workflows are in `workflows/`.

## Options

### Custom output directory

```bash
agentspex run workflows/quickstart.yaml --output_dir /path/to/output
# or with the persistent VM:
bash ./scripts/run_agent.sh workflows/quickstart.yaml --output_dir /path/to/output
```

### Resume from checkpoint

```bash
agentspex run workflows/quickstart.yaml --resume
```

### Replay from trace (no real tool calls)

```bash
bash ./scripts/run_agent.sh workflows/quickstart.yaml --replay_trace /path/to/trace.jsonl
```

## Live dashboard

The agent streams structured events to a live dashboard that opens automatically when using `run_agent.sh`. To open it manually against any event log:

```bash
python scripts/dashboard.py /path/to/agent_events.log
```

Options: `--port 5050`, `--host 127.0.0.1`, `--no-browser`, `--no-auto-close`.

## Sandbox VM

The sandbox VM provides the tools that workflows interact with. Source code is in `src/sandbox_vm/`.

### Adding custom tools

1. Add tool functions under `src/sandbox_vm/tools/`
2. Register in `src/sandbox_vm/tools/mcp_server_tool_config.yaml`
3. Public functions (not `_`-prefixed) are auto-registered as MCP tools

### Environment variables

Copy `config/vm.env.example` → `config/vm.env` (container-side: ports, MCP/VNC) and `config/host.env.example` → `config/host.env` (host-side paths). `$HOST_WORKSPACE` (set in `host.env`) is mounted at `$VM_WORKSPACE` inside the VM.

### Troubleshooting the persistent VM

**`run_vm.sh start` prints success but `run_agent.sh` fails with `httpx.ConnectError: All connection attempts failed`.**
`docker run -d` returns as soon as the container is *created* — it does not mean the sandbox survived startup. Without `--profile` the container runs with `--rm`, so a crashed sandbox is removed immediately and leaves no trace in `docker ps -a`. To capture the crash, start a throwaway copy without `--rm` and read its logs:

```bash
docker run -d --name sandbox-debug -v "$(pwd)/workspace:/workspace:rw" \
  --env-file config/vm.env agentspex-sandbox:latest
docker logs -f sandbox-debug   # afterwards: docker rm -f sandbox-debug
```

Known causes:

- `mkdir: cannot create directory '/workspace/logs': Permission denied` (container exits within a second) — the container user cannot write the bind-mounted workspace. The image pins `agent` to UID 1000 (`config/Dockerfile`) to match the usual host user; if your host user has a different UID, run `chmod -R a+rwX workspace`.
- `ImportError: cannot import name ... from 'fastmcp...'` (container stays up but port 7002 never answers) — mixed fastmcp installation. The fastmcp version must be pinned to the **same** release in `config/Dockerfile` and `src/sandbox_vm/requirements.txt`; if they diverge, pip leaves files from two releases in one package directory. Keep both at `fastmcp==2.12.2` and rebuild.

**Restarting:** use `run_vm.sh stop` then `start`, never `docker restart` — the entrypoint is not restart-safe (a stale `/tmp/.X100-lock` makes Xvfb fail with `[ERROR] Xvfb not ready`).

## Project structure

```
workflows/           Workflow definitions (YAML)
src/harness/         Workflow execution engine
src/sandbox_vm/      Sandbox VM and MCP server
src/mcp_client/      MCP client library
docs/                Documentation
scripts/             Shell scripts and dashboard
config/              Environment and Docker configuration
```
