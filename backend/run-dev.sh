#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &>/dev/null && pwd)
cd "$SCRIPT_DIR"

source .venv/bin/activate

if [ -f ../docker.local.env ]; then
  set -a
  source ../docker.local.env
  set +a
fi

export WEBUI_SECRET_KEY="${WEBUI_SECRET_KEY:-$(cat .webui_secret_key 2>/dev/null || (head -c 12 /dev/random | base64 | tee .webui_secret_key))}"

# ---------------------------------------------------------------------------
# Mirror the Dockerfile's ENV defaults so local dev behaves like the container.
# Cache dirs point at ./data/cache instead of /app/backend/data/cache since
# there's no /app here. Anything already set (e.g. via docker.local.env or the
# shell) takes precedence over these defaults.
# ---------------------------------------------------------------------------
export OLLAMA_BASE_URL="${OLLAMA_BASE_URL:-http://localhost:11434}"
export OPENAI_API_BASE_URL="${OPENAI_API_BASE_URL:-}"

export SCARF_NO_ANALYTICS="${SCARF_NO_ANALYTICS:-true}"
export DO_NOT_TRACK="${DO_NOT_TRACK:-true}"
export ANONYMIZED_TELEMETRY="${ANONYMIZED_TELEMETRY:-false}"

export WHISPER_MODEL="${WHISPER_MODEL:-base}"
export WHISPER_MODEL_DIR="${WHISPER_MODEL_DIR:-$SCRIPT_DIR/data/cache/whisper/models}"

export RAG_EMBEDDING_MODEL="${RAG_EMBEDDING_MODEL:-sentence-transformers/all-MiniLM-L6-v2}"
export RAG_RERANKING_MODEL="${RAG_RERANKING_MODEL:-}"
export AUXILIARY_EMBEDDING_MODEL="${AUXILIARY_EMBEDDING_MODEL:-TaylorAI/bge-micro-v2}"
export SENTENCE_TRANSFORMERS_HOME="${SENTENCE_TRANSFORMERS_HOME:-$SCRIPT_DIR/data/cache/embedding/models}"
export HF_HOME="${HF_HOME:-$SCRIPT_DIR/data/cache/embedding/models}"

export TIKTOKEN_ENCODING_NAME="${TIKTOKEN_ENCODING_NAME:-cl100k_base}"
export TIKTOKEN_CACHE_DIR="${TIKTOKEN_CACHE_DIR:-$SCRIPT_DIR/data/cache/tiktoken}"

mkdir -p "$WHISPER_MODEL_DIR" "$SENTENCE_TRANSFORMERS_HOME" "$TIKTOKEN_CACHE_DIR"

bash dev.sh
