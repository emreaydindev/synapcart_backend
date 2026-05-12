import google.generativeai as genai
from app.core.config import settings

genai.configure(api_key=settings.GEMINI_API_KEY)
model = genai.GenerativeModel('gemini-2.5-flash-lite')

async def get_chat_response(prompt: str):
    response = await model.generate_content_async(prompt)
    return response.text

async def get_keywords_from_gemini(user_msg: str):
    prompt = f"""Sen uzman bir alışveriş asistanısın. Kullanıcının şu isteğini analiz et: '{user_msg}'
    Bu bütçe ve ihtiyaçlara en uygun olan spesifik 1 adet ürün modelini (Örneğin 'iPad 10. Nesil' veya 'iPad Air 5') belirle.
    Google Shopping'de aratmak için SADECE bu ürünün adını dön. 
    Fiyat, öğrenci, kalem, oyun gibi kelimeleri arama teriminden KESİNLİKLE ÇIKAR. Sadece net ürün modelini yaz."""
    
    response = await get_chat_response(prompt)
    return response.strip()

async def analyze_product_performances(products_info: str):
    prompt = f"Şu ürünleri fiyat/performans açısından analiz et ve kısa bir özet çıkar: {products_info}"
    response = await model.generate_content_async(prompt)
    return response.text