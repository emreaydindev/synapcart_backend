# SynapCart Backend API

SynapCart projesinin çekirdek API hizmetidir. FastAPI tabanlı bu servis, kullanıcı oturum yönetimi, AI destekli alışveriş asistanı (LangGraph + Gemini) ve e-posta tabanlı şifre sıfırlama işlevlerini yönetir.

## Teknik Yığın

- **Framework:** FastAPI
- **Veritabanı:** SQLAlchemy + Alembic (PostgreSQL / SQLite)
- **AI Entegrasyonu:** LangGraph, Google Gemini (`google-genai`)
- **Arama Servisi:** SerpAPI (Google Shopping)

## Kurulum ve Başlatma

### 1. Ortam Kurulumu

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
```

### 2. Yapılandırma

`.env.example` dosyasını `.env` olarak kopyalayın ve değerleri doldurun:

```bash
cp .env.example .env
```

Zorunlu anahtarlar: `SECRET_KEY`, `DATABASE_URL`, `GEMINI_API_KEY`, `SERP_API_KEY`, `SMTP_USER`, `SMTP_PASSWORD`.
`ENV=prod` olduğunda `SECRET_KEY` en az 32 karakter olmalıdır ve `/docs` kapatılır.

### 3. Veritabanı

Şema Alembic ile yönetilir. Geliştirme ortamında (`AUTO_MIGRATE=true`, varsayılan) migrasyonlar uygulama açılışında otomatik çalışır. Elle çalıştırmak için:

```bash
python -m app.db.migrate
```

Eski `create_all` ile oluşturulmuş veritabanları otomatik olarak baseline'a işaretlenir ve sadece yeni migrasyonlar uygulanır.

Yeni bir model değişikliği için:

```bash
alembic revision --autogenerate -m "aciklama"
```

### 4. Sunucuyu Çalıştırma

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8001 --reload
```

API dokümantasyonu: http://localhost:8001/docs

### 5. Testler

```bash
pytest
```

Testler SQLite kullanır; Gemini ve SerpAPI çağrıları taklit edilir (gerçek API anahtarı gerekmez).

## Deploy (Render)

`render.yaml` bir Render Blueprint'idir: migrasyonları çalıştırır, ardından `uvicorn`'u proxy başlıklarına güvenerek başlatır (rate limit gerçek istemci IP'sini görsün diye). Gizli anahtarlar Render panelinden girilir.
