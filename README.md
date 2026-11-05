# SynapCart Backend API

SynapCart'ın çekirdek API'si. **Cloudflare Workers** üzerinde çalışan bir TypeScript (Hono) servisidir. Veritabanı olarak **Cloudflare D1** kullanır. Şunları yönetir:

- kullanıcı hesapları;
- AI alışveriş asistanı (Gemini ve SerpAPI Google Shopping);
- favoriler ve fiyat alarmları;
- Free/Premium planlar;
- Google Play ve App Store abonelik doğrulaması;
- e-posta ile şifre sıfırlama ve hesap silme (Resend).

| Ortam | Adres |
|---|---|
| Production | `https://api.synapcart.emreaydin.dev` |
| Staging | `https://staging-api.synapcart.emreaydin.dev` |
| Yerel | `http://localhost:8001` |

## Teknik yığın

- **Runtime:** Cloudflare Workers (`nodejs_compat`), Hono
- **Veritabanı:** Cloudflare D1 (SQLite). Migrasyonlar `migrations/` altında, `wrangler d1 migrations` ile uygulanır.
- **AI:** Gemini REST API (`gemini-2.5-flash-lite`; Premium analizde `PREMIUM_ANALYST_MODEL`)
- **Arama:** SerpAPI `google_shopping` (30 dakika Workers Cache API önbelleği)
- **E-posta:** Resend HTTP API (ücretsiz katman: ayda 3.000, günde 100 e-posta). Workers Paid planında isteğe bağlı olarak Cloudflare Email Service (`send_email` binding).
- **Push:** FCM HTTP v1 (Android ve iOS)
- **Ödemeler:**
  - Google Play Developer API ve RTDN;
  - App Store: StoreKit 2 JWS doğrulaması ve App Store Server Notifications V2.
- **Testler:** Vitest ve `@cloudflare/vitest-plugin`, gerçek workerd ve yerel D1 ile.

## Yerel geliştirme

```bash
npm install
cp .dev.vars.example .dev.vars      # SECRET_KEY, GEMINI_API_KEY, SERP_API_KEY
npm run db:migrate:local
npm run dev -- --port 8001          # http://localhost:8001/api/v1/health
npm test                            # 60 test; dış servisler taklit edilir
npm run typecheck
```

Yerelde `RESEND_API_KEY` boşsa e-postalar gönderilmez, yalnızca konsola yazılır.

## İlk kurulum (Cloudflare)

1. `synapcart.emreaydin.dev` alan adı Cloudflare'de olmalıdır. Workers **Free** planı yeterlidir (günde 100.000 istek, istek başına 10 ms CPU). 10 ms sınırı için `PASSWORD_ITERATIONS` 25000'dir; Paid plana geçerseniz 100000 yapın, mevcut hash'ler kullanıcının bir sonraki girişinde yükseltilir.
2. D1 veritabanlarını oluşturun ve çıkan `database_id` değerlerini `wrangler.jsonc` dosyasına yazın:

   ```bash
   npx wrangler d1 create synapcart-prod
   npx wrangler d1 create synapcart-staging
   ```

3. E-posta: resend.com'da ücretsiz hesap açın, **Domains → Add Domain** ile `synapcart.emreaydin.dev` alan adını ekleyip verdiği DNS kayıtlarını Cloudflare DNS'e girin. **API Keys** bölümünden bir anahtar oluşturup `RESEND_API_KEY` olarak kaydedin.
4. Gizli anahtarları her ortam için ayrı girin:

   ```bash
   npx wrangler secret put SECRET_KEY --env staging     # openssl rand -base64 48
   npx wrangler secret put GEMINI_API_KEY --env staging
   npx wrangler secret put SERP_API_KEY --env staging
   npx wrangler secret put RESEND_API_KEY --env staging
   # İsteğe bağlı: GOOGLE_PLAY_SERVICE_ACCOUNT_JSON, PLAY_RTDN_TOKEN,
   # FIREBASE_SERVICE_ACCOUNT_JSON, APPLE_ISSUER_ID, APPLE_KEY_ID, APPLE_PRIVATE_KEY
   ```

   Production için aynı komutları `--env=""` ile çalıştırın.
5. Migrasyonları uygulayın ve deploy edin:

   ```bash
   npm run db:migrate:staging && npm run deploy:staging
   npm run db:migrate:prod && npm run deploy:prod
   ```

   Custom domain'ler (`api.` ve `staging-api.`) deploy sırasında otomatik oluşturulur.

GitHub Actions (`.github/workflows/ci.yml`):
- her push ve PR'da typecheck ve testleri çalıştırır;
- `main` dalını staging'e deploy eder;
- `v*` etiketlerini production'a deploy eder.

Gereken repo secret'ları: `CLOUDFLARE_API_TOKEN` ve `CLOUDFLARE_ACCOUNT_ID`.

## Mağaza entegrasyonları

- **Google Play RTDN:** Pub/Sub push URL'si `https://api.synapcart.emreaydin.dev/api/v1/billing/google/rtdn?token=<PLAY_RTDN_TOKEN>`.
- **App Store Server Notifications V2:** App Store Connect → App Information bölümünde production URL'si `https://api.synapcart.emreaydin.dev/api/v1/billing/apple/notifications`, sandbox URL'si `https://staging-api.synapcart.emreaydin.dev/api/v1/billing/apple/notifications`.
- `APPLE_BUNDLE_ID`, `APPLE_PRODUCT_IDS` ve `APPLE_APP_ID` (`wrangler.jsonc` içinde) App Store Connect ile aynı olmalıdır.
