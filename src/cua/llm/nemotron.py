"""NVIDIA Nemotron on Nebius Token Factory — the discovery driver.

Token Factory is OpenAI-compatible, so we use the standard ``openai`` client with
a different base URL. Tiers (pick per use):
  * ULTRA     — discovery reasoning (drive an unfamiliar UI). The expensive one,
                used ONCE per capability.
  * LIGHTNING / NANO — cheap, fast; for per-step checks and error classification.
"""
import json
import os

from openai import OpenAI

from cua.schema import Action

from .base import LLM, LLMError

TOKEN_FACTORY_BASE_URL = "https://api.tokenfactory.nebius.com/v1/"

ULTRA = "nvidia/Nemotron-3-Ultra-550b-a55b"
SUPER = "nvidia/nemotron-3-super-120b-a12b"
LIGHTNING = "nvidia/Nemotron-3_5-Lightning"
NANO = "nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B"


def _assistant_to_dict(msg) -> dict:
    """Serialize an SDK assistant message back into the dict form the API expects on replay."""
    d: dict = {"role": "assistant", "content": msg.content or ""}
    if msg.tool_calls:
        d["tool_calls"] = [
            {
                "id": tc.id,
                "type": "function",
                "function": {"name": tc.function.name, "arguments": tc.function.arguments},
            }
            for tc in msg.tool_calls
        ]
    return d


class NemotronLLM(LLM):
    def __init__(self, model: str = ULTRA, temperature: float = 0.0, api_key: str | None = None):
        self.model = model
        self.temperature = temperature
        self.client = OpenAI(
            base_url=TOKEN_FACTORY_BASE_URL,
            api_key=api_key or os.environ["NEBIUS_API_KEY"],
        )
        self._messages: list[dict] = []
        self._tools: list[dict] = []
        self._last_tool_call_id: str | None = None

    def start(self, system: str, tools: list[dict]) -> None:
        self._messages = [{"role": "system", "content": system}]
        self._tools = tools
        self._last_tool_call_id = None

    def next_action(self, observation: str) -> Action:
        self._messages.append({"role": "user", "content": observation})
        resp = self.client.chat.completions.create(
            model=self.model,
            messages=self._messages,
            tools=self._tools,
            tool_choice="auto",
            temperature=self.temperature,
        )
        msg = resp.choices[0].message
        self._messages.append(_assistant_to_dict(msg))

        if not msg.tool_calls:
            raise LLMError(f"model emitted no tool call. content={msg.content!r}")

        call = msg.tool_calls[0]
        self._last_tool_call_id = call.id
        try:
            args = json.loads(call.function.arguments or "{}")
            return Action(**args)
        except Exception as e:  # noqa: BLE001
            raise LLMError(f"could not parse action from {call.function.arguments!r}: {e}") from e

    def record_result(self, text: str) -> None:
        if self._last_tool_call_id is None:
            return
        self._messages.append(
            {"role": "tool", "tool_call_id": self._last_tool_call_id, "content": text}
        )
        self._last_tool_call_id = None
