import type { Env } from "./env";
import { app } from "./app";
import { refreshAppleSubscriptions, runPriceCheck } from "./jobs/priceCheck";

export default {
  fetch: app.fetch,

  /** Cron Trigger (wrangler.jsonc `triggers.crons`): daily price alerts + App Store status refresh. */
  async scheduled(_controller: ScheduledController, env: Env, ctx: ExecutionContext) {
    ctx.waitUntil(
      (async () => {
        const prices = await runPriceCheck(env);
        const apple = await refreshAppleSubscriptions(env);
        console.log("Scheduled jobs finished", JSON.stringify({ ...prices, ...apple }));
      })(),
    );
  },
} satisfies ExportedHandler<Env>;
