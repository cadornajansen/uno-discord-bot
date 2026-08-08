# UNO Discord Bot (`uno-discord-bot`)

An open-source Python Discord bot foundation built for our Computer Science college block section. 

The bot is currently being developed and tested inside a private development server before eventual deployment to the main block server.

---

## 📌 Current Phase Status

- [x] **Phase 1 — Core Bot Foundation** (`/ping`, `/hello`, `/userinfo`, `/serverinfo`, `/help`)
- [x] **Phase 2A — Local Ollama AI Integration** (`/ask` slash command via `phi4-mini`)
- [x] **Phase 2B — Controlled Discord Knowledge Ingestion** (Background indexing into Qdrant via `embeddinggemma`)
- [x] **Phase 2C — Discord Chat RAG Integration** (Grounded `/ask` answers using retrieved server messages)
- [x] **Phase 3 — Discord Knowledge Synchronization** (Live edit sync, delete sync, and historical backfill script)
- [x] **Phase 4A — Academic Search via Serper** (`/search` slash command returning organic Google results)
- [x] **Phase 4B — Local Document Analysis: PDF + PPTX** (`/analyze` slash command for local document summarization)
- [x] **Phase 4C — Temporary Document Q&A** (`/docask` slash command for interactive document questions)
- [x] **Phase 5A — Academic Schedule + Professor Lookup** (`/today`, `/schedule`, `/nextclass`, `/prof` offline commands)
- [x] **Phase 6A — Weather Forecast + PAGASA Alerts + Disruption Risk** (`/weather` slash command)
- [x] **Phase 6B — Local Image OCR Ingestion for Homework Channels** (RapidOCR + ONNX Runtime image text extraction)

---

## 🏗️ Architecture & Model Responsibilities

```text
1. Discord RAG Pipeline & Image OCR Ingestion:
   Discord Server Message / Homework Attachment (.png, .jpg, .jpeg, .webp)
              │
              ▼
        KnowledgeCog / Ingestion Pipeline (checks INDEXED_CHANNEL_IDS & OCR_CHANNEL_IDS)
              │
              ├─► Image Attachment? ──> OCRService (RapidOCR + ONNX Runtime) ──> Extracted OCR Text
              │                                                                         │
              └─────────────── Combined Text Content ◄──────────────────────────────────┘
                                      │
                                      ▼
                        EmbeddingService (embeddinggemma @ /api/embed)
                                      │
                                      ▼
                        VectorStore (Qdrant Point with stable Discord Message ID)

2. External Search Pipeline:
   Discord Server /search query:<text>
              │
              ▼
        SearchCog ──> SearchService ──> Serper API ──> Organic Google Results

3. Local Document Analysis & Interactive Q&A Pipeline:
   Discord Server /analyze file:<attachment>
              │
              ▼
        DocumentsCog (validates .pdf / .pptx extension & 15 MB size limit)
              │
              ▼
        DocumentService ──> Extracted Markdown (max 20,000 chars)
              │
              ├─► AIService (phi4-mini) ──> Document Summary
              │
              └─► DocumentSessionService (In-memory storage key: guild_id, channel_id, user_id; 30 min TTL)

   Discord Server /docask question:<text>
              │
              ▼
        Retrieve Active DocumentSession ──> AIService (phi4-mini) ──> Grounded Document Answer

4. Offline Academic Schedule & Professor Lookup Pipeline:
   Discord Server /today, /schedule, /nextclass, /prof
              │
              ▼
        AcademicsCog ──> AcademicScheduleService
              │
              ▼
        data/academics/{school_year}/semester-{semester}.json (Local Offline Data)

5. Weather Forecast & Disruption Risk Pipeline:
   Discord Server /weather
              │
              ▼
        WeatherCog ──> WeatherService
              │
              ├──► OpenMeteoClient (Current & Hourly Forecast)
              ├──► PagasaAlertClient (Official PAGASA NCR-PRSD Regional Forecast & Warnings)
              └──► WeatherRiskService (Deterministic LOW / MODERATE / HIGH Disruption Risk)
```

---

## 🔒 Security & Privacy Boundaries

1. **Guild Isolation**: Vector retrieval is strictly filtered by the current Discord `guild_id`. Data from one Discord server can **never** be retrieved in another server.
2. **Server-Only `/ask`**: `/ask` commands in Direct Messages (DMs) return a clear message: `"This command currently works inside a server."`
3. **Prompt Injection Boundary**: Retrieved Discord messages and uploaded document contents are injected as untrusted reference data with system instructions forbidding the model from executing commands found inside retrieved text.
4. **Explicit Channel Allowlist**: Messages are only indexed from channels explicitly listed in `INDEXED_CHANNEL_IDS`. If empty, no messages are indexed.
5. **Local Image OCR (`OCR_CHANNEL_IDS`)**: Image text extraction is performed **locally** using RapidOCR and ONNX Runtime only for supported image attachments (`.png`, `.jpg`, `.jpeg`, `.webp` up to 8 MB) in channels explicitly listed in both `INDEXED_CHANNEL_IDS` and `OCR_CHANNEL_IDS`. Image OCR is intended for assignment and homework screenshots containing text. Uno cannot understand arbitrary visual diagrams or photos from OCR alone. Images are processed strictly in-memory / locally and are **never** sent to cloud OCR services, Firecrawl, OpenAI, Gemini, or external vision models.
6. **External Web Search Privacy (`/search`)**: `/search` sends **only** the explicit user search query to Serper API to fetch Google search results. Discord guild messages, Qdrant vectors, user profile data, and local AI context are **never** sent with search requests.
7. **Local Document Privacy (`/analyze` & `/docask`)**: File attachments are downloaded temporarily into an OS temporary directory, parsed locally (`pdf-inspector` / `python-pptx`), and deleted immediately. Extracted text is held temporarily in-memory for up to 30 minutes (`DOCUMENT_SESSION_TTL_MINUTES=30`) isolated per user and channel. Document content is **never** sent to disk, Qdrant, Serper, or external AI services.
8. **Offline Academic Schedule (`/today`, `/schedule`, `/nextclass`, `/prof`)**: Schedule data is loaded directly from local JSON files (`data/academics/`) without any database, external API calls, or AI LLM processing. For details on customizing or adding schedule data for your school, see [`data/academics/README.md`](data/academics/README.md).
9. **Weather Privacy (`/weather`)**: Uses public configured campus coordinates (`WEATHER_LATITUDE=14.5869`, `WEATHER_LONGITUDE=120.9762`, `"Manila (PLM)"`). Open-Meteo receives only the configured latitude/longitude. PAGASA receives a standard HTTP GET request to its public NCR regional forecast page (`PAGASA_NCR_URL`). No user geolocation, Discord chat history, user profiles, or Qdrant data is collected or transmitted.
10. **Class Suspension Disclaimer**: Uno's Weather Disruption Risk level (`LOW`, `MODERATE`, `HIGH`) is a deterministic heuristic estimate based on weather conditions and official PAGASA warnings. Uno **never** claims that classes are officially suspended. Class suspension decisions rest solely with official university and government authorities.

---

## 🤖 Local AI, Qdrant & Serper Setup

### 1. Ollama Models Setup
Ensure Ollama is installed ([https://ollama.com](https://ollama.com)), then pull both models:

```bash
# Pull chat model
ollama pull phi4-mini

# Pull embedding model
ollama pull embeddinggemma
```

### 2. Qdrant Vector Database Setup
Run Qdrant locally using Docker:

```bash
# Create persistent storage volume
docker volume create uno_qdrant_storage

# Run Qdrant container
docker run -d --name uno-qdrant \
  -p 6333:6333 \
  -p 6334:6334 \
  -v uno_qdrant_storage:/qdrant/storage \
  qdrant/qdrant
```

### 3. Serper Web Search API Setup
Sign up for a free API key at [https://serper.dev](https://serper.dev) to enable the `/search` command.

---

## 🚀 Environment Configuration & Execution

### 1. Virtual Environment Setup

```bash
git clone https://github.com/your-username/uno-discord-bot.git
cd uno-discord-bot

python -m venv .venv

# Activate on Windows:
.venv\Scripts\activate

# Activate on Linux / macOS:
source .venv/bin/activate

# Install dependencies in editable mode
pip install -e ".[dev]"
```

### 2. Configure Environment (`.env`)

Copy `.env.example` to `.env`:

```bash
cp .env.example .env
```

Edit `.env`:

```env
DISCORD_TOKEN=your_bot_token_here
DEV_GUILD_ID=your_test_server_id_here

OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=phi4-mini
OLLAMA_EMBEDDING_MODEL=embeddinggemma
OLLAMA_TIMEOUT_SECONDS=180.0

QDRANT_URL=http://localhost:6333
QDRANT_COLLECTION=discord_messages

# Comma-separated allowlist of channel IDs eligible for indexing:
INDEXED_CHANNEL_IDS=123456789012345678

# RAG Configuration
RAG_TOP_K=5
RAG_MIN_SCORE=0.30

# Serper Search Configuration
SERPER_API_KEY=your_serper_api_key_here
SERPER_BASE_URL=https://google.serper.dev
SEARCH_RESULT_LIMIT=5

# Document Analysis Configuration
DOCUMENT_MAX_SIZE_MB=15
DOCUMENT_MAX_CHARS=20000
DOCUMENT_SESSION_TTL_MINUTES=30

# Academic Schedule Configuration
ACADEMIC_SCHOOL_YEAR=2026-2027
ACADEMIC_SEMESTER=1
ACADEMIC_TIMEZONE=Asia/Manila

# Weather Configuration
WEATHER_LATITUDE=14.5869
WEATHER_LONGITUDE=120.9762
WEATHER_LOCATION_NAME=Manila (PLM)
WEATHER_TIMEZONE=Asia/Manila
PAGASA_NCR_URL=https://www.pagasa.dost.gov.ph/regional-forecast/ncrprsd
```

### 3. Run Automated Tests

```bash
python -m pytest
```

### 4. Developer CLI Scripts

- **Semantic Search Test**:
  ```bash
  python scripts/test_semantic_search.py "When is the data structures quiz?"
  ```
- **Historical Message Backfill**:
  ```bash
  python scripts/backfill_discord_history.py --limit 200
  ```

### 5. Launch Bot

```bash
python main.py
```

---

## 📜 License

Distributed under the [MIT License](LICENSE).
