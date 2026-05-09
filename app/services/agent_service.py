from typing import TypedDict, Annotated, List
import operator
import google.generativeai as genai
from langgraph.graph import StateGraph, END
from app.core.config import settings

# Gemini Configuration
genai.configure(api_key=settings.GEMINI_API_KEY)
model = genai.GenerativeModel('gemini-2.5-flash-lite')

class AgentState(TypedDict):
    messages: Annotated[List[str], operator.add]
    products: List[dict]
    analysis: str

# --- NODES ---

async def searcher_node(state: AgentState):
    # Gemini burada "Arama Stratejisti" rolünde
    user_msg = state["messages"][-1]
    prompt = f"Kullanıcı şunu arıyor: '{user_msg}'. Bu arama için en iyi 3 teknik anahtar kelimeyi virgülle ayırarak yaz."
    
    response = await model.generate_content_async(prompt)
    keywords = response.text
    
    # Şimdilik örnek veri, ileride SerpApi buraya gelecek
    mock_products = [
        {"name": "Profesyonel Koşu Ayakkabısı", "price": "2100 TL", "desc": "Karbon taban"},
        {"name": "Günlük Yürüyüş Ayakkabısı", "price": "1200 TL", "desc": "Hafif yapı"}
    ]
    return {
        "products": mock_products, 
        "messages": [f"Aranan kelimeler: {keywords}. Ürünler listelendi."]
    }

async def analyst_node(state: AgentState):
    products_info = str(state["products"])
    prompt = f"Şu ürünleri fiyat/performans açısından analiz et ve kısa bir özet çıkar: {products_info}"
    
    response = await model.generate_content_async(prompt)
    return {"analysis": response.text, "messages": ["Analiz tamamlandı."]}

#Graphic Setup

workflow = StateGraph(AgentState)
workflow.add_node("searcher", searcher_node)
workflow.add_node("analyst", analyst_node)

workflow.set_entry_point("searcher")
workflow.add_edge("searcher", "analyst")
workflow.add_edge("analyst", END)

app_agent = workflow.compile()