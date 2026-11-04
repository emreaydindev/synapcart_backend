import type { ContentfulStatusCode } from "hono/utils/http-status";

/**
 * An HTTP error whose body is {"detail": <string>, "code"?: <machine code>}.
 * Clients branch on `code` (the apps open the paywall on 402 quota_exceeded /
 * premium_required / history_locked).
 */
export class ApiError extends Error {
  constructor(
    public status: ContentfulStatusCode,
    public detail: string,
    public code?: string,
    public headers?: Record<string, string>,
  ) {
    super(detail);
  }
}

export const notFound = (detail: string) => new ApiError(404, detail);
export const badRequest = (detail: string) => new ApiError(400, detail);

export const unauthorized = () =>
  new ApiError(401, "Oturumunuzun süresi doldu. Lütfen tekrar giriş yapın.", undefined, {
    "WWW-Authenticate": "Bearer",
  });

export const quotaExceeded = (limit: number) =>
  new ApiError(
    402,
    `Bugünkü ${limit} mesaj hakkını kullandın. Premium ile daha fazla mesaj gönderebilir ya da yarın tekrar deneyebilirsin.`,
    "quota_exceeded",
  );

export const premiumRequired = () => new ApiError(402, "Bu özellik Premium üyelere özeldir.", "premium_required");

export const historyLocked = () =>
  new ApiError(
    402,
    "Bu eski sohbet ücretsiz planda kilitli. Tüm geçmişine erişmek için Premium'a geç.",
    "history_locked",
  );

export const rateLimited = () =>
  new ApiError(429, "Çok fazla istek gönderdiniz. Lütfen biraz bekleyip tekrar deneyin.", "rate_limited");
