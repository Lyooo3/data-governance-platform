import { spawn } from "node:child_process";
import path from "node:path";
import { fileURLToPath } from "node:url";

const projectDir = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const port = Number(process.env.PORT || 4173);
const url = `http://127.0.0.1:${port}/workbench`;
const [major,minor] = process.versions.node.split('.').map(Number);
if (major < 22 || major === 22 && minor < 14) { console.error('需要Node.js 22.14或以上版本。'); process.exit(1); }

async function probe() {
  try {
    const response = await fetch(`http://127.0.0.1:${port}/api/health`, { signal: AbortSignal.timeout(1000) });
    const data = await response.json();
    return response.ok && data.data?.mode === 'live' ? 'replica' : 'occupied';
  } catch {
    return "offline";
  }
}

function openBrowser() {
  if (process.argv.includes("--no-open")) return;
  if (process.platform !== "win32") {
    console.log(`请在浏览器打开：${url}`);
    return;
  }
  const browser = spawn("cmd.exe", ["/d", "/c", "start", "", url], { windowsHide: true });
  browser.on("error", () => console.log(`请在浏览器打开：${url}`));
}

const state = await probe();
if (state === "occupied") {
  console.error(`端口 ${port} 已被其他服务占用，请更换 PORT 后重试。`);
  process.exitCode = 1;
} else if (state === "replica") {
  console.log(`项目已在运行：${url}`);
  openBrowser();
} else {
  const server = spawn(process.execPath, [path.join(projectDir, "server.mjs")], {
    cwd: projectDir,
    stdio: "inherit",
    env: process.env,
  });
  let stopped = false;
  server.on("error", (error) => {
    stopped = true;
    console.error(`启动失败：${error.message}`);
    process.exitCode = 1;
  });
  server.on("exit", (code) => {
    stopped = true;
    process.exitCode = code || 0;
  });
  let ready = false;
  for (let attempt = 0; attempt < 40 && !stopped; attempt++) {
    if (await probe() === "replica") {
      ready = true;
      openBrowser();
      break;
    }
    await new Promise((resolve) => setTimeout(resolve, 250));
  }
  if (!ready && !stopped) {
    console.error("服务未能就绪，请检查上方错误信息。");
    server.kill();
    process.exitCode = 1;
  }
}
