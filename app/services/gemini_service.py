import google.generativeai as genai
from app.core.config import settings

genai.configure(api_key=settings.GEMINI_API_KEY)

async def get_chat_response(prompt: str):
    model = genai.GenerativeModel('gemini-2.5-flash-lite')
    response = await model.generate_content_async(prompt)
    return response.text