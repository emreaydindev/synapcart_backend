# SynapCart AI - Backend

SynapCart'ın "beyni" olan bu proje, **FastAPI**, **Gemini API** ve **LangGraph** kullanılarak geliştirilmiş bir AI orkestrasyon merkezidir. Alışveriş süreçlerini optimize etmek için ajan tabanlı bir mimari (Agentic Workflow) kullanır.

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