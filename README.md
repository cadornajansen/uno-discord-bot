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

---

## 🔮 Future Direction (*Not Implemented Yet*)

Future phases may expand the bot to include:
- Self-hosted AI models
- Self-hosted text embeddings
- Local vector database
- Discord chat RAG (Retrieval-Augmented Generation)
- Internet search integration
- Weather forecasts
- Schedules and reminders

*(Note: None of these services or dependencies are implemented in Phase 1.)*

---

## 🛠️ Discord Developer Portal Setup

Follow these steps to set up your bot application in Discord:

1. **Create Application**: Go to the [Discord Developer Portal](https://discord.com/developers/applications) and click **New Application**.
2. **Add Bot**: Navigate to the **Bot** tab and click **Add Bot**.
3. **Copy Bot Token**: Under the **Bot** section, click **Reset Token** and copy the generated token string.
4. **Developer Mode**: In your Discord client, go to **User Settings > Advanced** and turn on **Developer Mode**.
5. **Copy Server ID**: Right-click your private test Discord server icon and select **Copy Server ID**.
6. **Generate Bot Invite URL**:
   - Go to **OAuth2 > URL Generator** in the Developer Portal.
   - Under **Scopes**, select:
     - `bot`
     - `applications.commands`
   - Under **Bot Permissions**, select ONLY:
     - `View Channels`
     - `Send Messages`
     - `Embed Links`
     - `Use Application Commands`
   - *(Do **NOT** request Administrator permissions, and do **NOT** enable Message Content Intent for Phase 1.)*
7. **Invite Bot**: Copy the generated invite link, open it in a browser, and invite the bot to your private development server.

---

## 🚀 Environment Setup & Local Running

### 1. Clone & Setup Virtual Environment

```bash
git clone https://github.com/your-username/uno-discord-bot.git
cd uno-discord-bot

# Create virtual environment
python -m venv .venv

# Activate on Windows PowerShell / CMD:
.venv\Scripts\activate

# Activate on Linux / macOS:
source .venv/bin/activate
```

### 2. Install Project Dependencies

Install the project in editable mode with development dependencies:

```bash
pip install -e ".[dev]"
```

### 3. Environment Configuration

Copy `.env.example` to create your private `.env` file:

```bash
cp .env.example .env
```

Edit `.env` and set your credentials:

```env
DISCORD_TOKEN=your_bot_token_here
DEV_GUILD_ID=your_test_server_id_here
```

*(Warning: Never commit your `.env` file or bot secrets to Git! `.env` is listed in `.gitignore`.)*

### 4. Run the Bot

```bash
python main.py
```

### 5. Run Automated Tests

```bash
python -m pytest
```

---

## 📜 License

Distributed under the [MIT License](LICENSE).
