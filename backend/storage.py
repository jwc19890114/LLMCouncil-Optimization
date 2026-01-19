"""JSON-based storage for conversations."""

import json
from datetime import datetime
from typing import List, Dict, Any, Optional
from pathlib import Path
from .config import DATA_DIR
from .file_utils import atomic_write_json


DATA_DIR_PATH = Path(DATA_DIR)


def ensure_data_dir():
    """Ensure the data directory exists."""
    DATA_DIR_PATH.mkdir(parents=True, exist_ok=True)


def get_conversation_path(conversation_id: str) -> Path:
    """Get the file path for a conversation."""
    return DATA_DIR_PATH / f"{conversation_id}.json"


def create_conversation(conversation_id: str) -> Dict[str, Any]:
    """
    Create a new conversation.

    Args:
        conversation_id: Unique identifier for the conversation

    Returns:
        New conversation dict
    """
    ensure_data_dir()

    conversation = {
        "id": conversation_id,
        "created_at": datetime.utcnow().isoformat(),
        "title": "New Conversation",
        "agent_ids": None,
        "chairman_model": "",
        "chairman_agent_id": "",
        "kb_doc_ids": [],
        "report_requirements": "",
        # Discussion mode + controls
        # serious: staged process + report iteration rounds
        # lively: free-flow multi-agent chat with script switching + final report
        "discussion_mode": "serious",
        "serious_iteration_rounds": 1,
        "lively_script": "groupchat",  # brainstorm | interview | groupchat
        "lively_script_history": [],
        "lively_max_messages": 24,
        "lively_max_turns": 6,
        "messages": []
    }

    # Save to file
    path = get_conversation_path(conversation_id)
    atomic_write_json(path, conversation, ensure_ascii=False, indent=2)

    return conversation


def get_conversation(conversation_id: str) -> Optional[Dict[str, Any]]:
    """
    Load a conversation from storage.

    Args:
        conversation_id: Unique identifier for the conversation

    Returns:
        Conversation dict or None if not found
    """
    path = get_conversation_path(conversation_id)

    if not path.exists():
        return None

    try:
        with open(path, "r", encoding="utf-8") as f:
            conv = json.load(f)
    except Exception as e:
        print(f"Failed to load conversation {conversation_id}: {e}")
        return None

    # Backwards compatible defaults for older conversation files.
    if isinstance(conv, dict):
        if "chairman_model" not in conv or conv.get("chairman_model") is None:
            conv["chairman_model"] = ""
        if "chairman_agent_id" not in conv or conv.get("chairman_agent_id") is None:
            conv["chairman_agent_id"] = ""
        if "kb_doc_ids" not in conv or conv.get("kb_doc_ids") is None:
            conv["kb_doc_ids"] = []
        if "report_requirements" not in conv or conv.get("report_requirements") is None:
            conv["report_requirements"] = ""
        if "discussion_mode" not in conv or conv.get("discussion_mode") is None:
            conv["discussion_mode"] = "serious"
        if "serious_iteration_rounds" not in conv or conv.get("serious_iteration_rounds") is None:
            conv["serious_iteration_rounds"] = 1
        if "lively_script" not in conv or conv.get("lively_script") is None:
            conv["lively_script"] = "groupchat"
        if "lively_script_history" not in conv or conv.get("lively_script_history") is None:
            conv["lively_script_history"] = []
        if "lively_max_messages" not in conv or conv.get("lively_max_messages") is None:
            conv["lively_max_messages"] = 24
        if "lively_max_turns" not in conv or conv.get("lively_max_turns") is None:
            conv["lively_max_turns"] = 6
    return conv


def save_conversation(conversation: Dict[str, Any]):
    """
    Save a conversation to storage.

    Args:
        conversation: Conversation dict to save
    """
    ensure_data_dir()

    path = get_conversation_path(conversation['id'])
    atomic_write_json(path, conversation, ensure_ascii=False, indent=2)


def list_conversations() -> List[Dict[str, Any]]:
    """
    List all conversations (metadata only).

    Returns:
        List of conversation metadata dicts
    """
    ensure_data_dir()

    conversations = []
    for path in DATA_DIR_PATH.glob("*.json"):
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            continue
        # Return metadata only
        conversations.append(
            {
                "id": data["id"],
                "created_at": data["created_at"],
                "title": data.get("title", "New Conversation"),
                "message_count": len(data["messages"]),
            }
        )

    # Sort by creation time, newest first
    conversations.sort(key=lambda x: x["created_at"], reverse=True)

    return conversations


def delete_conversation(conversation_id: str) -> bool:
    """Delete a conversation file. Returns True if deleted."""
    path = get_conversation_path(conversation_id)
    if not path.exists():
        return False
    path.unlink()
    return True


def add_user_message(conversation_id: str, content: str):
    """
    Add a user message to a conversation.

    Args:
        conversation_id: Conversation identifier
        content: User message content
    """
    conversation = get_conversation(conversation_id)
    if conversation is None:
        raise ValueError(f"Conversation {conversation_id} not found")

    conversation["messages"].append({
        "role": "user",
        "content": content
    })

    save_conversation(conversation)


def add_assistant_message(
    conversation_id: str,
    stage1: List[Dict[str, Any]],
    stage2: List[Dict[str, Any]],
    stage3: Dict[str, Any],
    *,
    stage0: Any = None,
    stage2b: Any = None,
    stage2c: Any = None,
    stage4: Any = None,
    metadata: Any = None,
):
    """
    Add an assistant message with all 3 stages to a conversation.

    Args:
        conversation_id: Conversation identifier
        stage1: List of individual model responses
        stage2: List of model rankings
        stage3: Final synthesized response
    """
    conversation = get_conversation(conversation_id)
    if conversation is None:
        raise ValueError(f"Conversation {conversation_id} not found")

    conversation["messages"].append({
        "role": "assistant",
        "stage0": stage0,
        "stage1": stage1,
        "stage2": stage2,
        "stage2b": stage2b,
        "stage2c": stage2c,
        "stage3": stage3,
        "stage4": stage4,
        "metadata": metadata,
    })

    save_conversation(conversation)


def update_conversation_title(conversation_id: str, title: str):
    """
    Update the title of a conversation.

    Args:
        conversation_id: Conversation identifier
        title: New title for the conversation
    """
    conversation = get_conversation(conversation_id)
    if conversation is None:
        raise ValueError(f"Conversation {conversation_id} not found")

    conversation["title"] = title
    save_conversation(conversation)


def add_direct_assistant_message(
    conversation_id: str,
    *,
    agent_id: str,
    agent_name: str,
    model_spec: str,
    content: str,
):
    conversation = get_conversation(conversation_id)
    if conversation is None:
        raise ValueError(f"Conversation {conversation_id} not found")
    conversation["messages"].append(
        {
            "role": "assistant",
            "direct": {
                "agent_id": agent_id,
                "agent_name": agent_name,
                "model_spec": model_spec,
                "content": content,
            },
        }
    )
    save_conversation(conversation)


def add_stage4_report_message(
    conversation_id: str,
    *,
    report: Dict[str, Any],
    agent_id: str = "",
    agent_name: str = "",
):
    conversation = get_conversation(conversation_id)
    if conversation is None:
        raise ValueError(f"Conversation {conversation_id} not found")
    conversation["messages"].append(
        {
            "role": "assistant",
            "stage4": report,
            "metadata": {"type": "ad_hoc_report", "agent_id": agent_id, "agent_name": agent_name},
        }
    )
    save_conversation(conversation)


def update_conversation_agents(conversation_id: str, agent_ids):
    conversation = get_conversation(conversation_id)
    if conversation is None:
        raise ValueError(f"Conversation {conversation_id} not found")
    if agent_ids is not None and isinstance(agent_ids, list) and len(agent_ids) == 0:
        conversation["agent_ids"] = None
    else:
        conversation["agent_ids"] = agent_ids
    save_conversation(conversation)


def update_conversation_kb_doc_ids(conversation_id: str, doc_ids: List[str]):
    conversation = get_conversation(conversation_id)
    if conversation is None:
        raise ValueError(f"Conversation {conversation_id} not found")
    cleaned = [d.strip() for d in (doc_ids or []) if isinstance(d, str) and d.strip()]
    # De-duplicate, preserve order.
    seen = set()
    unique = []
    for d in cleaned:
        if d in seen:
            continue
        seen.add(d)
        unique.append(d)
    conversation["kb_doc_ids"] = unique
    save_conversation(conversation)


def update_conversation_report_requirements(conversation_id: str, report_requirements: str):
    conversation = get_conversation(conversation_id)
    if conversation is None:
        raise ValueError(f"Conversation {conversation_id} not found")
    conversation["report_requirements"] = str(report_requirements or "").strip()
    save_conversation(conversation)


def update_conversation_chairman_model(conversation_id: str, chairman_model: str):
    conversation = get_conversation(conversation_id)
    if conversation is None:
        raise ValueError(f"Conversation {conversation_id} not found")
    conversation["chairman_model"] = (chairman_model or "").strip()
    save_conversation(conversation)


def update_conversation_chairman_agent(conversation_id: str, chairman_agent_id: str):
    conversation = get_conversation(conversation_id)
    if conversation is None:
        raise ValueError(f"Conversation {conversation_id} not found")
    conversation["chairman_agent_id"] = (chairman_agent_id or "").strip()
    save_conversation(conversation)


def update_conversation_discussion_config(
    conversation_id: str,
    *,
    discussion_mode: str | None = None,
    serious_iteration_rounds: int | None = None,
    lively_script: str | None = None,
    lively_max_messages: int | None = None,
    lively_max_turns: int | None = None,
    lively_script_history_append: dict | None = None,
):
    conversation = get_conversation(conversation_id)
    if conversation is None:
        raise ValueError(f"Conversation {conversation_id} not found")

    if discussion_mode is not None:
        mode = str(discussion_mode or "").strip().lower()
        if mode in ("serious", "lively"):
            conversation["discussion_mode"] = mode

    if serious_iteration_rounds is not None:
        try:
            n = int(serious_iteration_rounds)
        except Exception:
            n = 1
        conversation["serious_iteration_rounds"] = max(1, min(8, n))

    if lively_script is not None:
        script = str(lively_script or "").strip().lower()
        if script in ("brainstorm", "interview", "groupchat"):
            conversation["lively_script"] = script

    if lively_max_messages is not None:
        try:
            n = int(lively_max_messages)
        except Exception:
            n = 24
        conversation["lively_max_messages"] = max(6, min(200, n))

    if lively_max_turns is not None:
        try:
            n = int(lively_max_turns)
        except Exception:
            n = 6
        conversation["lively_max_turns"] = max(1, min(50, n))

    if lively_script_history_append is not None and isinstance(lively_script_history_append, dict):
        hist = conversation.get("lively_script_history")
        if not isinstance(hist, list):
            hist = []
        hist.append(lively_script_history_append)
        # Keep it bounded.
        conversation["lively_script_history"] = hist[-200:]

    save_conversation(conversation)
