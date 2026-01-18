# LLM Council – Architecture & Extension Points

## Goals

- **Stable**: local-first, resilient to partial failures (provider/Neo4j unavailable).
- **Efficient**: parallel Stage1/2 calls, incremental context injection, minimal UI blocking.
- **Extensible**: make it easy to add “data analysis” capabilities (text now, images next).

## High-Level Flow

1. **User message** → `POST /api/conversations/{id}/message`
2. **Stage 1**: each enabled agent answers (in parallel)
   - optional: web search summary
   - optional: knowledge base hits (scoped by conversation attachments / agent scope)
   - optional: Neo4j subgraph (if agent graph bound)
3. **Stage 2**: agents anonymized peer-review & ranking
4. **Stage 3**: Chairman synthesizes final response (global default or per-conversation override)
5. **Frontend** renders Stage 1/2/3 + trace

## Backend Modules

- `backend/main.py`: FastAPI entrypoint + API endpoints
- `backend/council.py`: core 3-stage pipeline + context injection
- `backend/llm_client.py`: provider abstraction (`<provider>:<model>`), OpenAI-compatible calls
- `backend/agents_store.py`: persistent Agents config (`data/agents.json`)
- `backend/settings_store.py`: persistent runtime settings (`data/settings.json`)
- `backend/storage.py`: persistent conversations (`data/conversations/*.json`)
- `backend/trace_store.py`: JSONL trace (`data/traces/<conversation>.jsonl`)
- `backend/kb_store.py`: SQLite knowledge base (`data/kb.sqlite`)
- `backend/kb_retrieval.py`: FTS / semantic / hybrid retrieval (+ optional rerank)
- `backend/neo4j_store.py`: knowledge graph store (Neo4j)
- `backend/file_utils.py`: shared atomic JSON write helper (prevents partial JSON corruption)

## Key Persisted Data

- `data/conversations/*.json`
  - `agent_ids`: per-conversation participating agents (optional)
  - `kb_doc_ids`: per-conversation attached text documents (optional)
  - `chairman_agent_id`: per-conversation Chairman override (optional)
- `data/kb.sqlite`: uploaded/imported documents and chunks (FTS5 + optional embeddings)
- `data/agents.json`: Agent definitions (persona/system prompt, model_spec, graph_id, etc.)
- `data/settings.json`: global settings (retrieval mode, output language, etc.)
- `data/traces/*.jsonl`: step-by-step trace for debugging & export

## “Text Data Upload & Analysis” (Current Implementation)

- Frontend uploads a local text file from Chat toolbar:
  - Reads file text in browser (size-limited)
  - `POST /api/kb/documents` to persist into KB
  - `PUT /api/conversations/{id}/kb/doc_ids` to attach the KB document to the conversation
- Stage 1 injection prioritizes `conversation.kb_doc_ids` when present (so agents focus on attached docs).

## Chairman Selection (Per Conversation)

- Global default: `agents_store.get_models()["chairman_model"]`
- Per-conversation override:
  - `conversation.chairman_agent_id` → resolved to that agent’s `model_spec` during Stage 3
  - UI: Chat toolbar dropdown uses **Agent names** for selection

## Extension Points for Multimodal (Planned)

Recommended path for “images” without breaking the current design:

1. Introduce a unified `attachments[]` in conversation schema:
   - `{ id, type: "text"|"image", kb_doc_id?, file_path?, meta }`
2. For images:
   - store raw file under `data/uploads/`
   - generate OCR text → write to KB as a doc → link via `kb_doc_id`
   - (optional) generate image embeddings for semantic retrieval
3. Stage injection reads from `attachments`:
   - inject OCR/KB hits by query
   - provide structured “Attachment Summary” to models

## Operational Notes

- Run `frontend` quality checks: `cd frontend && npm run lint && npm run build`
- If you see Vite warning about Node version, upgrade Node to a supported version.

