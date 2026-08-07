# Uno Discord Bot

[![Python 3.12+](https://img.shields.io/badge/Python-3.12%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![discord.py](https://img.shields.io/badge/discord.py-2.3.2%2B-5865F2?logo=discord&logoColor=white)](https://discordpy.readthedocs.io/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

A privacy-conscious Discord assistant for a Computer Science class community. Uno runs its AI stack locally, indexes messages only from explicitly approved channels, and answers `/ask` questions with server-scoped context.

> **Current status:** The core AI/RAG MVP is complete. Discord foundations, local Ollama chat, controlled message ingestion, and guild-isolated retrieval-augmented generation are implemented and covered by 39 tests.

## Features

- Slash commands for bot health, greetings, user details, server details, and help
- Local AI responses through Ollama using `phi4-mini`
- Controlled message ingestion from an explicit channel allowlist
- Local embeddings through Ollama using `embeddinggemma`
- Semantic message storage and retrieval with Qdrant
- Guild-isolated RAG answers with configurable result count and score threshold
- Lightweight message references when retrieved context is used
- Plain-AI fallback when embedding or vector retrieval is unavailable
- Prompt-injection boundary that treats retrieved messages as untrusted data

## Commands

| Command | Description |
| --- | --- |
| `/ask question:<text>` | Ask Uno a question using relevant context from the current server when available. |
| `/ping` | Check the bot's Discord WebSocket latency. |
| `/hello` | Receive a greeting. |
| `/userinfo [member]` | View public account details for yourself or another member. |
| `/serverinfo` | View details about the current server. |
| `/help` | List the available utility commands. |

## Architecture

```text
Approved Discord message
  -> embeddinggemma (Ollama)
  -> Qdrant collection

/ask question
  -> embeddinggemma query embedding
  -> Qdrant similarity search filtered by guild_id
  -> RAGService score filtering and context formatting
  -> phi4-mini (Ollama)
  -> answer with lightweight sources
```

The main responsibilities are intentionally small:

- `KnowledgeCog` decides which new messages may be indexed.
- `EmbeddingService` creates vectors through Ollama's `/api/embed` endpoint.
- `VectorStore` stores and searches vectors in Qdrant.
- `RAGService` retrieves server-scoped context and coordinates the answer.
- `AIService` generates the final response through Ollama's `/api/chat` endpoint.

## Stack

- Python 3.12+
- [discord.py](https://discordpy.readthedocs.io/) for Discord events and slash commands
- [Ollama](https://ollama.com/) with `phi4-mini` and `embeddinggemma`
- [Qdrant](https://qdrant.tech/) for vector storage and similarity search
- `httpx` for asynchronous Ollama requests
- `pytest` for automated tests

## Setup

### 1. Create and configure a Discord bot

1. Create an application in the [Discord Developer Portal](https://discord.com/developers/applications).
2. Open **Bot** -> **Privileged Gateway Intents** and enable **Message Content Intent**. This is required for reading messages in approved indexing channels.
3. Invite the bot to a development server with permission to view channels, read message history, send messages, and use application commands.
4. Enable Discord **Developer Mode**, then copy the development server ID and each channel ID that may be indexed.

### 2. Install the project

```bash
git clone https://github.com/cadornajansen/uno-discord-bot.git
cd uno-discord-bot
python -m venv .venv
```

Activate the virtual environment:

```powershell
# Windows PowerShell
.venv\Scripts\Activate.ps1
```

```bash
# Linux or macOS
source .venv/bin/activate
```

Install the application and development dependencies:

```bash
python -m pip install -e ".[dev]"
```

### 3. Start Ollama

Install [Ollama](https://ollama.com/), ensure its local service is running, and pull both models:

```bash
ollama pull phi4-mini
ollama pull embeddinggemma
```

### 4. Start Qdrant

The following Docker commands run Qdrant locally with persistent storage:

```bash
docker volume create uno_qdrant_storage
docker run -d --name uno-qdrant \
  -p 6333:6333 \
  -p 6334:6334 \
  -v uno_qdrant_storage:/qdrant/storage \
  qdrant/qdrant
```

### 5. Configure environment variables

Copy `.env.example` to `.env`, then replace the placeholder values:

```powershell
# Windows PowerShell
Copy-Item .env.example .env
```

```bash
# Linux or macOS
cp .env.example .env
```

| Variable | Required | Default | Purpose |
| --- | --- | --- | --- |
| `DISCORD_TOKEN` | Yes | None | Discord bot token. Never commit this value. |
| `DEV_GUILD_ID` | No | Global sync | Development server for immediate slash-command syncing. |
| `OLLAMA_BASE_URL` | No | `http://localhost:11434` | Ollama service URL. |
| `OLLAMA_MODEL` | No | `phi4-mini` | Chat model used to generate answers. |
| `OLLAMA_EMBEDDING_MODEL` | No | `embeddinggemma` | Model used to embed messages and questions. |
| `QDRANT_URL` | No | `http://localhost:6333` | Qdrant service URL. |
| `QDRANT_COLLECTION` | No | `discord_messages` | Qdrant collection name. |
| `INDEXED_CHANNEL_IDS` | No | Empty | Comma-separated channel allowlist. Empty means no messages are indexed. |
| `RAG_TOP_K` | No | `5` | Maximum number of retrieved message candidates. |
| `RAG_MIN_SCORE` | No | `0.30` | Minimum similarity score accepted as context, from `0.0` to `1.0`. |

Example:

```env
DISCORD_TOKEN=your_bot_token_here
DEV_GUILD_ID=123456789012345678

OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=phi4-mini
OLLAMA_EMBEDDING_MODEL=embeddinggemma

QDRANT_URL=http://localhost:6333
QDRANT_COLLECTION=discord_messages

INDEXED_CHANNEL_IDS=123456789012345678,987654321098765432
RAG_TOP_K=5
RAG_MIN_SCORE=0.30
```

### 6. Run Uno

```bash
python main.py
```

With `DEV_GUILD_ID` set, slash commands sync to that server immediately. Without it, commands sync globally and may take longer to appear.

## Privacy and security

- **Explicit collection:** Uno indexes only non-empty, human-authored messages from channels in `INDEXED_CHANNEL_IDS`. Direct messages, bot messages, and webhook messages are ignored.
- **Server isolation:** `/ask` retrieval is always filtered by the current Discord `guild_id`; the command is unavailable in DMs.
- **Local services:** Ollama and Qdrant default to local endpoints. Discord message content is not sent to a hosted AI provider by this project.
- **Untrusted context:** Retrieved messages are provided to the model as reference material, never as instructions.
- **Secret handling:** `.env` is ignored by Git. Do not commit Discord tokens or expose an unsecured Qdrant instance publicly.
- **Data lifecycle:** Edited and deleted message synchronization is not implemented yet. See the roadmap before using Uno in a production server.

Server operators should disclose what channels are indexed, obtain any consent required by their community or jurisdiction, and restrict bot and database access appropriately.

## Testing

Run the automated test suite:

```bash
python -m pytest
```

Check that all Python modules compile:

```bash
python -m compileall bot config main.py scripts
```

With Ollama, Qdrant, and a configured `.env` running, verify semantic retrieval manually:

```bash
python scripts/test_semantic_search.py "When is the data structures quiz?"
```

## Roadmap

The core MVP is complete. The next planned work is knowledge correctness and runtime hardening:

- synchronize edited Discord messages with Qdrant
- remove deleted Discord messages from Qdrant
- optionally backfill approved channel history
- improve source links and end-to-end prompt-injection coverage
- add startup health checks, retry behavior, and cleaner service shutdown
- prepare secure production configuration and deployment

Internet search, weather, schedules, reminders, conversation memory, and admin configuration are deferred features, not part of the current MVP.

## License

Licensed under the [MIT License](LICENSE).
