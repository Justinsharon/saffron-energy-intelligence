import { defineConfig, type Plugin, type ViteDevServer } from "vite";
import react from "@vitejs/plugin-react";
import { resolve } from "node:path";

// Dev only, opt-in (SAFFRON_DEV_FUNCTIONS=1): serve /.netlify/functions/<name> from netlify/functions/<name>.ts in this process, so the
// Plant Room and the app can be run end to end locally (with SAFFRON_MEMORY_STORE=1 the shared state lives in memory). Never in a build.
function devFunctions(): Plugin {
  return {
    name: "saffron-dev-functions",
    apply: "serve",
    configureServer(server: ViteDevServer) {
      if (process.env.SAFFRON_DEV_FUNCTIONS !== "1") return;
      server.middlewares.use(async (req, res, next) => {
        const m = /^\/\.netlify\/functions\/([a-z_]+)/.exec(req.url ?? "");
        if (!m) return next();
        try {
          const mod = await server.ssrLoadModule(`/netlify/functions/${m[1]}.ts`);
          const chunks: Buffer[] = [];
          for await (const c of req) chunks.push(c as Buffer);
          const r: Response = await mod.default(new Request(`http://localhost${req.url}`, {
            method: req.method, headers: req.headers as Record<string, string>, body: chunks.length ? Buffer.concat(chunks) : undefined }));
          res.statusCode = r.status;
          r.headers.forEach((v, k) => res.setHeader(k, v));
          res.end(Buffer.from(await r.arrayBuffer()));
        } catch (e) { res.statusCode = 500; res.end(String(e)); }
      });
    },
  };
}

// /api in dev: proxied to SAFFRON_API_URL when set (e.g. a local uvicorn or the Cloud Run service), as Netlify does in production.
const api = process.env.SAFFRON_API_URL;
export default defineConfig({
  plugins: [react(), devFunctions()],
  build: { chunkSizeWarningLimit: 900, rollupOptions: { input: { main: resolve(__dirname, "index.html"), plant: resolve(__dirname, "plant.html") } } },
  server: api ? { proxy: { "/api": { target: api, changeOrigin: true, rewrite: (p) => p.replace(/^\/api/, "") } } } : undefined,
});
