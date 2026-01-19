"""FastAPI backend for SynthesisLab."""

import os
from fastapi import FastAPI, HTTPException, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel
from typing import List, Dict, Any, Optional
import uuid
import json
import asyncio

from . import storage
from . import agents_store, trace_store, settings_store
from .llm_client import parse_model_spec, query_model
from .council import (
    calculate_aggregate_rankings,
    generate_conversation_title,
    run_full_council,
    stage1_collect_responses,
    stage2_collect_rankings,
    stage2b_roundtable,
    stage2b_lively,
    stage2c_fact_check,
    stage3_synthesize_final,
    stage0_preprocess,
    stage4_generate_report,
    direct_invoke_agent,
)
from .kb_store import KBStore
from .kb_retrieval import KBHybridRetriever
from .entity_type_normalizer import canonicalize_entity_type
from .kg_extractor import DEFAULT_ONTOLOGY, extract_kg_incremental
from .kg_interpret import build_components, interpret_entity, summarize_community
from .neo4j_store import KGChunk, KGEntity, KGRelation, Neo4jKGStore
from .jobs_store import JobsStore
from .job_runner import JobRunner
from .tool_context import ToolContext
from .plugin_manager import PluginManager
from .kb_store import KBStore

class UTF8JSONResponse(JSONResponse):
    media_type = "application/json; charset=utf-8"


app = FastAPI(title="SynthesisLab API", default_response_class=UTF8JSONResponse)

# Enable CORS for local development
app.add_middleware(
    CORSMiddleware,
    # Allow local dev frontends on any port via localhost/127.0.0.1.
    # This avoids common CORS preflight failures when opening the frontend with 127.0.0.1.
    allow_origin_regex=r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class CreateConversationRequest(BaseModel):
    """Request to create a new conversation."""
    agent_ids: Optional[List[str]] = None


class SendMessageRequest(BaseModel):
    """Request to send a message in a conversation."""
    content: str


class AgentUpsertRequest(BaseModel):
    id: Optional[str] = None
    name: str
    model_spec: str
    enabled: bool = True
    persona: str = ""
    influence_weight: float = 1.0
    seniority_years: int = 0
    kb_doc_ids: Optional[List[str]] = None
    kb_categories: Optional[List[str]] = None
    graph_id: str = ""


class AgentModelsRequest(BaseModel):
    chairman_model: Optional[str] = None
    title_model: Optional[str] = None


class AgentPersonaGenerateRequest(BaseModel):
    name: str
    model_spec: Optional[str] = None


class SettingsPatchRequest(BaseModel):
    output_language: Optional[str] = None
    enable_date_context: Optional[bool] = None
    enable_web_search: Optional[bool] = None
    web_search_results: Optional[int] = None
    enable_agent_web_search: Optional[bool] = None
    agent_web_search_results: Optional[int] = None
    kb_retrieval_mode: Optional[str] = None
    kb_embedding_model: Optional[str] = None
    kb_enable_rerank: Optional[bool] = None
    kb_rerank_model: Optional[str] = None
    kb_semantic_pool: Optional[int] = None
    kb_initial_k: Optional[int] = None
    kb_watch_enable: Optional[bool] = None
    kb_watch_roots: Optional[List[str]] = None
    kb_watch_exts: Optional[List[str]] = None
    kb_watch_interval_seconds: Optional[int] = None
    kb_watch_max_file_mb: Optional[int] = None
    kb_watch_index_embeddings: Optional[bool] = None
    enable_preprocess: Optional[bool] = None
    enable_roundtable: Optional[bool] = None
    enable_fact_check: Optional[bool] = None
    roundtable_rounds: Optional[int] = None
    enable_report_generation: Optional[bool] = None
    report_instructions: Optional[str] = None
    auto_save_report_to_kb: Optional[bool] = None
    auto_bind_report_to_conversation: Optional[bool] = None
    report_kb_category: Optional[str] = None
    enable_history_context: Optional[bool] = None
    history_max_messages: Optional[int] = None

class PluginPatchRequest(BaseModel):
    enabled: Optional[bool] = None
    config: Optional[Dict[str, Any]] = None


class KBAddRequest(BaseModel):
    id: Optional[str] = None
    title: str
    source: str = ""
    text: str
    categories: Optional[List[str]] = None
    agent_ids: Optional[List[str]] = None
    # Best-effort: index embeddings after insertion.
    # When omitted, the server will index if an embedding model is configured.
    index_embeddings: Optional[bool] = None
    embedding_model: Optional[str] = None


class KBSearchResponse(BaseModel):
    results: List[Dict[str, Any]]

class KBUpdateRequest(BaseModel):
    categories: Optional[List[str]] = None
    agent_ids: Optional[List[str]] = None


class KBIndexRequest(BaseModel):
    agent_id: Optional[str] = None
    doc_ids: Optional[List[str]] = None
    categories: Optional[List[str]] = None
    embedding_model: Optional[str] = None
    pool: int = 5000
    async_job: bool = False
    conversation_id: str = ""


class KBAddBatchRequest(BaseModel):
    documents: List[KBAddRequest]
    # When omitted, the server will index if an embedding model is configured.
    index_embeddings: Optional[bool] = None
    embedding_model: Optional[str] = None


class KGExtractRequest(BaseModel):
    text: str
    graph_id: str
    model_spec: Optional[str] = None
    ontology: Optional[Dict[str, Any]] = None
    async_job: bool = False
    conversation_id: str = ""


class KGCreateRequest(BaseModel):
    name: str
    agent_id: str = ""


class KGInterpretRequest(BaseModel):
    mode: str = "both"  # nodes|communities|both
    model_spec: Optional[str] = None
    max_nodes: int = 60
    max_mentions: int = 3
    max_communities: int = 8


class ConversationMetadata(BaseModel):
    """Conversation metadata for list view."""
    id: str
    created_at: str
    title: str
    message_count: int


class Conversation(BaseModel):
    """Full conversation with all messages."""
    id: str
    created_at: str
    title: str
    agent_ids: Optional[List[str]] = None
    chairman_model: str = ""
    chairman_agent_id: str = ""
    kb_doc_ids: List[str] = []
    report_requirements: str = ""
    discussion_mode: str = "serious"
    serious_iteration_rounds: int = 1
    lively_script: str = "groupchat"
    lively_script_history: List[Dict[str, Any]] = []
    lively_max_messages: int = 24
    lively_max_turns: int = 6
    messages: List[Dict[str, Any]]


class ConversationKBDocsRequest(BaseModel):
    doc_ids: List[str] = []


class ConversationChairmanRequest(BaseModel):
    chairman_model: str = ""
    chairman_agent_id: str = ""


class ConversationReportRequest(BaseModel):
    report_requirements: str = ""

class ConversationDiscussionRequest(BaseModel):
    discussion_mode: Optional[str] = None  # serious | lively
    serious_iteration_rounds: Optional[int] = None
    lively_script: Optional[str] = None  # brainstorm | interview | groupchat
    lively_max_messages: Optional[int] = None
    lively_max_turns: Optional[int] = None


class ConversationInvokeRequest(BaseModel):
    action: str  # ask | report
    agent_id: str
    content: str = ""
    report_requirements: str = ""

class JobCreateRequest(BaseModel):
    job_type: str
    conversation_id: str = ""
    payload: Dict[str, Any] = {}


@app.get("/")
async def root():
    """Health check endpoint."""
    return {"status": "ok", "service": "SynthesisLab API"}


@app.get("/api/status")
async def status():
    """Basic runtime configuration (no secrets)."""
    agents_store.ensure_initialized()
    models = agents_store.get_models()
    agents = agents_store.list_agents()
    return {
        "settings": settings_store.get_settings().__dict__,
        "agents": [
            {
                "id": a.id,
                "name": a.name,
                "model_spec": a.model_spec,
                "provider": parse_model_spec(a.model_spec).provider,
                "model": parse_model_spec(a.model_spec).model,
                "enabled": a.enabled,
                "influence_weight": a.influence_weight,
                "seniority_years": a.seniority_years,
                "kb_doc_ids": a.kb_doc_ids,
                "kb_categories": a.kb_categories,
                "graph_id": a.graph_id,
            }
            for a in agents
        ],
        "council_models": [
            {"spec": a.model_spec, "provider": parse_model_spec(a.model_spec).provider, "model": parse_model_spec(a.model_spec).model}
            for a in agents
            if a.enabled
        ],
        "chairman_model": {"spec": models["chairman_model"], **parse_model_spec(models["chairman_model"]).__dict__},
        "title_model": {"spec": models["title_model"], **parse_model_spec(models["title_model"]).__dict__},
    }


@app.get("/api/agents")
async def list_agents():
    agents_store.ensure_initialized()
    return [
        {
            "id": a.id,
            "name": a.name,
            "model_spec": a.model_spec,
            "enabled": a.enabled,
            "persona": a.persona,
            "influence_weight": a.influence_weight,
            "seniority_years": a.seniority_years,
            "kb_doc_ids": a.kb_doc_ids,
            "kb_categories": a.kb_categories,
            "graph_id": a.graph_id,
            "created_at": a.created_at,
        }
        for a in agents_store.list_agents()
    ]


@app.post("/api/agents")
async def create_agent(request: AgentUpsertRequest):
    agent_id = request.id or str(uuid.uuid4())
    agent = agents_store.AgentConfig(
        id=agent_id,
        name=request.name,
        model_spec=request.model_spec,
        enabled=request.enabled,
        persona=request.persona or "",
        influence_weight=request.influence_weight,
        seniority_years=request.seniority_years,
        kb_doc_ids=list(request.kb_doc_ids or []),
        kb_categories=list(request.kb_categories or []),
        graph_id=request.graph_id or "",
    )
    agents_store.upsert_agent(agent)
    return {"ok": True, "agent": {"id": agent.id}}


@app.put("/api/agents/{agent_id}")
async def update_agent(agent_id: str, request: AgentUpsertRequest):
    existing = agents_store.get_agent(agent_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="Agent not found")
    agent = agents_store.AgentConfig(
        id=agent_id,
        name=request.name,
        model_spec=request.model_spec,
        enabled=request.enabled,
        persona=request.persona or "",
        influence_weight=request.influence_weight,
        seniority_years=request.seniority_years,
        kb_doc_ids=list(request.kb_doc_ids or []),
        kb_categories=list(request.kb_categories or []),
        graph_id=request.graph_id or "",
        created_at=existing.created_at,
    )
    agents_store.upsert_agent(agent)
    return {"ok": True}


@app.delete("/api/agents/{agent_id}")
async def delete_agent(agent_id: str):
    deleted = agents_store.delete_agent(agent_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Agent not found")
    return {"ok": True}


@app.post("/api/agents/models")
async def set_agent_models(request: AgentModelsRequest):
    models = agents_store.set_models(chairman_model=request.chairman_model, title_model=request.title_model)
    return {"ok": True, "models": models}


@app.post("/api/agents/persona/generate")
async def generate_agent_persona(request: AgentPersonaGenerateRequest):
    name = (request.name or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="name 不能为空")

    models = agents_store.get_models()
    model_spec = (request.model_spec or models.get("chairman_model") or "").strip()
    if not model_spec:
        raise HTTPException(status_code=400, detail="model_spec 不能为空")

    system_prompt = (
        "你是“Agent 人设(System Prompt)撰写专家”。\n"
        "你的任务：根据给定的 Agent 名称，生成一段可直接作为 LLM system prompt 的中文人设。\n"
        "要求：\n"
        "- 不要输出 JSON，不要输出 Markdown 代码块。\n"
        "- 不要编造具体真实个人隐私（手机号/地址/身份证等）；可使用合理但虚构且泛化的背景。\n"
        "- 用第二人称“你是…”写法，清晰可执行。\n"
        "- 包含：角色定位、能力边界、沟通风格、偏好/禁忌、输出格式要求（简洁、结构化）。\n"
        "- 长度建议 300~800 字。\n"
    )

    user_prompt = f"Agent 名称：{name}\n\n请输出该 Agent 的 system prompt（纯文本）。"

    resp = await query_model(
        model_spec,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        timeout=120.0,
    )
    content = (resp or {}).get("content") if isinstance(resp, dict) else None
    if not content or not str(content).strip():
        raise HTTPException(status_code=502, detail="人设生成失败：模型未返回内容")

    persona = str(content).strip()
    return {"ok": True, "persona": persona, "model_spec": model_spec}


@app.get("/api/settings")
async def get_settings():
    return settings_store.get_settings().__dict__


@app.post("/api/settings")
async def patch_settings(request: SettingsPatchRequest):
    patch = request.model_dump(exclude_none=True)
    s = settings_store.update_settings(patch)
    return {"ok": True, "settings": s.__dict__}


@app.get("/api/plugins")
async def list_plugins():
    return {"plugins": [p.__dict__ for p in plugin_manager.list_plugins()], "tools": plugin_manager.registry.list()}


@app.put("/api/plugins/{name}")
async def patch_plugin(name: str, request: PluginPatchRequest):
    if request.enabled is None and request.config is None:
        raise HTTPException(status_code=400, detail="No changes")
    if request.enabled is not None:
        plugin_manager.set_enabled(name, bool(request.enabled))
    if request.config is not None:
        plugin_manager.set_config(name, request.config or {})
    job_runner.set_tools(plugin_manager.registry, tool_ctx)
    return {
        "ok": True,
        "plugin": next((p.__dict__ for p in plugin_manager.list_plugins() if p.name == name), None),
        "tools": plugin_manager.registry.list(),
    }


@app.post("/api/plugins/reload")
async def reload_plugins():
    plugin_manager.reload()
    job_runner.set_tools(plugin_manager.registry, tool_ctx)
    return {"ok": True, "plugins": [p.__dict__ for p in plugin_manager.list_plugins()], "tools": plugin_manager.registry.list()}


kb = KBStore()
kb_retriever = KBHybridRetriever(kb)
from .kb_watch import KBWatchService

kb_watch = KBWatchService(kb, kb_retriever)
jobs_store = JobsStore()
job_runner = JobRunner(jobs_store, workers=1)
plugin_manager = PluginManager()
tool_ctx = ToolContext(kb_retriever=kb_retriever, get_neo4j=lambda: _get_neo4j())


@app.on_event("startup")
async def _startup_tasks():
    job_runner.set_tools(plugin_manager.registry, tool_ctx)
    await job_runner.start()
    await kb_watch.start()


@app.on_event("shutdown")
async def _shutdown_tasks():
    await kb_watch.stop()
    await job_runner.stop()


@app.get("/api/kb/documents")
async def kb_list_documents():
    return {"documents": kb.list_documents()}

@app.get("/api/kb/watch/status")
async def kb_watch_status():
    return kb_watch.status().__dict__


@app.post("/api/kb/watch/scan")
async def kb_watch_scan():
    # Run a scan immediately (best-effort).
    return await kb_watch.scan_once()


# NOTE: This route must be declared before "/api/kb/documents/{doc_id}" routes,
# otherwise "batch" will be captured as a doc_id and POST will return 405.
@app.post("/api/kb/documents/batch")
async def kb_add_documents_batch(request: KBAddBatchRequest):
    import uuid as _uuid

    settings = settings_store.get_settings()
    results: List[Dict[str, Any]] = []
    ok_doc_ids: List[str] = []

    for d in request.documents or []:
        doc_id = d.id or _uuid.uuid4().hex
        try:
            r = kb.add_document(
                doc_id=doc_id,
                title=d.title,
                source=d.source or "",
                text=d.text,
                categories=d.categories or [],
                agent_ids=d.agent_ids or [],
            )
            ok_doc_ids.append(doc_id)
            results.append({"ok": True, **r})
        except Exception as e:
            results.append({"ok": False, "doc_id": doc_id, "error": str(e)})

    model = (request.embedding_model or settings.kb_embedding_model or "").strip()
    should_index = request.index_embeddings if request.index_embeddings is not None else bool(model)
    embeddings = None
    if should_index and model and ok_doc_ids:
        embeddings = await kb_retriever.index_embeddings(
            embedding_model_spec=model,
            doc_ids=ok_doc_ids,
            pool=max(int(settings.kb_semantic_pool or 2000) * 10, 5000),
        )

    return {"ok": True, "results": results, "embeddings": embeddings}


def _truthy_form(v: str) -> bool:
    s = str(v or "").strip().lower()
    return s in ("1", "true", "yes", "on", "y", "t")


@app.post("/api/kb/documents/upload")
async def kb_upload_document(
    file: UploadFile = File(...),
    conversation_id: str = Form(""),
    title: str = Form(""),
    source: str = Form(""),
    categories_json: str = Form("[]"),
    agent_ids_json: str = Form("[]"),
    index_embeddings: str = Form(""),
    embedding_model: str = Form(""),
):
    import json as _json
    import tempfile as _tempfile
    from pathlib import Path as _Path

    settings = settings_store.get_settings()
    conversation_id = (conversation_id or "").strip()
    if conversation_id and storage.get_conversation(conversation_id) is None:
        raise HTTPException(status_code=404, detail="Conversation not found")

    filename = (file.filename or "").strip() or "uploaded"
    ext = filename.lower().rsplit(".", 1)[-1] if "." in filename else ""

    try:
        categories = _json.loads(categories_json or "[]")
        if not isinstance(categories, list):
            categories = []
    except Exception:
        categories = []
    categories = [str(x).strip() for x in (categories or []) if str(x).strip()]
    if not categories:
        categories = ["upload"]

    try:
        agent_ids = _json.loads(agent_ids_json or "[]")
        if not isinstance(agent_ids, list):
            agent_ids = []
    except Exception:
        agent_ids = []
    agent_ids = [str(x).strip() for x in (agent_ids or []) if str(x).strip()]

    content = await file.read()
    max_bytes = int(getattr(settings, "kb_watch_max_file_mb", 20) or 20) * 1024 * 1024
    if len(content) > max_bytes:
        raise HTTPException(status_code=413, detail=f"File too large (limit {max_bytes // (1024*1024)}MB)")

    # Extract text (best-effort)
    text = ""
    if ext in ("docx", "xlsx"):
        try:
            from .office_extract import extract_office_text

            fd, tmp_path = _tempfile.mkstemp(prefix="kb_upload_", suffix="." + ext)
            try:
                with os.fdopen(fd, "wb") as f:
                    f.write(content)
                text = extract_office_text(_Path(tmp_path))
            finally:
                try:
                    os.unlink(tmp_path)
                except Exception:
                    pass
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Office extract failed: {e}")
    else:
        try:
            decoded = content.decode("utf-8", errors="ignore")
        except Exception:
            decoded = ""
        if ext == "json":
            try:
                obj = _json.loads(decoded)
                text = _json.dumps(obj, ensure_ascii=False, indent=2)
            except Exception:
                text = decoded
        else:
            text = decoded

    if not (text or "").strip():
        raise HTTPException(status_code=400, detail="No text extracted from file")

    # Create KB doc
    doc_id = uuid.uuid4().hex
    final_title = (title or "").strip() or (filename.rsplit(".", 1)[0] if "." in filename else filename) or filename
    final_source = (source or "").strip() or f"upload:{filename}"
    kb_result = kb.add_document(
        doc_id=doc_id,
        title=final_title,
        source=final_source,
        text=text,
        categories=categories,
        agent_ids=agent_ids,
    )

    # Bind to conversation if provided
    if conversation_id:
        conv = storage.get_conversation(conversation_id) or {}
        existing = conv.get("kb_doc_ids") or []
        merged = list(existing) + [doc_id]
        storage.update_conversation_kb_doc_ids(conversation_id, merged)

    # Optional: index embeddings (best-effort)
    model = (embedding_model or settings.kb_embedding_model or "").strip()
    should_index = _truthy_form(index_embeddings) if str(index_embeddings or "").strip() else bool(model)
    embeddings = None
    if should_index and model:
        embeddings = await kb_retriever.index_embeddings(
            embedding_model_spec=model,
            doc_ids=[doc_id],
            pool=max(int(settings.kb_semantic_pool or 2000) * 10, 5000),
        )

    return {"ok": True, **kb_result, "doc_id": doc_id, "title": final_title, "source": final_source, "embeddings": embeddings}


@app.get("/api/kb/documents/{doc_id}")
async def kb_get_document(doc_id: str):
    doc = kb.get_document(doc_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="Document not found")
    return {"document": doc}

@app.put("/api/kb/documents/{doc_id}")
async def kb_update_document(doc_id: str, request: KBUpdateRequest):
    updated_any = False
    if request.categories is not None:
        updated_any = kb.set_document_categories(doc_id, request.categories) or updated_any
    if request.agent_ids is not None:
        updated_any = kb.set_document_agents(doc_id, request.agent_ids) or updated_any
    if not updated_any:
        raise HTTPException(status_code=404, detail="Document not found")
    return {"ok": True}

@app.post("/api/kb/index")
async def kb_index(request: KBIndexRequest):
    settings = settings_store.get_settings()
    model = (request.embedding_model or settings.kb_embedding_model or "").strip()
    if bool(request.async_job):
        conversation_id = (request.conversation_id or "").strip()
        if conversation_id and storage.get_conversation(conversation_id) is None:
            raise HTTPException(status_code=404, detail="Conversation not found")
        if not plugin_manager.registry.get("kb_index"):
            raise HTTPException(status_code=400, detail="Plugin disabled: kb_index")
        job = job_runner.create_and_enqueue(
            job_type="kb_index",
            conversation_id=conversation_id,
            payload={
                "embedding_model": model,
                "agent_id": request.agent_id or "",
                "doc_ids": request.doc_ids,
                "categories": request.categories,
                "pool": int(request.pool or 5000),
            },
        )
        return {"ok": True, "queued": True, "job": job.__dict__}
    return await kb_retriever.index_embeddings(
        embedding_model_spec=model,
        agent_id=(request.agent_id or "").strip() or None,
        doc_ids=request.doc_ids,
        categories=request.categories,
        pool=int(request.pool or 5000),
    )


@app.post("/api/kb/documents")
async def kb_add_document(request: KBAddRequest):
    import uuid as _uuid

    settings = settings_store.get_settings()
    doc_id = request.id or _uuid.uuid4().hex
    result = kb.add_document(
        doc_id=doc_id,
        title=request.title,
        source=request.source or "",
        text=request.text,
        categories=request.categories or [],
        agent_ids=request.agent_ids or [],
    )

    model = (request.embedding_model or settings.kb_embedding_model or "").strip()
    should_index = request.index_embeddings if request.index_embeddings is not None else bool(model)
    embeddings = None
    if should_index and model:
        embeddings = await kb_retriever.index_embeddings(
            embedding_model_spec=model,
            doc_ids=[doc_id],
            pool=max(int(settings.kb_semantic_pool or 2000) * 10, 5000),
        )

    return {"ok": True, **result, "embeddings": embeddings}


@app.delete("/api/kb/documents/{doc_id}")
async def kb_delete_document(doc_id: str):
    deleted = kb.delete_document(doc_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Document not found")
    return {"ok": True}


@app.get("/api/kb/search", response_model=KBSearchResponse)
async def kb_search(q: str, agent_id: Optional[str] = None, limit: int = 6):
    settings = settings_store.get_settings()
    results = await kb_retriever.search(
        query=q,
        agent_id=agent_id,
        doc_ids=None,
        categories=None,
        limit=limit,
        mode=settings.kb_retrieval_mode,
        embedding_model_spec=settings.kb_embedding_model,
        enable_rerank=bool(settings.kb_enable_rerank),
        rerank_model_spec=settings.kb_rerank_model or agents_store.get_models().get("chairman_model") or "",
        semantic_pool=int(settings.kb_semantic_pool),
        initial_k=int(settings.kb_initial_k),
    )
    return {"results": results}


def _get_neo4j() -> Neo4jKGStore:
    try:
        return Neo4jKGStore()
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Neo4j 未配置或连接失败：{e}")


@app.get("/api/kg/graphs")
async def kg_list_graphs(agent_id: Optional[str] = None):
    store = _get_neo4j()
    try:
        return {"graphs": store.list_graphs(agent_id=agent_id)}
    finally:
        store.close()


@app.post("/api/kg/graphs")
async def kg_create_graph(request: KGCreateRequest):
    store = _get_neo4j()
    try:
        graph_id = store.create_graph(name=request.name, agent_id=request.agent_id)
        if request.agent_id:
            existing = agents_store.get_agent(request.agent_id)
            if existing and not (existing.graph_id or "").strip():
                agents_store.upsert_agent(
                    agents_store.AgentConfig(
                        id=existing.id,
                        name=existing.name,
                        model_spec=existing.model_spec,
                        enabled=existing.enabled,
                        persona=existing.persona,
                        influence_weight=existing.influence_weight,
                        seniority_years=existing.seniority_years,
                        kb_doc_ids=list(existing.kb_doc_ids or []),
                        kb_categories=list(existing.kb_categories or []),
                        graph_id=graph_id,
                        created_at=existing.created_at,
                    )
                )
        return {"ok": True, "graph_id": graph_id}
    finally:
        store.close()


@app.post("/api/kg/extract")
async def kg_extract_and_upsert(request: KGExtractRequest):
    if bool(request.async_job):
        conversation_id = (request.conversation_id or "").strip()
        if conversation_id and storage.get_conversation(conversation_id) is None:
            raise HTTPException(status_code=404, detail="Conversation not found")
        if not plugin_manager.registry.get("kg_extract"):
            raise HTTPException(status_code=400, detail="Plugin disabled: kg_extract")
        job = job_runner.create_and_enqueue(
            job_type="kg_extract",
            conversation_id=conversation_id,
            payload={
                "graph_id": request.graph_id,
                "text": request.text,
                "model_spec": request.model_spec or "",
                "ontology": request.ontology or DEFAULT_ONTOLOGY,
            },
        )
        return {"ok": True, "queued": True, "job": job.__dict__}

    # Default to Chairman model for extraction.
    models = agents_store.get_models()
    model_spec = request.model_spec or models["chairman_model"]

    ontology = request.ontology or DEFAULT_ONTOLOGY
    extracted = await extract_kg_incremental(model_spec=model_spec, text=request.text, ontology=ontology)

    store = _get_neo4j()
    try:
        chunks = extracted.get("chunks") or []
        total_entities = 0
        total_relations = 0

        for c in chunks:
            chunk_id = f"chunk_{uuid.uuid4().hex[:12]}"
            chunk_text = str((c.get("text") or "")) if isinstance(c, dict) else ""
            store.upsert_chunk(KGChunk(graph_id=request.graph_id, chunk_id=chunk_id, text=chunk_text))

            entities_in_chunk = c.get("entities") or []
            relations_in_chunk = c.get("relations") or []

            entities: List[KGEntity] = []
            uuid_by_key: Dict[str, str] = {}
            for ent in entities_in_chunk:
                raw_type = ent.get("type", "")
                canonical_type = canonicalize_entity_type(raw_type)
                name = (ent.get("name") or "").strip()
                if not name:
                    continue
                eobj = KGEntity(
                    graph_id=request.graph_id,
                    name=name,
                    entity_type=canonical_type,
                    summary=(ent.get("summary") or "").strip(),
                    attributes=ent.get("attributes") or {},
                    source_entity_types=[str(raw_type).strip()] if raw_type else [],
                )
                entities.append(eobj)
                uuid_by_key[f"{canonical_type}:{name}".lower()] = eobj.uuid

            if entities:
                entity_uuids = store.upsert_entities(entities)
                store.link_mentions(chunk_id=chunk_id, entity_uuids=entity_uuids, graph_id=request.graph_id)
                total_entities += len(entities)

            relations: List[KGRelation] = []
            # Ensure endpoints exist for relations, even if not emitted as entities in this chunk.
            missing_endpoint_entities: List[KGEntity] = []
            for rel in relations_in_chunk:
                s_type_raw = rel.get("source_type") or "Entity"
                t_type_raw = rel.get("target_type") or "Entity"
                s_type = canonicalize_entity_type(s_type_raw)
                t_type = canonicalize_entity_type(t_type_raw)
                s_name = (rel.get("source") or "").strip()
                t_name = (rel.get("target") or "").strip()
                if not s_name or not t_name:
                    continue
                s_key = f"{s_type}:{s_name}".lower()
                t_key = f"{t_type}:{t_name}".lower()
                s_uuid = uuid_by_key.get(s_key) or _stable_uuid_fallback(request.graph_id, s_type, s_name)
                t_uuid = uuid_by_key.get(t_key) or _stable_uuid_fallback(request.graph_id, t_type, t_name)

                if s_key not in uuid_by_key:
                    missing_endpoint_entities.append(
                        KGEntity(
                            graph_id=request.graph_id,
                            name=s_name,
                            entity_type=s_type,
                            summary="",
                            attributes={},
                            source_entity_types=[str(s_type_raw).strip()] if s_type_raw else [],
                        )
                    )
                if t_key not in uuid_by_key:
                    missing_endpoint_entities.append(
                        KGEntity(
                            graph_id=request.graph_id,
                            name=t_name,
                            entity_type=t_type,
                            summary="",
                            attributes={},
                            source_entity_types=[str(t_type_raw).strip()] if t_type_raw else [],
                        )
                    )

                relations.append(
                    KGRelation(
                        graph_id=request.graph_id,
                        source_uuid=s_uuid,
                        target_uuid=t_uuid,
                        relation_name=(rel.get("relation") or "").strip(),
                        fact=(rel.get("fact") or "").strip(),
                        attributes=rel.get("attributes") or {},
                    )
                )

            if missing_endpoint_entities:
                store.upsert_entities(missing_endpoint_entities)
            if relations:
                store.upsert_relations(relations)
                total_relations += len(relations)

        return {"ok": True, "extracted": extracted, "entities": total_entities, "relations": total_relations}
    finally:
        store.close()


def _stable_uuid_fallback(graph_id: str, entity_type: str, name: str) -> str:
    # Backwards-compatible shim.
    from .kg_utils import stable_uuid_fallback

    return stable_uuid_fallback(graph_id, entity_type, name)


@app.get("/api/kg/graphs/{graph_id}")
async def kg_get_graph(graph_id: str):
    store = _get_neo4j()
    try:
        data = store.get_graph_data(graph_id)
        community = store.get_graph_community_summaries(graph_id=graph_id)
        if community:
            data["community_summaries"] = community
        return data
    finally:
        store.close()


@app.get("/api/kg/graphs/{graph_id}/subgraph")
async def kg_subgraph(graph_id: str, q: str):
    store = _get_neo4j()
    try:
        return store.query_subgraph(graph_id, q)
    finally:
        store.close()


@app.post("/api/kg/graphs/{graph_id}/interpret")
async def kg_interpret(graph_id: str, request: KGInterpretRequest):
    models = agents_store.get_models()
    model_spec = request.model_spec or models["chairman_model"]
    mode = (request.mode or "both").strip().lower()
    max_nodes = max(1, min(200, int(request.max_nodes or 60)))
    max_mentions = max(0, min(10, int(request.max_mentions or 3)))
    max_communities = max(0, min(50, int(request.max_communities or 8)))

    store = _get_neo4j()
    try:
        graph = store.get_graph_data(graph_id, limit=2000)
        nodes = graph.get("nodes") or []
        edges = graph.get("edges") or []

        id_to_node = {n["id"]: n for n in nodes if n.get("id")}
        id_to_label = {n["id"]: n.get("label") or n["id"] for n in nodes if n.get("id")}

        # Degree for ordering
        degree = {nid: 0 for nid in id_to_node.keys()}
        for e in edges:
            a = e.get("from")
            b = e.get("to")
            if a in degree:
                degree[a] += 1
            if b in degree:
                degree[b] += 1

        result: Dict[str, Any] = {"ok": True, "graph_id": graph_id, "mode": mode, "model_spec": model_spec}

        if mode in ("nodes", "both"):
            selected_ids = sorted(degree.keys(), key=lambda x: degree.get(x, 0), reverse=True)[:max_nodes]
            done = 0
            for eid in selected_ids:
                entity = id_to_node.get(eid)
                if not entity:
                    continue
                neighbors = []
                for rel in edges:
                    if rel.get("from") == eid:
                        neighbors.append(f"{entity.get('label')} -[{rel.get('label')}]-> {id_to_label.get(rel.get('to'), rel.get('to'))}")
                    elif rel.get("to") == eid:
                        neighbors.append(f"{id_to_label.get(rel.get('from'), rel.get('from'))} -[{rel.get('label')}]-> {entity.get('label')}")
                mentions = []
                if max_mentions > 0:
                    hits = store.get_entity_mentions(graph_id=graph_id, entity_uuid=eid, limit=max_mentions)
                    for h in hits:
                        t = (h.get("text") or "").strip()
                        if len(t) > 360:
                            t = t[:360] + "…"
                        if t:
                            mentions.append(t)
                interp = await interpret_entity(
                    model_spec=model_spec,
                    query_language="zh",
                    entity=entity,
                    neighbors=neighbors,
                    mentions=mentions,
                    timeout=120.0,
                )
                if interp:
                    store.set_entity_interpretation(
                        graph_id=graph_id,
                        entity_uuid=eid,
                        summary=interp.get("summary") or "",
                        key_facts=list(interp.get("key_facts") or []),
                        model_spec=model_spec,
                    )
                    done += 1
            result["nodes_interpreted"] = done

        if mode in ("communities", "both"):
            comps = build_components(nodes, edges)
            # Build lightweight edge strings for each community
            comm_summaries: List[Dict[str, Any]] = []
            for idx, comp in enumerate(comps[:max_communities], start=1):
                comp_nodes = [id_to_node[c] for c in comp if c in id_to_node]
                # pick most connected nodes as representatives
                comp_nodes.sort(key=lambda n: degree.get(n["id"], 0), reverse=True)
                edge_strs = []
                comp_set = set(comp)
                for rel in edges:
                    a = rel.get("from")
                    b = rel.get("to")
                    if a in comp_set and b in comp_set:
                        edge_strs.append(f"{id_to_label.get(a,a)} -[{rel.get('label')}]-> {id_to_label.get(b,b)}")
                summ = await summarize_community(
                    model_spec=model_spec,
                    query_language="zh",
                    community_index=idx,
                    entities=comp_nodes[:60],
                    edges=edge_strs[:80],
                    timeout=120.0,
                )
                if summ:
                    comm_summaries.append(summ)

            store.set_graph_community_summaries(graph_id=graph_id, summaries=comm_summaries, model_spec=model_spec)
            result["communities"] = comm_summaries

        return result
    finally:
        store.close()


@app.post("/api/kg/graphs/{graph_id}/interpret/stream")
async def kg_interpret_stream(graph_id: str, request: KGInterpretRequest):
    models = agents_store.get_models()
    model_spec = request.model_spec or models["chairman_model"]
    mode = (request.mode or "both").strip().lower()
    max_nodes = max(1, min(200, int(request.max_nodes or 60)))
    max_mentions = max(0, min(10, int(request.max_mentions or 3)))
    max_communities = max(0, min(50, int(request.max_communities or 8)))

    async def event_stream():
        store = _get_neo4j()
        try:
            graph = store.get_graph_data(graph_id, limit=2000)
            nodes = graph.get("nodes") or []
            edges = graph.get("edges") or []

            id_to_node = {n["id"]: n for n in nodes if n.get("id")}
            id_to_label = {n["id"]: n.get("label") or n["id"] for n in nodes if n.get("id")}
            degree = {nid: 0 for nid in id_to_node.keys()}
            for e in edges:
                a = e.get("from")
                b = e.get("to")
                if a in degree:
                    degree[a] += 1
                if b in degree:
                    degree[b] += 1

            yield f"data: {json.dumps({'type':'start','mode':mode,'model_spec':model_spec}, ensure_ascii=False)}\n\n"

            interpreted = 0
            if mode in ("nodes", "both"):
                selected_ids = sorted(degree.keys(), key=lambda x: degree.get(x, 0), reverse=True)[:max_nodes]
                yield f"data: {json.dumps({'type':'nodes_start','total':len(selected_ids)}, ensure_ascii=False)}\n\n"
                for i, eid in enumerate(selected_ids, start=1):
                    entity = id_to_node.get(eid)
                    if not entity:
                        continue
                    yield f"data: {json.dumps({'type':'node_progress','current':i,'total':len(selected_ids),'entity':entity.get('label')}, ensure_ascii=False)}\n\n"

                    neighbors = []
                    for rel in edges:
                        if rel.get("from") == eid:
                            neighbors.append(
                                f"{entity.get('label')} -[{rel.get('label')}]-> {id_to_label.get(rel.get('to'), rel.get('to'))}"
                            )
                        elif rel.get("to") == eid:
                            neighbors.append(
                                f"{id_to_label.get(rel.get('from'), rel.get('from'))} -[{rel.get('label')}]-> {entity.get('label')}"
                            )
                    mentions = []
                    if max_mentions > 0:
                        hits = store.get_entity_mentions(graph_id=graph_id, entity_uuid=eid, limit=max_mentions)
                        for h in hits:
                            t = (h.get("text") or "").strip()
                            if len(t) > 360:
                                t = t[:360] + "…"
                            if t:
                                mentions.append(t)
                    interp = await interpret_entity(
                        model_spec=model_spec,
                        query_language="zh",
                        entity=entity,
                        neighbors=neighbors,
                        mentions=mentions,
                        timeout=120.0,
                    )
                    if interp:
                        ok = store.set_entity_interpretation(
                            graph_id=graph_id,
                            entity_uuid=eid,
                            summary=interp.get("summary") or "",
                            key_facts=list(interp.get("key_facts") or []),
                            model_spec=model_spec,
                        )
                        if ok:
                            interpreted += 1
                    yield f"data: {json.dumps({'type':'node_done','current':i,'total':len(selected_ids),'interpreted':interpreted}, ensure_ascii=False)}\n\n"
                yield f"data: {json.dumps({'type':'nodes_complete','interpreted':interpreted}, ensure_ascii=False)}\n\n"

            communities_payload = None
            if mode in ("communities", "both"):
                comps = build_components(nodes, edges)
                yield f"data: {json.dumps({'type':'communities_start','total':min(len(comps), max_communities)}, ensure_ascii=False)}\n\n"
                comm_summaries: List[Dict[str, Any]] = []
                for idx, comp in enumerate(comps[:max_communities], start=1):
                    yield f"data: {json.dumps({'type':'community_progress','current':idx,'total':min(len(comps), max_communities)}, ensure_ascii=False)}\n\n"
                    comp_nodes = [id_to_node[c] for c in comp if c in id_to_node]
                    comp_nodes.sort(key=lambda n: degree.get(n["id"], 0), reverse=True)
                    comp_set = set(comp)
                    edge_strs = []
                    for rel in edges:
                        a = rel.get("from")
                        b = rel.get("to")
                        if a in comp_set and b in comp_set:
                            edge_strs.append(
                                f"{id_to_label.get(a,a)} -[{rel.get('label')}]-> {id_to_label.get(b,b)}"
                            )
                    summ = await summarize_community(
                        model_spec=model_spec,
                        query_language="zh",
                        community_index=idx,
                        entities=comp_nodes[:60],
                        edges=edge_strs[:80],
                        timeout=120.0,
                    )
                    if summ:
                        comm_summaries.append(summ)
                store.set_graph_community_summaries(graph_id=graph_id, summaries=comm_summaries, model_spec=model_spec)
                communities_payload = comm_summaries
                yield f"data: {json.dumps({'type':'communities_complete','communities':comm_summaries}, ensure_ascii=False)}\n\n"

            yield f"data: {json.dumps({'type':'complete','nodes_interpreted':interpreted,'communities':communities_payload}, ensure_ascii=False)}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'type':'error','message':str(e)}, ensure_ascii=False)}\n\n"
        finally:
            store.close()

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@app.get("/api/conversations", response_model=List[ConversationMetadata])
async def list_conversations():
    """List all conversations (metadata only)."""
    return storage.list_conversations()


@app.post("/api/conversations", response_model=Conversation)
async def create_conversation(request: CreateConversationRequest):
    """Create a new conversation."""
    conversation_id = str(uuid.uuid4())
    conversation = storage.create_conversation(conversation_id)
    if request.agent_ids is not None:
        storage.update_conversation_agents(conversation_id, request.agent_ids)
        conversation = storage.get_conversation(conversation_id)
    return conversation


@app.get("/api/conversations/{conversation_id}", response_model=Conversation)
async def get_conversation(conversation_id: str):
    """Get a specific conversation with all its messages."""
    conversation = storage.get_conversation(conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return conversation


@app.put("/api/conversations/{conversation_id}/kb/doc_ids")
async def set_conversation_kb_doc_ids(conversation_id: str, request: ConversationKBDocsRequest):
    conversation = storage.get_conversation(conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")

    # Validate documents exist.
    missing = []
    for doc_id in request.doc_ids or []:
        did = (doc_id or "").strip()
        if not did:
            continue
        if kb.get_document(did) is None:
            missing.append(did)
    if missing:
        raise HTTPException(status_code=404, detail=f"KB 文档不存在: {', '.join(missing[:8])}")

    storage.update_conversation_kb_doc_ids(conversation_id, request.doc_ids or [])
    return {"ok": True, "kb_doc_ids": storage.get_conversation(conversation_id).get("kb_doc_ids", [])}


@app.put("/api/conversations/{conversation_id}/chairman")
async def set_conversation_chairman(conversation_id: str, request: ConversationChairmanRequest):
    conversation = storage.get_conversation(conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    # Prefer agent-id (UI selection), fall back to explicit model_spec for backwards compatibility.
    if (request.chairman_agent_id or "").strip():
        storage.update_conversation_chairman_agent(conversation_id, request.chairman_agent_id)
        # Clear explicit model override to avoid ambiguity.
        storage.update_conversation_chairman_model(conversation_id, "")
    else:
        storage.update_conversation_chairman_agent(conversation_id, "")
        storage.update_conversation_chairman_model(conversation_id, request.chairman_model or "")

    conv = storage.get_conversation(conversation_id) or {}
    return {
        "ok": True,
        "chairman_agent_id": conv.get("chairman_agent_id", ""),
        "chairman_model": conv.get("chairman_model", ""),
    }


@app.put("/api/conversations/{conversation_id}/report")
async def set_conversation_report(conversation_id: str, request: ConversationReportRequest):
    conversation = storage.get_conversation(conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    storage.update_conversation_report_requirements(conversation_id, request.report_requirements)
    conv = storage.get_conversation(conversation_id) or {}
    return {"ok": True, "report_requirements": conv.get("report_requirements", "")}


@app.post("/api/conversations/{conversation_id}/report/save_to_kb")
async def save_conversation_report_to_kb(conversation_id: str):
    """
    Persist the latest Stage4 report into the KB and (optionally) bind it to the conversation.

    This is a manual "rescue" endpoint in case auto-save was disabled or previously failed.
    """
    conversation = storage.get_conversation(conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")

    # Find latest report in conversation.
    msgs = conversation.get("messages") or []
    last_report = None
    for m in reversed(msgs):
        if not isinstance(m, dict) or m.get("role") != "assistant":
            continue
        s4 = m.get("stage4")
        if isinstance(s4, dict) and (s4.get("report_markdown") or "").strip():
            last_report = s4
            break
    if last_report is None:
        raise HTTPException(status_code=400, detail="No Stage4 report found in this conversation")

    existing_kb_doc_id = str(last_report.get("kb_doc_id") or "").strip()
    if existing_kb_doc_id and kb.get_document(existing_kb_doc_id) is not None:
        return {"ok": True, "kb_doc_id": existing_kb_doc_id, "already_saved": True}

    settings = settings_store.get_settings()
    title = f"讨论报告：{conversation.get('title') or conversation_id}"
    category = (settings.report_kb_category or "council_reports").strip() or "council_reports"
    report_md = str(last_report.get("report_markdown") or "").strip()

    # Bind the report only to agents selected in this conversation.
    # If the conversation uses default agents (agent_ids=None), fall back to all enabled agents.
    enabled_ids = {a.id for a in agents_store.list_agents() if getattr(a, "enabled", False)}
    selected = conversation.get("agent_ids")
    if isinstance(selected, list) and selected:
        agent_ids = [str(a).strip() for a in selected if str(a).strip() and str(a).strip() in enabled_ids]
    else:
        agent_ids = sorted(enabled_ids)
    doc_id = uuid.uuid4().hex
    kb.add_document(
        doc_id=doc_id,
        title=title,
        source=f"conversation:{conversation_id}",
        text=report_md,
        categories=[category],
        agent_ids=agent_ids,
    )

    # Best-effort embeddings.
    model = (settings.kb_embedding_model or "").strip()
    embeddings = None
    if model:
        try:
            embeddings = await kb_retriever.index_embeddings(
                embedding_model_spec=model,
                doc_ids=[doc_id],
                pool=max(int(settings.kb_semantic_pool or 2000) * 10, 5000),
            )
        except Exception:
            embeddings = None

    # Bind to conversation KB scope (best-effort).
    if bool(settings.auto_bind_report_to_conversation):
        try:
            existing = conversation.get("kb_doc_ids") or []
            storage.update_conversation_kb_doc_ids(conversation_id, list(existing) + [doc_id])
        except Exception:
            pass

    # Append a new Stage4 message that includes kb_doc_id so the UI can display it.
    try:
        storage.add_stage4_report_message(
            conversation_id,
            report={
                "model": str(last_report.get("model") or ""),
                "report_markdown": report_md,
                "kb_doc_id": doc_id,
            },
        )
    except Exception:
        pass

    return {"ok": True, "kb_doc_id": doc_id, "embeddings": embeddings}


@app.put("/api/conversations/{conversation_id}/discussion")
async def set_conversation_discussion(conversation_id: str, request: ConversationDiscussionRequest):
    conversation = storage.get_conversation(conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")

    storage.update_conversation_discussion_config(
        conversation_id,
        discussion_mode=request.discussion_mode,
        serious_iteration_rounds=request.serious_iteration_rounds,
        lively_script=request.lively_script,
        lively_max_messages=request.lively_max_messages,
        lively_max_turns=request.lively_max_turns,
    )
    conv = storage.get_conversation(conversation_id) or {}
    return {
        "ok": True,
        "discussion_mode": conv.get("discussion_mode", "serious"),
        "serious_iteration_rounds": conv.get("serious_iteration_rounds", 1),
        "lively_script": conv.get("lively_script", "groupchat"),
        "lively_max_messages": conv.get("lively_max_messages", 24),
        "lively_max_turns": conv.get("lively_max_turns", 6),
    }


@app.post("/api/conversations/{conversation_id}/invoke")
async def invoke_agent(conversation_id: str, request: ConversationInvokeRequest):
    conversation = storage.get_conversation(conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")

    action = (request.action or "").strip().lower()
    agent_id = (request.agent_id or "").strip()
    if not agent_id:
        raise HTTPException(status_code=400, detail="agent_id 不能为空")

    agent = agents_store.get_agent(agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail="Agent not found")

    if action in ("ask", "say", "speak"):
        resp = await direct_invoke_agent(conversation_id=conversation_id, agent=agent, content=request.content)
        content = (resp or {}).get("content") or ""
        if not content:
            raise HTTPException(status_code=400, detail="Agent 未返回有效内容")
        storage.add_direct_assistant_message(
            conversation_id,
            agent_id=agent.id,
            agent_name=agent.name,
            model_spec=agent.model_spec,
            content=content,
        )
        return {"ok": True, "type": "direct", "agent": agent.__dict__, "content": content}

    if action in ("report", "write_report"):
        # Use latest available discussion bundle from conversation (best-effort).
        msgs = conversation.get("messages") or []
        last_user = ""
        for m in reversed(msgs):
            if isinstance(m, dict) and m.get("role") == "user":
                last_user = str(m.get("content") or "").strip()
                if last_user:
                    break
        topic = (request.content or "").strip() or last_user

        # Find the latest assistant message that contains stage outputs.
        bundle = None
        for m in reversed(msgs):
            if not isinstance(m, dict) or m.get("role") != "assistant":
                continue
            if isinstance(m.get("stage3"), dict) or isinstance(m.get("stage2"), list) or isinstance(m.get("stage1"), list):
                bundle = m
                break
        if bundle is None:
            raise HTTPException(status_code=400, detail="未找到可用于生成报告的讨论结果（请先完成一次讨论）")

        report = await stage4_generate_report(
            topic,
            stage0=bundle.get("stage0") if isinstance(bundle.get("stage0"), dict) else None,
            stage1_results=list(bundle.get("stage1") or []),
            stage2_results=list(bundle.get("stage2") or []),
            roundtable=list(bundle.get("stage2b") or []),
            fact_check=bundle.get("stage2c") if isinstance(bundle.get("stage2c"), dict) else None,
            stage3_result=bundle.get("stage3") if isinstance(bundle.get("stage3"), dict) else {},
            conversation_id=conversation_id,
            writer_agent_id=agent.id,
            override_requirements=(request.report_requirements or "").strip() or None,
        )
        if not report:
            raise HTTPException(status_code=400, detail="报告生成失败")

        # Save as a standalone assistant message entry (stage4 only).
        storage.add_stage4_report_message(
            conversation_id,
            report=report,
            agent_id=agent.id,
            agent_name=agent.name,
        )
        return {"ok": True, "type": "report", "agent": agent.__dict__, "report": report}

    raise HTTPException(status_code=400, detail="action 不支持（可用：ask|report）")


@app.post("/api/jobs")
async def create_job(request: JobCreateRequest):
    job_type = (request.job_type or "").strip()
    if not job_type:
        raise HTTPException(status_code=400, detail="job_type 不能为空")
    if not plugin_manager.registry.get(job_type):
        raise HTTPException(status_code=400, detail=f"Unknown job_type: {job_type}")
    conversation_id = (request.conversation_id or "").strip()
    if conversation_id:
        conv = storage.get_conversation(conversation_id)
        if conv is None:
            raise HTTPException(status_code=404, detail="Conversation not found")
    payload = request.payload or {}
    job = job_runner.create_and_enqueue(job_type=job_type, payload=payload, conversation_id=conversation_id)
    return {"ok": True, "job": job.__dict__}


@app.get("/api/jobs/{job_id}")
async def get_job(job_id: str):
    job = jobs_store.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return {"job": job.__dict__}


@app.get("/api/jobs")
async def list_jobs(conversation_id: str = "", status: str = "", limit: int = 50):
    jobs = jobs_store.list_jobs(conversation_id=(conversation_id or "").strip(), status=(status or "").strip(), limit=limit)
    return {"jobs": [j.__dict__ for j in jobs]}


@app.post("/api/jobs/{job_id}/cancel")
async def cancel_job(job_id: str):
    ok = jobs_store.cancel_job(job_id)
    if not ok:
        raise HTTPException(status_code=400, detail="Cannot cancel job")
    return {"ok": True}


@app.get("/api/conversations/{conversation_id}/jobs")
async def list_conversation_jobs(conversation_id: str, limit: int = 50):
    conv = storage.get_conversation(conversation_id)
    if conv is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    jobs = jobs_store.list_jobs(conversation_id=conversation_id, limit=limit)
    return {"jobs": [j.__dict__ for j in jobs]}


@app.put("/api/conversations/{conversation_id}/agents")
async def set_conversation_agents(conversation_id: str, agent_ids: List[str]):
    conversation = storage.get_conversation(conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    storage.update_conversation_agents(conversation_id, agent_ids)
    return {"ok": True}


@app.delete("/api/conversations/{conversation_id}")
async def delete_conversation(conversation_id: str):
    deleted = storage.delete_conversation(conversation_id)
    trace_store.delete(conversation_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return {"ok": True}


@app.get("/api/conversations/{conversation_id}/trace")
async def get_conversation_trace(conversation_id: str):
    conversation = storage.get_conversation(conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return {"events": trace_store.read_events(conversation_id)}


@app.get("/api/conversations/{conversation_id}/export")
async def export_conversation(conversation_id: str):
    conversation = storage.get_conversation(conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    export = {
        "conversation": conversation,
        "trace": trace_store.read_events(conversation_id),
        "agents": [a.__dict__ for a in agents_store.list_agents()],
        "models": agents_store.get_models(),
    }
    return export


@app.post("/api/conversations/{conversation_id}/message")
async def send_message(conversation_id: str, request: SendMessageRequest):
    """
    Send a message and run the 3-stage council process.
    Returns the complete response with all stages.
    """
    # Check if conversation exists
    conversation = storage.get_conversation(conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")

    # Check if this is the first message
    is_first_message = len(conversation["messages"]) == 0

    # Add user message
    storage.add_user_message(conversation_id, request.content)

    # If this is the first message, generate a title
    if is_first_message:
        title = await generate_conversation_title(request.content, conversation_id=conversation_id)
        storage.update_conversation_title(conversation_id, title)

    # Run the council process (mode-aware)
    mode = str(conversation.get("discussion_mode") or "serious").strip().lower()
    if mode not in ("serious", "lively"):
        mode = "serious"

    if mode == "lively":
        preprocess = await stage0_preprocess(request.content, conversation_id)
        lively_script = str(conversation.get("lively_script") or "groupchat").strip().lower()
        lively_max_messages = int(conversation.get("lively_max_messages") or 24)
        lively_max_turns = int(conversation.get("lively_max_turns") or 6)
        lively_out = await stage2b_lively(
            user_query=request.content,
            conversation_id=conversation_id,
            initial_script=lively_script,
            max_messages=lively_max_messages,
            max_turns=lively_max_turns,
        )
        roundtable = list(lively_out.get("transcript") or [])
        # Reuse stage3/4 generators by synthesizing stage1 from transcript.
        stage1_results = [
            {"agent_name": m.get("agent_name") or "Agent", "model": m.get("model") or "", "response": m.get("message") or ""}
            for m in roundtable
        ]
        stage2_results = []
        fact_check = None
        stage3_result = await stage3_synthesize_final(
            request.content,
            stage1_results,
            stage2_results,
            roundtable=roundtable,
            fact_check=fact_check,
            conversation_id=conversation_id,
        )
        report = await stage4_generate_report(
            request.content,
            stage0=preprocess,
            stage1_results=stage1_results,
            stage2_results=stage2_results,
            roundtable=roundtable,
            fact_check=fact_check,
            stage3_result=stage3_result,
            conversation_id=conversation_id,
        )

        # Persist script updates (best-effort)
        final_script = str(lively_out.get("script") or lively_script).strip().lower()
        if final_script and final_script != lively_script:
            storage.update_conversation_discussion_config(conversation_id, lively_script=final_script)
        for item in list(lively_out.get("script_history") or []):
            if isinstance(item, dict):
                storage.update_conversation_discussion_config(
                    conversation_id,
                    lively_script_history_append=item,
                )

        metadata = {
            "preprocess": preprocess,
            "roundtable": roundtable,
            "fact_check": fact_check,
            "report": report,
            "discussion_mode": "lively",
            "lively": lively_out,
        }
    else:
        preprocess = await stage0_preprocess(request.content, conversation_id)
        rounds = max(1, min(8, int(conversation.get("serious_iteration_rounds") or 1)))
        stage1_results = []
        stage2_results = []
        stage3_result = {}
        roundtable = []
        fact_check = None
        report = None
        iterations_meta = []
        draft = ""
        label_to_agent = {}
        aggregate_rankings = {}

        for i in range(1, rounds + 1):
            q = request.content if i == 1 else (request.content + "\n\n【上轮报告草稿（用于继续迭代）】\n" + (draft or "") + "\n\n请继续完善并修订。")
            stage1_results = await stage1_collect_responses(q, conversation_id=conversation_id, preprocess=preprocess)
            stage2_results, label_to_agent = await stage2_collect_rankings(q, stage1_results, conversation_id=conversation_id)
            aggregate_rankings = calculate_aggregate_rankings(stage2_results, label_to_agent)
            roundtable = await stage2b_roundtable(q, stage1_results, stage2_results, conversation_id=conversation_id)
            fact_check = await stage2c_fact_check(q, stage1_results, stage2_results, roundtable, conversation_id=conversation_id)
            stage3_result = await stage3_synthesize_final(
                q,
                stage1_results,
                stage2_results,
                roundtable=roundtable,
                fact_check=fact_check,
                conversation_id=conversation_id,
            )
            report = await stage4_generate_report(
                q,
                stage0=preprocess,
                stage1_results=stage1_results,
                stage2_results=stage2_results,
                roundtable=roundtable,
                fact_check=fact_check,
                stage3_result=stage3_result,
                conversation_id=conversation_id,
            )
            draft = str((report or {}).get("report_markdown") or "")
            iterations_meta.append(
                {
                    "iteration": i,
                    "aggregate_rankings": aggregate_rankings,
                    "report_kb_doc_id": (report or {}).get("kb_doc_id") if isinstance(report, dict) else "",
                }
            )

        metadata = {
            "label_to_agent": label_to_agent,
            "aggregate_rankings": aggregate_rankings,
            "preprocess": preprocess,
            "roundtable": roundtable,
            "fact_check": fact_check,
            "report": report,
            "discussion_mode": "serious",
            "serious_iterations": iterations_meta,
        }

    # Add assistant message with all stages (including optional extra stages)
    storage.add_assistant_message(
        conversation_id,
        stage1_results,
        stage2_results,
        stage3_result,
        stage0=metadata.get("preprocess"),
        stage2b=metadata.get("roundtable"),
        stage2c=metadata.get("fact_check"),
        stage4=metadata.get("report"),
        metadata=metadata,
    )

    # Return the complete response with metadata
    return {
        "stage0": metadata.get("preprocess"),
        "stage1": stage1_results,
        "stage2": stage2_results,
        "stage2b": metadata.get("roundtable"),
        "stage2c": metadata.get("fact_check"),
        "stage3": stage3_result,
        "stage4": metadata.get("report"),
        "metadata": metadata,
    }


@app.post("/api/conversations/{conversation_id}/message/stream")
async def send_message_stream(conversation_id: str, request: SendMessageRequest):
    """
    Send a message and stream the 3-stage council process.
    Returns Server-Sent Events as each stage completes.
    """
    # Check if conversation exists
    conversation = storage.get_conversation(conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")

    # Check if this is the first message
    is_first_message = len(conversation["messages"]) == 0

    async def event_generator():
        try:
            # Add user message
            storage.add_user_message(conversation_id, request.content)

            # Start title generation in parallel (don't await yet)
            title_task = None
            if is_first_message:
                title_task = asyncio.create_task(generate_conversation_title(request.content, conversation_id=conversation_id))

            # Stage 0: Preprocess (optional)
            yield f"data: {json.dumps({'type': 'stage0_start'})}\n\n"
            preprocess = await stage0_preprocess(request.content, conversation_id)
            yield f"data: {json.dumps({'type': 'stage0_complete', 'data': preprocess})}\n\n"

            # Mode-aware discussion
            conv_now = storage.get_conversation(conversation_id) or {}
            mode = str(conv_now.get("discussion_mode") or "serious").strip().lower()
            if mode not in ("serious", "lively"):
                mode = "serious"

            label_to_agent = {}
            aggregate_rankings = {}
            roundtable = []
            fact_check = None
            report = None
            stage3_result = {}
            stage2_results = []
            stage1_results = []
            metadata = {}

            if mode == "lively":
                lively_script = str(conv_now.get("lively_script") or "groupchat").strip().lower()
                lively_max_messages = int(conv_now.get("lively_max_messages") or 24)
                lively_max_turns = int(conv_now.get("lively_max_turns") or 6)

                # Stage 1: empty (not used in lively)
                yield f"data: {json.dumps({'type': 'stage1_start', 'mode': 'lively'})}\n\n"
                stage1_results = []
                yield f"data: {json.dumps({'type': 'stage1_complete', 'data': stage1_results, 'mode': 'lively'})}\n\n"

                # Stage 2: empty (not used in lively)
                yield f"data: {json.dumps({'type': 'stage2_start', 'mode': 'lively'})}\n\n"
                stage2_results = []
                label_to_agent = {}
                aggregate_rankings = {}
                yield f"data: {json.dumps({'type': 'stage2_complete', 'data': stage2_results, 'metadata': {'label_to_agent': label_to_agent, 'aggregate_rankings': aggregate_rankings}, 'mode': 'lively'})}\n\n"

                # Stage 2B: lively transcript
                yield f"data: {json.dumps({'type': 'stage2b_start', 'mode': 'lively'})}\n\n"
                lively_out = await stage2b_lively(
                    user_query=request.content,
                    conversation_id=conversation_id,
                    initial_script=lively_script,
                    max_messages=lively_max_messages,
                    max_turns=lively_max_turns,
                )
                roundtable = list(lively_out.get("transcript") or [])
                yield f"data: {json.dumps({'type': 'stage2b_complete', 'data': roundtable, 'mode': 'lively', 'metadata': {'lively': lively_out}})}\n\n"

                # Persist script updates (best-effort)
                final_script = str(lively_out.get("script") or lively_script).strip().lower()
                if final_script and final_script != lively_script:
                    storage.update_conversation_discussion_config(conversation_id, lively_script=final_script)
                for item in list(lively_out.get("script_history") or []):
                    if isinstance(item, dict):
                        storage.update_conversation_discussion_config(conversation_id, lively_script_history_append=item)

                # Stage 2C: skipped in lively (optional future)
                yield f"data: {json.dumps({'type': 'stage2c_start', 'mode': 'lively'})}\n\n"
                fact_check = None
                yield f"data: {json.dumps({'type': 'stage2c_complete', 'data': fact_check, 'mode': 'lively'})}\n\n"

                # Synthesize stage1 from transcript for chairman summary/report
                stage1_results = [
                    {"agent_name": m.get("agent_name") or "Agent", "model": m.get("model") or "", "response": m.get("message") or ""}
                    for m in roundtable
                ]

                yield f"data: {json.dumps({'type': 'stage3_start', 'mode': 'lively'})}\n\n"
                stage3_result = await stage3_synthesize_final(
                    request.content,
                    stage1_results,
                    stage2_results,
                    roundtable=roundtable,
                    fact_check=fact_check,
                    conversation_id=conversation_id,
                )
                yield f"data: {json.dumps({'type': 'stage3_complete', 'data': stage3_result, 'mode': 'lively'})}\n\n"

                yield f"data: {json.dumps({'type': 'stage4_start', 'mode': 'lively'})}\n\n"
                report = await stage4_generate_report(
                    request.content,
                    stage0=preprocess,
                    stage1_results=stage1_results,
                    stage2_results=stage2_results,
                    roundtable=roundtable,
                    fact_check=fact_check,
                    stage3_result=stage3_result,
                    conversation_id=conversation_id,
                )
                yield f"data: {json.dumps({'type': 'stage4_complete', 'data': report, 'mode': 'lively'})}\n\n"

                metadata = {
                    "label_to_agent": label_to_agent,
                    "aggregate_rankings": aggregate_rankings,
                    "preprocess": preprocess,
                    "roundtable": roundtable,
                    "fact_check": fact_check,
                    "report": report,
                    "discussion_mode": "lively",
                    "lively": lively_out,
                }
            else:
                rounds = max(1, min(8, int(conv_now.get("serious_iteration_rounds") or 1)))
                iterations_meta = []
                draft = ""

                for it in range(1, rounds + 1):
                    q = request.content if it == 1 else (request.content + "\n\n【上轮报告草稿（用于继续迭代）】\n" + (draft or "") + "\n\n请继续完善并修订。")

                    yield f"data: {json.dumps({'type': 'stage1_start', 'mode': 'serious', 'iteration': it, 'iterations': rounds})}\n\n"
                    stage1_results = await stage1_collect_responses(q, conversation_id=conversation_id, preprocess=preprocess)
                    yield f"data: {json.dumps({'type': 'stage1_complete', 'data': stage1_results, 'mode': 'serious', 'iteration': it, 'iterations': rounds})}\n\n"

                    yield f"data: {json.dumps({'type': 'stage2_start', 'mode': 'serious', 'iteration': it, 'iterations': rounds})}\n\n"
                    stage2_results, label_to_agent = await stage2_collect_rankings(q, stage1_results, conversation_id=conversation_id)
                    aggregate_rankings = calculate_aggregate_rankings(stage2_results, label_to_agent)
                    yield f"data: {json.dumps({'type': 'stage2_complete', 'data': stage2_results, 'metadata': {'label_to_agent': label_to_agent, 'aggregate_rankings': aggregate_rankings}, 'mode': 'serious', 'iteration': it, 'iterations': rounds})}\n\n"

                    yield f"data: {json.dumps({'type': 'stage2b_start', 'mode': 'serious', 'iteration': it, 'iterations': rounds})}\n\n"
                    roundtable = await stage2b_roundtable(q, stage1_results, stage2_results, conversation_id=conversation_id)
                    yield f"data: {json.dumps({'type': 'stage2b_complete', 'data': roundtable, 'mode': 'serious', 'iteration': it, 'iterations': rounds})}\n\n"

                    yield f"data: {json.dumps({'type': 'stage2c_start', 'mode': 'serious', 'iteration': it, 'iterations': rounds})}\n\n"
                    fact_check = await stage2c_fact_check(q, stage1_results, stage2_results, roundtable, conversation_id=conversation_id)
                    yield f"data: {json.dumps({'type': 'stage2c_complete', 'data': fact_check, 'mode': 'serious', 'iteration': it, 'iterations': rounds})}\n\n"

                    yield f"data: {json.dumps({'type': 'stage3_start', 'mode': 'serious', 'iteration': it, 'iterations': rounds})}\n\n"
                    stage3_result = await stage3_synthesize_final(
                        q,
                        stage1_results,
                        stage2_results,
                        roundtable=roundtable,
                        fact_check=fact_check,
                        conversation_id=conversation_id,
                    )
                    yield f"data: {json.dumps({'type': 'stage3_complete', 'data': stage3_result, 'mode': 'serious', 'iteration': it, 'iterations': rounds})}\n\n"

                    yield f"data: {json.dumps({'type': 'stage4_start', 'mode': 'serious', 'iteration': it, 'iterations': rounds})}\n\n"
                    report = await stage4_generate_report(
                        q,
                        stage0=preprocess,
                        stage1_results=stage1_results,
                        stage2_results=stage2_results,
                        roundtable=roundtable,
                        fact_check=fact_check,
                        stage3_result=stage3_result,
                        conversation_id=conversation_id,
                    )
                    yield f"data: {json.dumps({'type': 'stage4_complete', 'data': report, 'mode': 'serious', 'iteration': it, 'iterations': rounds})}\n\n"

                    draft = str((report or {}).get("report_markdown") or "")
                    iterations_meta.append({"iteration": it, "report_kb_doc_id": (report or {}).get("kb_doc_id") if isinstance(report, dict) else ""})

                metadata = {
                    "label_to_agent": label_to_agent,
                    "aggregate_rankings": aggregate_rankings,
                    "preprocess": preprocess,
                    "roundtable": roundtable,
                    "fact_check": fact_check,
                    "report": report,
                    "discussion_mode": "serious",
                    "serious_iterations": iterations_meta,
                }

            # Wait for title generation if it was started
            if title_task:
                title = await title_task
                storage.update_conversation_title(conversation_id, title)
                yield f"data: {json.dumps({'type': 'title_complete', 'data': {'title': title}})}\n\n"

            # Save complete assistant message
            storage.add_assistant_message(
                conversation_id,
                stage1_results,
                stage2_results,
                stage3_result,
                stage0=preprocess,
                stage2b=roundtable,
                stage2c=fact_check,
                stage4=report,
                metadata=metadata,
            )

            # Send completion event
            yield f"data: {json.dumps({'type': 'complete'})}\n\n"

        except Exception as e:
            # Send error event
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        }
    )


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("BACKEND_PORT") or os.getenv("PORT") or "8001")
    uvicorn.run(app, host="0.0.0.0", port=port)
