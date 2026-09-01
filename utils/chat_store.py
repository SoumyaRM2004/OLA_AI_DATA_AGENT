import os
import json
import time
import uuid
from typing import Dict, Any, List, Optional
from datetime import datetime


CHATS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "chats")


def _ensure_dir():
    os.makedirs(CHATS_DIR, exist_ok=True)


def _get_index_path() -> str:
    _ensure_dir()
    return os.path.join(CHATS_DIR, "index.json")


def _get_chat_path(chat_id: str) -> str:
    _ensure_dir()
    safe_id = "".join(c for c in chat_id if c.isalnum() or c in ("-", "_"))
    return os.path.join(CHATS_DIR, f"{safe_id}.json")


def _generate_title_from_text(text: str) -> str:
    """Generates a clean, concise 3-6 word title from user's first prompt."""
    if not text:
        return "New Chat"
    cleaned = text.strip()
    words = cleaned.split()
    if len(words) <= 5:
        title = " ".join(words)
    else:
        title = " ".join(words[:5]) + "..."
    # Capitalize first letter
    return title[0].upper() + title[1:] if title else "New Chat"


class ChatStore:
    """
    Persistent storage engine for AI Chat Studio multi-conversation sessions.
    Stores metadata index and full conversation message streams safely as JSON files.
    """

    @classmethod
    def list_chats(cls, session_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """Returns all chat session summaries sorted by updated_at descending, optionally filtered by session_id."""
        _ensure_dir()
        index_path = _get_index_path()
        chats = []
        if os.path.exists(index_path):
            try:
                with open(index_path, "r", encoding="utf-8") as f:
                    chats = json.load(f)
            except Exception:
                chats = []

        if session_id:
            chats = [c for c in chats if c.get("session_id") == session_id]

        # If no chats exist for this session, initialize the default first chat
        if not chats:
            first_chat = cls.create_chat(title="New Chat", session_id=session_id)
            return [first_chat]

        return sorted(chats, key=lambda x: x.get("updated_at", ""), reverse=True)

    @classmethod
    def create_chat(cls, title: str = "New Chat", session_id: Optional[str] = None) -> Dict[str, Any]:
        """Creates and persists a new unique chat session associated with an optional session_id."""
        _ensure_dir()
        chat_id = f"chat_{int(time.time()*1000)}_{uuid.uuid4().hex[:6]}"
        now_iso = datetime.now().isoformat()

        chat_data = {
            "id": chat_id,
            "title": title.strip() or "New Chat",
            "session_id": session_id,
            "created_at": now_iso,
            "updated_at": now_iso,
            "messages": []
        }

        # Write individual chat file
        with open(_get_chat_path(chat_id), "w", encoding="utf-8") as f:
            json.dump(chat_data, f, indent=2, ensure_ascii=False)

        # Update index
        chats = cls.list_chats_raw()
        chats.insert(0, {
            "id": chat_id,
            "title": chat_data["title"],
            "session_id": session_id,
            "created_at": now_iso,
            "updated_at": now_iso,
            "message_count": 0
        })
        cls._save_index(chats)

        return chat_data

    @classmethod
    def get_chat(cls, chat_id: str, session_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """
        Fetches full chat session including message history.
        Enforces session ownership: if session_id is provided, chats belonging to other sessions return None.
        """
        if not chat_id:
            return None
        chat_path = _get_chat_path(chat_id)
        if not os.path.exists(chat_path):
            return None
        try:
            with open(chat_path, "r", encoding="utf-8") as f:
                chat_data = json.load(f)
            
            # Enforce session isolation if session_id is specified
            if session_id:
                chat_session = chat_data.get("session_id")
                if chat_session and chat_session != session_id:
                    return None

            return chat_data
        except Exception:
            return None

    @classmethod
    def update_chat_title(cls, chat_id: str, title: str, session_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Renames a specific chat session if owned by the active session."""
        chat_data = cls.get_chat(chat_id, session_id=session_id)
        if not chat_data:
            return None

        clean_title = title.strip() or "Untitled Chat"
        now_iso = datetime.now().isoformat()
        chat_data["title"] = clean_title
        chat_data["updated_at"] = now_iso

        # Save individual chat
        with open(_get_chat_path(chat_id), "w", encoding="utf-8") as f:
            json.dump(chat_data, f, indent=2, ensure_ascii=False)

        # Update index
        chats = cls.list_chats_raw()
        for c in chats:
            if c["id"] == chat_id:
                c["title"] = clean_title
                c["updated_at"] = now_iso
                break
        cls._save_index(chats)

        return chat_data

    @classmethod
    def delete_chat(cls, chat_id: str, session_id: Optional[str] = None) -> bool:
        """Deletes a chat session file and removes it from the index if owned by the active session."""
        chat_data = cls.get_chat(chat_id, session_id=session_id)
        if not chat_data:
            return False

        chat_path = _get_chat_path(chat_id)
        if os.path.exists(chat_path):
            try:
                os.remove(chat_path)
            except Exception:
                pass

        chats = cls.list_chats_raw()
        filtered = [c for c in chats if c["id"] != chat_id]
        cls._save_index(filtered)
        return True

    @classmethod
    def add_message(cls, chat_id: str, role: str, content: str, extra_data: Optional[Dict[str, Any]] = None, session_id: Optional[str] = None) -> Dict[str, Any]:
        """Appends a message to the specified chat session and updates metadata."""
        chat_data = cls.get_chat(chat_id, session_id=session_id)
        if not chat_data:
            chat_data = cls.create_chat(title="New Chat", session_id=session_id)
            chat_id = chat_data["id"]

        now_iso = datetime.now().isoformat()
        msg_id = f"msg_{int(time.time()*1000)}_{uuid.uuid4().hex[:4]}"

        message_obj = {
            "id": msg_id,
            "chat_id": chat_id,
            "role": role,
            "content": content,
            "timestamp": now_iso,
            "extra": extra_data or {}
        }

        chat_data["messages"].append(message_obj)
        chat_data["updated_at"] = now_iso

        # If first user message and title is default, auto-generate title
        user_messages = [m for m in chat_data["messages"] if m["role"] == "user"]
        if len(user_messages) == 1 and role == "user" and chat_data.get("title") in ("New Chat", "Untitled Chat", ""):
            chat_data["title"] = _generate_title_from_text(content)

        # Save individual chat
        with open(_get_chat_path(chat_id), "w", encoding="utf-8") as f:
            json.dump(chat_data, f, indent=2, ensure_ascii=False)

        # Update index
        chats = cls.list_chats_raw()
        found = False
        for c in chats:
            if c["id"] == chat_id:
                c["title"] = chat_data["title"]
                c["updated_at"] = now_iso
                c["message_count"] = len(chat_data["messages"])
                found = True
                break
        if not found:
            chats.insert(0, {
                "id": chat_id,
                "title": chat_data["title"],
                "session_id": session_id,
                "created_at": chat_data.get("created_at", now_iso),
                "updated_at": now_iso,
                "message_count": len(chat_data["messages"])
            })
        cls._save_index(chats)

        return message_obj

    @classmethod
    def clear_messages(cls, chat_id: str, session_id: Optional[str] = None) -> bool:
        """Clears message history of a chat without deleting the session if owned by the active session."""
        chat_data = cls.get_chat(chat_id, session_id=session_id)
        if not chat_data:
            return False

        now_iso = datetime.now().isoformat()
        chat_data["messages"] = []
        chat_data["updated_at"] = now_iso

        with open(_get_chat_path(chat_id), "w", encoding="utf-8") as f:
            json.dump(chat_data, f, indent=2, ensure_ascii=False)

        chats = cls.list_chats_raw()
        for c in chats:
            if c["id"] == chat_id:
                c["updated_at"] = now_iso
                c["message_count"] = 0
                break
        cls._save_index(chats)
        return True

    @classmethod
    def list_chats_raw(cls) -> List[Dict[str, Any]]:
        index_path = _get_index_path()
        if os.path.exists(index_path):
            try:
                with open(index_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                return []
        return []

    @classmethod
    def _save_index(cls, chats: List[Dict[str, Any]]):
        index_path = _get_index_path()
        with open(index_path, "w", encoding="utf-8") as f:
            json.dump(chats, f, indent=2, ensure_ascii=False)
