from typing import TypedDict, Annotated, List
import operator
import httpx
from langgraph.graph import StateGraph, END
from app.core.config import settings
from app.services.gemini_service import get_keywords_from_gemini, analyze_product_performances

class AgentState(TypedDict):
    messages: Annotated[List[str], operator.add]
    products: List[dict]
    analysis: str

# --- NODES ---

async def searcher_node(state: AgentState):
    user_msg = state["messages"][-1]
    
    keywords = await get_keywords_from_gemini(user_msg) 

    params = {
        "engine": "google_shopping",
        "q": keywords,
        "api_key": settings.SERP_API_KEY,
        "hl": "tr",
        "gl": "tr",
        "location": "Turkey"
    }
    
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
    
    return {"products": clean_products, "messages": [f"Aranan terim: {keywords}"]}

async def analyst_node(state: AgentState):
    products_info = str(state["products"])
    response = await analyze_product_performances(products_info)
    
    return {"analysis": response, "messages": ["Analiz tamamlandı."]}

# --- GRAPH SETUP ---

workflow = StateGraph(AgentState)
workflow.add_node("searcher", searcher_node)
workflow.add_node("analyst", analyst_node)

workflow.set_entry_point("searcher")
workflow.add_edge("searcher", "analyst")
workflow.add_edge("analyst", END)

app_agent = workflow.compile()