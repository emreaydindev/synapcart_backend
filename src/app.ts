import { Hono } from "hono";
import { cors } from "hono/cors";
import type { AppEnv } from "./context";
import { errorBody } from "./context";
import { settings } from "./config";
import { ApiError } from "./lib/errors";
import auth from "./routes/auth";
import billing from "./routes/billing";
import chat from "./routes/chat";
import favorites from "./routes/favorites";
import user from "./routes/user";

export const app = new Hono<AppEnv>({ strict: false });

// Mobile clients don't need CORS; this only governs browsers. Auth is a bearer
// header (no cookies), so credentials are not allowed.
app.use("*", async (c, next) => {
  const origins = settings(c.env).corsOrigins;
  return cors({
    origin: (origin) => (origins.includes(origin) ? origin : null),
    allowMethods: ["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allowHeaders: ["Authorization", "Content-Type"],
    credentials: false,
    maxAge: 600,
  })(c, next);
});

app.onError((err, c) => {
  if (err instanceof ApiError) {
    return c.json(errorBody(err), err.status, err.headers);
  }
  console.error(`Unhandled error on ${c.req.method} ${c.req.path}`, err);
  return c.json({ detail: "Beklenmeyen bir hata oluştu. Lütfen tekrar deneyin." }, 500);
});

app.notFound((c) => c.json({ detail: "Not Found" }, 404));

app.get("/", (c) => c.json({ message: "SynapCart API is running", status: "active" }));

const v1 = new Hono<AppEnv>({ strict: false });
v1.get("/health", async (c) => {
  try {
    await c.env.DB.prepare("SELECT 1").first();
  } catch {
    return c.json({ status: "degraded", database: "unreachable" }, 503);
  }
  return c.json({ status: "ok", service: "v1_api", database: "ok", env: settings(c.env).env });
});
v1.route("/auth", auth);
v1.route("/chat", chat);
v1.route("/favorites", favorites);
v1.route("/user", user);
v1.route("/billing", billing);

app.route("/api/v1", v1);
