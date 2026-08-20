# Open WebUI production access and backup restoration

This runbook covers temporary direct HTTP access and restoration of a complete
Open WebUI backup into the production Docker Compose stack. Run Linux commands
from the production checkout unless a step is explicitly marked **Windows
PowerShell**.

The production stack is defined by `docker-compose.production.yaml`:

| Data | Production location | Backup artifact |
| --- | --- | --- |
| Users, chats, models, functions, configuration, and Knowledge Base metadata | PostgreSQL volume `rdc-nova-postgres-data` | `openwebui-postgres.dump` |
| Uploaded files, Chroma collections, and local application data | Volume `rdc-nova-openwebui-data` | `openwebui-data.tar.gz` |
| Runtime secrets and provider credentials | Ignored `.env.production` | Preserve separately; never commit |

Both backup artifacts must come from the same backup operation and must be
restored together. Restoring only PostgreSQL leaves file and vector references
without their data. Restoring only the application volume leaves those files
without database metadata.

## 1. Safety rules

- Keep backups outside the Git checkout, for example under
  `~/backups/<backup-id>`. Backups can contain user data, tokens, and internal
  documents.
- Never commit `.env.production`, a PostgreSQL dump, or an application-data
  archive.
- Never use `docker compose down -v` in production. It deletes both named data
  volumes.
- The schema reset and data-volume replacement below are destructive to the
  current target deployment. Use them only for a fresh target or after taking a
  separate backup of any target data that must be retained.
- Keep PostgreSQL bound to `127.0.0.1:6020`. Direct browser testing requires
  exposing only Open WebUI port `6010`.

## 2. Environment continuity

Use a URL-safe PostgreSQL password. The safest generated form is 64 hexadecimal
characters:

```bash
python3 -c 'import secrets; print(secrets.token_hex(32))'
```

Open WebUI currently constructs the SQLAlchemy database URL from the separate
database variables. Reserved URL characters such as `@`, `#`, `%`, `$`, `/`,
or `:` in `POSTGRES_PASSWORD` can be parsed as URL delimiters and make part of
the password appear to be the database hostname. A hexadecimal password avoids
that failure. If any password fragment appears in logs, rotate the password.

When migrating an existing installation:

- Reuse the old `WEBUI_SECRET_KEY` if available. It signs sessions and is the
  default key for encrypted OAuth information. Changing it invalidates existing
  sessions and can make encrypted OAuth data unreadable.
- Keep the new production `POSTGRES_PASSWORD`; database credentials are not
  restored from the dump.
- Do not copy the old `DATABASE_URL`, `WEBUI_URL`, CORS values, or database
  password.
- Copy required OAuth/provider environment variables separately and securely.
  Do not copy or upload the complete old environment file.

## 3. Temporary direct HTTP access without Nginx

Find the server's routed LAN address:

```bash
ip route get 1.1.1.1 | awk '{for(i=1;i<=NF;i++) if($i=="src"){print $(i+1); exit}}'
```

For the current production host at `192.168.100.7`, configure:

```dotenv
OPEN_WEBUI_BIND_ADDRESS=0.0.0.0
OPEN_WEBUI_PORT=6010
WEBUI_URL=http://192.168.100.7:6010
CORS_ALLOW_ORIGIN=http://192.168.100.7:6010
WEBUI_SESSION_COOKIE_SECURE=false
WEBUI_AUTH_COOKIE_SECURE=false
```

An environment-file edit does not change an existing container. Recreate only
Open WebUI; rebuilding the image is unnecessary:

```bash
cd ~/projects/rdc_nova
docker compose --env-file .env.production -f docker-compose.production.yaml up -d --force-recreate open-webui
```

Verify the process, host binding, and local health before testing remotely:

```bash
docker compose --env-file .env.production -f docker-compose.production.yaml ps
docker inspect --format='status={{.State.Status}} ports={{json .NetworkSettings.Ports}}' rdc-nova
sudo ss -ltnp | grep ':6010'
curl -fsS http://127.0.0.1:6010/health
```

The listener must be `0.0.0.0:6010`, and the expected health response is:

```json
{"status":true}
```

If UFW is active, allow only the testing workstation rather than opening the
port globally:

```bash
sudo ufw status
sudo ufw allow from <WORKSTATION_IPV4> to any port 6010 proto tcp
```

From Windows PowerShell, verify the network path:

```powershell
Test-NetConnection 192.168.100.7 -Port 6010
```

Then open `http://192.168.100.7:6010`. HTTP sends login and application traffic
without transport encryption, so this configuration is only for short-lived
testing on a trusted network. Bind back to `127.0.0.1` when Nginx/TLS becomes
the public entry point.

## 4. Transfer backup artifacts from Windows

Create the destination on the Linux server:

```bash
BACKUP_ID="openwebui-production-YYYYMMDD-HHMMSS"
mkdir -p "$HOME/backups/$BACKUP_ID"
chmod 700 "$HOME/backups/$BACKUP_ID"
```

Run `scp` from **Windows PowerShell**, where the prompt resembles
`PS C:\Users\...>`. Do not run a command containing `D:\...` from an SSH prompt
such as `developer@RDC-AI-UBUNTU`; Linux has no Windows `D:` drive and `scp`
will interpret `D` as a hostname.

```powershell
scp "D:\path\to\openwebui-postgres.dump" "developer@192.168.100.7:/home/developer/backups/<backup-id>/"
scp "D:\path\to\openwebui-data.tar.gz" "developer@192.168.100.7:/home/developer/backups/<backup-id>/"
```

Do not transfer the old environment file. Verify the received files on Linux:

First record the source hashes in Windows PowerShell:

```powershell
Get-FileHash -Algorithm SHA256 "D:\path\to\openwebui-postgres.dump"
Get-FileHash -Algorithm SHA256 "D:\path\to\openwebui-data.tar.gz"
```

Then calculate the destination hashes on Linux:

```bash
BACKUP_DIR="$HOME/backups/$BACKUP_ID"
ls -lh "$BACKUP_DIR"
sha256sum "$BACKUP_DIR/openwebui-postgres.dump" "$BACKUP_DIR/openwebui-data.tar.gz"
```

Compare these hashes with hashes calculated on the source machine. Validate the
archive formats before changing production data:

```bash
docker run --rm \
  -v "$BACKUP_DIR:/backup:ro" \
  postgres:16-alpine \
  pg_restore --list /backup/openwebui-postgres.dump >/dev/null \
  && echo "PostgreSQL dump: OK"

tar -tzf "$BACKUP_DIR/openwebui-data.tar.gz" >/dev/null \
  && echo "Application data archive: OK"
```

## 5. Restore PostgreSQL

Stop Open WebUI so it cannot write while the database and application volume
are being replaced. Keep PostgreSQL running:

```bash
cd ~/projects/rdc_nova
BACKUP_DIR="$HOME/backups/<backup-id>"
docker compose --env-file .env.production -f docker-compose.production.yaml stop open-webui
```

For a fresh target, reset the complete `public` schema. `DROP SCHEMA ...
CASCADE` lets PostgreSQL remove dependent foreign keys in a safe dependency
order:

```bash
docker compose --env-file .env.production -f docker-compose.production.yaml exec -T postgres \
  sh -c 'psql -v ON_ERROR_STOP=1 --username="$POSTGRES_USER" --dbname="$POSTGRES_DB"' <<'SQL'
DROP SCHEMA public CASCADE;
CREATE SCHEMA public;
SQL
```

Restore without `--clean`, because the schema is already empty:

```bash
docker compose --env-file .env.production -f docker-compose.production.yaml exec -T postgres \
  sh -c 'pg_restore --username="$POSTGRES_USER" --dbname="$POSTGRES_DB" --no-owner --no-privileges --exit-on-error --single-transaction' \
  < "$BACKUP_DIR/openwebui-postgres.dump"
```

`--single-transaction` ensures that a failed restore is rolled back instead of
leaving a partially imported database. `--no-owner` maps restored objects to
the new production database user, and `--no-privileges` avoids restoring
environment-specific grants.

Verify expected tables:

```bash
docker compose --env-file .env.production -f docker-compose.production.yaml exec postgres \
  sh -c 'psql --username="$POSTGRES_USER" --dbname="$POSTGRES_DB" -c "\dt"'
```

The result should include tables such as `user`, `model`, `function`,
`knowledge`, `file`, `chat`, and `config`.

## 6. Restore uploaded files and Chroma

The following operation replaces all contents of the exact named volume
`rdc-nova-openwebui-data`. Inspect that target and capture the application
container user first:

```bash
docker volume inspect rdc-nova-openwebui-data
APP_UID_GID=$(docker inspect --format '{{.Config.User}}' rdc-nova)
printf '%s\n' "$APP_UID_GID" | grep -Eq '^[0-9]+:[0-9]+$' \
  || { echo "STOP: could not determine the application UID:GID"; exit 1; }
echo "Application user: $APP_UID_GID"
```

Restore the archive and fix ownership so the non-root application process can
update Chroma and uploaded files:

```bash
docker run --rm --user 0:0 --entrypoint sh \
  -e APP_UID_GID="$APP_UID_GID" \
  -v rdc-nova-openwebui-data:/data \
  -v "$BACKUP_DIR:/backup:ro" \
  postgres:16-alpine \
  -c 'find /data -mindepth 1 -maxdepth 1 -exec rm -rf -- {} + && tar -xzf /backup/openwebui-data.tar.gz -C /data && chown -R "$APP_UID_GID" /data'
```

An archive from a PostgreSQL-backed installation can still contain legacy
`webui.db`, `webui.db-wal`, and `webui.db-shm` files. They are ignored while
`DATABASE_TYPE=postgresql`; the PostgreSQL dump remains the authoritative
database backup.

## 7. Start and verify the restored system

```bash
docker compose --env-file .env.production -f docker-compose.production.yaml up -d open-webui
docker compose --env-file .env.production -f docker-compose.production.yaml ps
docker compose --env-file .env.production -f docker-compose.production.yaml logs --tail=150 open-webui
curl -fsS http://127.0.0.1:6010/health
```

The first startup may run database migrations. After health succeeds, verify:

1. Existing administrator and user accounts can sign in.
2. The `nova` model and `Nova V2` pipe function exist.
3. Knowledge Bases list their expected files.
4. A known Knowledge Base question returns grounded citations.
5. Chroma retrieval uses the same embedding model and dimension used when the
   backup was indexed. Reindex only if the embedding configuration changed.
6. Gemini and LangSmith credentials are supplied by `.env.production`, and a
   Nova V2 request appears in LangSmith with all expected stages.
7. OAuth login works if it is enabled.

After verification, set `ENABLE_SIGNUP=false` and recreate Open WebUI if this
is not already enforced.

## 8. Troubleshooting knowledge

### `could not translate host name ... to address`

Part of `POSTGRES_PASSWORD` was parsed as the hostname. Rotate the password to
a 64-character hexadecimal value. On a newly initialized empty deployment,
remove and recreate only `rdc-nova-postgres-data`; changing the environment
value alone does not change the password stored in an existing PostgreSQL
volume. Never delete a populated volume to rotate a password.

### `cannot drop constraint ... because other objects depend on it`

`pg_restore --clean` is dropping individual constraints in an incompatible
order. If the target is intentionally replaceable, reset the entire `public`
schema with `DROP SCHEMA public CASCADE`, recreate it, and restore without
`--clean`. A restore using `--single-transaction` rolls back fully on failure.

### Local health works, but Windows cannot open port 6010

Check Docker's actual binding and the firewall. The container must be recreated
after changing `OPEN_WEBUI_BIND_ADDRESS`:

```bash
docker inspect --format='{{json .NetworkSettings.Ports}}' rdc-nova
sudo ss -ltnp | grep ':6010'
sudo ufw status
```

If Windows can ping the server but `Test-NetConnection ... -Port 6010` fails,
the problem is the Docker host binding, a stopped/restarting container, or a
firewall rule—not the browser URL.

### `curl: (56) Recv failure: Connection reset by peer`

The host port is reachable, but the application process is restarting or has
not finished startup. Check status, restart count, and logs before rebuilding:

```bash
docker compose --env-file .env.production -f docker-compose.production.yaml ps
docker inspect --format='status={{.State.Status}} restart_count={{.RestartCount}} exit_code={{.State.ExitCode}}' rdc-nova
docker compose --env-file .env.production -f docker-compose.production.yaml logs --tail=150 open-webui
```

### `ssh: Could not resolve hostname d`

A Windows path was passed to `scp` from Linux. Run the upload from Windows
PowerShell, or use a real Linux-mounted path when operating from local WSL.

### Restored files exist but retrieval or citations fail

Confirm that both the PostgreSQL dump and application-data archive came from
the same backup, that the data volume is writable by the configured application
UID:GID, and that the embedding model matches the vectors in Chroma. PostgreSQL
contains Knowledge Base/file relationships; the application volume contains
the corresponding uploads and vectors.
