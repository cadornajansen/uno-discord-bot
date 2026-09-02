<div align="center">

![Uno AI Banner](uno-banner.png)

# 🤖 Uno AI (`uno-discord-bot`)

**A class-aware Discord assistant for BSCS 1-4 — assignments, schedules, OCR, and grounded AI chat.**
*Pamantasan ng Lungsod ng Maynila (PLM)*

[![Python 3.14](https://img.shields.io/badge/Python-3.14-3776AB?style=flat-square&logo=python&logoColor=white)](https://python.org)
[![Discord.py](https://img.shields.io/badge/Discord.py-2.3+-5865F2?style=flat-square&logo=discord&logoColor=white)](https://discordpy.readthedocs.io/)
[![Gemini 3.5 Flash](https://img.shields.io/badge/Gemini-3.5_Flash-4285F4?style=flat-square&logo=google&logoColor=white)](https://www.assemblyai.com/docs/llm-gateway/quickstart)
[![Qdrant Vector DB](https://img.shields.io/badge/Qdrant-Vector--DB-DC2626?style=flat-square&logo=qdrant&logoColor=white)](https://qdrant.tech)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg?style=flat-square)](LICENSE)

</div>

---

## 👋 Welcome Freshmen! What is Uno AI?

**Uno AI** is a smart, nonchalant Discord bot designed specifically for our Computer Science college block section (**BSCS 1-4**).

Uno AI reads approved class announcements, scans homework screenshots, keeps track of the section schedule, and answers questions using retrieval-augmented generation. Qdrant stores the controlled class index, Google Gemini creates embeddings, and Gemini 3.5 Flash generates answers through AssemblyAI's LLM Gateway.

---

## ⚡ Quick Command Reference

Uno AI supports both **Slash Commands (`/`)** and **Prefix Commands (`!`)**. Commands work identically in both formats!

### 🤖 AI & Knowledge Retrieval
| Slash Command | Prefix Alias | What It Does |
|---|---|---|
| `/ask question:<text>` | `!ask <question>` | Ask Uno AI anything! Uses class message memory & OCR homework notes when relevant. |
| `/reset-chat` | `!reset-chat` | Clear your private Uno AI chat memory for the current channel. |
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

### 💰 Economy, Attendance & Campus Bank
| Slash Command | Prefix Alias | What It Does |
|---|---|---|
| `/daily` | `!daily` | Claim daily attendance points (20 base + up to +20 streak bonus). Resets midnight PHT. |
| `/profile [user]` | `!profile` | View wallet balance, bank vault, net worth, daily streak, active companion pet, and inventory. |
| `/leaderboard` | `!leaderboard` | Browse top students on the global Uno Points leaderboard. |
| `/starter` | `!starter` | Claim free starter grant (+50 pts & adopt your first companion pet). |
| `/bank [action] [amount]` | `!bank` | Deposit or withdraw points from your secure bank vault (*10% fee on deposits/withdrawals, immune to pickpocketing*). |
| `/shop` | `!shop` | Open the campus store to buy consumable cards, pet snacks, and real physical prizes (50,000–100,000 pts). |
| `/inventory` | `!inventory` | Browse owned skill cards, shields, and items. |
| `/use item:<name>` | `!use <item>` | Activate an inventory item (*pickpocket, 1-week shield, uno reverse, gacha box, coffee bribe*). |
| `/give target:<user> amount:<pts>` | `!give <user> <pts>` | Transfer points to a classmate (*15% transfer tax, requires 100 pt wallet*). |
| `/steal target:<user>` | `!steal <user>` | Pickpocket 15%–25% (max 100 pts) from a classmate (*60s cooldown, requires Pickpocket card, beware of Guard Dogs & Uno Reverses!*). |

### 💼 Work & Campus Activities
| Slash Command | Prefix Alias | What It Does |
|---|---|---|
| `/trivia` | `!trivia` | Test your CS, Math, and PLM knowledge (+25 pts per correct answer, 3 daily attempts). |
| `/work` | `!work` | Work a 1-hour campus shift (earns 18–45 pts + 15% chance of consumable skill card drop). |
| `/scavenge` or `/beg` | `!scavenge`, `!beg` | Scavenge around Intramuros/CET for loose points (5–18 pts, 30-min cooldown). |
| `/study` | `!study` | Complete a study session for 200–300 points (12-hour cooldown). |

### Cooperative Games & Campus Systems
| Slash Command | Prefix Alias | What It Does |
|---|---|---|
| `/raid create` | `!raid create` | Open a persistent 2–8 player Study Raid with team puzzle stages and contribution-based rewards. |
| `/escape create` | `!escape create` | Start a 1–4 player coding escape room; hints help but reduce the final reward. |
| `/startup start name:<name>` | `!startup start <name>` | Run a three-phase guild startup where members choose build, research, market, or stabilize actions. |
| `/review history` and `/review file` | `!review history`, `!review file` | Find an eligible transaction, file a Campus Review case, let the respondent defend, and have moderators resolve it. |
| `/economy pulse` | `!economy pulse` | Show eight-hour earnings, spending, casino aggregates, leaderboard movement, and major net-worth changes. |
| `/bulletin latest` | `!bulletin latest` | Read source links from the latest Uno AI Bulletin posts. |

Raid, escape-room, and startup rewards can each be claimed once per player per Manila calendar day. Players may still join later sessions to help classmates.

### 🎰 Casino & Gambling Games
| Slash Command | Prefix Alias | What It Does |
|---|---|---|
| `/bet amount:<pts>` | `!bet <pts>` | Spin the roulette wheel (*4x Jackpot, 2x Double, Skill Drop, Bust; 500-point max, 15 casino games/day*). |
| `/coinflip choice:<h/t> wager:<pts>` | `!coinflip <h/t> <pts>` | Coin toss (*46% base win chance, 1.70x payout*). |
| `/slots wager:<pts>` | `!slots <pts>` | Spin the 3-reel slot machine (consolation matching from 0.4x up to 20x Uno Wild jackpot). |
| `/blackjack wager:<pts>` | `!blackjack <pts>` | Play 21 against the dealer (*3:2 natural blackjack payout, supports hit, stand, double down*). |
| `/highlow wager:<pts>` | `!highlow <pts>` | Guess higher or lower cards on a streak ladder up to 10.0x multiplier cashout. |
| `/cups cup:<1/2/3> wager:<pts>` | `!cups <1/2/3> <pts>` | Intramuros 3-Cup Shell Game (*30% win chance, 1.5x payout, 50-point max wager*). |

### 🐾 Companion Pets
| Slash Command | Prefix Alias | What It Does |
|---|---|---|
| `/pets store` | `!pets store` | Browse adoptable pets (*Tuxedo Cat, Golden Dog, Oogway Turtle, Scholar Owl, Pink Axolotl, Desert Fox, Lucky Bunny*). |
| `/pets list` | `!pets list` | View your adopted companion collection and active buddy. |
| `/pets switch pet_id:<id>` | `!pets switch <id>` | Switch your active companion pet to gain their unique passive gameplay perk. |
| `/pets interact action:<feed/pet>` | `!pets interact` | Feed treats or pet your buddy to gain XP, level up, and increase happiness. |
| `/pets rename nickname:<name>` | `!pets rename <name>` | Give your active companion pet a custom nickname. |

### ⚔️ PvP Duels & Wanted Bounty Board
| Slash Command | Prefix Alias | What It Does |
|---|---|---|
| `/duel target:<user> wager:<pts>` | `!duel <user> <pts>` | Challenge a classmate to a 1v1 PvP dice wager roll (*5% server rake, 60s cooldown*). |
| `/bounty place target:<user> amount:<pts>` | `!bounty place` | Place a wanted bounty on a classmate (awarded to whoever defeats them in a duel!). |
| `/bounty list` | `!bounty list` | View the top 10 wanted classroom bounty targets. |

### ⚙️ General & Info
| Slash Command | Prefix Alias | What It Does |
|---|---|---|
| `/about` | `!about` | Learn how Uno AI retrieves context and generates answers. |
| `/help` | `!help` | Open the interactive command guide. |
| `/ping` | `!ping` | Check bot connection latency. |
| `/userinfo` | `!userinfo` | View public account details. |
| `/serverinfo` | `!serverinfo` | View server metadata. |

---

## Economy, Banking & Gambling Rules

Uno AI features a balanced classroom economy designed so that accumulating points and redeeming real-world physical prizes (coffee treats, GCash gift cards, free printing services, Discord Nitro) requires **weeks of consistent participation**.

### 🎁 Real-World Prize Catalog (50,000 – 100,000 pts)
- **☕ Intramuros Coffee Treat**: `50,000 pts` (7-Eleven / Lawson beverage treat)
- **💳 GCash Gift Card ₱100**: `65,000 pts` (Direct mobile cash transfer)
- **🖨️ Free Printing Service (1 Month)**: `80,000 pts` (Academic reviewer/project printing)
- **🚀 1 Month Discord Nitro**: `100,000 pts` (Discord Nitro gift link)

### Banking & Transfer Fees
- **10% Banking Fees**: A **10% transaction fee** applies to all `/bank deposit` and `/bank withdraw` operations. Deposited bank points are 100% immune to `/steal` pickpockets.
- **15% Peer Transfer Fee**: A **15% treasury tax** applies to `/give` transfers with a 100 pt minimum sender wallet balance requirement.

### Gambling Safeguards
- **Wager Caps**: `/bet`, `/slots`, `/coinflip`, `/blackjack`, and `/highlow` accept up to **500 Uno Points**. `/duel` remains capped at **150 pts** and `/cups` at **50 pts**.
- **No Shared Daily Cap**: Standard casino games can be played repeatedly; wager and payout safeguards still apply.
- **Payout Guard**: A single standard casino payout cannot exceed **5,000 points**.
- **High-Roller Risk Adjustment**: Accounts with at least 5,000 wallet points and 4 wins in their latest 6 resolved games within 12 hours receive a modest odds reduction in chance-based games. It never forces a loss.
- **3-Cup Shell Game (`/cups`)**: Low-stakes street game with a flat 30% win chance, 1.5x payout, and 50-point maximum wager.

### 🐾 Companion Pet Perks
- 🐱 **Tuxedo Cat**: Doubles `/daily` attendance reward points and adds luck to roulette, slots, coinflip, and cups.
- 🐶 **Golden Dog**: Guards against pickpocketing (75% catch rate + inflicts 50 pt bite fine on thief).
- 🐢 **Oogway Turtle**: Freezes daily attendance streak on missed days & extends shields by +2 days.
- 🦉 **Scholar Owl**: Grants +40 pts per correct trivia quiz and unlocks a 4th daily quiz attempt.
- 🦎 **Pink Axolotl**: Grants 5% cashback on all shop purchases.
- 🦊 **Desert Fox**: Boosts pickpocket success rate to 75% and siphons back 20% wager on duel loss.
- 🐱 **Feline Fortune**: Doubles `/daily` points and adds +3% win chance in chance-based casino games.
- 🐰 **Lucky Bunny**: Improves roulette outcomes, adds +4% coinflip and +5% cups odds, and boosts rare slot symbols.

---

## 💡 Casual Chat & Mention Feature

You don't always need to run a command!
- **`@Uno AI` in chat**: Tag Uno AI anywhere in a channel and it will reply contextually.
- **Reply to Uno AI**: Reply naturally; Uno keeps a small per-user history and only reads up to three nearby messages for an ambiguous reply.

Chat memory is isolated by server, channel, and user. It keeps at most four completed turns, expires after 30 minutes, and can be cleared with `/reset-chat`.

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
  | Shared Chat  |   |  OCRService   |        | Shared Chat   |       | Local JSON    |   | Open-Meteo +  |
  | Orchestrator |   | (RapidOCR +   |        | Orchestrator  |       | Schedule Data |   | PAGASA Parser |
  | + Safe Tools |   |  ONNX Local)  |        +-------+-------+       +---------------+   +---------------+
  +------+-------+   +-------+-------+                |
         |                   |                        |
         +-------------------+------------------------+
                             |
                             v
               +---------------------------+
               | Qdrant + Gemini Embedding |
               | 2 + Gemini 3.5 Flash      |
               +---------------------------+
```

1. 🧠 **Gemini 3.5 Flash through AssemblyAI**: Generates concise answers from the user's question and any relevant class context.
2. 📦 **Qdrant + Gemini Embedding 2**: Stores 768-dimensional vectors and source metadata so Uno can retrieve semantically related class messages.
   Assignment retrieval favors newer structured homework and announcement posts over casual messages. Schedule, subject, and professor lookups use local trusted data and still work if Qdrant or embeddings are unavailable.
3. 👁️ **RapidOCR (Local OCR)**: Scans homework images (`.png`, `.jpg`) posted in approved homework channels and extracts the text so `/ask` can recall assignments from screenshots.
4. ⛅ **Open-Meteo & PAGASA Scraper**: Pulls live Manila weather data and scrapes official PAGASA NCR-PRSD rainfall/thunderstorm warnings to compute class disruption risk.

---

## 🔒 Security & Privacy Guarantees

- **Controlled Cloud Processing**: Approved messages are sent to Google to create embeddings. A user's question and relevant retrieved context are sent through AssemblyAI's LLM Gateway to Gemini for answer generation.
- **Private Vector Store**: The Qdrant service is not exposed publicly and remains under the deployment owner's control.
- **Guild Isolation**: Knowledge indexed in one Discord server can **never** be accessed or retrieved in another server.
- **Allowlisted Channels**: Uno AI only indexes messages from channels explicitly specified in `INDEXED_CHANNEL_IDS`.
- **Command Disconnection**: Commands (like `!ask` or `/search`) are excluded from Qdrant indexing so bot prompts are never re-indexed as knowledge.

---

## 💻 Developer Setup Guide (How to Run Locally)

Want to run Uno AI on your own computer or contribute code? Follow these steps:

### 1. Prerequisites
- **Python 3.12+** installed
- **Docker Desktop** installed (for Qdrant)
- **AssemblyAI API key** for Gemini 3.5 Flash generation
- **Google Gemini API key** for Gemini Embedding 2

### 2. Start Qdrant Vector Database

```bash
docker volume create uno_qdrant_storage

docker run -d --name uno-qdrant \
  -p 6333:6333 \
  -v uno_qdrant_storage:/qdrant/storage \
  qdrant/qdrant
```

### 3. Clone & Setup Project Environment

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

### 4. Configure `.env` File

Copy `.env.example` to `.env`:

```bash
cp .env.example .env
```

Fill in your `.env` configuration:

```env
DISCORD_TOKEN=your_bot_token_here
DEV_GUILD_ID=your_test_server_id_here

ASSEMBLYAI_API_KEY=your_assemblyai_api_key_here
ASSEMBLYAI_LLM_MODEL=gemini-3.5-flash
ASSEMBLYAI_LLM_MAX_TOKENS=1000

GEMINI_API_KEY=your_gemini_api_key_here
GEMINI_EMBEDDING_MODEL=gemini-embedding-2
GEMINI_EMBEDDING_DIMENSIONS=768

QDRANT_URL=http://localhost:6333
QDRANT_COLLECTION=discord_messages_gemini_v1
INDEXED_CHANNEL_IDS=123456789012345678
OCR_CHANNEL_IDS=123456789012345678

RAG_TOP_K=5
RAG_MIN_SCORE=0.50
RAG_MAX_CONTEXT_RESULTS=3

SERPER_API_KEY=your_serper_key_here
```

### 5. Run Automated Tests

```bash
python -m pytest
```

### 6. Launch the Bot

```powershell
# Standard run:
python main.py

# Or use the production auto-restart launcher:
.\start.ps1
```

### Azure Deployment

The low-usage deployment needs only Uno and Qdrant on one CPU VM; Gemini APIs
handle embeddings and generation. Follow the tested setup and safety checklist
in [`deploy/azure/README.md`](deploy/azure/README.md).

---

## 📜 License

Distributed under the [MIT License](LICENSE).
