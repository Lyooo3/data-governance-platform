import { createHash } from "node:crypto";
import { mkdir, readdir, readFile, rm, stat, writeFile } from "node:fs/promises";
import path from "node:path";
import process from "node:process";

const workspace = process.cwd();
const inputArgument = process.argv[2] || "数据治理";
const inputPath = path.resolve(workspace, inputArgument);
const publicDir = path.join(workspace, "public");
const mockDir = path.join(workspace, "mock");
const bodyDir = path.join(mockDir, "bodies");
const localReplayPort = Number(process.env.PORT || 4173);
const localWebSocketUrl = `ws://127.0.0.1:${localReplayPort}`;

function assertInsideWorkspace(target, label) {
  const relative = path.relative(workspace, target);
  if (relative.startsWith("..") || path.isAbsolute(relative)) {
    throw new Error(`${label}不在工作区内：${target}`);
  }
}

function findHeader(headers = [], name) {
  const item = headers.find((header) => header.name?.toLowerCase() === name.toLowerCase());
  return item?.value || "";
}

function responseBody(content = {}) {
  if (typeof content.text !== "string") return null;
  return content.encoding === "base64"
    ? Buffer.from(content.text, "base64")
    : Buffer.from(content.text, "utf8");
}

function requestBody(request = {}) {
  const postData = request.postData;
  if (!postData) return Buffer.alloc(0);
  if (typeof postData.text === "string") {
    return postData.encoding === "base64"
      ? Buffer.from(postData.text, "base64")
      : Buffer.from(postData.text, "utf8");
  }
  if (Array.isArray(postData.params)) {
    return Buffer.from(
      new URLSearchParams(postData.params.map((item) => [item.name || "", item.value || ""])).toString(),
      "utf8"
    );
  }
  return Buffer.alloc(0);
}

function bodyHash(body) {
  if (!body?.length) return "";
  return createHash("sha256").update(body).digest("hex");
}

function queryPairs(url) {
  return [...url.searchParams.entries()].sort(([ak, av], [bk, bv]) =>
    `${ak}=${av}`.localeCompare(`${bk}=${bv}`)
  );
}

function safeRelativePath(urlPath) {
  const normalized = path.posix.normalize(urlPath || "/");
  if (!normalized.startsWith("/")) return null;
  return normalized === "/" ? "/" : normalized;
}

function isConfigResource(urlPath) {
  return path.posix.basename(urlPath).toLowerCase() === "configout.js";
}

function rewriteTextResource(urlPath, contentType, body) {
  const type = String(contentType).toLowerCase();
  if (!type.includes("text") && !type.includes("javascript") && !type.includes("css") && !type.includes("json")) return body;

  let text = body.toString("utf8");
  text = text
    .replace(/https?:\/\/(?:\d{1,3}\.){3}\d{1,3}(?::\d+)?/g, "")
    .replace(/wss?:\/\/(?:\d{1,3}\.){3}\d{1,3}(?::\d+)?/g, localWebSocketUrl);

  if (isConfigResource(urlPath)) {
    text = text
      .replace(/webSocketUrl\s*:\s*['"][^'"]*['"]/g, `webSocketUrl: '${localWebSocketUrl}'`)
      // 本地回放没有真实登录页。置空后，原系统的登录兜底不会把当前
      // /home 与已有 jumpOrigin/jumpHash 反复拼接成无限增长的 URL。
      .replace(/loginPath\s*:\s*['"][^'"]*['"]/g, "loginPath: ''");
  }
  return Buffer.from(text, "utf8");
}

function bootstrapHtml(html) {
  const bootstrap = `
  <script>
    window.__LOCAL_HAR_REPLICA__ = true;
    document.cookie = "token=offline-har-replay; Path=/; SameSite=Lax";
    document.cookie = "user=%7B%7D; Path=/; SameSite=Lax";
    try {
      localStorage.setItem("token", "offline-har-replay");
      localStorage.setItem("user", "{}");
    } catch (_) {}
    window.addEventListener("error", function (event) {
      if (event && event.message && /WebSocket|CrossStorage/i.test(event.message)) event.preventDefault();
    });
  </script>`;
  return html.includes("</head>") ? html.replace("</head>", `${bootstrap}\n</head>`) : `${bootstrap}\n${html}`;
}

function syntheticMicroAppHtml({ appName, title, description }) {
  const escapedName = JSON.stringify(appName);
  const escapedTitle = JSON.stringify(title);
  const escapedDescription = JSON.stringify(description);
  return `<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>${title}</title>
  <style>
    :root { color-scheme: light; font-family: -apple-system,BlinkMacSystemFont,"Segoe UI","Microsoft YaHei",sans-serif; }
    body { margin: 0; background: #f5f7fa; color: #1f2937; }
    .har-placeholder { max-width: 920px; margin: 48px auto; padding: 28px 32px; background: #fff; border: 1px solid #e5e7eb; border-radius: 10px; box-shadow: 0 8px 24px rgba(15,23,42,.06); }
    .har-placeholder h1 { margin: 0 0 12px; font-size: 24px; }
    .har-placeholder p { margin: 8px 0; line-height: 1.7; color: #4b5563; }
    .har-placeholder code { padding: 2px 6px; border-radius: 4px; background: #f3f4f6; color: #374151; }
    .har-placeholder .tag { display: inline-block; margin-top: 12px; padding: 4px 10px; border-radius: 999px; background: #e8f3ff; color: #1677ff; font-size: 13px; }
  </style>
</head>
<body>
  <div id="har-replica-root"></div>
  <script>
    (function () {
      var appName = ${escapedName};
      var appTitle = ${escapedTitle};
      var appDescription = ${escapedDescription};
      function getRoot(props) {
        if (props && props.container && props.container.nodeType === 1) return props.container;
        return document.getElementById("har-replica-root");
      }
      function mountApp(props) {
        var root = getRoot(props);
        if (!root) return;
        root.innerHTML = "<section class='har-placeholder'><span class='tag'>本地 HAR 回放</span><h1>" + appTitle + "</h1><p>" + appDescription + "</p><p>入口页面正文未包含在当前 HAR 中，已提供 qiankun 兼容入口，避免主应用因 404 中断。</p><p>应用标识：<code>" + appName + "</code></p></section>";
      }
      window[appName] = {
        bootstrap: function () { return Promise.resolve(); },
        mount: function (props) { mountApp(props); return Promise.resolve(); },
        unmount: function (props) {
          var root = getRoot(props);
          if (root) root.innerHTML = "";
          return Promise.resolve();
        }
      };
    })();
  </script>
</body>
</html>`;
}

async function discoverHarFiles(target) {
  const info = await stat(target);
  if (info.isFile()) return [target];
  if (!info.isDirectory()) throw new Error(`输入路径不是文件或目录：${target}`);
  return (await readdir(target))
    .filter((name) => name.toLowerCase().endsWith(".har"))
    .sort((a, b) => a.localeCompare(b, "zh-CN"))
    .map((name) => path.join(target, name));
}

assertInsideWorkspace(inputPath, "HAR输入路径");
assertInsideWorkspace(mockDir, "模拟响应目录");
assertInsideWorkspace(publicDir, "公共入口目录");

const harFiles = await discoverHarFiles(inputPath);
if (!harFiles.length) throw new Error(`输入目录没有 HAR 文件：${inputPath}`);

await rm(mockDir, { recursive: true, force: true });
await mkdir(bodyDir, { recursive: true });
await mkdir(publicDir, { recursive: true });

const manifest = {
  version: 2,
  source: path.relative(workspace, inputPath),
  generatedAt: new Date().toISOString(),
  mode: "multi-har-raw-response-replay",
  sourceFiles: [],
  skippedFiles: [],
  fallbackDocument: null,
  staticEntries: [],
  apiEntries: [],
  websocketEntries: [],
  missingBodies: []
};

let bodyIndex = 0;
const staticByKey = new Map();
const seenApiBodies = new Set();

for (const file of harFiles) {
  const relativeFile = path.relative(workspace, file);
  let har;
  try {
    har = JSON.parse(await readFile(file, "utf8"));
  } catch (error) {
    manifest.skippedFiles.push({ file: relativeFile, reason: String(error.message || error) });
    console.warn(`跳过无法解析的 HAR：${relativeFile}；${error.message || error}`);
    continue;
  }

  const entries = Array.isArray(har?.log?.entries) ? har.log.entries : [];
  manifest.sourceFiles.push({ file: relativeFile, entries: entries.length });
  for (const entry of entries) {
    let requestUrl;
    try {
      requestUrl = new URL(entry.request.url);
    } catch {
      continue;
    }

    const method = String(entry.request?.method || "GET").toUpperCase();
    const content = entry.response?.content || {};
    const body = responseBody(content);
    const isWebSocket = requestUrl.protocol === "ws:" || requestUrl.protocol === "wss:" || entry._resourceType === "websocket";
    if (isWebSocket) {
      manifest.websocketEntries.push({
        source: relativeFile,
        method,
        url: entry.request.url,
        status: Number(entry.response?.status || 0)
      });
      continue;
    }

    const relativePath = safeRelativePath(requestUrl.pathname);
    if (!relativePath) continue;
    const status = Number(entry.response?.status || 0);
    const contentType = content.mimeType || findHeader(entry.response?.headers, "content-type") || "application/octet-stream";
    if (!body || status <= 0) {
      manifest.missingBodies.push({ source: relativeFile, method, path: relativePath, status, contentType });
      continue;
    }

    let capturedBody = rewriteTextResource(relativePath, contentType, body);
    if (entry._resourceType === "document" || String(contentType).toLowerCase().includes("text/html")) {
      capturedBody = Buffer.from(bootstrapHtml(capturedBody.toString("utf8")), "utf8");
    }

    const bodyName = `${String(bodyIndex++).padStart(6, "0")}.bin`;
    const bodyFile = path.posix.join("bodies", bodyName);
    await writeFile(path.join(bodyDir, bodyName), capturedBody);
    const query = queryPairs(requestUrl);
    const baseEntry = {
      source: relativeFile,
      method,
      path: relativePath,
      query,
      status,
      contentType,
      bodyFile,
      bodyBytes: capturedBody.length
    };

    if (relativePath.startsWith("/api/")) {
      const request = requestBody(entry.request);
      const requestHash = bodyHash(request);
      const apiKey = `${method}\0${relativePath}\0${JSON.stringify(query)}\0${requestHash}\0${bodyHash(capturedBody)}`;
      if (seenApiBodies.has(apiKey)) continue;
      seenApiBodies.add(apiKey);
      manifest.apiEntries.push({ ...baseEntry, requestBodyHash: requestHash, requestBodyBytes: request.length });
    } else {
      const staticKey = `${relativePath}\0${JSON.stringify(query)}`;
      const existing = staticByKey.get(staticKey);
      if (existing) {
        const existingBody = await readFile(path.join(mockDir, existing.bodyFile));
        if (bodyHash(existingBody) === bodyHash(capturedBody)) continue;
      }
      staticByKey.set(staticKey, baseEntry);
    }
  }
}

manifest.staticEntries = [...staticByKey.values()];

// zt-sjjr 的 HAR 只包含后续静态资源和接口，没有入口 HTML/主包。
// 生成一个最小 qiankun 入口，避免主应用把缺失正文当成 404 或无生命周期模块。
if (!manifest.staticEntries.some((entry) => entry.path === "/sjjr/")) {
  const bodyName = `${String(bodyIndex++).padStart(6, "0")}.bin`;
  const bodyFile = path.posix.join("bodies", bodyName);
  const syntheticBody = Buffer.from(bootstrapHtml(syntheticMicroAppHtml({
    appName: "zt-sjjr",
    title: "数据接入",
    description: "当前 HAR 未保存数据接入模块的入口正文，已切换到本地兼容壳。"
  })), "utf8");
  await writeFile(path.join(bodyDir, bodyName), syntheticBody);
  manifest.staticEntries.push({
    source: "generated:zt-sjjr-entry",
    method: "GET",
    path: "/sjjr/",
    query: [],
    status: 200,
    contentType: "text/html; charset=utf-8",
    bodyFile,
    bodyBytes: syntheticBody.length
  });
}

const fallback = manifest.staticEntries.find((entry) => entry.path === "/home")?.bodyFile
  || manifest.staticEntries.find((entry) => entry.contentType.includes("html") && entry.path !== "/login-hub/")?.bodyFile;
if (!fallback) throw new Error("HAR中没有可用的HTML入口正文");
manifest.fallbackDocument = fallback;

await writeFile(path.join(mockDir, "manifest.json"), `${JSON.stringify(manifest, null, 2)}\n`, "utf8");
await writeFile(path.join(publicDir, "index.html"), await readFile(path.join(mockDir, fallback)));

console.log(JSON.stringify({
  validFiles: manifest.sourceFiles.length,
  skippedFiles: manifest.skippedFiles.length,
  staticEntries: manifest.staticEntries.length,
  apiEntries: manifest.apiEntries.length,
  websocketEntries: manifest.websocketEntries.length,
  missingBodies: manifest.missingBodies.length,
  fallbackDocument: manifest.fallbackDocument
}, null, 2));
