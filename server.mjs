import { createHash } from "node:crypto";
import { createServer } from "node:http";
import { readFile, stat } from "node:fs/promises";
import path from "node:path";
import process from "node:process";
import { fileURLToPath } from "node:url";

const rootDir = path.dirname(fileURLToPath(import.meta.url));
const publicDir = path.join(rootDir, "public");
const mockDir = path.join(rootDir, "mock");
const manifestPath = path.join(mockDir, "manifest.json");
const host = "127.0.0.1";
const port = Number(process.env.PORT || 4173);
const replayMode = process.argv.includes('--replay') || process.env.BACKEND_MODE === 'replay';
let backend;

const mimeTypes = new Map([
  [".html", "text/html; charset=utf-8"],
  [".js", "application/javascript; charset=utf-8"],
  [".css", "text/css; charset=utf-8"],
  [".json", "application/json; charset=utf-8"],
  [".png", "image/png"],
  [".jpg", "image/jpeg"],
  [".jpeg", "image/jpeg"],
  [".gif", "image/gif"],
  [".svg", "image/svg+xml"],
  [".ico", "image/x-icon"],
  [".woff", "font/woff"],
  [".woff2", "font/woff2"],
  [".ttf", "font/ttf"]
]);

const csp = [
  "default-src 'self' data: blob:",
  "script-src 'self' 'unsafe-inline' 'unsafe-eval'",
  "style-src 'self' 'unsafe-inline'",
  "img-src 'self' data: blob:",
  "font-src 'self' data:",
  "connect-src 'self' ws: wss:",
  "frame-src 'self' blob:",
  "object-src 'none'",
  "base-uri 'self'",
  "form-action 'self'",
  "navigate-to 'self'"
].join("; ");

function safePath(base, relativePath) {
  const target = path.resolve(base, relativePath);
  const relative = path.relative(base, target);
  if (relative.startsWith("..") || path.isAbsolute(relative)) return null;
  return target;
}

function queryPairs(url) {
  return [...url.searchParams.entries()].sort(([ak, av], [bk, bv]) =>
    `${ak}=${av}`.localeCompare(`${bk}=${bv}`)
  );
}

function pairMap(pairs) {
  const result = new Map();
  for (const [key, value] of pairs || []) {
    if (!result.has(key)) result.set(key, []);
    result.get(key).push(value);
  }
  return result;
}

function queryScore(candidatePairs, requestPairs) {
  const candidate = pairMap(candidatePairs);
  const request = pairMap(requestPairs);
  let score = 0;
  for (const [key, values] of candidate) {
    const actual = request.get(key);
    if (!actual) {
      score -= key === "pageNum" || key === "pageSize" ? 1 : 4;
      continue;
    }
    for (const value of values) {
      if (actual.includes(value)) score += key === "pageNum" || key === "pageSize" ? 1 : 12;
      else score -= 4;
    }
  }
  for (const key of request.keys()) {
    if (!candidate.has(key)) score -= 1;
  }
  return score;
}

function bodyHash(body) {
  if (!body?.length) return "";
  return createHash("sha256").update(body).digest("hex");
}

function acceptWebSocket(request, socket) {
  const key = request.headers["sec-websocket-key"];
  if (typeof key !== "string" || !key) {
    socket.end("HTTP/1.1 400 Bad Request\r\nConnection: close\r\n\r\n");
    return;
  }
  const accept = createHash("sha1")
    .update(`${key.trim()}258EAFA5-E914-47DA-95CA-C5AB0DC85B11`)
    .digest("base64");
  const protocol = request.headers["sec-websocket-protocol"];
  const lines = [
    "HTTP/1.1 101 Switching Protocols",
    "Upgrade: websocket",
    "Connection: Upgrade",
    `Sec-WebSocket-Accept: ${accept}`
  ];
  if (typeof protocol === "string" && protocol.trim()) {
    lines.push(`Sec-WebSocket-Protocol: ${protocol.split(",")[0].trim()}`);
  }
  socket.write(`${lines.join("\r\n")}\r\n\r\n`);

  // 只维持本地回放连接。处理客户端 ping 和 close，忽略业务消息即可，
  // 这样页面不会因 426 或连接断开触发重连循环。
  let pending = Buffer.alloc(0);
  socket.on("data", (chunk) => {
    const buffer = Buffer.concat([pending,chunk]);
    pending = Buffer.alloc(0);
    if (buffer.length > 1024 * 1024) { socket.end(Buffer.from([0x88,0x00])); return; }
    let offset = 0;
    while (offset + 2 <= buffer.length) {
      const first = buffer[offset];
      const second = buffer[offset + 1];
      const opcode = first & 0x0f;
      let length = second & 0x7f;
      let headerLength = 2;
      if (length === 126) {
        if (offset + 4 > buffer.length) { pending = buffer.subarray(offset); return; }
        length = buffer.readUInt16BE(offset + 2);
        headerLength = 4;
      } else if (length === 127) {
        if (offset + 10 > buffer.length) { pending = buffer.subarray(offset); return; }
        const high = buffer.readUInt32BE(offset + 2);
        const low = buffer.readUInt32BE(offset + 6);
        if (high !== 0) return;
        length = low;
        headerLength = 10;
      }
      const masked = (second & 0x80) !== 0;
      const frameLength = headerLength + (masked ? 4 : 0) + length;
      if (offset + frameLength > buffer.length) { pending = buffer.subarray(offset); return; }
      if (opcode === 0x8) {
        socket.end(Buffer.from([0x88, 0x00]));
        return;
      }
      if (opcode === 0x9) {
        const payloadStart = offset + headerLength + (masked ? 4 : 0);
        if (length > 125) { socket.end(Buffer.from([0x88,0x00])); return; }
        const payload = Buffer.from(buffer.subarray(payloadStart, payloadStart + length));
        if (masked) { const mask = buffer.subarray(offset+headerLength,offset+headerLength+4); for(let i=0;i<payload.length;i++)payload[i]^=mask[i%4]; }
        const pong = Buffer.alloc(2 + payload.length);
        pong[0] = 0x8a;
        pong[1] = payload.length;
        payload.copy(pong, 2);
        socket.write(pong);
      }
      offset += frameLength;
    }
    pending = buffer.subarray(offset);
  });
  socket.on("error", () => {});
}

function bodyScore(entry, requestBody) {
  const captured = entry.requestBodyHash || "";
  const actual = bodyHash(requestBody);
  if (captured && actual && captured === actual) return 40;
  if (!captured && !actual) return 5;
  if (!captured) return 1;
  return -4;
}

function chooseEntry(candidates, url, requestBody = Buffer.alloc(0)) {
  const requestedQuery = queryPairs(url);
  return candidates
    .map((entry, index) => ({
      entry,
      index,
      score: queryScore(entry.query, requestedQuery) + bodyScore(entry, requestBody)
    }))
    .sort((left, right) => right.score - left.score || left.index - right.index)[0]?.entry || null;
}

function commonHeaders(contentType) {
  return {
    "Content-Type": contentType || "application/octet-stream",
    "Cache-Control": "no-store",
    "Content-Security-Policy": csp,
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer"
  };
}

function sendJson(response, status, payload) {
  const body = Buffer.from(JSON.stringify(payload), "utf8");
  response.writeHead(status, {
    ...commonHeaders("application/json; charset=utf-8"),
    "Content-Length": body.length
  });
  response.end(body);
}

function readRequestBody(request) {
  return new Promise((resolve, reject) => {
    const chunks = [];
    let size = 0;
    request.on("data", (chunk) => {
      size += chunk.length;
      if (size > 8 * 1024 * 1024) {
        reject(new Error("请求体超过本地复刻上限"));
        request.destroy();
        return;
      }
      chunks.push(chunk);
    });
    request.on("end", () => resolve(Buffer.concat(chunks)));
    request.on("error", reject);
  });
}

function listLikePath(pathname) {
  return /(?:\/list|\/query|queryPage|queryList|selectPage|dbList|page)$/i.test(pathname);
}

function adaptListResponse(body, contentType, url, capturedQuery) {
  if (!String(contentType).toLowerCase().includes("json")) return body;
  if (JSON.stringify(capturedQuery || []) === JSON.stringify(queryPairs(url))) return body;

  let payload;
  try {
    payload = JSON.parse(body.toString("utf8"));
  } catch {
    return body;
  }
  if (!Array.isArray(payload?.rows)) return body;

  const ignored = new Set(["pageNum", "pageSize", "pageNumber", "orderByColumn", "isAsc"]);
  const filters = queryPairs(url).filter(([key, value]) => value !== "" && !ignored.has(key));
  let rows = payload.rows.filter((row) => filters.every(([key, expected]) => {
    if (row == null || !Object.prototype.hasOwnProperty.call(row, key)) return true;
    const actual = row[key];
    return actual != null && String(actual).toLowerCase().includes(String(expected).toLowerCase());
  }));
  const total = rows.length;
  const pageNum = Math.max(1, Number(url.searchParams.get("pageNum") || url.searchParams.get("pageNumber") || 1));
  const pageSize = Math.max(1, Number(url.searchParams.get("pageSize") || rows.length || 10));
  rows = rows.slice((pageNum - 1) * pageSize, pageNum * pageSize);
  return Buffer.from(JSON.stringify({ ...payload, total, rows }), "utf8");
}

async function loadManifest() {
  return JSON.parse(await readFile(manifestPath, "utf8"));
}

async function sendCaptured(response, request, entry, manifest, url) {
  const bodyPath = safePath(mockDir, entry.bodyFile);
  if (!bodyPath) {
    sendJson(response, 500, { code: 500, msg: "模拟响应路径无效" });
    return;
  }
  let body = await readFile(bodyPath);
  const isHtml = String(entry.contentType).toLowerCase().includes('text/html');
  if (backend && isHtml) {
    const link = '<a href="/workbench" target="_top" style="position:fixed;right:22px;bottom:22px;z-index:99999;background:#214caf;color:white;padding:12px 18px;border-radius:8px;text-decoration:none;font:14px Microsoft YaHei">治理工作台 ↗</a>';
    body = Buffer.from(body.toString('utf8').replace('</head>', '<script src="/workbench/session.js"></script></head>').replace('</body>',link + '</body>'));
  }
  if (entry.path.endsWith('/configOut.js') || entry.path === '/configOut.js') body = Buffer.from(body.toString('utf8').replace(/ws:\/\/127\.0\.0\.1:\d+/g, `ws://${request.headers.host}`));
  if (request.method === "GET" && entry.path.startsWith("/api/")) {
    body = adaptListResponse(body, entry.contentType, url, entry.query);
  }
  const headers = {
    ...commonHeaders(entry.contentType || mimeTypes.get(path.extname(entry.path).toLowerCase())),
    "Content-Length": body.length,
    "X-Local-HAR-Replay": "true",
    ...(backend ? { "X-Governance-Backend": "live" } : {})
  };
  if (String(entry.contentType).toLowerCase().includes("text/html")) {
    headers["Set-Cookie"] = [
      "token=offline-har-replay; Path=/; SameSite=Lax",
      "user=%7B%7D; Path=/; SameSite=Lax"
    ];
  }
  response.writeHead(entry.status === 304 ? 200 : entry.status, headers);
  if (request.method === "HEAD") response.end();
  else response.end(body);
}

async function serveApi(request, response, url, manifest) {
  if (backend) {
    const imageEntry = manifest.apiEntries.find(entry => entry.path === url.pathname && entry.method === 'GET' && /^image\//.test(entry.contentType));
    if (request.method === 'GET' && imageEntry) { await sendCaptured(response,request,imageEntry,manifest,url); return; }
    await backend.handle(request,response,url,readRequestBody,sendJson);
    return;
  }
  const method = String(request.method || "GET").toUpperCase();
  if (method === "OPTIONS") {
    response.writeHead(204, commonHeaders("text/plain; charset=utf-8"));
    response.end();
    return;
  }

  const candidates = manifest.apiEntries.filter((entry) => entry.method === method && entry.path === url.pathname);
  const requestBody = method === "GET" || method === "HEAD" ? Buffer.alloc(0) : await readRequestBody(request);
  const selected = chooseEntry(candidates, url, requestBody);
  if (selected) {
    await sendCaptured(response, { ...request, method }, selected, manifest, url);
    return;
  }

  if (method !== "GET" && method !== "HEAD") {
    sendJson(response, 200, { code: 601, msg: "本地复刻环境不执行未捕获的写操作" });
    return;
  }
  if (listLikePath(url.pathname)) {
    sendJson(response, 200, { code: 200, msg: "本地复刻暂无该接口抓包数据", total: 0, rows: [] });
  } else {
    sendJson(response, 200, { code: 200, msg: "本地复刻暂无该接口抓包数据", data: {} });
  }
}

async function serveStatic(request, response, url, manifest) {
  const method = String(request.method || "GET").toUpperCase();
  if (method === "OPTIONS") {
    response.writeHead(204, commonHeaders("text/plain; charset=utf-8"));
    response.end();
    return;
  }

  // 旧登录兜底可能已经把 jumpOrigin/jumpHash 叠加成很长的地址。
  // 本地回放没有登录跳转需求，先规范化到干净入口，避免继续递归。
  if (url.pathname === "/home" && (url.searchParams.has("jumpOrigin") || url.searchParams.has("jumpHash"))) {
    response.writeHead(302, {
      ...commonHeaders("text/plain; charset=utf-8"),
      Location: "/home"
    });
    response.end();
    return;
  }

  if (!['GET', 'HEAD'].includes(method)) {
    sendJson(response, 200, { code: 601, msg: "本地复刻环境不执行写操作" });
    return;
  }

  if (backend && (url.pathname === '/workbench' || url.pathname.startsWith('/workbench/'))) {
    const relative = url.pathname === '/workbench' || url.pathname === '/workbench/' ? 'workbench/index.html' : url.pathname.slice(1);
    const target = safePath(publicDir,relative);
    if (!target) { sendJson(response,400,{code:400,msg:'资源路径无效'}); return; }
    try {
      const body = await readFile(target);
      response.writeHead(200,{...commonHeaders(mimeTypes.get(path.extname(target))),'Content-Length':body.length});
      response.end(method === 'HEAD' ? undefined : body);
    } catch { sendJson(response,404,{code:404,msg:'工作台资源不存在'}); }
    return;
  }
  if (backend && ['/sjjr/','/ztgl/'].includes(url.pathname)) {
    const name = url.pathname === '/sjjr/' ? 'zt-sjjr' : 'zt-ztgl';
    const html = `<!doctype html><html><head><meta charset="utf-8"></head><body><div id="local-micro-root"></div><script>window[${JSON.stringify(name)}]={bootstrap:function(){return Promise.resolve()},mount:function(p){var root=p.container.querySelector('#local-micro-root');if(root){var frame=document.createElement('iframe');frame.src='/workbench?embed=1${name === 'zt-sjjr' ? '&view=sources' : '&view=settings'}';frame.title='数据治理工作台';frame.style.cssText='width:100%;height:calc(100vh - 64px);border:0';root.appendChild(frame)}return Promise.resolve()},unmount:function(p){var root=p.container.querySelector('#local-micro-root');if(root)root.replaceChildren();return Promise.resolve()}};</script></body></html>`;
    response.writeHead(200,commonHeaders('text/html; charset=utf-8')); response.end(method === 'HEAD' ? undefined : html); return;
  }

  if (url.pathname === "/favicon.ico" && !manifest.staticEntries.some((entry) => entry.path === url.pathname)) {
    response.writeHead(204, commonHeaders("image/x-icon"));
    response.end();
    return;
  }

  const candidates = manifest.staticEntries.filter((entry) => entry.method === "GET" && entry.path === url.pathname);
  const selected = chooseEntry(candidates, url);
  if (selected) {
    await sendCaptured(response, request, selected, manifest, url);
    return;
  }

  const isAppRoute = url.pathname === "/" || url.pathname === "/index.html" ||
    url.pathname === "/home" || url.pathname.startsWith("/zt-");
  if (isAppRoute) {
    await sendCaptured(response, request, {
      status: 200,
      contentType: "text/html; charset=utf-8",
      bodyFile: manifest.fallbackDocument,
      path: "/index.html",
      query: []
    }, manifest, url);
    return;
  }

  sendJson(response, 404, { code: 404, msg: "本地复刻资源不存在", path: url.pathname });
}

async function validate() {
  const manifest = await loadManifest();
  const entries = [...(manifest.staticEntries || []), ...(manifest.apiEntries || [])];
  if (!manifest.fallbackDocument) throw new Error("缺少入口页面");
  if (entries.length < 100) throw new Error(`复刻条目数量异常：${entries.length}`);
  for (const entry of entries) {
    const target = safePath(mockDir, entry.bodyFile);
    if (!target) throw new Error(`非法响应路径：${entry.bodyFile}`);
    const info = await stat(target);
    if (!info.isFile() || info.size === 0) throw new Error(`响应文件为空：${entry.bodyFile}`);
  }
  const fallback = safePath(mockDir, manifest.fallbackDocument);
  if (!fallback) throw new Error(`非法入口路径：${manifest.fallbackDocument}`);
  await stat(fallback);
  console.log(JSON.stringify({
    valid: true,
    sourceFiles: manifest.sourceFiles?.length || 0,
    skippedFiles: manifest.skippedFiles?.length || 0,
    staticEntries: manifest.staticEntries?.length || 0,
    apiEntries: manifest.apiEntries?.length || 0,
    websocketEntries: manifest.websocketEntries?.length || 0,
    missingBodies: manifest.missingBodies?.length || 0
  }, null, 2));
}

if (process.argv.includes("--validate")) {
  await validate();
} else {
  const manifest = await loadManifest();
  if (!replayMode) {
    const { Backend } = await import('./backend/service.mjs');
    const menus = [];
    for (const entry of manifest.apiEntries.filter(e => e.path === '/api/login/login/getTreeResources')) {
      const payload = JSON.parse(await readFile(path.join(mockDir,entry.bodyFile),'utf8'));
      if (Array.isArray(payload.data)) menus.push(payload.data);
    }
    backend = new Backend({dataDir:process.env.DATA_DIR || path.join(rootDir,'.data'),menus});
  }
  const server = createServer((request, response) => {
    const url = new URL(request.url || "/", `http://${request.headers.host || `${host}:${port}`}`);
    const task = url.pathname.startsWith("/api/")
      ? serveApi(request, response, url, manifest)
      : serveStatic(request, response, url, manifest);
    task.catch((error) => {
      console.error(error);
      if (!response.headersSent) sendJson(response, 500, { code: 500, msg: "本地复刻服务异常" });
      else response.end();
    });
  });
  server.on("upgrade", (request, socket) => {
    if (backend && (!backend.user(request) || request.headers.origin && request.headers.origin !== `http://${request.headers.host}`)) { socket.end('HTTP/1.1 403 Forbidden\r\nConnection: close\r\n\r\n'); return; }
    acceptWebSocket(request, socket);
  });
  server.listen(port, host, () => {
    const actualPort = server.address().port;
    console.log(`数据治理${backend ? '真实后端' : '录制回放'}已启动：http://${host}:${actualPort}/home`);
    if (backend) console.log(`治理工作台：http://${host}:${actualPort}/workbench`);
  });
  const stop = async () => { server.close(); if (backend) await backend.close(); process.exit(0); };
  if (backend) backend.onShutdown = stop;
  process.on('SIGINT',stop); process.on('SIGTERM',stop);
}
