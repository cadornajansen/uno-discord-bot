# Uno AI Azure Operations Runbook

This guide covers the routine workflow for developing Uno locally, letting
GitHub Actions verify changes, and manually deploying an approved `main` branch
to the existing Azure VM.

## Production details

| Setting | Value |
| --- | --- |
| Azure subscription | `Azure for Students` |
| Resource group | `uno-prod-au-rg` |
| VM | `uno-prod-au-vm` |
| VM user | `uno` |
| Repository directory | `/opt/uno-ai` |
| Production environment file | `/opt/uno-ai/.env.azure-vm` |
| Compose file | `/opt/uno-ai/compose.azure-vm.yml` |
| Bot container | `uno-azure-vm-bot-1` |
| Qdrant container | `uno-azure-vm-qdrant-1` |

The bot and Qdrant run on the same VM. Routine deployments rebuild and recreate
only the bot. Qdrant stays online and keeps its persistent index.

## Security first

Never paste or screenshot the contents of `.env.azure-vm`. Rotate any token or
API key that has appeared in a screenshot, terminal recording, chat, or commit.

The production file should be readable only by its owner:

```bash
cd /opt/uno-ai
chmod 600 .env.azure-vm
```

Do not commit either `.env` or `.env.azure-vm`.

## 1. Prepare PowerShell

Open PowerShell and select the correct Azure subscription:

```powershell
az login
az account set --subscription "Azure for Students"
```

Set reusable variables for the current PowerShell window:

```powershell
$unoResourceGroup = "uno-prod-au-rg"
$unoVmName = "uno-prod-au-vm"
$unoIp = az vm show `
  --resource-group $unoResourceGroup `
  --name $unoVmName `
  --show-details `
  --query publicIps `
  --output tsv
```

Confirm the VM address and power state:

```powershell
$unoIp

az vm get-instance-view `
  --resource-group $unoResourceGroup `
  --name $unoVmName `
  --query "instanceView.statuses[-1].displayStatus" `
  --output tsv
```

If the VM is stopped, start it:

```powershell
az vm start `
  --resource-group $unoResourceGroup `
  --name $unoVmName
```

## 2. Connect to the VM

```powershell
ssh "uno@$unoIp"
```

After connecting, enter the repository:

```bash
cd /opt/uno-ai
```

If SSH times out, verify port 22 from PowerShell:

```powershell
Test-NetConnection $unoIp -Port 22
```

A timeout normally means the Azure network rule does not allow the current
public IP. It is not a Docker or Uno error.

## 3. Normal development and CI workflow

Do feature work on the local computer, not directly on the production VM.

From the local repository in PowerShell:

```powershell
git switch main
git pull --ff-only origin main
git switch -c feature/short-description
```

After making the focused change, run the local checks:

```powershell
python -m pytest -q

$env:UNO_ENV_FILE = "deploy/azure/.env.azure-vm.example"
docker compose -f compose.azure-vm.yml config --quiet
Remove-Item Env:UNO_ENV_FILE
```

Commit and push only the intended files:

```powershell
git status --short
git add path/to/changed-file.py path/to/changed-test.py
git commit -m "Describe the focused change"
git push -u origin feature/short-description
```

Open a pull request on GitHub. The existing GitHub Actions workflow will:

1. install Python 3.12 dependencies;
2. run the test suite;
3. compile the Python modules;
4. validate the production Compose configuration; and
5. build the production Docker image without publishing it.

Merge only after `Test and build` passes. The push to `main` runs the checks
again. Deployment to Azure is intentionally manual after the merge.

## 4. Standard production deployment

Connect to the VM, then check that the production checkout has no unexpected
local source changes:

```bash
cd /opt/uno-ai
git status --short
```

The private `.env.azure-vm` file is expected to remain untracked. Investigate
any unexpected tracked-file changes before pulling. Do not use
`git reset --hard` to hide them.

Pull the approved `main` branch:

```bash
git switch main
git pull --ff-only origin main
```

Validate the production Compose configuration:

```bash
sudo env UNO_ENV_FILE=.env.azure-vm \
  docker compose -f compose.azure-vm.yml config --quiet
```

Build only the bot image:

```bash
sudo env UNO_ENV_FILE=.env.azure-vm \
  docker compose -f compose.azure-vm.yml build bot
```

Recreate only the bot container:

```bash
sudo env UNO_ENV_FILE=.env.azure-vm \
  docker compose -f compose.azure-vm.yml \
  up -d --no-deps --force-recreate bot
```

This command loads the current `.env.azure-vm`, replaces the bot container,
and leaves Qdrant untouched.

## 5. Quick copy-paste deployment

Use this block after a pull request has passed CI and been merged:

```bash
cd /opt/uno-ai
git switch main
git pull --ff-only origin main
sudo env UNO_ENV_FILE=.env.azure-vm docker compose -f compose.azure-vm.yml config --quiet
sudo env UNO_ENV_FILE=.env.azure-vm docker compose -f compose.azure-vm.yml build bot
sudo env UNO_ENV_FILE=.env.azure-vm docker compose -f compose.azure-vm.yml up -d --no-deps --force-recreate bot
sudo env UNO_ENV_FILE=.env.azure-vm docker compose -f compose.azure-vm.yml ps
sudo docker logs --tail 100 uno-azure-vm-bot-1
```

## 6. Update production environment values

On the VM:

```bash
cd /opt/uno-ai
nano .env.azure-vm
```

In Nano, press `Ctrl+O`, then `Enter` to save, and `Ctrl+X` to exit.

Apply environment-only changes by recreating only the bot; a rebuild is not
needed when source code did not change:

```bash
sudo env UNO_ENV_FILE=.env.azure-vm \
  docker compose -f compose.azure-vm.yml \
  up -d --no-deps --force-recreate bot
```

Verify a non-secret value:

```bash
sudo docker exec uno-azure-vm-bot-1 \
  printenv ASSEMBLYAI_LLM_MAX_TOKENS
```

Verify that a secret exists without printing it:

```bash
sudo docker exec uno-azure-vm-bot-1 sh -c \
  'test -n "$ASSEMBLYAI_API_KEY" && echo "AssemblyAI key is set" || echo "AssemblyAI key is missing"'
```

## 7. Health checks and logs

Show both containers:

```bash
sudo env UNO_ENV_FILE=.env.azure-vm \
  docker compose -f compose.azure-vm.yml ps
```

Expected result:

- the bot is `Up`;
- Qdrant is `Up` and `healthy`; and
- Qdrant has an older creation time than the newly deployed bot.

Follow live bot logs:

```bash
sudo docker logs --tail 100 --follow uno-azure-vm-bot-1
```

Press `Ctrl+C` to stop watching. This does not stop the bot.

Show only recent logs:

```bash
sudo docker logs --since 30m --tail 200 uno-azure-vm-bot-1
```

Check container restart counts:

```bash
sudo docker inspect uno-azure-vm-bot-1 --format '{{.RestartCount}}'
sudo docker inspect uno-azure-vm-qdrant-1 --format '{{.RestartCount}}'
```

Check disk and memory:

```bash
df -h
free -h
sudo docker stats --no-stream
```

## 8. Discord smoke test

After deployment, test:

1. `/ping`
2. `/help`
3. `/ask question:what are the latest assignments?`
4. `@Uno AI what classes do we have today?`
5. one message in an approved indexing channel

Watch the logs during this test:

```bash
sudo docker logs --tail 100 --follow uno-azure-vm-bot-1
```

## 9. Stop and start only Uno

Stop the bot without stopping Qdrant or the VM:

```bash
cd /opt/uno-ai
sudo env UNO_ENV_FILE=.env.azure-vm \
  docker compose -f compose.azure-vm.yml stop bot
```

Start it again:

```bash
sudo env UNO_ENV_FILE=.env.azure-vm \
  docker compose -f compose.azure-vm.yml start bot
```

## 10. Azure Run Command fallback

If SSH is unavailable, PowerShell can run a non-interactive deployment through
Azure. This cannot be used with `nano`; update secrets through an SSH session or
another secure secret-management method.

```powershell
az vm run-command invoke `
  --resource-group $unoResourceGroup `
  --name $unoVmName `
  --command-id RunShellScript `
  --scripts `
    "set -eu" `
    "cd /opt/uno-ai" `
    "sudo -u uno git switch main" `
    "sudo -u uno git pull --ff-only origin main" `
    "sudo env UNO_ENV_FILE=.env.azure-vm docker compose -f compose.azure-vm.yml config --quiet" `
    "sudo env UNO_ENV_FILE=.env.azure-vm docker compose -f compose.azure-vm.yml build bot" `
    "sudo env UNO_ENV_FILE=.env.azure-vm docker compose -f compose.azure-vm.yml up -d --no-deps --force-recreate bot" `
    "sudo env UNO_ENV_FILE=.env.azure-vm docker compose -f compose.azure-vm.yml ps"
```

Read recent logs through Azure Run Command:

```powershell
az vm run-command invoke `
  --resource-group $unoResourceGroup `
  --name $unoVmName `
  --command-id RunShellScript `
  --scripts "sudo docker logs --tail 100 uno-azure-vm-bot-1 2>&1" `
  --query "value[0].message" `
  --output tsv
```

## Commands to avoid

Do not use these during routine deployment:

```text
docker compose down
docker compose down --volumes
docker volume rm ...
git reset --hard
docker system prune --volumes
```

`down --volumes` or volume-removal commands can destroy Uno's persistent class
index and local bot data. Routine deployments need only `build bot` followed by
`up -d --no-deps --force-recreate bot`.

## Routine workflow summary

```text
Local feature branch
  -> local tests
  -> push and open pull request
  -> GitHub Actions test and build
  -> merge into main
  -> SSH into Azure VM
  -> git pull --ff-only origin main
  -> build bot
  -> recreate bot only
  -> inspect status and logs
  -> Discord smoke test
```
