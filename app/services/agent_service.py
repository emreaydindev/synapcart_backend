from typing import TypedDict, Annotated, List, Optional, Literal
import operator
import httpx
from langgraph.graph import StateGraph, END
from app.core.config import settings
from app.models.user import User
from app.services.gemini_service import (
    get_keywords_from_gemini, 
    analyze_product_performances, 
    is_shopping_related
)
from app.services.search_service import get_serp_params

class AgentState(TypedDict):
    messages: Annotated[List[str], operator.add]
    products: List[dict]
    analysis: str
    user_object: Optional[User]
    status: str        # 'searching', 'out_of_scope', 'completed'

# --- NODES ---

async def refusal_node(state: AgentState):
    user = state.get("user_object")
    lang = user.language if user else "tr"
    name = user.full_name if user and user.full_name else ""
    
    refusal_messages = {
        "tr": f"Üzgünüm {name}, ben sadece alışveriş asistanıyım. Ürün bulma veya fiyat karşılaştırma konusunda yardımcı olabilirim.",
        "en": f"Sorry {name}, I am only a shopping assistant. I can help you with product search or price comparison.",
        "ar": f"معذرة {name}، أنا مجرد مساعد تسوق. يمكنني مساعدتك في العثur على المنتجات أو مقارنة الأسعار.",
        "ru": f"Извините, {name}, я всего лишь помощник по покупкам. Я могу помочь вам найти товары или сравнить цены.",
        "fr": f"Désolé {name}, je ne suis qu'un assistant shopping. Je peux vous aider à trouver des produits ou à comparer les prix.",
        "de": f"Entschuldigung {name}, ich bin nur bir Shopping-Assistent. Ich kann dir helfen, Produkte zu finden oder Preise zu vergleichen.",
        "es": f"Lo siento {name}, solo soy un asistente de compras. Pueden ayudarte a encontrar productos o comparar precios.",
        "it": f"Scusa {name}, sono solo un assistente agli acquisti. Posso aiutarti a trovare prodotti o confrontare i prezzi.",
        "zh": f"抱歉 {name}，我只是一个购物助手。我可以帮您查找产品或比较价格。",
        "ja": f"申し訳ありません {name}、私はショッピングアシスタントです。商品の検索や価格の比較をお手伝いできます。"
    }
    
    response = refusal_messages.get(lang, refusal_messages["en"])
    return {"analysis": response, "status": "out_of_scope"}

async def searcher_node(state: AgentState):
    user_msg = state["messages"][-1]
    
    keywords = await get_keywords_from_gemini(user_msg) 

    params = get_serp_params(keywords, state.get("user_object"))
    params["api_key"] = settings.SERP_API_KEY
    
    async with httpx.AsyncClient() as client:
        response = await client.get("https://serpapi.com/search", params=params)
        raw_results = response.json().get("shopping_results", [])[:3]
    
    clean_products = []
    for item in raw_results:
        clean_products.append({
            "title": item.get("title"),
            "price": item.get("extracted_price"),
            "source": item.get("source"),
            "link": item.get("product_link"),
            "thumbnail": item.get("thumbnail")
        })
    
    return {
        "products": clean_products, 
        "messages": [f"Aranan terim: {keywords}"],
        "status": "searching"
    }

async def router_node(state: AgentState):
    last_message = state["messages"][-1]
    
    message_text = last_message.content if hasattr(last_message, 'content') else last_message
    
    is_related = await is_shopping_related(message_text)
    
    if is_related:
        return "searcher"
    return "refusal"

async def analyst_node(state: AgentState):
    products_info = str(state["products"])
    user = state.get("user_object")
    
    name = user.full_name if user and user.full_name else "Misafir"
    currency = user.currency if user else "TRY"
    
    prompt = (
        f"Kullanıcı Adı: {name}. Tercih Edilen Para Birimi: {currency}. "
        f"Lütfen ürünleri analiz et ve kullanıcı misafir değilse ismiyle hitap ederek öneride bulun: {products_info}"
    )
    
    response = await analyze_product_performances(prompt)
    return {"analysis": response, "status": "completed"}

# --- GRAPH SETUP ---

workflow = StateGraph(AgentState)

workflow.add_node("searcher", searcher_node)
workflow.add_node("analyst", analyst_node)
workflow.add_node("refusal", refusal_node)

workflow.set_conditional_entry_point(
    router_node,
    {
        "searcher": "searcher",
        "refusal": "refusal"
    }
)

workflow.add_edge("searcher", "analyst")
workflow.add_edge("analyst", END)
workflow.add_edge("refusal", END)

app_agent = workflow.compile()