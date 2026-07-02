import { defineConfig, type Plugin } from 'vite'
import react from '@vitejs/plugin-react'
import type { IncomingMessage, ServerResponse } from 'node:http'
import { spawn, type ChildProcessWithoutNullStreams } from 'node:child_process'
import fs from 'node:fs'
import path from 'node:path'
import crypto from 'node:crypto'
import { fileURLToPath } from 'node:url'
import { Readable } from 'node:stream'
import net from 'node:net'

type RunState = 'starting' | 'running' | 'exited'

type RunInfo = {
  id: string
  createdAt: number
  startedAt?: number
  endedAt?: number
  exitCode?: number | null
  state: RunState
  planPath: string
  cmd: string
  proc?: ChildProcessWithoutNullStreams
  killTimer?: NodeJS.Timeout
  log: string
  subscribers: Set<ServerResponse>
  dashboardPort?: number
  dashboardPid?: number
}

function readBody(req: IncomingMessage, limitBytes = 2 * 1024 * 1024): Promise<string> {
  return new Promise((resolve, reject) => {
    let total = 0
    const chunks: Buffer[] = []
    req.on('data', (chunk: Buffer) => {
      total += chunk.length
      if (total > limitBytes) {
        reject(new Error('Request body too large'))
        req.destroy()
        return
      }
      chunks.push(chunk)
    })
    req.on('end', () => resolve(Buffer.concat(chunks).toString('utf8')))
    req.on('error', reject)
  })
}

function writeJson(res: ServerResponse, status: number, payload: unknown) {
  res.statusCode = status
  res.setHeader('Content-Type', 'application/json; charset=utf-8')
  res.end(JSON.stringify(payload))
}

function sseWrite(res: ServerResponse, event: string, data: unknown) {
  res.write(`event: ${event}\n`)
  res.write(`data: ${JSON.stringify(data)}\n\n`)
}

function runAgentApiPlugin(): Plugin {
  const runs = new Map<string, RunInfo>()
  const thisDir = path.dirname(fileURLToPath(import.meta.url))
  const DASHBOARD_PORT_RE = /Dashboard:\s*https?:\/\/127\.0\.0\.1:(\d+)/i

  function getProjectRoot() {
    // vite.config.ts lives in <repo>/yaml-flow-editor
    return path.resolve(thisDir, '..')
  }

  function dashboardProxyPath(run: RunInfo) {
    return run.dashboardPort ? `/api/dashboard/${run.id}/` : null
  }

  function runMetaPath(projectRoot: string, runId: string) {
    return path.join(projectRoot, 'outputs', '_ui_runs', `run_${runId}.meta.json`)
  }

  function writeRunMeta(projectRoot: string, run: RunInfo) {
    try {
      const p = runMetaPath(projectRoot, run.id)
      fs.mkdirSync(path.dirname(p), { recursive: true })
      fs.writeFileSync(
        p,
        JSON.stringify(
          {
            id: run.id,
            planPath: run.planPath,
            dashboardPort: run.dashboardPort ?? null,
            dashboardPid: run.dashboardPid ?? null,
            updatedAt: Date.now(),
          },
          null,
          2
        ),
        'utf8'
      )
    } catch {
      // best-effort
    }
  }

  function readRunMeta(projectRoot: string, runId: string): { dashboardPort?: number; dashboardPid?: number } | null {
    try {
      const p = runMetaPath(projectRoot, runId)
      if (!fs.existsSync(p)) return null
      const raw = fs.readFileSync(p, 'utf8')
      const j = JSON.parse(raw)
      const port = typeof j?.dashboardPort === 'number' ? j.dashboardPort : undefined
      const pid = typeof j?.dashboardPid === 'number' ? j.dashboardPid : undefined
      return { dashboardPort: port, dashboardPid: pid }
    } catch {
      return null
    }
  }

  function parseTaskNameFromYamlText(yamlText: string): string | null {
    // Very small heuristic: the editor always writes `name: ...` at the top.
    const m = yamlText.match(/^\s*name:\s*("?)([^\n"]+)\1\s*$/m)
    const name = m?.[2]?.trim()
    return name ? name : null
  }

  function toPosixRelative(fromDir: string, toPath: string): string {
    return path.relative(fromDir, toPath).split(path.sep).join('/')
  }

  function rewriteModuleRefsForUiRun(
    yamlText: string,
    currentFileDir: string,
    moduleTargetByOriginalPath: Map<string, string>,
  ): string {
    return yamlText.replace(
      /^(\s*module\s*:\s*)(?:(["'])([^"'\n]+)\2|([^#\n][^\n#]*?))(\s*(?:#.*)?)$/gm,
      (full, prefix: string, quoted: string | undefined, quotedPath: string | undefined, barePath: string | undefined, suffix: string | undefined) => {
        const originalPath = (quotedPath ?? barePath ?? '').trim()
        const targetPath = moduleTargetByOriginalPath.get(originalPath)
        if (!targetPath) return full
        const nextPath = toPosixRelative(currentFileDir, targetPath)
        if (quoted) return `${prefix}${quoted}${nextPath}${quoted}${suffix ?? ''}`
        return `${prefix}${nextPath}${suffix ?? ''}`
      }
    )
  }

  function eventLogPathForRun(projectRoot: string, run: RunInfo): string | null {
    try {
      const planText = fs.readFileSync(run.planPath, 'utf8')
      const taskName = parseTaskNameFromYamlText(planText)
      if (!taskName) return null
      return path.join(projectRoot, 'outputs', taskName, 'agent_events.log')
    } catch {
      return null
    }
  }

  function canListen(port: number, host = '127.0.0.1'): Promise<boolean> {
    return new Promise((resolve) => {
      const srv = net.createServer()
      srv.once('error', () => resolve(false))
      srv.listen(port, host, () => {
        srv.close(() => resolve(true))
      })
    })
  }

  async function pickFreePort(start = 5050, end = 5150): Promise<number> {
    for (let p = start; p <= end; p += 1) {
      // eslint-disable-next-line no-await-in-loop
      const ok = await canListen(p)
      if (ok) return p
    }
    throw new Error(`No free port found in range ${start}-${end}`)
  }

  async function isDashboardAlive(port: number): Promise<boolean> {
    try {
      const ctrl = new AbortController()
      const t = setTimeout(() => ctrl.abort(), 700)
      const res = await fetch(`http://127.0.0.1:${port}/api/state`, { signal: ctrl.signal })
      clearTimeout(t)
      return res.ok
    } catch {
      return false
    }
  }

  async function ensureDashboard(projectRoot: string, run: RunInfo): Promise<void> {
    // If we already have a port and it responds, keep it.
    if (run.dashboardPort && (await isDashboardAlive(run.dashboardPort))) return

    const eventLogPath = eventLogPathForRun(projectRoot, run)
    if (!eventLogPath) throw new Error('Unable to determine event log path for dashboard')

    const port = await pickFreePort()
    const dashScript = path.join(projectRoot, 'scripts', 'dashboard.py')
    const dashLogDir = path.dirname(eventLogPath)
    const dashLogFile = path.join(dashLogDir, `dashboard_ui_${run.id}.log`)

    const outFd = fs.openSync(dashLogFile, 'a')
    const child = spawn('python', [dashScript, eventLogPath, '--port', String(port), '--no-browser', '--no-auto-close'], {
      cwd: projectRoot,
      detached: true,
      stdio: ['ignore', outFd, outFd],
      env: {
        ...process.env,
        PYTHONUNBUFFERED: '1',
      },
    })
    child.unref()
    run.dashboardPort = port
    run.dashboardPid = child.pid ?? undefined
    writeRunMeta(projectRoot, run)

    // Wait briefly for it to come up.
    for (let i = 0; i < 50; i += 1) {
      // eslint-disable-next-line no-await-in-loop
      const ok = await isDashboardAlive(port)
      if (ok) return
      // eslint-disable-next-line no-await-in-loop
      await new Promise((r) => setTimeout(r, 200))
    }
    throw new Error('Dashboard failed to start')
  }

  function appendLog(run: RunInfo, stream: 'stdout' | 'stderr', chunk: string) {
    const prefix = stream === 'stderr' ? '[stderr] ' : ''
    const text = prefix + chunk
    run.log += text
    // cap memory usage (keep last ~200KB)
    if (run.log.length > 200_000) {
      run.log = run.log.slice(run.log.length - 200_000)
    }
    for (const sub of run.subscribers) {
      try {
        sseWrite(sub, 'log', { id: run.id, stream, chunk })
      } catch {
        // ignore broken pipes; cleanup happens on 'close'
      }
    }

    // UI input requests: detect sentinel lines emitted by the agent and broadcast as SSE.
    // Format: [ui-input-request]{...json...}
    try {
      const parts = text.split(/\r?\n/)
      for (const line of parts) {
        const m = line.match(/^\[ui-input-request\](\{.*\})\s*$/)
        if (!m) continue
        const payload = JSON.parse(m[1])
        for (const sub of run.subscribers) {
          try {
            sseWrite(sub, 'input_request', payload)
          } catch {
            // ignore
          }
        }
      }
    } catch {
      // ignore parse errors
    }

    // Discover dashboard port from run output (printed by scripts/run_agent.sh).
    // We proxy it through Vite so it works via port-forwarding / remote dev envs.
    if (!run.dashboardPort) {
      const m = text.match(DASHBOARD_PORT_RE)
      const port = m?.[1] ? Number(m[1]) : NaN
      if (Number.isFinite(port) && port > 0) {
        run.dashboardPort = port
        writeRunMeta(getProjectRoot(), run)
        broadcastStatus(run)
      }
    }
  }

  function broadcastStatus(run: RunInfo) {
    const payload = {
      id: run.id,
      state: run.state,
      startedAt: run.startedAt ?? null,
      endedAt: run.endedAt ?? null,
      exitCode: run.exitCode ?? null,
      planPath: run.planPath,
      cmd: run.cmd,
      dashboardUrl: dashboardProxyPath(run),
    }
    for (const sub of run.subscribers) {
      try {
        sseWrite(sub, 'status', payload)
      } catch {
        // ignore
      }
    }
  }

  async function proxyHttp(
    req: IncomingMessage,
    res: ServerResponse,
    targetUrl: string
  ): Promise<void> {
    const method = (req.method || 'GET').toUpperCase()
    const body =
      method === 'GET' || method === 'HEAD' ? undefined : await readBody(req, 20 * 1024 * 1024)

    // Drop hop-by-hop headers; keep the rest.
    const headers: Record<string, string> = {}
    for (const [k, v] of Object.entries(req.headers)) {
      if (!v) continue
      const key = k.toLowerCase()
      if (
        key === 'host' ||
        key === 'connection' ||
        key === 'upgrade' ||
        key === 'proxy-connection' ||
        key === 'keep-alive' ||
        key === 'transfer-encoding' ||
        key === 'content-length' ||
        key === 'te' ||
        key === 'trailer'
      ) {
        continue
      }
      if (Array.isArray(v)) headers[k] = v.join(', ')
      else headers[k] = String(v)
    }

    const upstream = await fetch(targetUrl, {
      method,
      headers,
      body,
      redirect: 'manual',
    })

    res.statusCode = upstream.status
    upstream.headers.forEach((value, key) => {
      const lk = key.toLowerCase()
      if (lk === 'transfer-encoding') return
      res.setHeader(key, value)
    })

    if (!upstream.body) {
      res.end()
      return
    }

    const nodeStream = Readable.fromWeb(upstream.body as any)
    await new Promise<void>((resolve) => {
      nodeStream.on('error', () => resolve())
      res.on('close', () => resolve())
      nodeStream.pipe(res)
      nodeStream.on('end', () => resolve())
    })
  }

  // Ensure that when the Vite dev server process exits (e.g. Ctrl+C),
  // we also best-effort stop any agent runs and dashboards it started.
  function installProcessExitHooks() {
    const projectRoot = getProjectRoot()
    const uiRunsDir = path.join(projectRoot, 'outputs', '_ui_runs')

    const cleanup = (signal: NodeJS.Signals | 'exit') => {
      // Stop all tracked runs (agent + dashboard processes).
      for (const run of runs.values()) {
        try {
          if (run.proc?.pid) {
            // Kill the whole process group for the agent.
            try {
              process.kill(-run.proc.pid, 'SIGTERM')
            } catch {
              try {
                run.proc.kill('SIGTERM')
              } catch {
                // ignore
              }
            }
          }
        } catch {
          // ignore
        }

        // Kill any dashboards we started and recorded a PID for.
        if (run.dashboardPid) {
          try {
            process.kill(run.dashboardPid, 'SIGTERM')
          } catch {
            // ignore (already gone)
          }
        }
      }

      // Also kill the "last UI dashboard" recorded in .dashboard_pid, if present.
      try {
        const pidFile = path.join(uiRunsDir, '.dashboard_pid')
        if (fs.existsSync(pidFile)) {
          const raw = fs.readFileSync(pidFile, 'utf8').trim()
          const pid = Number(raw)
          if (Number.isFinite(pid) && pid > 0) {
            try {
              process.kill(pid, 'SIGTERM')
            } catch {
              // ignore
            }
          }
        }
      } catch {
        // best-effort only
      }

      if (signal !== 'exit') {
        // Let default handlers run after cleanup.
        process.exit(0)
      }
    }

    // Avoid installing multiple handlers if Vite reloads config.
    if (!(globalThis as any).__YAML_FLOW_EDITOR_EXIT_HOOK_INSTALLED__) {
      ;(globalThis as any).__YAML_FLOW_EDITOR_EXIT_HOOK_INSTALLED__ = true
      process.on('SIGINT', () => cleanup('SIGINT'))
      process.on('SIGTERM', () => cleanup('SIGTERM'))
      process.on('exit', () => cleanup('exit'))
    }
  }

  // Install exit hooks immediately when plugin is created.
  installProcessExitHooks()

  return {
    name: 'yaml-flow-editor-run-agent-api',
    configureServer(server) {
      server.middlewares.use(async (req, res, next) => {
        try {
          if (!req.url) return next()

          const url = new URL(req.url, 'http://localhost')
          const isRunApi = url.pathname.startsWith('/api/run-agent')
          const isDashboardApi = url.pathname.startsWith('/api/dashboard/')
          if (!isRunApi && !isDashboardApi) return next()

          // CORS/preflight (mostly for safety; UI is same-origin)
          res.setHeader('Access-Control-Allow-Origin', '*')
          res.setHeader('Access-Control-Allow-Methods', 'GET,POST,OPTIONS')
          res.setHeader('Access-Control-Allow-Headers', 'Content-Type')
          if (req.method === 'OPTIONS') {
            res.statusCode = 204
            return res.end()
          }

          const projectRoot = getProjectRoot()

          // /api/dashboard/:id/*  -> proxy to local dashboard server
          {
            const m = url.pathname.match(/^\/api\/dashboard\/([^/]+)(\/.*)?$/)
            if (m) {
              const id = m[1]
              let run = runs.get(id)
              if (!run) {
                // Best-effort recovery for old runs after dev-server restart.
                const recoveredPlanPath = path.join(projectRoot, 'outputs', '_ui_runs', `run_${id}.yaml`)
                if (!fs.existsSync(recoveredPlanPath)) {
                  return writeJson(res, 404, { error: 'Run not found' })
                }
                run = {
                  id,
                  createdAt: Date.now(),
                  state: 'exited',
                  planPath: recoveredPlanPath,
                  cmd: '',
                  log: '',
                  subscribers: new Set(),
                }
                const meta = readRunMeta(projectRoot, id)
                if (meta?.dashboardPort) run.dashboardPort = meta.dashboardPort
                if (meta?.dashboardPid) run.dashboardPid = meta.dashboardPid
                runs.set(id, run)
              }

              // Backfill from disk if needed (survives page refreshes / reconnects).
              if (!run.dashboardPort) {
                const meta = readRunMeta(projectRoot, id)
                if (meta?.dashboardPort) run.dashboardPort = meta.dashboardPort
                if (meta?.dashboardPid) run.dashboardPid = meta.dashboardPid
              }

              // If the dashboard process is gone (port dead), restart it on demand.
              try {
                await ensureDashboard(projectRoot, run)
              } catch (e: any) {
                return writeJson(res, 500, { error: String(e?.message || e) })
              }

              const restPath = m[2] && m[2] !== '' ? m[2] : '/'
              const targetUrl = `http://127.0.0.1:${run.dashboardPort}${restPath}${url.search}`
              try {
                await proxyHttp(req, res, targetUrl)
              } catch (e) {
                // One retry after ensuring dashboard (handles races).
                try {
                  await ensureDashboard(projectRoot, run)
                  const retryUrl = `http://127.0.0.1:${run.dashboardPort}${restPath}${url.search}`
                  await proxyHttp(req, res, retryUrl)
                } catch (err: any) {
                  return writeJson(res, 500, { error: String(err?.message || err) })
                }
              }
              return
            }
          }

          // POST /api/run-agent  { yaml: string, args?: string[], dashboard?: boolean }
          if (req.method === 'POST' && url.pathname === '/api/run-agent') {
            const raw = await readBody(req)
            let body: any
            try {
              body = raw ? JSON.parse(raw) : {}
            } catch {
              return writeJson(res, 400, { error: 'Invalid JSON body' })
            }

            let yamlContent = typeof body?.yaml === 'string' ? body.yaml : ''
            const extraArgs = Array.isArray(body?.args) ? body.args.filter((x: any) => typeof x === 'string') : []
            const dashboard = body?.dashboard === true
            const modules = body?.modules && typeof body.modules === 'object' ? body.modules as Record<string, string> : null
            if (!yamlContent.trim()) {
              return writeJson(res, 400, { error: 'Missing yaml' })
            }

            const id = crypto.randomBytes(8).toString('hex')
            const uiRunsDir = path.join(projectRoot, 'outputs', '_ui_runs')
            fs.mkdirSync(uiRunsDir, { recursive: true })

            if (modules && Object.keys(modules).length > 0) {
              const runModulesDir = path.join(uiRunsDir, `run_${id}_modules`)
              fs.mkdirSync(runModulesDir, { recursive: true })

              const moduleTargetByOriginalPath = new Map<string, string>()
              for (const relPath of Object.keys(modules)) {
                moduleTargetByOriginalPath.set(relPath, path.join(runModulesDir, relPath))
              }

              yamlContent = rewriteModuleRefsForUiRun(
                yamlContent,
                uiRunsDir,
                moduleTargetByOriginalPath,
              )

              for (const [relPath, content] of Object.entries(modules)) {
                if (typeof content !== 'string') continue
                const targetFile = moduleTargetByOriginalPath.get(relPath)!
                fs.mkdirSync(path.dirname(targetFile), { recursive: true })
                const rewrittenContent = rewriteModuleRefsForUiRun(
                  content,
                  path.dirname(targetFile),
                  moduleTargetByOriginalPath,
                )
                fs.writeFileSync(targetFile, rewrittenContent, 'utf8')
              }
            }

            const planPath = path.join(uiRunsDir, `run_${id}.yaml`)
            fs.writeFileSync(planPath, yamlContent, 'utf8')

            const scriptPath = path.join(projectRoot, 'scripts', 'run_agent.sh')
            const cmd = `bash "${scriptPath}" "${planPath}"${dashboard ? '' : ' --no_dashboard'}${extraArgs.length ? ' ' + extraArgs.join(' ') : ''}`

            const run: RunInfo = {
              id,
              createdAt: Date.now(),
              startedAt: Date.now(),
              state: 'starting',
              planPath,
              cmd,
              log: '',
              subscribers: new Set(),
            }
            runs.set(id, run)

            // Spawn: bash ./scripts/run_agent.sh <planPath> [--no_dashboard] [<extra args>]
            const spawnArgs = [scriptPath, planPath, ...(dashboard ? [] : ['--no_dashboard']), ...extraArgs]
            const inputDir = path.join(uiRunsDir, `run_${id}_input`)
            const child = spawn('bash', spawnArgs, {
              cwd: projectRoot,
              // Start a new process group so we can stop the whole tree.
              detached: true,
              env: {
                ...process.env,
                // Make python output line-buffered where possible
                PYTHONUNBUFFERED: '1',
                // Force colored output even without a TTY (pipes)
                FORCE_COLOR: '1',
                CLICOLOR: '1',
                TERM: process.env.TERM || 'xterm-256color',
                COLORTERM: process.env.COLORTERM || 'truecolor',
                RICH_FORCE_TERMINAL: '1',
                // Allow agent input steps to request input via the UI.
                CS_UI_RUN_ID: id,
                CS_UI_INPUT_DIR: inputDir,
                ...(dashboard ? { CS_DASHBOARD_NO_BROWSER: '1', CS_DASHBOARD_NO_WAIT: '1' } : {}),
              },
            })
            run.proc = child
            run.state = 'running'
            appendLog(run, 'stdout', `Starting: ${cmd}\n\n`)
            broadcastStatus(run)

            child.stdout.setEncoding('utf8')
            child.stderr.setEncoding('utf8')
            child.stdout.on('data', (d: string) => appendLog(run, 'stdout', d))
            child.stderr.on('data', (d: string) => appendLog(run, 'stderr', d))
            child.on('close', (code) => {
              run.state = 'exited'
              run.endedAt = Date.now()
              run.exitCode = code
              if (run.killTimer) {
                clearTimeout(run.killTimer)
                run.killTimer = undefined
              }
              appendLog(run, 'stdout', `\n\nProcess exited with code ${code}\n`)
              broadcastStatus(run)
            })

            return writeJson(res, 200, { id, planPath })
          }

          // POST /api/run-agent/:id/stop
          {
            const m = url.pathname.match(/^\/api\/run-agent\/([^/]+)\/stop$/)
            if (req.method === 'POST' && m) {
              const id = m[1]
              const run = runs.get(id)
              if (!run) return writeJson(res, 404, { error: 'Run not found' })
              if (!run.proc || run.state !== 'running') return writeJson(res, 200, { id, state: run.state })
              try {
                const pid = run.proc.pid
                if (!pid) {
                  run.proc.kill('SIGTERM')
                  appendLog(run, 'stdout', '\n[ui] Sent SIGTERM\n')
                } else {
                  // Kill the whole process group (negative PID).
                  process.kill(-pid, 'SIGTERM')
                  appendLog(run, 'stdout', `\n[ui] Sent SIGTERM to process group ${pid}\n`)
                  // Escalate to SIGKILL if it doesn't exit soon.
                  if (!run.killTimer) {
                    run.killTimer = setTimeout(() => {
                      try {
                        process.kill(-pid, 'SIGKILL')
                        appendLog(run, 'stderr', `\n[ui] Sent SIGKILL to process group ${pid}\n`)
                      } catch {
                        // ignore
                      }
                    }, 5000)
                  }
                }
              } catch (e: any) {
                appendLog(run, 'stderr', `\n[ui] Failed to stop: ${String(e?.message || e)}\n`)
              }
              return writeJson(res, 200, { id, state: run.state })
            }
          }

          // POST /api/run-agent/:id/input  { stepId: string, value: string }
          // Writes response_<stepId>.txt under outputs/_ui_runs/run_<id>_input/
          {
            const m = url.pathname.match(/^\/api\/run-agent\/([^/]+)\/input$/)
            if (req.method === 'POST' && m) {
              const id = m[1]
              const run = runs.get(id)
              if (!run) return writeJson(res, 404, { error: 'Run not found' })
              const raw = await readBody(req)
              let body: any
              try {
                body = raw ? JSON.parse(raw) : {}
              } catch {
                return writeJson(res, 400, { error: 'Invalid JSON body' })
              }
              const stepId = typeof body?.stepId === 'string' ? body.stepId : ''
              const value = typeof body?.value === 'string' ? body.value : ''
              if (!stepId) return writeJson(res, 400, { error: 'Missing stepId' })

              const uiRunsDir = path.join(projectRoot, 'outputs', '_ui_runs')
              const inputDir = path.join(uiRunsDir, `run_${id}_input`)
              try {
                fs.mkdirSync(inputDir, { recursive: true })
                fs.writeFileSync(path.join(inputDir, `response_${stepId}.txt`), value + '\n', 'utf8')
              } catch (e: any) {
                return writeJson(res, 500, { error: String(e?.message || e) })
              }
              appendLog(run, 'stdout', `\n[ui] Sent input for step ${stepId}\n`)
              return writeJson(res, 200, { ok: true })
            }
          }

          // GET /api/run-agent/:id (status)
          {
            const m = url.pathname.match(/^\/api\/run-agent\/([^/]+)$/)
            if (req.method === 'GET' && m) {
              const id = m[1]
              let run = runs.get(id)
              if (!run) {
                // Best-effort recovery for old runs after dev-server restart.
                const recoveredPlanPath = path.join(projectRoot, 'outputs', '_ui_runs', `run_${id}.yaml`)
                if (!fs.existsSync(recoveredPlanPath)) {
                  return writeJson(res, 404, { error: 'Run not found' })
                }
                run = {
                  id,
                  createdAt: Date.now(),
                  state: 'exited',
                  planPath: recoveredPlanPath,
                  cmd: '',
                  log: '',
                  subscribers: new Set(),
                }
                const meta = readRunMeta(projectRoot, id)
                if (meta?.dashboardPort) run.dashboardPort = meta.dashboardPort
                if (meta?.dashboardPid) run.dashboardPid = meta.dashboardPid
                runs.set(id, run)
              }
              return writeJson(res, 200, {
                id: run.id,
                state: run.state,
                createdAt: run.createdAt,
                startedAt: run.startedAt ?? null,
                endedAt: run.endedAt ?? null,
                exitCode: run.exitCode ?? null,
                planPath: run.planPath,
                cmd: run.cmd,
                dashboardUrl: dashboardProxyPath(run),
              })
            }
          }

          // GET /api/run-agent/:id/stream (SSE)
          {
            const m = url.pathname.match(/^\/api\/run-agent\/([^/]+)\/stream$/)
            if (req.method === 'GET' && m) {
              const id = m[1]
              const run = runs.get(id)
              if (!run) {
                res.statusCode = 404
                return res.end('Run not found')
              }

              res.statusCode = 200
              res.setHeader('Content-Type', 'text/event-stream; charset=utf-8')
              res.setHeader('Cache-Control', 'no-cache, no-transform')
              res.setHeader('Connection', 'keep-alive')
              if (typeof res.flushHeaders === 'function') res.flushHeaders()

              run.subscribers.add(res)
              // send current state + backlog
              sseWrite(res, 'status', {
                id: run.id,
                state: run.state,
                startedAt: run.startedAt ?? null,
                endedAt: run.endedAt ?? null,
                exitCode: run.exitCode ?? null,
                planPath: run.planPath,
                cmd: run.cmd,
                dashboardUrl: dashboardProxyPath(run),
              })
              if (run.log) {
                sseWrite(res, 'log', { id: run.id, stream: 'stdout', chunk: run.log })
              }

              req.on('close', () => {
                run.subscribers.delete(res)
                try {
                  res.end()
                } catch {
                  // ignore
                }
              })
              return
            }
          }

          return writeJson(res, 404, { error: 'Not found' })
        } catch (err: any) {
          return writeJson(res, 500, { error: String(err?.message || err) })
        }
      })
    },
  }
}

export default defineConfig({
  plugins: [react(), runAgentApiPlugin()],
  server: {
    port: 3000,
    host: true
  }
})
