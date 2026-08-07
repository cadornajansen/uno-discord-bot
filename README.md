# UNO Discord Bot (`uno-discord-bot`)

An open-source Python Discord bot foundation built for our Computer Science college block section. 

The bot is currently being developed and tested inside a private development server before eventual deployment to the main block server.

---

## 📌 Current Phase

### **Phase 1 — Core Bot Foundation**
- [x] Discord bot foundation & client runner
- [x] Slash command system (`discord.app_commands`)
- [x] Fast development guild command syncing (`DEV_GUILD_ID`)
- [x] `/ping` — Connection latency check
- [x] `/hello` — User greeting
- [x] `/userinfo` — Public user account metadata
- [x] `/serverinfo` — Server details embed
- [x] `/help` — Command guide

### **Phase 2A — Local Ollama AI Integration**
- [x] Local Ollama AI integration via direct HTTP API (`httpx`)
- [x] `/ask question:<text>` — Slash command for AI interaction
- [x] `phi4-mini` model configured for local inference
- [x] Automatic response chunking for long AI outputs (`split_message`)
- [x] Failure fallback handling (Ollama offline, model missing, inference timeout)

*(Note: No external AI API, hosted LLM provider, or cloud SDK is used.)*

---

## 🔮 Future Direction (*Not Implemented Yet*)

Future phases may expand the bot to include:
- Phase 2B: Local Qdrant vector database & text embeddings (Discord Chat RAG)
- Phase 3: Internet search & Open-Meteo weather forecasts
- Phase 4: SQLite schedules & reminders

---

## 🤖 Local AI Setup (Ollama)

To enable the `/ask` command:

1. **Install Ollama**: Download and install Ollama from [https://ollama.com](https://ollama.com).
2. **Pull Model**: Open your terminal and pull the `phi4-mini` model:
   ```bash
   ollama pull phi4-mini
   ```
3. **Test Model Locally**:
   ```bash
   ollama run phi4-mini
   ```
4. **Run Discord Bot**: Ensure Ollama is running in the background (`http://localhost:11434`), then start the bot:
   ```bash
   python main.py
   ```
5. **Test in Discord**:
   ```text
   /ask question:Explain pointers in C
   ```

---

## 🛠️ Discord Developer Portal Setup

1. **Create Application**: Go to the [Discord Developer Portal](https://discord.com/developers/applications) → **New Application**.
2. **Add Bot**: Go to **Bot** tab → **Add Bot**.
3. **Copy Bot Token**: Click **Reset Token** and copy the generated token string.
4. **Developer Mode**: In Discord client, go to **User Settings > Advanced** and turn on **Developer Mode**.
5. **Copy Server ID**: Right-click your private test server icon and select **Copy Server ID**.
6. **Generate Invite Link**:
   - Go to **OAuth2 > URL Generator**.
   - Select Scopes: `bot`, `applications.commands`.
   - Select Permissions: `View Channels`, `Send Messages`, `Embed Links`, `Use Application Commands`.
   - *(Do **NOT** request Administrator permissions, and do **NOT** enable Message Content Intent yet.)*
7. **Invite Bot**: Open the generated invite link to add the bot to your private test server.

---

## 🚀 Environment Setup & Local Running

### 1. Clone & Setup Virtual Environment

```bash
git clone https://github.com/your-username/uno-discord-bot.git
cd uno-discord-bot

# Create virtual environment
python -m venv .venv

# Activate on Windows:
.venv\Scripts\activate

# Activate on Linux / macOS:
source .venv/bin/activate
```

### 2. Install Project Dependencies

```bash
pip install -e ".[dev]"
```

### 3. Environment Configuration

Copy `.env.example` to create your private `.env` file:

```bash
cp .env.example .env
```

Edit `.env`:

```env
DISCORD_TOKEN=your_bot_token_here
DEV_GUILD_ID=your_test_server_id_here

OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=phi4-mini
```

### 4. Run Automated Tests

```bash
python -m pytest
```

### 5. Start Bot

```bash
python main.py
```

---

## 📜 License

Distributed under the [MIT License](LICENSE).
