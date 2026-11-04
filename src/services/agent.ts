/**
 * Shopping agent: router -> (searcher -> analyst) | refusal.
 *
 * A small explicit state machine (it replaced the LangGraph graph). `streamAgent`
 * yields the client-facing SSE events the apps consume ({status, analysis?, products?});
 * `runAgent` drives the same generator to completion for the non-streaming route.
 */
import type { Env } from "../env";
import * as gemini from "./gemini";
import { searchProducts, type Product } from "./search";

export const DEFAULT_MAX_PRODUCTS = 3;

export interface AgentInput {
  question: string;
  history: string[];
  userName: string;
  language: string;
  currency: string;
  maxProducts?: number;
  analystModel?: string;
}

export type AgentStatus = "routing" | "searching" | "thinking" | "completed" | "out_of_scope" | "error";

export interface AgentEvent {
  status: AgentStatus;
  analysis?: string;
  products?: Product[];
}

export const REFUSAL_MESSAGES: Record<string, string> = {
  tr: "Üzgünüm{name}, ben sadece bir alışveriş asistanıyım. Ürün bulma veya fiyat karşılaştırma konusunda yardımcı olabilirim.",
  en: "Sorry{name}, I'm only a shopping assistant. I can help you find products or compare prices.",
  ar: "معذرة{name}، أنا مجرد مساعد تسوق. يمكنني مساعدتك في العثور على المنتجات أو مقارنة الأسعار.",
  ru: "Извините{name}, я всего лишь помощник по покупкам. Я могу помочь вам найти товары или сравнить цены.",
  fr: "Désolé{name}, je ne suis qu'un assistant shopping. Je peux vous aider à trouver des produits ou à comparer les prix.",
  de: "Entschuldigung{name}, ich bin nur ein Shopping-Assistent. Ich kann dir helfen, Produkte zu finden oder Preise zu vergleichen.",
  es: "Lo siento{name}, solo soy un asistente de compras. Puedo ayudarte a encontrar productos o comparar precios.",
  it: "Scusa{name}, sono solo un assistente agli acquisti. Posso aiutarti a trovare prodotti o confrontare i prezzi.",
  zh: "抱歉{name}，我只是一个购物助手。我可以帮您查找产品或比较价格。",
  ja: "申し訳ありません{name}、私はショッピングアシスタントです。商品の検索や価格の比較をお手伝いできます。",
};

export const NO_RESULTS_MESSAGES: Record<string, string> = {
  tr: "Bu arama için uygun ürün bulamadım. İsteğini biraz farklı ifade etmeyi dener misin?",
  en: "I couldn't find matching products for this search. Could you try phrasing it differently?",
};

export const ERROR_MESSAGES: Record<string, string> = {
  tr: "Şu an yanıt veremiyorum, lütfen birazdan tekrar dene.",
  en: "I can't respond right now, please try again shortly.",
};

export function localized(messages: Record<string, string>, language: string | null | undefined): string {
  return messages[(language || "tr").toLowerCase()] ?? messages.en;
}

/** Dependencies, injectable for tests. */
export interface AgentDeps {
  isShoppingRelated: typeof gemini.isShoppingRelated;
  extractSearchQuery: typeof gemini.extractSearchQuery;
  analyzeProducts: typeof gemini.analyzeProducts;
  searchProducts: typeof searchProducts;
}

export const defaultDeps: AgentDeps = {
  isShoppingRelated: gemini.isShoppingRelated,
  extractSearchQuery: gemini.extractSearchQuery,
  analyzeProducts: gemini.analyzeProducts,
  searchProducts,
};

/**
 * Event sequence: routing -> [searching -> thinking(products) -> completed] | out_of_scope.
 * Intermediate events carry no `analysis`; only the final event does. Errors propagate.
 */
export async function* streamAgent(env: Env, input: AgentInput, deps: AgentDeps = defaultDeps): AsyncGenerator<AgentEvent> {
  yield { status: "routing" };

  // router
  const related = await deps.isShoppingRelated(env, input.question, input.history);
  if (!related) {
    const template = localized(REFUSAL_MESSAGES, input.language);
    yield { status: "out_of_scope", analysis: template.replace("{name}", input.userName ? ` ${input.userName}` : "") };
    return;
  }
  yield { status: "searching" };

  // searcher
  const query = await deps.extractSearchQuery(env, input.question, input.history);
  const products = await deps.searchProducts(env, query, input.language, input.currency, input.maxProducts ?? DEFAULT_MAX_PRODUCTS);
  yield { status: "thinking", products };

  // analyst: don't spend an LLM call analysing nothing.
  if (!products.length) {
    yield { status: "completed", analysis: localized(NO_RESULTS_MESSAGES, input.language), products };
    return;
  }
  const analysis = await deps.analyzeProducts(env, input.question, products, {
    userName: input.userName,
    currency: input.currency || "TRY",
    language: input.language || "tr",
    history: input.history,
    model: input.analystModel,
  });
  yield { status: "completed", analysis, products };
}

/** Runs the agent to its final event. */
export async function runAgent(env: Env, input: AgentInput, deps: AgentDeps = defaultDeps): Promise<AgentEvent> {
  let last: AgentEvent = { status: "error" };
  for await (const event of streamAgent(env, input, deps)) last = event;
  return last;
}
