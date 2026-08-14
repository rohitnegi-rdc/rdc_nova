# Open WebUI manual production deployment

This runbook performs the first deployment manually. It exposes Open WebUI on
port `6010` and binds PostgreSQL to the server loopback interface on port `6020`.
PostgreSQL is not directly reachable from other machines.

## 1. Update the server checkout

Run from the repository cloned on the production server:

```bash
git pull --ff-only origin main
git status --short --branch
docker --version
docker compose version
```

Do not continue if `git status` reports unexpected local changes.

## 2. Create the private production environment

```bash
umask 077
cp docker.production.env.example .env.production
chmod 600 .env.production
python3 -c 'import secrets; print(secrets.token_hex(32))'
python3 -c 'import secrets; print(secrets.token_hex(32))'
nano .env.production
```

Use the two generated values for `POSTGRES_PASSWORD` and `WEBUI_SECRET_KEY`.
They must be different. Replace every `CHANGE_ME` value, including the server
host/IP, Gemini key, LangSmith key, and Knowledge Base ID. Do not paste the
completed file into chat or commit it.

For the first fresh deployment, keep `ENABLE_SIGNUP=true` so the first account
can be created as administrator. Disable it after the administrator exists.

## 3. Validate without printing secrets

```bash
docker compose --env-file .env.production -f docker-compose.production.yaml config --quiet
sudo ss -ltnp | grep -E ':(6010|6020)\b' || echo "Ports 6010 and 6020 are free"
```

Use `config --quiet`; running `docker compose config` without `--quiet` prints
the resolved environment, including secrets.

## 4. Build the application image

```bash
docker compose --env-file .env.production -f docker-compose.production.yaml build open-webui
```

The first build can take approximately 10-15 minutes. Follow the output and do
not interrupt it while Python dependencies are being installed.

## 5. Start PostgreSQL, then Open WebUI

```bash
docker compose --env-file .env.production -f docker-compose.production.yaml up -d postgres
docker compose --env-file .env.production -f docker-compose.production.yaml ps
docker compose --env-file .env.production -f docker-compose.production.yaml up -d open-webui
docker compose --env-file .env.production -f docker-compose.production.yaml ps
```

## 6. Verify health and logs

```bash
curl -fsS http://127.0.0.1:6010/health
docker compose --env-file .env.production -f docker-compose.production.yaml exec postgres sh -lc 'pg_isready -U "$POSTGRES_USER" -d "$POSTGRES_DB"'
docker compose --env-file .env.production -f docker-compose.production.yaml logs --tail=150 postgres open-webui
```

Expected application health response:

```json
{"status":true}
```

Open `http://SERVER_IP:6010` from an allowed workstation and create or verify
the administrator account.

## 7. Lock registration after the first administrator

Change this value in `.env.production`:

```dotenv
ENABLE_SIGNUP=false
```

Apply only the application configuration change:

```bash
docker compose --env-file .env.production -f docker-compose.production.yaml up -d --no-deps open-webui
```

## 8. Configure application data

For a fresh database, configure these through the Admin interface:

1. Add the Gemini provider/base model and create the `nova` model preset.
2. Apply Nova's system prompt.
3. Import `tools/main_pipe.py` as the `Nova V2` pipe function.
4. Configure the pipe valves and confirm the Knowledge Base ID.
5. Upload the Knowledge Base documents, index them with
   `gemini-embedding-2`, and verify citations.
6. Test one Knowledge Base answer, one in-domain web fallback, and one
   out-of-domain request while checking LangSmith traces.

If an existing deployment must be migrated, stop before this fresh-data setup.
The PostgreSQL database and `rdc-nova-openwebui-data` volume must both be
restored. PostgreSQL stores users and configuration; the Open WebUI data volume
stores uploaded files, Chroma collections, and other local application data.

## 9. Operational commands

```bash
# Status
docker compose --env-file .env.production -f docker-compose.production.yaml ps

# Follow application logs
docker compose --env-file .env.production -f docker-compose.production.yaml logs -f --tail=100 open-webui

# Restart only the application
docker compose --env-file .env.production -f docker-compose.production.yaml restart open-webui

# Stop containers without deleting data
docker compose --env-file .env.production -f docker-compose.production.yaml down
```

Never use `docker compose down -v` in production; it deletes both named data
volumes. Add TLS through a reverse proxy before exposing the service beyond the
trusted internal network.
