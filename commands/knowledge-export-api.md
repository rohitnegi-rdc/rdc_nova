# Kanhaiya support-thread export API

Status: local implementation; not deployed. This exports evidence, not automatically approved knowledge-base solutions.

## Server configuration

Set `KNOWLEDGE_EXPORT_SECRET` to a new random secret of at least 32 characters in `.env.production`. Never commit it or reuse the admin password. The existing production Compose service already loads `.env.production` through its service `env_file`, so this variable is injected without a Compose edit. Recreate the service after building the updated image. Without this secret the endpoint is disabled.

The route is `GET /api/v1/knowledge-export/export`. With the existing reverse-proxy prefix the public URL is `https://ops.rdcc.ai/opsmitra/api/v1/knowledge-export/export`.

Authorization: `Authorization: Bearer <export-secret>`. The secret grants only this read-only export route, not login or the general file API. Treat exported chat and images as confidential. Use HTTPS. For development only, `KNOWLEDGE_EXPORT_ALLOW_HTTP=true` permits local HTTP; never enable this in production.

Limits: five authenticated admission attempts globally per India calendar day, including failed/busy attempts. One ZIP generation/download at a time across Linux workers sharing the same local data volume. State defaults to `DATA_DIR/knowledge-export-limits.sqlite`; `KNOWLEDGE_EXPORT_STATE_PATH` can override this. A local OS lock releases on worker crash. Do not run multiple replicas with separate volumes or a network-filesystem SQLite database.

Ten requests within one minute from the socket peer trigger a one-hour block. Unauthorized requests also count toward that flood threshold, but not the five-export quota. Forwarded IP headers are not trusted by this route. Behind nginx, the socket peer may be the proxy; configure proxy-level per-client throttling and network allowlisting to avoid proxy-wide bans. Network floods require firewall/nginx protection; the API is not a DDoS firewall.

## Date selection

### Admin ID list

Set this comma-separated list in the server environment:

```env
KNOWLEDGE_EXPORT_ADMIN_IDS=a49a4c0b-b8e0-41d1-88be-8d5798044ed9
```

To include more admins, append their verified user UUIDs separated by commas. This list selects whose replies qualify threads for export; it does not grant API access or change application roles. Kanhaiya's ID remains the default when the variable is absent. An empty list, invalid UUID, or more than 50 entries fails closed with HTTP 503. Duplicates are removed. Recreate the container after changing its environment.

The ZIP uses schema version 2 with an `admin_ids` array instead of the former scalar `admin_id`. Each message retains its author `user_id`; `is_admin_reply` is true for every configured admin. Threads answered by multiple configured admins appear once. The five-attempt daily quota and concurrent-export lock remain global, not per admin.

`from=2026-09-18&to=2026-09-30`: inclusive India calendar dates. Omit `to` for current time. Omit both for all history up to now. Threads are selected by any configured admin's reply timestamp; the default is Kanhaiya's verified ID `a49a4c0b-b8e0-41d1-88be-8d5798044ed9`. Full selected threads include older questions and replies outside the selection interval. Re-exporting later ranges can intentionally repeat threads when new replies arrive; deduplicate by question/reply IDs during curation.

Exports contain all participants' replies for clarification, with `is_admin_reply` marking replies from configured admins. No acknowledgement filtering happens at extraction. Unlinked admin messages and missing original questions are listed under `unpaired`; never infer a question from message proximity.

## Download from Windows PowerShell

Prompt for the secret without displaying it or putting it in command history:

```powershell
$secureExportSecret = Read-Host 'Export secret' -AsSecureString
$exportSecret = [System.Net.NetworkCredential]::new('', $secureExportSecret).Password
try {
    Invoke-WebRequest -Uri 'https://ops.rdcc.ai/opsmitra/api/v1/knowledge-export/export?from=2026-09-18' -Headers @{Authorization="Bearer $exportSecret"} -OutFile "$env:TEMP\kanhaiya-export.zip"
} finally {
    Remove-Variable exportSecret,secureExportSecret -ErrorAction SilentlyContinue
}
```

First reconcile the incomplete historical export by requesting `?to=2026-09-17` instead. Do not ingest or replace the existing Markdown automatically.

## ZIP contents and processing

`threads.json` contains raw questions, full replies, attachment metadata, date bounds, missing media, unpaired records, and a `complete` flag. `attachments/` contains actual upload bytes, with safe UUID filenames. Local storage paths are removed. Attachments referenced in legacy message `data.files` are also checked. Base64 inline PNG/JPEG/GIF/WebP images are decoded and included. URL-only media without a stored upload ID is flagged as unavailable; arbitrary external URLs are never fetched (SSRF protection).

Maximum: 10,000 selected replies / thread messages, 64 MiB total uncompressed content, and 120 seconds generation time. Oversized requests return 413 rather than silently truncating; use smaller date ranges. Missing attachments return an explicitly incomplete ZIP. HTTP 409 means an export is busy; 429 includes Retry-After; 504 means use a smaller interval.

After downloading, retain the raw ZIP privately. Inspect every relevant image/formula and review all admin replies and user clarifications. Produce clean Question/Solution Markdown with `cum`, no source IDs/links/mention markup, and verified image descriptions. Keep a separate reconciliation report for every included, duplicate, acknowledgement-only, ambiguous, missing-media, and unresolved question. Never invent unreadable formulas or treat an incomplete ZIP as complete.

## Local tests

Run from the WSL runtime checkout with its existing virtual environment:

```bash
cd ~/projects/open-webui/backend
.venv/bin/python -m pytest open_webui/utils/test_knowledge_export.py -q
```
