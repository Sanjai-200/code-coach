"""
firebase_config.py
-------------------
Initializes Firebase Admin SDK using firebase-key.json and provides a
generic, dynamic reader of Firestore's current contents.

No collection or field names are hardcoded here. The developer creates and
maintains whatever collections/documents/fields make sense for their domain,
and this module just reads whatever exists at request time and hands it to
the chatbot as context. Gemini is responsible for interpreting field names,
abbreviations, and relationships (see chatbot_config.py).
"""

import json
import os

import firebase_admin
from firebase_admin import credentials, firestore

_FIREBASE_KEY_PATH = os.path.join(os.path.dirname(__file__), "firebase-key.json")

# Safety limits so one huge collection can't blow up the prompt / bill.
MAX_DOCS_PER_COLLECTION = 100
MAX_FIELD_VALUE_CHARS = 2000

_app = None
_db = None


def _looks_like_placeholder(key_path: str) -> bool:
    try:
        with open(key_path, "r") as f:
            data = json.load(f)
        return data.get("type") == "PLACEHOLDER"
    except Exception:
        return False


def init_firebase():
    """Initializes the Firebase Admin app once. Safe to call multiple times."""
    global _app, _db
    if _app is not None:
        return _app

    if not os.path.exists(_FIREBASE_KEY_PATH):
        raise RuntimeError(
            "firebase-key.json not found. Replace the placeholder with your "
            "own Firebase service-account key."
        )

    if _looks_like_placeholder(_FIREBASE_KEY_PATH):
        raise RuntimeError(
            "firebase-key.json is still the placeholder file. Replace it with "
            "your real Firebase service-account JSON before running the app."
        )

    cred = credentials.Certificate(_FIREBASE_KEY_PATH)
    _app = firebase_admin.initialize_app(cred)
    _db = firestore.client()
    return _app


def get_db():
    if _db is None:
        init_firebase()
    return _db


def _truncate(value):
    if isinstance(value, str) and len(value) > MAX_FIELD_VALUE_CHARS:
        return value[:MAX_FIELD_VALUE_CHARS] + "...(truncated)"
    return value


def get_all_knowledge() -> str:
    """
    Dynamically reads every collection and document currently in Firestore
    and returns it as a compact text block suitable for including in a
    Gemini prompt. Collection/field names are never assumed in advance —
    whatever the developer has put in Firestore is what gets read.
    """
    db = get_db()
    lines = []

    try:
        collections = db.collections()
    except Exception as e:
        return f"[Firebase unavailable: {e}]"

    found_any = False
    for collection in collections:
        docs = collection.limit(MAX_DOCS_PER_COLLECTION).stream()
        collection_lines = []
        for doc in docs:
            data = {k: _truncate(v) for k, v in doc.to_dict().items()}
            collection_lines.append(f"  - id={doc.id} :: {json.dumps(data, default=str)}")

        if collection_lines:
            found_any = True
            lines.append(f"Collection: {collection.id}")
            lines.extend(collection_lines)

    if not found_any:
        return "[No data currently in Firestore]"

    return "\n".join(lines)
