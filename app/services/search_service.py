from typing import Optional

from app.models.user import User

def get_serp_params(keywords: str, user: Optional[User] = None):

    params = {
        "engine": "google_shopping",
        "q": keywords,
        "hl": "tr",
        "gl": "tr",
        "location": "Turkey"
    }

    if not user:
        return params

    lang_map = {
        "tr": {"hl": "tr", "gl": "tr", "location": "Turkey"},
        "en": {"hl": "en", "gl": "us", "location": "United States"},
        "ar": {"hl": "ar", "gl": "sa", "location": "Saudi Arabia"},
        "ru": {"hl": "ru", "gl": "ru", "location": "Russian Federation"},
        "fr": {"hl": "fr", "gl": "fr", "location": "France"},
        "de": {"hl": "de", "gl": "de", "location": "Germany"},
        "es": {"hl": "es", "gl": "es", "location": "Spain"},
        "it": {"hl": "it", "gl": "it", "location": "Italy"},
        "zh": {"hl": "zh-cn", "gl": "cn", "location": "China"},
        "ja": {"hl": "ja", "gl": "jp", "location": "Japan"}
    }

    user_lang = user.language.lower() if user.language else "tr"

    if user_lang in lang_map:
        params.update(lang_map[user_lang])
    
    if user.currency == "EUR" and user_lang not in ["fr", "de", "es", "it"]:
        params["gl"] = "de"
        params["location"] = "Germany"
    elif user.currency == "USD" and user_lang != "en":
        params["gl"] = "us"
        params["location"] = "United States"

    return params