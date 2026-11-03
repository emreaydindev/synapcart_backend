"""Shopping agent: router -> (searcher -> analyst) | refusal.

The compiled graph is the single implementation. `stream_agent` runs the same
graph with `astream` and maps node completions to the SSE events the mobile
app consumes ({status, analysis?, products?}).
"""
import logging
from typing import Any, AsyncGenerator, Dict, List, Literal, Optional, TypedDict

from langgraph.graph import END, StateGraph

from app.services import gemini_service
from app.services.search_service import search_products

logger = logging.getLogger(__name__)

DEFAULT_MAX_PRODUCTS = 3


class AgentState(TypedDict, total=False):
    # Inputs
    question: str
    history: List[str]
    user_name: str
    language: str
    currency: str
    max_products: int
    analyst_model: str
    # Outputs
    route: Literal["searcher", "refusal"]
    search_query: str
    products: List[dict]
    analysis: str
    status: str  # 'searching' | 'completed' | 'out_of_scope'


REFUSAL_MESSAGES = {
    "tr": "Üzgünüm{name}, ben sadece bir alışveriş asistanıyım. Ürün bulma veya fiyat karşılaştırma konusunda yardımcı olabilirim.",
    "en": "Sorry{name}, I'm only a shopping assistant. I can help you find products or compare prices.",
    "ar": "معذرة{name}، أنا مجرد مساعد تسوق. يمكنني مساعدتك في العثور على المنتجات أو مقارنة الأسعار.",
    "ru": "Извините{name}, я всего лишь помощник по покупкам. Я могу помочь вам найти товары или сравнить цены.",
    "fr": "Désolé{name}, je ne suis qu'un assistant shopping. Je peux vous aider à trouver des produits ou à comparer les prix.",
    "de": "Entschuldigung{name}, ich bin nur ein Shopping-Assistent. Ich kann dir helfen, Produkte zu finden oder Preise zu vergleichen.",
    "es": "Lo siento{name}, solo soy un asistente de compras. Puedo ayudarte a encontrar productos o comparar precios.",
    "it": "Scusa{name}, sono solo un assistente agli acquisti. Posso aiutarti a trovare prodotti o confrontare i prezzi.",
    "zh": "抱歉{name}，我只是一个购物助手。我可以帮您查找产品或比较价格。",
    "ja": "申し訳ありません{name}、私はショッピングアシスタントです。商品の検索や価格の比較をお手伝いできます。",
}

NO_RESULTS_MESSAGES = {
    "tr": "Bu arama için uygun ürün bulamadım. İsteğini biraz farklı ifade etmeyi dener misin?",
    "en": "I couldn't find matching products for this search. Could you try phrasing it differently?",
}

ERROR_MESSAGES = {
    "tr": "Şu an yanıt veremiyorum, lütfen birazdan tekrar dene.",
    "en": "I can't respond right now, please try again shortly.",
}


def localized(messages: Dict[str, str], language: Optional[str]) -> str:
    lang = (language or "tr").lower()
    return messages.get(lang) or messages["en"]


# --- NODES ---

async def router_node(state: AgentState) -> Dict[str, Any]:
    related = await gemini_service.is_shopping_related(state["question"], state.get("history", []))
    return {"route": "searcher" if related else "refusal"}


async def searcher_node(state: AgentState) -> Dict[str, Any]:
    query = await gemini_service.extract_search_query(state["question"], state.get("history", []))
    products = await search_products(
        query,
        state.get("language"),
        state.get("currency"),
        limit=state.get("max_products", DEFAULT_MAX_PRODUCTS),
    )
    return {"search_query": query, "products": products, "status": "searching"}


async def analyst_node(state: AgentState) -> Dict[str, Any]:
    products = state.get("products") or []
    if not products:
        # Don't spend an LLM call analysing nothing.
        return {"analysis": localized(NO_RESULTS_MESSAGES, state.get("language")), "status": "completed"}

    kwargs = {}
    if state.get("analyst_model"):
        kwargs["model_name"] = state["analyst_model"]
    analysis = await gemini_service.analyze_products(
        state["question"],
        products,
        user_name=state.get("user_name", ""),
        currency=state.get("currency") or "TRY",
        language=state.get("language") or "tr",
        history=state.get("history", []),
        **kwargs,
    )
    return {"analysis": analysis, "status": "completed"}


async def refusal_node(state: AgentState) -> Dict[str, Any]:
    name = state.get("user_name")
    template = localized(REFUSAL_MESSAGES, state.get("language"))
    return {"analysis": template.format(name=f" {name}" if name else ""), "status": "out_of_scope"}


# --- GRAPH ---

workflow = StateGraph(AgentState)
workflow.add_node("router", router_node)
workflow.add_node("searcher", searcher_node)
workflow.add_node("analyst", analyst_node)
workflow.add_node("refusal", refusal_node)

workflow.set_entry_point("router")
workflow.add_conditional_edges("router", lambda s: s["route"], {"searcher": "searcher", "refusal": "refusal"})
workflow.add_edge("searcher", "analyst")
workflow.add_edge("analyst", END)
workflow.add_edge("refusal", END)

app_agent = workflow.compile()


async def stream_agent(initial_state: AgentState) -> AsyncGenerator[Dict[str, Any], None]:
    """Run the graph and yield client-facing events.

    Event sequence: routing -> [searching -> thinking(products)] -> completed | out_of_scope.
    Intermediate events carry no `analysis`; only the final event does.
    """
    yield {"status": "routing"}

    products: List[dict] = []
    async for update in app_agent.astream(initial_state, stream_mode="updates"):
        for node, output in update.items():
            output = output or {}
            if node == "router" and output.get("route") == "searcher":
                yield {"status": "searching"}
            elif node == "searcher":
                products = output.get("products", [])
                yield {"status": "thinking", "products": products}
            elif node == "analyst":
                yield {"status": "completed", "analysis": output.get("analysis", ""), "products": products}
            elif node == "refusal":
                yield {"status": "out_of_scope", "analysis": output.get("analysis", "")}
