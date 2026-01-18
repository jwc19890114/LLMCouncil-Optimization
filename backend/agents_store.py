"""Persistent agent configuration store."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from .config import PROJECT_ROOT, COUNCIL_MODELS, CHAIRMAN_MODEL, TITLE_MODEL
from .file_utils import atomic_write_json


AGENTS_FILE = PROJECT_ROOT / "data" / "agents.json"


@dataclass
class AgentConfig:
    id: str
    name: str
    model_spec: str
    enabled: bool = True
    persona: str = ""
    influence_weight: float = 1.0
    seniority_years: int = 0
    kb_doc_ids: List[str] = field(default_factory=list)
    kb_categories: List[str] = field(default_factory=list)
    graph_id: str = ""
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())


def _ensure_agents_file_dir():
    AGENTS_FILE.parent.mkdir(parents=True, exist_ok=True)


def _default_agents_from_config() -> List[AgentConfig]:
    agents: List[AgentConfig] = []
    for idx, spec in enumerate(COUNCIL_MODELS, start=1):
        agents.append(
            AgentConfig(
                id=f"agent-{idx}",
                name=f"Agent {idx}",
                model_spec=spec,
            )
        )
    return agents


def _load_raw() -> Dict[str, Any]:
    if not AGENTS_FILE.exists():
        return {}
    with open(AGENTS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def _save_raw(data: Dict[str, Any]):
    _ensure_agents_file_dir()
    atomic_write_json(AGENTS_FILE, data, ensure_ascii=False, indent=2)


def ensure_initialized():
    if AGENTS_FILE.exists():
        return
    data = {
        "agents": [asdict(a) for a in _default_agents_from_config()],
        "chairman_model": CHAIRMAN_MODEL,
        "title_model": TITLE_MODEL,
        "updated_at": datetime.utcnow().isoformat(),
    }
    _save_raw(data)


def list_agents() -> List[AgentConfig]:
    ensure_initialized()
    data = _load_raw()
    agents = data.get("agents", [])
    out: List[AgentConfig] = []
    for a in agents:
        out.append(
            AgentConfig(
                id=a["id"],
                name=a.get("name", a["id"]),
                model_spec=a["model_spec"],
                enabled=bool(a.get("enabled", True)),
                persona=a.get("persona", "") or "",
                influence_weight=float(a.get("influence_weight", 1.0)),
                seniority_years=int(a.get("seniority_years", 0)),
                kb_doc_ids=list(a.get("kb_doc_ids") or []),
                kb_categories=list(a.get("kb_categories") or []),
                graph_id=a.get("graph_id", "") or "",
                created_at=a.get("created_at") or datetime.utcnow().isoformat(),
            )
        )
    return out


def get_agent(agent_id: str) -> Optional[AgentConfig]:
    for a in list_agents():
        if a.id == agent_id:
            return a
    return None


def upsert_agent(agent: AgentConfig) -> AgentConfig:
    ensure_initialized()
    data = _load_raw()
    agents = data.get("agents", [])

    replaced = False
    for i, a in enumerate(agents):
        if a.get("id") == agent.id:
            agents[i] = asdict(agent)
            replaced = True
            break
    if not replaced:
        agents.append(asdict(agent))

    data["agents"] = agents
    data["updated_at"] = datetime.utcnow().isoformat()
    _save_raw(data)
    return agent


def delete_agent(agent_id: str) -> bool:
    ensure_initialized()
    data = _load_raw()
    agents = data.get("agents", [])
    new_agents = [a for a in agents if a.get("id") != agent_id]
    if len(new_agents) == len(agents):
        return False
    data["agents"] = new_agents
    data["updated_at"] = datetime.utcnow().isoformat()
    _save_raw(data)
    return True


def set_models(chairman_model: Optional[str] = None, title_model: Optional[str] = None) -> Dict[str, str]:
    ensure_initialized()
    data = _load_raw()
    if chairman_model is not None:
        data["chairman_model"] = chairman_model
    if title_model is not None:
        data["title_model"] = title_model
    data["updated_at"] = datetime.utcnow().isoformat()
    _save_raw(data)
    return {
        "chairman_model": data.get("chairman_model", CHAIRMAN_MODEL),
        "title_model": data.get("title_model", TITLE_MODEL),
    }


def get_models() -> Dict[str, str]:
    ensure_initialized()
    data = _load_raw()
    return {
        "chairman_model": data.get("chairman_model", CHAIRMAN_MODEL),
        "title_model": data.get("title_model", TITLE_MODEL),
    }
