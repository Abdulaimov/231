// Локальный просмотр готового сайта: node tools/serve.mjs [порт]
// Отдаёт папку site/ со сжатием gzip для текста и поддержкой Range для видео — почти как хостинг.
import { createServer } from "node:http";
import { createReadStream, statSync } from "node:fs";
import { extname, join, normalize, resolve } from "node:path";
import { gzipSync } from "node:zlib";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

const ROOT = resolve(fileURLToPath(new URL("../site", import.meta.url)));
const PORT = Number(process.argv[2] || process.env.PORT || 8231);
const TYPES = {
  ".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8", ".css": "text/css; charset=utf-8",
  ".json": "application/json", ".svg": "image/svg+xml", ".txt": "text/plain; charset=utf-8",
  ".avif": "image/avif", ".webp": "image/webp", ".jpg": "image/jpeg", ".png": "image/png",
  ".woff2": "font/woff2", ".mp4": "video/mp4",
};
const COMPRESS = new Set([".html", ".js", ".css", ".json", ".svg", ".txt"]);

createServer((req, res) => {
  const url = new URL(req.url, "http://localhost");
  let path = normalize(join(ROOT, decodeURIComponent(url.pathname)));
  if (!path.startsWith(ROOT)) { res.writeHead(403).end(); return; }
  let st;
  try { st = statSync(path); if (st.isDirectory()) { path = join(path, "index.html"); st = statSync(path); } }
  catch { res.writeHead(404, { "content-type": "text/plain; charset=utf-8" }).end("Не найдено"); return; }
  const ext = extname(path);
  const headers = {
    "content-type": TYPES[ext] || "application/octet-stream",
    "cache-control": ext === ".html" ? "no-cache" : "public, max-age=31536000, immutable",
    "accept-ranges": "bytes",
  };
  if (COMPRESS.has(ext) && /\bgzip\b/.test(req.headers["accept-encoding"] || "")) {
    const body = gzipSync(readFileSync(path), { level: 9 });
    res.writeHead(200, { ...headers, "content-encoding": "gzip", "content-length": body.length, vary: "accept-encoding" });
    res.end(req.method === "HEAD" ? undefined : body);
    return;
  }
  const range = /^bytes=(\d*)-(\d*)$/.exec(req.headers.range || "");
  if (range) {
    const start = range[1] ? Number(range[1]) : st.size - Number(range[2]);
    const end = range[1] && range[2] ? Math.min(Number(range[2]), st.size - 1) : st.size - 1;
    res.writeHead(206, { ...headers, "content-range": `bytes ${start}-${end}/${st.size}`, "content-length": end - start + 1 });
    createReadStream(path, { start, end }).pipe(res);
    return;
  }
  res.writeHead(200, { ...headers, "content-length": st.size });
  if (req.method === "HEAD") res.end(); else createReadStream(path).pipe(res);
}).listen(PORT, () => console.log(`Сайт 231inc: http://localhost:${PORT}`));
