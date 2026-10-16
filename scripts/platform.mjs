import { spawn, spawnSync } from 'node:child_process'
import { existsSync, mkdirSync, openSync, closeSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import path from 'node:path'
const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const executable = process.platform === 'win32' ? '.venv/Scripts/python.exe' : '.venv/bin/python'
const python =
  process.env.PYTHON ||
  (existsSync(path.join(root, executable)) ? path.join(root, executable) : 'python')
const port = Number(process.env.PORT || 4173),
  base = `http://127.0.0.1:${port}`
const command = process.argv[2] || 'start'
function launch(args, background = false) {
  if (background && process.platform === 'win32') {
    const logDir = path.join(process.env.GOV_DATA_DIR || path.join(root, '.data-v3'), 'logs')
    // Start-Process creates an independent Windows process. Node's detached
    // child alone can still be reclaimed with its calling terminal/job.
    const startScript = `
$ErrorActionPreference = 'Stop'
New-Item -ItemType Directory -Path $env:GOV_START_LOGDIR -Force | Out-Null
$serviceStamp = Get-Date -Format 'yyyyMMdd-HHmmss-fff'
$serviceStdout = Join-Path $env:GOV_START_LOGDIR "service-$serviceStamp.stdout.log"
$serviceStderr = Join-Path $env:GOV_START_LOGDIR "service-$serviceStamp.stderr.log"
$serviceProcess = Start-Process -FilePath $env:GOV_START_PYTHON -ArgumentList '-m','api.serve' -WorkingDirectory $env:GOV_START_ROOT -WindowStyle Hidden -RedirectStandardOutput $serviceStdout -RedirectStandardError $serviceStderr -PassThru
@{pid=$serviceProcess.Id;stdout=$serviceStdout;stderr=$serviceStderr} | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $env:GOV_START_LOGDIR 'service-latest.json') -Encoding UTF8
`
    return spawn('powershell.exe', ['-NoProfile', '-NonInteractive', '-Command', startScript], {
      cwd: root,
      stdio: 'inherit',
      windowsHide: true,
      env: {
        ...process.env,
        PYTHONUTF8: '1',
        GOV_START_PYTHON: python,
        GOV_START_ROOT: root,
        GOV_START_LOGDIR: logDir,
      },
    })
  }
  const logFiles = []
  if (background) {
    const logDir = path.join(process.env.GOV_DATA_DIR || path.join(root, '.data-v3'), 'logs')
    mkdirSync(logDir, { recursive: true })
    logFiles.push(
      openSync(path.join(logDir, 'service.stdout.log'), 'a'),
      openSync(path.join(logDir, 'service.stderr.log'), 'a'),
    )
  }
  try {
    const child = spawn(python, args, {
      cwd: root,
      stdio: background ? ['ignore', ...logFiles] : 'inherit',
      detached: background,
      windowsHide: true,
      env: { ...process.env, PYTHONUTF8: '1' },
    })
    if (background) child.unref()
    return child
  } finally {
    for (const file of logFiles) closeSync(file)
  }
}
async function health() {
  try {
    return await fetch(base + '/api/health', { signal: AbortSignal.timeout(1200) }).then((r) =>
      r.json(),
    )
  } catch {
    return null
  }
}
function open() {
  if (!process.argv.includes('--no-open')) {
    if (process.platform === 'win32')
      spawn('cmd.exe', ['/d', '/c', 'start', '', base + '/home'], { windowsHide: true })
    else console.log('打开页面：' + base + '/home')
  }
}
if (command.startsWith('db:')) {
  const child = launch(['-m', 'api.database_cli', command.slice(3), ...process.argv.slice(3)])
  child.on('error', (e) => {
    console.error(e.message)
    process.exitCode = 1
  })
  child.on('exit', (code) => {
    process.exitCode = code || 0
  })
} else if (command === 'test' || command === 'dev') {
  const child = launch(
    command === 'test'
      ? ['-m', 'pytest', 'api/tests', '-q']
      : [
          '-m',
          'uvicorn',
          'api.main:app',
          '--host',
          '127.0.0.1',
          '--port',
          String(port),
          '--reload',
          '--loop',
          'api.loop:create_event_loop',
        ],
  )
  child.on('error', (e) => {
    console.error(e.message)
    process.exitCode = 1
  })
  child.on('exit', (code) => {
    process.exitCode = code || 0
  })
} else if (command === 'stop') {
  try {
    const info = await health()
    if (info?.data?.backend !== 'fastapi') throw Error('当前端口不是新版FastAPI服务')
    const session = await fetch(base + '/api/auth/local-session', {
      method: 'POST',
      headers: { Origin: base, 'Content-Type': 'application/json' },
      body: '{}',
    })
    if (!session.ok) throw Error('自动登录已关闭，请在服务终端按Ctrl+C停止')
    const cookie = session.headers.get('set-cookie').split(';')[0]
    const response = await fetch(base + '/api/governance/shutdown', {
      method: 'POST',
      headers: { Cookie: cookie, Origin: base, 'Content-Type': 'application/json' },
      body: '{}',
    })
    const result = await response.json()
    if (!response.ok) throw Error(result.message)
    console.log(result.message)
  } catch (e) {
    console.error(e.message)
    process.exitCode = 1
  }
} else {
  const info = await health()
  if (info?.data?.backend === 'fastapi') {
    console.log('新版平台已在运行：' + base + '/home')
    open()
  } else if (info) {
    console.error(`端口${port}已被其他服务占用，请先停止旧服务。`)
    process.exitCode = 1
  } else {
    const check = spawnSync(python, ['-c', 'import fastapi,uvicorn'], {
      cwd: root,
      windowsHide: true,
      stdio: 'ignore',
    })
    if (check.status !== 0) {
      console.error('请先创建Python环境并安装requirements.lock.txt中的依赖，详见README。')
      process.exitCode = 1
    } else {
      if (!existsSync(path.join(root, 'dist/index.html'))) {
        console.log('首次启动，正在构建Vue 3前端…')
        const args = [path.join(root, 'node_modules/vite/bin/vite.js'), 'build']
        const build = spawnSync(process.execPath, args, {
          cwd: root,
          stdio: 'inherit',
          windowsHide: true,
        })
        if (build.status !== 0) {
          process.exit(1)
        }
      }
      const background = process.argv.includes('--background')
      const child = launch(['-m', 'api.serve'], background)
      let failed = false
      child.on('error', (e) => {
        failed = true
        console.error(e.message)
        process.exitCode = 1
      })
      child.on('exit', (code) => {
        if (background && process.platform === 'win32' && code === 0) return
        failed = true
        process.exitCode = code || 0
      })
      for (let attempt = 0; attempt < 60 && !failed; attempt++) {
        const ready = await health()
        if (ready?.data?.backend === 'fastapi') {
          console.log(
            `Vue 3 + FastAPI已启动：${base}/home\n接口文档：${base}/docs\n数据库采集：支持8种常见数据库只读采集`,
          )
          if (background)
            console.log('服务在后台运行；使用“停止项目.cmd”停止。日志保存在数据目录的logs文件夹。')
          open()
          break
        }
        await new Promise((resolve) => setTimeout(resolve, 300))
        if (attempt === 59) {
          child.kill()
          console.error('服务启动超时，请检查Python依赖与端口。')
          process.exitCode = 1
        }
      }
    }
  }
}
