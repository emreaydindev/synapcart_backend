/** Worker bindings, vars and secrets (see wrangler.jsonc and .dev.vars.example). */
export interface Env {
  DB: D1Database;
  /** Cloudflare Email Service binding. Unset = emails are logged, not sent (dev/test). */
  SEND_EMAIL?: SendEmail;
  /** Workers Rate Limiting bindings. Unset = no rate limiting (dev/test). */
  AUTH_LIMITER?: RateLimit;
  EMAIL_LIMITER?: RateLimit;
  AGENT_LIMITER?: RateLimit;
  BILLING_LIMITER?: RateLimit;

  // Vars
  ENV?: string; // "dev" | "test" | "staging" | "prod"
  CORS_ORIGINS?: string; // comma-separated
  APP_FRONTEND_URL?: string;
  EMAIL_FROM?: string;
  ACCESS_TOKEN_EXPIRE_MINUTES?: string;
  PREMIUM_ANALYST_MODEL?: string;
  PLAY_PACKAGE_NAME?: string;
  PLAY_SUBSCRIPTION_IDS?: string; // comma-separated
  APPLE_BUNDLE_ID?: string;
  APPLE_APP_ID?: string; // numeric App Store id, required by Apple for Production JWS checks
  APPLE_PRODUCT_IDS?: string; // comma-separated
  APPLE_ENVIRONMENT?: string; // "Production" | "Sandbox"
  FIREBASE_PROJECT_ID?: string;

  // Secrets
  SECRET_KEY: string;
  GEMINI_API_KEY: string;
  SERP_API_KEY: string;
  GOOGLE_PLAY_SERVICE_ACCOUNT_JSON?: string;
  PLAY_RTDN_TOKEN?: string;
  FIREBASE_SERVICE_ACCOUNT_JSON?: string;
  /** App Store Server API key (optional; used by the daily status refresh). */
  APPLE_ISSUER_ID?: string;
  APPLE_KEY_ID?: string;
  APPLE_PRIVATE_KEY?: string;
}
