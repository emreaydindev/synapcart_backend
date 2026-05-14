from typing import Optional

from app.models.user import User

def get_system_prompt(user: Optional[User] = None):
    name_str = f"Adı: {user.full_name}" if user and user.full_name else "Misafir"
    lang_str = "Türkçe" if not user or user.language == "tr" else "English"
    curr_str = user.currency if user else "TRY"

    return (
        f"Sen profesyonel bir alışveriş asistanısın. Şu anki kullanıcı: {name_str}. "
        f"Lütfen cevaplarını {lang_str} dilinde ver ve fiyat analizlerini {curr_str} üzerinden yap. "
        "Kullanıcıya ismiyle hitap ederek samimi ama profesyonel bir dil kullan."
    )