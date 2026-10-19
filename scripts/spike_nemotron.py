"""One-off diagnostic: does Nemotron-3-Ultra on Nebius Token Factory return
clean tool calls for a UI-action schema? This is throwaway — not part of the system.

Run:
    python scripts/spike_nemotron.py
"""
from dotenv import load_dotenv
load_dotenv()

import os
import sys
import json

from openai import OpenAI

key = os.environ.get("NEBIUS_API_KEY", "").strip()
if not key or key == "REPLACE_ME":
    sys.exit("❌ NEBIUS_API_KEY not set. Open .env, paste your Nebius API key, save, and re-run.")

client = OpenAI(base_url="https://api.tokenfactory.nebius.com/v1/", api_key=key)
ULTRA = "nvidia/Nemotron-3-Ultra-550b-a55b"

tools = [{
    "type": "function",
    "function": {
        "name": "act",
        "description": "Perform one UI action on the current screen.",
        "parameters": {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["click", "type", "navigate", "read", "finish"]},
                "target": {"type": "string", "description": "accessible name/role of the element"},
                "text": {"type": "string", "description": "text to type, if action=type"},
            },
            "required": ["action"],
        },
    },
}]

observation = (
    "URL: http://127.0.0.1:5001/members\n"
    '[textbox] "Member ID"\n'
    '[button] "Search"\n'
    "Goal: look up member 12345 and read their savings balance."
)

try:
    resp = client.chat.completions.create(
        model=ULTRA,
        messages=[
            {"role": "system", "content": "You drive a UI by emitting ONE act() tool call per turn."},
            {"role": "user", "content": observation},
        ],
        tools=tools,
        tool_choice="auto",
        temperature=0,
    )
except Exception as e:
    sys.exit(f"❌ API call failed: {type(e).__name__}: {e}")

msg = resp.choices[0].message
if msg.tool_calls:
    c = msg.tool_calls[0]
    print("✅ TOOL CALL:", c.function.name, "| args:", json.loads(c.function.arguments))
    print("\nGreen light — Nemotron tool-calling works. We build the real adapter.")
else:
    print("⚠️  No tool_call. Model replied with content instead:\n", msg.content)
    print("\nNot fatal — we'll use the strict-JSON fallback path.")
