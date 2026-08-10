<div align="center">

![Uno AI Banner](uno-banner.png)

# 🤖 Uno AI (`uno-discord-bot`)

**The local-first Discord AI assistant built for BSCS 1-4**  
*Pamantasan ng Lungsod ng Maynila (PLM)*

[![Python 3.14](https://img.shields.io/badge/Python-3.14-3776AB?style=flat-square&logo=python&logoColor=white)](https://python.org)
[![Discord.py](https://img.shields.io/badge/Discord.py-2.3+-5865F2?style=flat-square&logo=discord&logoColor=white)](https://discordpy.readthedocs.io/)
[![Ollama Local AI](https://img.shields.io/badge/Ollama-phi4--mini-000000?style=flat-square&logo=ollama&logoColor=white)](https://ollama.com)
[![Qdrant Vector DB](https://img.shields.io/badge/Qdrant-Vector--DB-DC2626?style=flat-square&logo=qdrant&logoColor=white)](https://qdrant.tech)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg?style=flat-square)](LICENSE)

</div>

---

## 👋 Welcome Freshmen! What is Uno AI?

**Uno AI** is a smart, nonchalant Discord bot designed specifically for our Computer Science college block section (**BSCS 1-4**).

Unlike typical bots that send your messages to cloud data centers (like ChatGPT or Gemini), **Uno AI runs 100% locally** on a regular computer. It reads class announcements, scans homework screenshots, keeps track of our schedule, and answers questions -- all without sending your data to external servers or consuming massive cloud data center resources.

---

## ⚡ Quick Command Reference

Uno AI supports both **Slash Commands (`/`)** and **Prefix Commands (`!`)**. Commands work identically in both formats!

### 🤖 AI & Knowledge Retrieval
| Slash Command | Prefix Alias | What It Does |
|---|---|---|
| `/ask question:<text>` | `!ask <question>` | Ask Uno AI anything! Uses class message memory & OCR homework notes when relevant. |
| `/search query:<text>` | `!search <query>` | Search Google for programming docs or academic topics (returns clean, preview-free links). |

### 📄 Document Analysis (Slash-Only)
| Slash Command | What It Does |
|---|---|
| `/analyze file:<attachment>` | Upload a PDF or PPTX slide deck to get an instant AI summary. |
| `/docask question:<text>` | Ask follow-up questions grounded strictly in your uploaded document. |

### 📅 Academic Schedule & Professors
| Slash Command | Prefix Alias | What It Does |
|---|---|---|
| `/today` | `!today` | Show today's class schedule, room assignments, and times. |
| `/schedule` | `!schedule` | Display the full weekly section schedule. |
| `/nextclass` | `!nextclass` | View the next upcoming class for today. |
| `/prof subject:<name>` | `!prof <subject>` | Look up instructor name, email, and subject details. |

### ⛅ Weather & Disruption Risk
| Slash Command | Prefix Alias | What It Does |
|---|---|---|
| `/weather` | `!weather` | Real-time weather, 6-hour forecast, official PAGASA NCR warnings, and class disruption risk (*LOW*, *MODERATE*, *HIGH*). |

### ⚙️ General & Info
| Slash Command | Prefix Alias | What It Does |
|---|---|---|
| `/about` | `!about` | Learn how Uno AI works and why local AI matters. |
| `/help` | `!help` | Open the interactive command guide. |
| `/ping` | `!ping` | Check bot connection latency. |
| `/userinfo` | `!userinfo` | View public account details. |
| `/serverinfo` | `!serverinfo` | View server metadata. |

---

## 💡 Casual Chat & Mention Feature

You don't always need to run a command!
- **`@Uno AI` in chat**: Tag Uno AI anywhere in a channel and it will reply contextually.
- **Reply to Uno AI**: Reply to any message sent by Uno AI, and it will read the last 10 messages in the channel to understand the conversation flow and give a natural, nonchalant answer.

---

## 🧩 How Uno AI Works (Under the Hood)

Here is how the system works in simple terms:

```text
                                  +---------------------------------------+
                                  |            Discord Client             |
                                  +-------------------+-------------------+
                                                      |
                                                      v
                                        +---------------------------+
                                        |  UnoDiscordBot (client.py)|
                                        +-------------+-------------+
                                                      |
         +-------------------+------------------------+-----------------------+-------------------+
         |                   |                        |                       |                   |
         v                   v                        v                       v                   v
  +--------------+   +---------------+        +---------------+       +---------------+   +---------------+
  |   AICog      |   | KnowledgeCog  |        |  MentionsCog  |       |  AcademicsCog |   |  WeatherCog   |
  | (/ask, !ask) |   |  (Ingestion)  |        | (@Uno AI &    |       | (/today,      |   |  (/weather,   |
  +------+-------+   +-------+-------+        |   replies)    |       |  /schedule)   |   |   !weather)   |
         |                   |                +-------+-------+       +-------+-------+   +-------+-------+
         |                   |                        |                       |                   |
         v                   v                        v                       v                   v
  +--------------+   +---------------+        +---------------+       +---------------+   +---------------+
  | RAGService   |   |  OCRService   |        | RAG + 10-Msg  |       | Local JSON    |   | Open-Meteo +  |
  | (Vector Search   | (RapidOCR +   |        | Channel Hist  |       | Schedule Data |   | PAGASA Parser |
  |  + Grounded) |   |  ONNX Local)  |        +-------+-------+       +---------------+   +---------------+
  +------+-------+   +-------+-------+                |
         |                   |                        |
         +-------------------+------------------------+
                             |
                             v
               +---------------------------+
               | VectorStore (Qdrant DB)   |
               | & Ollama (phi4-mini)      |
               +---------------------------+
```

1. 🧠 **Ollama (`phi4-mini`)**: The local AI brain running on CPU/GPU. It generates text answers locally without any cloud subscription.
2. 📦 **Qdrant Vector Database**: A local database that converts text into mathematical numbers (embeddings via `embeddinggemma`). This acts as Uno AI's memory vault for past class messages.
3. 👁️ **RapidOCR (Local OCR)**: Scans homework images (`.png`, `.jpg`) posted in approved homework channels and extracts the text so `/ask` can recall assignments from screenshots.
4. ⛅ **Open-Meteo & PAGASA Scraper**: Pulls live Manila weather data and scrapes official PAGASA NCR-PRSD rainfall/thunderstorm warnings to compute class disruption risk.

---

## 🔒 Security & Privacy Guarantees

- **100% Local & Private**: Your messages are stored locally in Qdrant. They are **never** sent to OpenAI, Google, Anthropic, or any third-party AI provider.
- **Guild Isolation**: Knowledge indexed in one Discord server can **never** be accessed or retrieved in another server.
- **Allowlisted Channels**: Uno AI only indexes messages from channels explicitly specified in `INDEXED_CHANNEL_IDS`.
- **Command Disconnection**: Commands (like `!ask` or `/search`) are excluded from Qdrant indexing so bot prompts are never re-indexed as knowledge.

---

## 💻 Developer Setup Guide (How to Run Locally)

Want to run Uno AI on your own computer or contribute code? Follow these steps:

### 1. Prerequisites
- **Python 3.11+** installed
- **Docker Desktop** installed (for Qdrant)
- **Ollama** installed ([ollama.com](https://ollama.com))

### 2. Pull Required Ollama Models

```bash
# Pull the chat model
ollama pull phi4-mini

# Pull the embedding model
ollama pull embeddinggemma
```

### 3. Start Qdrant Vector Database

```bash
docker volume create uno_qdrant_storage

docker run -d --name uno-qdrant \
  -p 6333:6333 \
  -v uno_qdrant_storage:/qdrant/storage \
  qdrant/qdrant
```

### 4. Clone & Setup Project Environment

```bash
git clone https://github.com/cadornajansen/uno-discord-bot.git
cd uno-discord-bot

# Create and activate virtual environment
python -m venv .venv
.venv\Scripts\activate       # On Windows
# source .venv/bin/activate  # On Linux/macOS

# Install dependencies
pip install -e ".[dev]"
```

### 5. Configure `.env` File

Copy `.env.example` to `.env`:

```bash
cp .env.example .env
```

Fill in your `.env` configuration:

```env
DISCORD_TOKEN=your_bot_token_here
DEV_GUILD_ID=your_test_server_id_here

OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=phi4-mini
OLLAMA_EMBEDDING_MODEL=embeddinggemma
OLLAMA_TIMEOUT_SECONDS=180.0
OLLAMA_MAX_TOKENS=400

QDRANT_URL=http://localhost:6333
QDRANT_COLLECTION=discord_messages
INDEXED_CHANNEL_IDS=123456789012345678
OCR_CHANNEL_IDS=123456789012345678

RAG_TOP_K=5
RAG_MIN_SCORE=0.50
RAG_MAX_CONTEXT_RESULTS=3

SERPER_API_KEY=your_serper_key_here
```

### 6. Run Automated Tests

```bash
python -m pytest
```

### 7. Launch the Bot

```powershell
# Standard run:
python main.py

# Or use the production auto-restart launcher:
.\start.ps1
```

---

## 📜 License

Distributed under the [MIT License](LICENSE).
