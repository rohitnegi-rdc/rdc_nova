# Open WebUI command index

The verified WSL startup, troubleshooting, and Windows Playwright process is documented in [openwebui-wsl-visual-testing-runbook.md](openwebui-wsl-visual-testing-runbook.md).

## Docker image path

```powershell
docker build -t open-webui:local .
docker rm -f open-webui
docker run -d -p 3000:8080 -v open-webui:/app/backend/data --env-file docker.local.env --network nova-net --name open-webui --restart unless-stopped open-webui:local
```

## Native WSL development path

Open WSL:

```powershell
wsl -d Ubuntu
```

Frontend, in WSL terminal 2:

```bash
cd ~/projects/open-webui
nvm use 22
npm run dev -- --port 5173
```

For the backend, use the environment-loading and Docker-hostname translation commands in the full runbook. Do not use the Docker hostname `nova-postgres` from native WSL.

Quick listener check:

```bash
pgrep -af 'uvicorn|vite'
ss -ltnp | grep -E ':5173|:8080|:5432'
```

## Sync Windows source into WSL

```bash
rsync -a --info=progress2 \
  --exclude='.git' \
  --exclude='node_modules' \
  --exclude='.svelte-kit' \
  --exclude='graphify-out' \
  --exclude='.venv' \
  --exclude='**/.venv' \
  --exclude='__pycache__' \
  --exclude='docker.local.env' \
  --exclude='.env.qa.local' \
  "/mnt/d/My Projects/OpenWeb Ui/open-webui-test/open-webui/" \
  "$HOME/projects/open-webui/"
```
