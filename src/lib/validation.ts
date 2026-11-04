import { z } from "zod";
import type { Context } from "hono";
import { ApiError } from "./errors";

export const SUPPORTED_LANGUAGES = ["tr", "en", "ar", "ru", "fr", "de", "es", "it", "zh", "ja"] as const;
export const SUPPORTED_CURRENCIES = ["TRY", "USD", "EUR", "GBP"] as const;
export const MIN_PASSWORD_LENGTH = 8;
export const MAX_PASSWORD_BYTES = 72; // kept from the bcrypt era so app-side rules stay the same

/** A field error whose message becomes the response `detail` verbatim. */
const fail = (ctx: z.RefinementCtx, message: string) => ctx.addIssue({ code: "custom", message });

export const email = z
  .string()
  .trim()
  .toLowerCase()
  .pipe(z.email());

export const newPassword = z.string().superRefine((v, ctx) => {
  if (v.length < MIN_PASSWORD_LENGTH) return fail(ctx, `Şifre en az ${MIN_PASSWORD_LENGTH} karakter olmalıdır.`);
  if (new TextEncoder().encode(v).length > MAX_PASSWORD_BYTES) return fail(ctx, "Şifre çok uzun.");
  if (/^\d+$/.test(v) || /^\p{L}+$/u.test(v)) return fail(ctx, "Şifre hem harf hem rakam içermelidir.");
});

const httpLink = z
  .string()
  .min(1)
  .max(2048)
  .superRefine((v, ctx) => {
    if (!/^https?:\/\//.test(v)) fail(ctx, "Geçersiz ürün linki.");
  });

/** The mobile app may send the price as a string; tolerate "1.299,00"-style values and "". */
export function parsePrice(v: unknown): number | null {
  if (v === null || v === undefined || v === "") return null;
  if (typeof v === "number") return Number.isFinite(v) ? v : null;
  if (typeof v !== "string") return null;
  let s = v.replace(/\s/g, "");
  s = s.includes(",") && s.includes(".") ? s.replace(/\./g, "").replace(",", ".") : s.replace(",", ".");
  const n = Number(s);
  return s !== "" && Number.isFinite(n) ? n : null;
}

const optStr = (max: number) => z.string().max(max).nullish();

export const schemas = {
  register: z.object({
    email,
    password: newPassword,
    name: z
      .string()
      .max(80)
      .transform((s) => s.trim())
      .superRefine((v, ctx) => {
        if (!v) fail(ctx, "İsim boş olamaz.");
      }),
  }),
  login: z.object({ email, password: z.string().max(256) }),
  emailOnly: z.object({ email }),
  tokenOnly: z.object({ token: z.string().min(1).max(256) }),
  resetPassword: z.object({ token: z.string().min(1).max(256), new_password: newPassword }),
  changePassword: z.object({ current_password: z.string().max(256), new_password: newPassword }),
  deleteAccount: z.object({ password: z.string().max(256).nullish() }),
  profileUpdate: z.object({
    full_name: z.string().max(80).nullish(),
    language: z
      .string()
      .nullish()
      .transform((v) => v?.toLowerCase())
      .superRefine((v, ctx) => {
        if (v && !(SUPPORTED_LANGUAGES as readonly string[]).includes(v)) fail(ctx, "Desteklenmeyen dil.");
      }),
    currency: z
      .string()
      .nullish()
      .transform((v) => v?.toUpperCase())
      .superRefine((v, ctx) => {
        if (v && !(SUPPORTED_CURRENCIES as readonly string[]).includes(v)) fail(ctx, "Desteklenmeyen para birimi.");
      }),
  }),
  deviceToken: z.object({
    token: z.string().min(1).max(4096),
    platform: z.string().max(20).nullish().default("android"),
  }),
  chat: z.object({
    message: z
      .string()
      .min(1)
      .max(1000)
      .transform((s) => s.trim())
      .superRefine((v, ctx) => {
        if (!v) fail(ctx, "Mesaj boş olamaz.");
      }),
  }),
  sessionUpdate: z.object({ title: z.string().min(1).max(100) }),
  favoriteCreate: z.object({
    title: z.string().min(1).max(500),
    price: z.unknown().optional().transform(parsePrice),
    currency: optStr(8),
    source: optStr(200),
    link: httpLink,
    thumbnail: optStr(2048),
  }),
  favoriteUpdate: z.object({ target_price: z.number().gt(0).lt(1e9).nullish() }),
  compare: z.object({
    products: z
      .array(
        z.object({
          title: z.string().min(1).max(500),
          price: z.number().nullish(),
          source: optStr(200),
          link: optStr(2048),
          thumbnail: optStr(2048),
        }),
      )
      .min(2)
      .max(4),
  }),
  playVerify: z.object({
    purchase_token: z.string().min(1).max(4096),
    product_id: z.string().min(1).max(200),
  }),
  appleVerify: z.object({ signed_transaction: z.string().min(1).max(20_000) }),
  pubsub: z.object({
    message: z.object({ data: z.string().nullish(), messageId: z.string().nullish() }),
    subscription: z.string().nullish(),
  }),
  appleNotification: z.object({ signedPayload: z.string().min(1).max(100_000) }),
};

/** Clients (Android, iOS, web) expect `detail` to be a single readable string. */
export function validationError(error: z.ZodError): ApiError {
  const issue = error.issues[0];
  let detail = "Geçersiz istek.";
  if (issue) {
    if (issue.code === "custom") detail = issue.message;
    else if (issue.path.length) detail = `Geçersiz alan: ${issue.path.join(".")}`;
  }
  const err = new ApiError(422, detail);
  (err as ApiError & { errors?: unknown }).errors = error.issues.map((i) => ({ loc: ["body", ...i.path], msg: i.message }));
  return err;
}

export async function parseJson<T extends z.ZodType>(c: Context, schema: T, optional = false): Promise<z.infer<T>> {
  let raw: unknown;
  const text = await c.req.text();
  if (!text.trim()) {
    if (optional) raw = {};
    else throw new ApiError(422, "Geçersiz istek.");
  } else {
    try {
      raw = JSON.parse(text);
    } catch {
      throw new ApiError(422, "Geçersiz istek.");
    }
  }
  const result = schema.safeParse(raw);
  if (!result.success) throw validationError(result.error);
  return result.data;
}
