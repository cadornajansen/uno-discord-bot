# Azure VM deployment

Uno's production deployment is intentionally small:

```text
Azure Linux VM
├── Uno Discord bot + optional OCR
└── Qdrant with a persistent Docker volume
        │
        ├── AssemblyAI LLM Gateway → Gemini 3.5 Flash
        └── Google Gemini API → Gemini Embedding 2
```

Ollama and Azure GPU resources are not part of this deployment. The VM stays
connected to Discord, while AI generation and embeddings are billed only when
Uno makes an API request.

## 1. Create the VM

Create one Ubuntu Linux VM in your preferred nearby Azure region. Start with a
burstable CPU size and resize only if observed memory or OCR usage requires it.

Recommended safety settings:

- use SSH keys instead of a password;
- allow inbound SSH only from your own public IP;
- do not open ports 6333 or 6334 in the Azure network security group;
- use at least a 32-GB managed OS disk;
- configure an Azure budget alert before leaving the VM running continuously.

Install Git, Docker Engine, and the Docker Compose plugin using Docker's current
Ubuntu installation instructions.

## 2. Configure Uno

Clone the repository on the VM, then create the production environment file:

```bash
cp deploy/azure/.env.azure-vm.example .env.azure-vm
nano .env.azure-vm
```

Fill in these required secrets:

- `DISCORD_TOKEN`
- `ASSEMBLYAI_API_KEY`
- `GEMINI_API_KEY`

Set `DEV_GUILD_ID` while testing in one server. Leave it blank only when you are
ready for Discord to register the slash commands globally.

The template indexes only the announcement and homework channels. The removed
Chismis channel is not present. OCR is limited to the homework channel and can be
disabled by leaving `OCR_CHANNEL_IDS` blank.

## 3. Validate before starting

The example file is safe to use for syntax validation because it contains no
real credentials:

```bash
UNO_ENV_FILE=deploy/azure/.env.azure-vm.example \
  docker compose -f compose.azure-vm.yml config --quiet

docker compose -f compose.azure-vm.yml build bot
```

Do not continue if either command fails.

## 4. Start the services

```bash
docker compose -f compose.azure-vm.yml up -d
docker compose -f compose.azure-vm.yml ps
docker compose -f compose.azure-vm.yml logs --tail 100 bot
```

Expected state:

- `qdrant` reports healthy;
- `bot` remains running;
- the log says Uno logged in and synchronized commands;
- no Ollama process or GPU resource is required.

Qdrant's host port is bound to `127.0.0.1`, so it is not reachable through the
VM's public interface. The bot reaches it through Docker's internal network at
`http://qdrant:6333`.

## 5. Discord smoke test

Run these checks in the configured Discord server:

1. `/ping`
2. `/help`
3. `/ask question:what are the latest assignments?`
4. `@Uno AI what classes do we have today?`
5. Post a short test message in an approved channel and confirm it is indexed.

Inspect errors with:

```bash
docker compose -f compose.azure-vm.yml logs --tail 200 bot
```

## Operations

Update Uno:

```bash
git pull --ff-only
docker compose -f compose.azure-vm.yml up -d --build
```

Stop Uno without deleting data:

```bash
docker compose -f compose.azure-vm.yml stop
```

Start it again:

```bash
docker compose -f compose.azure-vm.yml start
```

The `uno_qdrant_storage` volume contains the class index. Do not run
`docker compose down --volumes` unless you deliberately intend to delete that
index. Take a Qdrant snapshot before destructive VM maintenance or migration.

## Remaining deployment boundary

These files prepare and validate the application stack, but they do not create
an Azure subscription, VM, network rule, DNS record, backup policy, or budget.
Those are external resources and should be created only when you are ready to
start incurring Azure charges.
