# SynapCart Backend API

SynapCart projesinin çekirdek API hizmetidir. FastAPI tabanlı bu servis, kullanıcı oturum yönetimi, AI destekli alışveriş asistanı (LangGraph/Gemini entegrasyonu) ve e-posta tabanlı şifre sıfırlama işlevlerini yönetir.

## Teknik Yığın
* **Framework:** FastAPI
* **Veritabanı:** SQLAlchemy (PostgreSQL/SQLite)
* **AI Entegrasyonu:** LangGraph, Google Gemini API
* **Arama Servisi:** Serper.dev (Search API)

## Kurulum ve Başlatma

### 1. Ortam Kurulumu
Gerekli bağımlılıkları yüklemek için terminalde ana dizinde şu komutu çalıştırın:
```bash
pip install -r requirements.txt
```

2. Yapılandırma
Ana dizinde .env adında bir dosya oluşturun ve aşağıdaki değişkenleri kendi sisteminize göre doldurun:

Ini, TOML 
# Proje Ayarları
PROJECT_NAME=SynapCart
SECRET_KEY=your_secret_key
RESET_TOKEN_EXPIRE_HOURS=24

# API Anahtarları
GEMINI_API_KEY=your_gemini_api_key
SERP_API_KEY=your_serper_api_key

# Veritabanı
DATABASE_URL=sqlite:///./synapcart.db

# SMTP (E-posta) Ayarları
SMTP_SERVER=smtp.example.com
SMTP_PORT=587
SMTP_USER=your_email@example.com
SMTP_PASSWORD=your_email_password

# Web Arayüzü Entegrasyonu
APP_FRONTEND_URL=[https://synapcart-web.vercel.app](https://synapcart-web.vercel.app)

3. Sunucuyu Çalıştırma
API sunucusunu başlatmak için aşağıdaki komutu kullanın:

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8001 --reload
```

API Dokümantasyonu
Proje ayağa kalktıktan sonra, API uç noktalarını görüntülemek ve test etmek için tarayıcınızda şu adresi ziyaret edebilirsiniz:

http://localhost:8001/docs
