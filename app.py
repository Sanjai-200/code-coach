"""
app.py
------
Flask application for a domain-specific AI chatbot.

Routes:
  GET  /            -> serves templates/index.html
  POST /api/chat     -> processes a chat message and returns {"reply": "..."}

Architecture (fixed for every chatbot built from this template):
  1. Read the user's message + this session's conversation history.
  2. Retrieve current Firebase knowledge dynamically (firebase_config.py).
  3. Build the system prompt from chatbot_config.py (title/purpose-specific).
  4. Send everything to Gemini.
  5. Store the exchange in this session's history and return the reply.

Conversation history is kept per-Flask-session (signed cookie), so different
users/browsers never share history.
"""

import os
import secrets
import traceback

from flask import Flask, jsonify, render_template, request, session
from google import genai
from google.genai import types

import chatbot_config
import firebase_config

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", secrets.token_hex(32)) 

GEMINI_MODEL = "gemini-3.1-flash-lite"  # latest generally available Gemini model

MAX_HISTORY_MESSAGES = 20  # keep the last N messages (user+assistant combined)

_client = None


def get_gemini_client():
    global _client
    if _client is None:
        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            raise RuntimeError("GEMINI_API_KEY environment variable is not set.")
        _client = genai.Client(api_key=api_key)
    return _client


@app.route("/", methods=["GET"])
def index():
    return render_template("index.html", chatbot_title=chatbot_config.CHATBOT_TITLE)


@app.route("/api/chat", methods=["POST"])
def chat():
    try:
        payload = request.get_json(silent=True)
        if not payload or "message" not in payload:
            return jsonify({"error": "Request must include 'message'."}), 400

        user_message = str(payload["message"]).strip()
        if not user_message:
            return jsonify({"error": "'message' cannot be empty."}), 400
        if len(user_message) > 4000:
            return jsonify({"error": "Message is too long."}), 400

        # Per-session conversation history (never shared across users).
        history = session.get("history", [])

        # 1 & 2. Retrieve Firebase knowledge dynamically for this request.
        try:
            firebase_knowledge = firebase_config.get_all_knowledge()
        except Exception as e:
            firebase_knowledge = f"[Firebase knowledge unavailable: {e}]"

        # 3. Build system prompt (domain-specific, from chatbot_config.py).
        system_prompt = chatbot_config.build_system_prompt()
        system_prompt += (
            "\n\nCURRENT FIREBASE DATABASE CONTENTS "
            "(authoritative for domain facts):\n" + firebase_knowledge
        )

        # Build Gemini conversation contents from history + new message.
        contents = []
        for turn in history[-MAX_HISTORY_MESSAGES:]:
            role = "model" if turn["role"] == "assistant" else "user"
            contents.append(
                types.Content(role=role, parts=[types.Part(text=turn["content"])])
            )
        contents.append(
            types.Content(role="user", parts=[types.Part(text=user_message)])
        )

        # 4. Send to Gemini.
        client = get_gemini_client()
        response = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=contents,
            config=types.GenerateContentConfig(system_instruction=system_prompt),
        )

        reply_text = (response.text or "").strip()
        if not reply_text:
            reply_text = "Sorry, I couldn't generate a response. Please try again."

        # 5. Update per-session history and return.
        history.append({"role": "user", "content": user_message})
        history.append({"role": "assistant", "content": reply_text})
        session["history"] = history[-MAX_HISTORY_MESSAGES:]

        return jsonify({"reply": reply_text})

    except Exception:
        # Never expose stack traces or secrets to the client.
        traceback.print_exc()
        return jsonify({"error": "Something went wrong processing your request."}), 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
