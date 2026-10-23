import logging

from ai.chat import ACTION_ADD_FEATURE, ACTION_NEW_IDEA, ChatAction, ChatAssistant, ChatTurn
from ai.errors import AIError
from ai.providers import build_default_client

from .chat_context import ChatScope, build_context
from .models import (
    ACTION_APPLIED,
    ACTION_DISMISSED,
    ACTION_PENDING,
    ROLE_ASSISTANT,
    ROLE_USER,
    ChatMessage,
    Feature,
    Idea,
)

logger = logging.getLogger(__name__)

HISTORY_LIMIT = 10
HISTORY_MESSAGE_CHARS = 1500


class ActionNotApplicable(Exception):
    """The proposed change no longer makes sense (e.g. its idea was deleted)."""


def build_assistant() -> ChatAssistant:
    return ChatAssistant(build_default_client())


def save_user_message(scope: ChatScope, text: str) -> ChatMessage:
    return ChatMessage.objects.create(owner=scope.owner, idea=scope.idea, project=scope.project, role=ROLE_USER, content=text)


def needs_reply(scope: ChatScope) -> bool:
    last = scope.messages().last()
    return last is not None and last.role == ROLE_USER


def ask_assistant(scope: ChatScope, assistant_factory=None) -> ChatMessage | None:
    """Replies to the conversation. Returns None (user messages are kept) if the AI is unavailable."""
    recent = list(scope.messages().order_by("-id")[:HISTORY_LIMIT])[::-1]
    history = [ChatTurn(m.role, m.content[:HISTORY_MESSAGE_CHARS]) for m in recent]
    try:
        assistant = (assistant_factory or build_assistant)()
        reply = assistant.respond(build_context(scope), history)
    except AIError as error:
        logger.warning("AI chat failed (%s scope): %s", scope.kind, error)
        return None
    return ChatMessage.objects.create(
        owner=scope.owner,
        idea=scope.idea,
        project=scope.project,
        role=ROLE_ASSISTANT,
        content=reply.reply,
        actions=_pending_actions(scope, reply.actions),
    )


def _pending_actions(scope: ChatScope, actions: list[ChatAction]) -> list[dict]:
    allowed_ids = {idea.pk for idea in scope.visible_ideas()}
    stored = []
    for action in actions:
        idea_id = _target_idea_id(scope, action)
        if action.type == ACTION_ADD_FEATURE and idea_id not in allowed_ids:
            continue  # the model named an idea outside this conversation
        stored.append({"type": action.type, "text": action.text, "idea_id": idea_id, "status": ACTION_PENDING})
    return stored


def _target_idea_id(scope: ChatScope, action: ChatAction) -> int | None:
    if action.type == ACTION_ADD_FEATURE and scope.idea:
        return scope.idea.pk
    return action.idea_id


def decide_action(message: ChatMessage, index: int, apply: bool) -> None:
    """Applies or dismisses one proposed action. Decided actions are left untouched (idempotent)."""
    action = message.actions[index]
    if action["status"] != ACTION_PENDING:
        return
    if apply:
        _apply(message, action)
    action["status"] = ACTION_APPLIED if apply else ACTION_DISMISSED
    message.save(update_fields=["actions"])


def _apply(message: ChatMessage, action: dict) -> None:
    if action["type"] == ACTION_ADD_FEATURE:
        idea = _owned_idea_in_scope(message, action["idea_id"])
        Feature.objects.create(idea=idea, text=action["text"])
    elif action["type"] == ACTION_NEW_IDEA:
        idea = Idea.objects.create(owner=message.owner, body=action["text"])
        if message.project:
            idea.projects.add(message.project)


def _owned_idea_in_scope(message: ChatMessage, idea_id: int | None) -> Idea:
    scope = ChatScope(message.owner, message.idea, message.project)
    idea = scope.visible_ideas().filter(pk=idea_id).first() if idea_id else None
    if idea is None:
        raise ActionNotApplicable("Target idea is no longer available")
    return idea
