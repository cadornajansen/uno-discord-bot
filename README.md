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

---

## 🏗️ Architecture & Model Responsibilities

```text
1. Discord RAG Pipeline:
   Discord Server /ask question:<text>
              │
              ▼
        EmbeddingService (embeddinggemma @ /api/embed)
              │
              ▼
        VectorStore (Qdrant search_similar, strictly filtered by current guild_id)
              │
              ▼
        RAGService (formats compact context + untrusted-data safety instructions)
              │
              ▼
        AIService (phi4-mini @ /api/chat) ──> Grounded Answer + Clickable Sources

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
```

---

## 🔒 Security & Privacy Boundaries

1. **Guild Isolation**: Vector retrieval is strictly filtered by the current Discord `guild_id`. Data from one Discord server can **never** be retrieved in another server.
2. **Server-Only `/ask`**: `/ask` commands in Direct Messages (DMs) return a clear message: `"This command currently works inside a server."`
3. **Prompt Injection Boundary**: Retrieved Discord messages and uploaded document contents are injected as untrusted reference data with system instructions forbidding the model from executing commands found inside retrieved text.
4. **Explicit Channel Allowlist**: Messages are only indexed from channels explicitly listed in `INDEXED_CHANNEL_IDS`. If empty, no messages are indexed.
5. **External Web Search Privacy (`/search`)**: `/search` sends **only** the explicit user search query to Serper API to fetch Google search results. Discord guild messages, Qdrant vectors, user profile data, and local AI context are **never** sent with search requests.
6. **Local Document Privacy (`/analyze` & `/docask`)**: File attachments are downloaded temporarily into an OS temporary directory, parsed locally (`pdf-inspector` / `python-pptx`), and deleted immediately. Extracted text is held temporarily in-memory for up to 30 minutes (`DOCUMENT_SESSION_TTL_MINUTES=30`) isolated per user and channel. Document content is **never** sent to disk, Qdrant, Serper, or external AI services.

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
