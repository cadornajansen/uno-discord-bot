# UNO Discord Bot (`uno-discord-bot`)

An open-source Python Discord bot foundation built for our Computer Science college block section. 

The bot is currently being developed and tested inside a private development server before eventual deployment to the main block server.

---

## 📌 Current Phase Status

- [x] **Phase 1 — Core Bot Foundation** (`/ping`, `/hello`, `/userinfo`, `/serverinfo`, `/help`)
- [x] **Phase 2A — Local Ollama AI Integration** (`/ask` slash command via `phi4-mini`)
- [x] **Phase 2B — Controlled Discord Knowledge Ingestion** (Background indexing into Qdrant via `embeddinggemma`)
- [ ] **Phase 2C — Discord Chat RAG** (*Not implemented yet*)

---

## 🏗️ Architecture & Model Responsibilities

```text
Discord
   │
   ├── /ask command ──> AIService ──> Ollama ──> phi4-mini (Chat Generation)
   │
   └── Approved messages ──> Knowledge Cog ──> EmbeddingService ──> Ollama ──> embeddinggemma (Embeddings)
                                                                                       │
                                                                                       ▼
                                                                           VectorStore (Qdrant)
```

- **`phi4-mini`**: Chat / response generation model.
- **`embeddinggemma`**: Dense text vector embedding model.
- **`Qdrant`**: Local vector database (`http://localhost:6333`).

---

## 🔒 Privacy & Ingestion Rules

To protect privacy in our class server:

1. **Explicit Channel Allowlist Only**: Uno does **not** index every channel it can access. Only channels explicitly listed in `INDEXED_CHANNEL_IDS` are indexed.
2. **Empty Allowlist Safety**: If `INDEXED_CHANNEL_IDS` is empty or unset, **no messages are indexed**.
3. **Ignored Content**:
   - Direct Messages (DMs) are ignored.
   - Bot messages are ignored.
   - Webhook messages are ignored.
   - Attachments-only or empty messages are ignored.
   - Historical message backfill is not performed (only live messages received while Uno is running are processed).

---

## 🤖 Local AI & Qdrant Setup

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

Verify Qdrant is running:
- Dashboard: [http://localhost:6333/dashboard](http://localhost:6333/dashboard)
- REST API: `http://localhost:6333`

---

## 🛠️ Discord Developer Portal Setup

1. **Create Application & Bot**: [Discord Developer Portal](https://discord.com/developers/applications).
2. **Enable Message Content Intent**:
   - Go to **Bot** → **Privileged Gateway Intents**.
   - Enable **Message Content Intent** (*required for Phase 2B message ingestion*).
3. **Developer Mode**: In Discord Settings > Advanced, enable **Developer Mode**.
4. **Copy Server & Channel IDs**:
   - Copy your test server ID (`DEV_GUILD_ID`).
   - Right-click an approved test channel → **Copy Channel ID** (`INDEXED_CHANNEL_IDS`).

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

QDRANT_URL=http://localhost:6333
QDRANT_COLLECTION=discord_messages

# Comma-separated allowlist of channel IDs eligible for indexing:
INDEXED_CHANNEL_IDS=123456789012345678
```

### 3. Run Automated Tests

```bash
python -m pytest
```

### 4. Launch Bot

```bash
python main.py
```

---

## 📜 License

Distributed under the [MIT License](LICENSE).
