---
title: Open WebUI WSL Development and Windows Visual QA Runbook
type: operational-runbook
status: verified
last_verified: 2026-08-12
environment: Windows + Ubuntu WSL + PostgreSQL + Windows Playwright
tags:
  - open-webui
  - wsl
  - playwright
  - visual-testing
  - tara-ops-v2
---

# Open WebUI WSL Development and Windows Visual QA Runbook

This is the canonical process for running this repository locally and testing it through a real browser.

## 0. Fast path and expected timing

Use this order for routine resync and verification. It avoids rediscovering environment-specific behavior:

1. Stop only the existing Uvicorn and Vite processes for this checkout.
2. Run the rsync command in section 2.
3. Verify PostgreSQL and the four non-secret flags below.
4. Start the backend and frontend in two persistent WSL terminals.
5. Wait for HTTP 200 from ports 8080 and 5173 before opening a browser.
6. Verify database-backed Admin values before visual QA.
7. On this workstation, use Windows Python Playwright with cached Chromium directly; the Playwright MCP currently expects a Chrome extension that is not installed.
8. Run one authenticated browser pass and collect the screenshot, console, failed requests, HTTP errors, and targeted outbound-request checks together.

Known-good WSL flags:

```env
WEBUI_NAME="RDC Tara Ops"
ENABLE_COMMUNITY_SHARING=false
ENABLE_VERSION_UPDATE_CHECK=false
ENABLE_OLLAMA_API=false
```

Check only these flags without printing the rest of the environment:

```bash
grep -nE '^(WEBUI_NAME|ENABLE_COMMUNITY_SHARING|ENABLE_VERSION_UPDATE_CHECK|ENABLE_OLLAMA_API)=' \
  ~/projects/open-webui/docker.local.env
```

Measured during the 2026-08-12 verification:

- Rsync: about 34 seconds.
- Vite ready after launch: about 3 seconds once dependencies were present.
- `/api/models` after Ollama was disabled: about 0.9 seconds.
- A normal authenticated browser smoke test should complete in roughly 30-60 seconds after both services are ready.

If a routine run takes materially longer, stop and inspect the current stage. Do not restart the whole workflow blindly.

The required boundary is:

- Open WebUI frontend runs in Ubuntu WSL on port `5173`.
- Open WebUI backend runs in Ubuntu WSL on port `8080`.
- PostgreSQL is reached from native WSL through `localhost:5432`.
- Playwright runs on Windows and opens `http://localhost:5173`.
- Docker is not part of this development test path.

Do not start either application service from the Windows-mounted checkout under `/mnt/d/...`. The WSL runtime checkout is `/home/rohit/projects/open-webui`.

## 1. Paths and persistent local state

| Purpose | Location |
|---|---|
| Windows source checkout | `D:\My Projects\OpenWeb Ui\open-webui-test\open-webui` |
| WSL runtime checkout | `/home/rohit/projects/open-webui` |
| WSL backend virtual environment | `/home/rohit/projects/open-webui/backend/.venv` |
| WSL application environment | `/home/rohit/projects/open-webui/docker.local.env` |
| Windows-only QA credentials | `.env.qa.local` in the Windows repository |
| Frontend URL | `http://localhost:5173` |
| Backend URL | `http://localhost:8080` |
| PostgreSQL | `localhost:5432` from native WSL |

`.env.qa.local` is ignored by Git. It contains `QA_BASE_URL`, `QA_EMAIL`, and `QA_PASSWORD`. Never place the password in this runbook, a committed test, a screenshot name, a shell history entry, or application logs.

After the QA password is reset, update only `.env.qa.local`. Verify it remains ignored:

```powershell
git check-ignore -v .env.qa.local
```

Never inspect this file with a command that prints its complete contents. A testing process should load the values into its own environment, use them, and clear them before exiting.

## 2. Sync Windows source into the WSL runtime checkout

Run this from Ubuntu WSL when the Windows source changes:

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

Why these exclusions matter:

- Windows `node_modules` must not be copied into Linux. Native packages such as Rollup and esbuild are platform-specific.
- The WSL `.venv` must remain Linux-native.
- `docker.local.env` is deliberately preserved in WSL.
- QA credentials remain Windows-only.

After syncing:

```bash
cd ~/projects/open-webui
pwd -P
```

Expected result:

```text
/home/rohit/projects/open-webui
```

If the result starts with `/mnt/d/`, stop. That is the wrong runtime checkout.

Do not edit the WSL environment file through an encoding-changing Windows pipeline. Preserve it with the rsync exclusions and edit it inside WSL, or use an explicit UTF-8-without-BOM writer. After an automated edit, validate both syntax and the targeted lines:

```bash
bash -n ~/projects/open-webui/docker.local.env
grep -nE '^(WEBUI_NAME|ENABLE_COMMUNITY_SHARING|ENABLE_VERSION_UPDATE_CHECK|ENABLE_OLLAMA_API)=' \
  ~/projects/open-webui/docker.local.env
```

## 3. One-time and recovery preparation

### Frontend

Use Linux Node 22 from WSL:

```bash
cd ~/projects/open-webui
nvm use 22
command -v node
command -v npm
node --version
npm --version
```

Both command paths must be Linux paths such as `/usr/bin/...` or `/home/rohit/.nvm/...`, not `/mnt/c/...`.

Install frontend packages only when `node_modules` is missing or the lockfile changed:

```bash
cd ~/projects/open-webui
npm ci --no-audit --no-fund
```

The first frontend launch runs `npm run pyodide:fetch`. It can download and cache Pyodide packages before Vite starts. Do not diagnose the frontend as failed until the terminal prints `VITE ... ready` or a real error.

### Backend

The known-good environment is the existing Python 3.11 venv at `backend/.venv`:

```bash
cd ~/projects/open-webui/backend
test -x .venv/bin/python
.venv/bin/python --version
.venv/bin/python -m pip --version
```

Tara Ops V2 declares `google-genai` and `langsmith` in its function frontmatter. Open WebUI checks those requirements while loading functions. Verify both imports without printing secrets:

```bash
cd ~/projects/open-webui/backend
.venv/bin/python -c 'import google.genai; import langsmith'
```

If the venv reports `No module named pip`, repair that venv with `uv`:

```bash
uv pip install --python ~/projects/open-webui/backend/.venv/bin/python pip
```

If Tara Ops V2 then fails to load because its declared packages are absent:

```bash
uv pip install --python ~/projects/open-webui/backend/.venv/bin/python google-genai langsmith
```

Install packages only in the WSL venv. Do not install backend dependencies into Windows Python.

During the verified recovery, the incomplete venv also required runtime packages including `Markdown`, PostgreSQL drivers, `python-mimeparse`, `pytz`, `ldap3`, `tiktoken`, `ddgs`, cloud-storage SDKs, `fpdf2`, and `validators`. Treat missing-import tracebacks as evidence and install the missing requirement into the same venv. Do not repeatedly reinstall the entire environment for each missing import.

Important dependency note: the repository currently pins `google-genai==1.66.0`, while the unpinned Tara Ops V2 frontmatter installed `google-genai==2.17.0` during the verified run. This is dependency drift. Before rebuilding a clean environment, align the function frontmatter and repository pin rather than assuming the newest package is always compatible.

Avoid using a full dependency reinstall as the first troubleshooting step. In this environment, a full `requirements.txt` installation attempted very large CUDA/PyTorch downloads and failed before completion. Reuse the existing venv, verify it, and repair only demonstrated gaps unless a clean rebuild is intentionally required.

## 4. Preflight checks

Open Ubuntu WSL:

```powershell
wsl -d Ubuntu
```

In WSL, confirm the project and PostgreSQL:

```bash
cd ~/projects/open-webui
pwd -P
pg_isready -h localhost -p 5432
test -f docker.local.env
test -x backend/.venv/bin/python
test -d node_modules
```

Expected PostgreSQL result contains `accepting connections`.

The WSL application database is PostgreSQL. The Docker hostname `nova-postgres` works only inside the Docker network. It does not resolve from a native WSL backend process. For native WSL, translate only the hostname to `localhost`; preserve the username, password, database name, and all other environment values.

If Ollama is not used, confirm `ENABLE_OLLAMA_API=false` before starting. This prevents unavailable-Ollama discovery from delaying `/api/models`.

## 5. Start the backend in WSL

Use terminal 1:

```bash
cd ~/projects/open-webui/backend

set -a
source ../docker.local.env
set +a

export DATABASE_URL="${DATABASE_URL/@nova-postgres:/@localhost:}"
export CORS_ALLOW_ORIGIN="http://localhost:5173;http://localhost:8080"

if [[ -z "${WEBUI_SECRET_KEY:-}" && -f .webui_secret_key ]]; then
  export WEBUI_SECRET_KEY="$(<.webui_secret_key)"
fi

source .venv/bin/activate
uvicorn open_webui.main:app \
  --port 8080 \
  --host 0.0.0.0 \
  --forwarded-allow-ips "*" \
  --reload
```

Keep this WSL terminal open. For automation started from Windows, keep the owning `wsl.exe` process attached to the foreground Uvicorn process. A command that launches `nohup ... &` and immediately lets `wsl.exe` exit is not reliable in this environment; WSL can terminate the detached Linux job when that session closes.

This ordering is important: source `docker.local.env` first, then replace the Docker-only database hostname. Setting `DATABASE_URL` before running `run-dev.sh` is not reliable because `run-dev.sh` sources the environment file again.

`bash run-dev.sh` is valid only when the environment file already contains a database host reachable from native WSL. In the present setup it requires the hostname override above.

The successful startup evidence is:

- Alembic reports `Context impl PostgresqlImpl`.
- Uvicorn reports `Uvicorn running on http://0.0.0.0:8080`.
- The server process reaches `Waiting for application startup` and completes startup.
- `GET /api/config` returns HTTP 200.

Warnings seen during the verified run:

- A JWT secret shorter than 32 bytes triggers an HMAC key warning. This does not block local startup, but a production secret should be at least 32 random bytes.
- Google OAuth without an OpenID logout endpoint warns that logout may not work correctly.
- A missing `USER_AGENT` warns during web-related initialization.

Do not confuse those warnings with a fatal traceback.

## 6. Start the frontend in WSL

Use terminal 2:

```bash
cd ~/projects/open-webui
pwd -P
nvm use 22
npm run dev -- --port 5173
```

Keep this WSL terminal open as well. The same WSL-session lifetime rule applies to Vite.

Expected evidence:

```text
VITE ... ready
Local: http://localhost:5173/
```

The process path must resolve under `/home/rohit/projects/open-webui/node_modules`, not the Windows checkout.

## 7. Confirm both services before opening a browser

From WSL:

```bash
pgrep -af 'uvicorn|vite'
ss -ltnp | grep -E ':5173|:8080|:5432'
```

Expected listeners:

- `5173` owned by Linux `node`/Vite.
- `8080` owned by the WSL Python/Uvicorn process.
- `5432` owned by PostgreSQL.

From Windows PowerShell:

```powershell
$frontend = Invoke-WebRequest -UseBasicParsing http://localhost:5173/
$backend = Invoke-WebRequest -UseBasicParsing http://localhost:8080/api/config
"Frontend: $($frontend.StatusCode) $($frontend.Headers['Content-Type'])"
"Backend:  $($backend.StatusCode) $($backend.Headers['Content-Type'])"
```

Expected:

- Frontend: HTTP 200, `text/html`.
- Backend: HTTP 200, `application/json`.

HTTP 200 is only a transport smoke test. It does not prove that Svelte hydrated or that dynamic Vite modules loaded. Browser verification is mandatory.

## 8. Windows Playwright visual testing

Use a fresh Windows browser context so a previous login does not hide authentication defects. The verified target is `http://localhost:5173`.

Preferred order:

1. On this workstation, use the installed Windows Python Playwright package with the cached Chromium executable.
2. Use the Playwright MCP only after its Chrome extension or executable-path configuration has been repaired.
3. Do not add a permanent QA script for dynamic investigations. Drive the page interactively and adapt assertions to the scenario.

The Windows Playwright installation has cached Chromium binaries under:

```text
C:\Users\RNEGI\AppData\Local\ms-playwright
```

At the last verified run, the usable executable was:

```text
C:\Users\RNEGI\AppData\Local\ms-playwright\chromium-1234\chrome-win64\chrome.exe
```

If Playwright asks for a missing older browser revision, either point the one-shot launch to an existing cached executable or install the exact required revision. Do not download another browser before checking the cache.

### Login test

Load the ignored `.env.qa.local` credentials into only the current Windows PowerShell process without printing them:

```powershell
Get-Content -LiteralPath .env.qa.local | ForEach-Object {
    if ($_ -match '^([^#][^=]*)=(.*)$') {
        [Environment]::SetEnvironmentVariable($matches[1].Trim(), $matches[2], 'Process')
    }
}
```

Run the dynamic browser session from that same process. Clear the values when testing finishes, including after a failure:

```powershell
Remove-Item Env:QA_BASE_URL -ErrorAction SilentlyContinue
Remove-Item Env:QA_EMAIL -ErrorAction SilentlyContinue
Remove-Item Env:QA_PASSWORD -ErrorAction SilentlyContinue
```

Do not run `Get-ChildItem Env:QA_*`, because it prints the values. Then perform these browser actions:

1. Navigate to `QA_BASE_URL`.
2. Wait briefly for hydration, then check for `#chat-input` first; a fresh context normally shows authentication, while a reused context may already be signed in.
3. If the composer is absent, wait explicitly for `input[type="email"]` before filling it. Do not test its count immediately after `DOMContentLoaded` and then wait 90 seconds for the chat input.
4. Assert the title is `RDC Tara Ops`.
5. Assert the page contains `Sign in to RDC Tara Ops` when signed out.
6. Fill `input[type="email"]` from `QA_EMAIL`.
7. Fill `input[type="password"]` from `QA_PASSWORD`.
8. Click `button[type="submit"]`.
9. Wait until the URL no longer contains `/auth`.
10. Confirm the success toast or authenticated navigation shell.
11. Wait for model bootstrap to complete.
12. Assert that model `Tara Ops` is visible.
13. Assert the composer exists as `#chat-input[contenteditable="true"]` or by its textbox role.

When checking backend configuration from the browser process, call `http://localhost:8080/api/config` directly. Do not fetch `/api/config` relative to the Vite origin and assume it is proxied; that produced a misleading 404 during verification.

Do not assert that a `<textarea>` exists. The chat composer is a TipTap/ProseMirror contenteditable element with id `chat-input`. A textarea-only assertion produced a false failure during the verified test.

### Visual evidence

For every scenario, collect:

- An accessibility snapshot before interacting.
- A desktop screenshot after the page stabilizes.
- Console messages at error level.
- Failed network requests.
- HTTP responses with status 400 or higher.
- Requests that remain pending unusually long.

For layout-sensitive changes, repeat at `1440x1000`, `768x1024`, and `375x812`.

### Determine whether a spinner is normal or broken

Do not rely only on a screenshot of a spinner.

1. Check whether `/api/models` is pending.
2. Correlate the request time with backend logs.
3. Check for function dependency installation errors.
4. Check model-provider connection attempts.
5. Allow known provider timeouts to finish before declaring the page permanently stuck.

In the verified run, the authenticated shell appeared immediately, but the main chat panel waited for `/api/models`. The browser showed no failed request because the request was still pending. Backend logs revealed two unavailable Ollama attempts of about 11 seconds each. After roughly 22–30 seconds, the Tara Ops chat UI rendered correctly.

That delay is not expected after Ollama is disabled. A fresh authenticated `/api/models` request measured about 0.9 seconds with `ENABLE_OLLAMA_API=false` persisted.

## 9. Persisted configuration can override environment variables

Open WebUI wraps many settings in database-backed `ConfigVar` objects. If an Admin-panel value exists, it overrides the environment default.

This matters for at least `ENABLE_OLLAMA_API` and `ENABLE_COMMUNITY_SHARING`:

- Setting `ENABLE_OLLAMA_API=false` only in the backend process did not disable Ollama.
- The persisted `ollama.enable` value remained active.
- `/api/models` therefore attempted the unavailable Ollama endpoint twice.
- Setting `ENABLE_COMMUNITY_SHARING=false` only in the environment likewise did not override an already saved Admin value.

If Ollama is not used:

1. Put `ENABLE_OLLAMA_API=false` in `docker.local.env` so clean databases default to disabled.
2. Open **Admin Panel -> Settings -> Connections**.
3. Turn the Ollama API connection toggle off and save. This updates the persisted `ollama.enable` value.
4. Verify authenticated `GET http://localhost:8080/ollama/config` reports `ENABLE_OLLAMA_API: false`.
5. Request `/api/models` and confirm it completes without Ollama connection errors.

Do not hide or downgrade all Ollama exceptions in code. Disabling the unused provider is safer: if Ollama is intentionally enabled later, real connection failures remain visible.

The relevant implementation is in:

- `backend/open_webui/config.py` for `ENABLE_OLLAMA_API`.
- `backend/open_webui/internal/config.py` for `ConfigVar` database precedence.
- `backend/open_webui/routers/ollama.py` for model discovery.

## 10. Dynamic scenario testing

The browser procedure is intentionally scenario-driven. After the stable logged-in page is confirmed, choose actions based on the feature under test.

### General UI change

1. Navigate to the changed screen through visible controls.
2. Capture the pre-action state.
3. Perform the action.
4. Assert the user-visible outcome.
5. Inspect console and network evidence.
6. Refresh and verify persistence if the change should persist.

### Tara Ops or Tara Ops V2 query

1. Select the intended model explicitly; do not assume the default.
2. Locate `#chat-input`.
3. Enter the exact query and submit it.
4. Wait for streaming to finish.
5. Capture the final answer, citations/source cards, and any visible origin label.
6. Check backend logs and LangSmith for the same request time.
7. Verify that the answer category matches the scenario.

Useful regression scenarios:

| Type | Example | Expected route |
|---|---|---|
| Known knowledge-base answer | `Running Two BINs/SILOs Simultaneously (Coarse Feeding / Parallel Feed)` | Knowledge base, grounded answer, citations |
| In-domain but absent from KB | `How to activate 3 silos at a time and optimize it` | Web search if enabled, otherwise escalation/controlled fallback |
| Corporate in-domain | `Who is the CEO of RDC Concrete?` | Corporate domain, web search when KB lacks it |
| Out of domain | `What is the capital of France?` | Exact configured domain-boundary response; no KB/web pipeline |

For citations, verify both presentation and evidence:

- The answer contains readable citation markers or source controls.
- The source object contains the expected document name/link.
- The cited chunk actually supports the answer.
- A web page blocked by JavaScript or returning `Just a moment...` is not accepted as evidence.

### Admin configuration change

1. Record the current value before changing it.
2. Change only the requested setting.
3. Save and verify success feedback.
4. Reload the page.
5. Confirm the value persisted.
6. Repeat the affected user journey.
7. Correlate with backend logs because persisted `ConfigVar` values may override environment defaults.

## 11. Fast diagnosis matrix

| Symptom | Actual cause seen | Correct response |
|---|---|---|
| `Cannot find module @rollup/rollup-linux-x64-gnu` with paths under `/mnt/d/...` | Vite used the Windows-mounted checkout or Windows `node_modules` from WSL | Stop that process; use `/home/rohit/projects/open-webui`; keep `node_modules` excluded from rsync; run Linux `npm ci` if needed |
| Frontend root is HTTP 200 but browser is blank | HTML shell loaded while dynamic modules failed or Vite exited | Inspect browser console and failed requests; verify Vite is still listening and module URLs load |
| `ERR_SOCKET_NOT_CONNECTED` / `ERR_EMPTY_RESPONSE` for many Vite modules | Vite process died or was restarted during page hydration | Fix/restart Vite, wait for `VITE ready`, then use a fresh browser context |
| Frontend startup appears slow with Pyodide package messages | `npm run dev` performs `pyodide:fetch` before Vite | Wait for the explicit Vite-ready message; do not launch the browser early |
| Backend cannot resolve `nova-postgres` | Docker-network hostname used from native WSL | Replace only `@nova-postgres:` with `@localhost:` after sourcing `docker.local.env` |
| Backend imports fail one module at a time | Existing `.venv` is incomplete | Install the demonstrated missing package into `backend/.venv`; rerun import/startup |
| Tara Ops V2 loader says `No module named pip` | Function frontmatter invokes `python -m pip`, but pip is absent from venv | Install `pip` into that exact venv with `uv pip install --python ... pip` |
| Tara Ops V2 loader cannot import `google-genai` or `langsmith` | Declared pipe dependencies missing | Install them into the WSL backend venv and verify imports |
| Login succeeds but center panel spins | `/api/models` is pending during provider discovery | Inspect backend logs; distinguish pending provider timeouts from browser failures |
| Ollama still runs after `ENABLE_OLLAMA_API=false` in the shell | Admin/database `ConfigVar` overrides env default | Disable Ollama in persisted Admin settings if it is unused |
| A boolean env flag looks correct but the UI reports the opposite | A database-backed Admin value overrides the environment default | Query the authenticated config endpoint and update the saved Admin setting; use env as the clean-install default |
| Playwright MCP says Chrome extension missing | MCP is configured for extension mode but extension is absent | Use Windows Python Playwright with cached Chromium for that dynamic run, or repair the extension |
| Browser test waits 90 seconds although the auth form is visible | Login detection ran before Svelte hydration and skipped form submission | Wait explicitly for either the composer or email input, then follow the matching branch |
| Browser-side `fetch('/api/config')` returns 404 on port 5173 | The Vite dev origin did not proxy that path in the test | Call `http://localhost:8080/api/config` directly |
| A WSL service disappears immediately after a detached Windows launch | The owning `wsl.exe` session exited | Keep Uvicorn/Vite in foreground WSL terminals or keep persistent `wsl.exe` owners attached |
| Playwright expects missing Chromium revision | Python package and cached browser revisions differ | Inspect `%LOCALAPPDATA%\ms-playwright`; point launch to an existing compatible executable or install the expected revision |
| `textarea` count is zero after login | Composer is contenteditable TipTap, not a textarea | Assert `#chat-input[contenteditable="true"]` or textbox role |
| Browser has no 4xx/5xx but UI waits | A request may be pending rather than failed | Record pending requests and correlate timestamps with backend logs |

## 12. Final pass criteria

A local visual test passes only when all applicable items are true:

- Frontend process runs from `/home/rohit/projects/open-webui` in WSL.
- Backend process runs from `backend/.venv` in WSL.
- PostgreSQL is reachable on `localhost:5432`.
- Windows receives HTTP 200 from `/` and `/api/config`.
- Browser renders `RDC Tara Ops`, not a blank HTML shell.
- Authentication succeeds with the local QA account.
- Model `Tara Ops` and `#chat-input` appear after bootstrap.
- Persisted Ollama config reports `ENABLE_OLLAMA_API=false` when Ollama is unused.
- `/api/models` completes without an unavailable-Ollama timeout.
- There are no unexplained console errors, failed requests, or HTTP errors.
- Any long pending request is identified and explained.
- The tested interaction has a visible, asserted outcome.
- Temporary screenshots or one-shot QA artifacts are removed unless intentionally retained as evidence.
- No secret is present in Git status or a tracked file.

The last verified visual result showed the complete Tara Ops chat screen, model `Tara Ops`, the composer, and suggestion prompts with zero console errors, zero failed requests, and zero HTTP error responses. After disabling persisted Ollama discovery, a fresh authenticated `/api/models` request completed in about 0.9 seconds.

## 13. Stopping the development services

When the two services are running in foreground terminals, stop each with `Ctrl+C`.

If a detached process must be stopped, identify it first:

```bash
pgrep -af 'uvicorn|vite'
```

Then terminate only the exact PID belonging to this WSL checkout. Never use a broad process kill when other Node or Python applications may be running.

## 14. Updating this runbook

Update `last_verified` whenever the complete startup and Windows browser login flow is rerun successfully. Add a failure mode only after its cause is confirmed by process, browser, network, or backend-log evidence. Keep passwords and API keys exclusively in ignored local environment files.
