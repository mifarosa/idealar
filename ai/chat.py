"""Conversational assistant: discusses ideas/projects and may propose concrete changes as actions.

Actions are only proposals; the application applies them after the user confirms (never the model).
"""
from collections.abc import Sequence
from dataclasses import dataclass

from .client import LLMClient
from .errors import AIResponseError

MAX_REPLY_CHARS = 2000
MAX_ACTIONS = 3
MAX_FEATURE_CHARS = 300
MAX_IDEA_CHARS = 500
ACTION_ADD_FEATURE = "add_feature"
ACTION_NEW_IDEA = "new_idea"

SYSTEM_PROMPT = """You are a candid, practical product and engineering sparring partner for a solo developer who
collects app ideas. Talk like a thoughtful colleague: give opinions and trade-offs, ask a sharp question when
something is unclear, point out risks and simpler alternatives. Reply in the user's language (usually Turkish),
in under 150 words, no filler.

You are given the current context (an idea, a project, or the idea list) with ids. Reply with ONLY a JSON object:
{
  "reply": "your message to the developer",
  "actions": [
    {"type": "add_feature", "idea_id": <id from the context>, "text": "short feature, under 12 words"},
    {"type": "new_idea", "text": "a new idea note"}
  ]
}
Rules for actions: propose at most 3, and only when you are concretely recommending something to add; otherwise
use an empty list. Use add_feature only with an idea_id that appears in the context. Never say you already added
something: the developer confirms each action with a button. Do not repeat features that already exist."""


@dataclass(frozen=True)
class ChatTurn:
    role: str  # "user" or "assistant"
    content: str


@dataclass(frozen=True)
class ChatAction:
    type: str
    text: str
    idea_id: int | None = None


@dataclass(frozen=True)
class ChatReply:
    reply: str
    actions: list[ChatAction]


class ChatAssistant:
    def __init__(self, client: LLMClient):
        self._client = client

    def respond(self, context: str, history: Sequence[ChatTurn]) -> ChatReply:
        system = f"{SYSTEM_PROMPT}\n\n--- CONTEXT ---\n{context}"
        messages = [{"role": turn.role, "content": turn.content} for turn in history]
        return _parse_reply(self._client.chat_json(system, messages))


def _parse_reply(answer: dict) -> ChatReply:
    reply = answer.get("reply")
    if not isinstance(reply, str) or not reply.strip():
        raise AIResponseError("Model answer has no reply text")
    return ChatReply(reply=reply.strip()[:MAX_REPLY_CHARS], actions=_parse_actions(answer.get("actions")))


def _parse_actions(raw) -> list[ChatAction]:
    candidates = raw if isinstance(raw, list) else []
    actions = (_parse_action(item) for item in candidates)
    return [action for action in actions if action is not None][:MAX_ACTIONS]


def _parse_action(item) -> ChatAction | None:
    if not isinstance(item, dict) or not isinstance(item.get("text"), str):
        return None
    text, kind = item["text"].strip(), item.get("type")
    if kind == ACTION_ADD_FEATURE and text:
        return ChatAction(kind, text[:MAX_FEATURE_CHARS], _parse_idea_id(item.get("idea_id")))
    if kind == ACTION_NEW_IDEA and text:
        return ChatAction(kind, text[:MAX_IDEA_CHARS])
    return None


def _parse_idea_id(value) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    return int(value) if isinstance(value, str) and value.strip().isdigit() else None
