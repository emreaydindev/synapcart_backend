# SynapCart AI - Backend 🛒🤖

SynapCart'ın "beyni" olan bu proje, **FastAPI**, **Gemini API** ve **LangGraph** kullanılarak geliştirilmiş bir AI orkestrasyon merkezidir. Alışveriş süreçlerini optimize etmek için ajan tabanlı bir mimari (Agentic Workflow) kullanır.

## 🛠 Teknik Mimari
Proje **Clean Architecture** prensiplerine göre yapılandırılmıştır:
- **API Katmanı:** Dış dünya ile iletişim kuran FastAPI endpointleri.
- **Service Katmanı:** LangGraph ajanlarının ve iş mantığının bulunduğu katman.
- **Core:** Yapılandırma ve güvenlik ayarları.
- **Schemas & Models:** Veri doğrulama (Pydantic) ve veritabanı (SQLAlchemy) tanımları.

## 🧠 Agentic AI Yapısı
Uygulama, karmaşık alışveriş görevlerini alt görevlere bölen bir ajan ağını yönetir:
1. **Araştırmacı Ajan:** API'lar üzerinden ürün verilerini toplar.
2. **Analist Ajan:** Kullanıcı yorumlarındaki duyguları (Sentiment Analysis) inceler.
3. **Karar Verici Ajan:** Elde edilen verileri sentezleyerek kullanıcıya en doğru ürünü önerir.

## 🚀 Hızlı Başlangıç

### 1. Bağımlılıkları Yükleyin
```bash
pip install -r requirements.txt

```

### 2. Ortam Değişkenlerini Ayarlayın

`.env` dosyasını ana dizinde oluşturun ve Gemini API anahtarınızı ekleyin:

```text
GEMINI_API_KEY=your_api_key_here
PROJECT_NAME=SynapCart

```

### 3. Sunucuyu Başlatın

```bash
python -m uvicorn app.main:app --reload --port 8001

```

## 📡 API Dokümantasyonu

Sunucu çalıştıktan sonra otomatik oluşan dokümantasyona şuradan ulaşabilirsiniz:

* **Swagger UI:** `http://127.0.0.1:8001/docs`