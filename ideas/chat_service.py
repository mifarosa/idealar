import logging

from ai.chat import ACTION_ADD_FEATURE, ACTION_LINK_PROJECT, ACTION_NEW_IDEA, ChatAction, ChatAssistant, ChatTurn
from ai.errors import AIError

from . import ai_failure, ai_registry
from .chat_context import ChatScope, build_context
from .errors import ActionNotApplicable
from .models import (
    ACTION_APPLIED,
    ACTION_DISMISSED,
    ACTION_PENDING,
    ROLE_ASSISTANT,
    ROLE_USER,
    ChatMessage,
    Conversation,
    Feature,
    Idea,
    Project,
)

logger = logging.getLogger(__name__)

HISTORY_LIMIT = 10
HISTORY_MESSAGE_CHARS = 1500
TITLE_CHARS = 50


def build_assistant(owner, preferred_provider: str | None = None) -> ChatAssistant:
    return ChatAssistant(ai_registry.build_client(owner, preferred=preferred_provider))


def _title_from(first_message: str) -> str:
    text = " ".join(first_message.split())
    return text if len(text) <= TITLE_CHARS else text[: TITLE_CHARS - 1].rstrip() + "…"


def start_conversation(scope: ChatScope, first_message: str) -> Conversation:
    conversation = Conversation.objects.create(
        owner=scope.owner, idea=scope.idea, project=scope.project, title=_title_from(first_message)
    )
    save_user_message(conversation, first_message)
    return conversation


def save_user_message(conversation: Conversation, text: str) -> ChatMessage:
    return _add_message(conversation, ROLE_USER, text)


def _add_message(conversation: Conversation, role: str, text: str, **extra) -> ChatMessage:
    message = ChatMessage.objects.create(conversation=conversation, role=role, content=text, **extra)
    conversation.save(update_fields=["updated_at"])  # keeps the most recently used chat on top
    return message


def needs_reply(conversation: Conversation) -> bool:
    last = conversation.messages.last()
    return last is not None and last.role == ROLE_USER


def ask_assistant(conversation: Conversation, assistant_factory=None, provider: str | None = None) -> ChatMessage | None:
    """Replies to the conversation, trying `provider` first when given. Returns None if no AI answered."""
    scope = ChatScope.of(conversation)
    recent = list(conversation.messages.order_by("-id")[:HISTORY_LIMIT])[::-1]
    history = [ChatTurn(m.role, m.content[:HISTORY_MESSAGE_CHARS]) for m in recent]
    try:
        assistant = assistant_factory() if assistant_factory else build_assistant(conversation.owner, provider)
        reply = assistant.respond(build_context(scope), history)
    except AIError as error:
        logger.warning("AI chat failed (%s scope): %s", scope.kind, error)
        conversation.failure_reason = ai_failure.describe(error)  # read by the view; not stored
        return None
    return _add_message(
        conversation,
        ROLE_ASSISTANT,
        reply.reply,
        actions=_pending_actions(scope, reply.actions),
        provider=reply.provider,
        failed_providers=list(reply.failed_providers),
    )


def _pending_actions(scope: ChatScope, actions: list[ChatAction]) -> list[dict]:
    visible_ids = {idea.pk for idea in scope.visible_ideas()}
    owned_idea_ids = set(Idea.objects.owned_by(scope.owner).values_list("pk", flat=True))
    owned_project_ids = set(Project.objects.filter(owner=scope.owner).values_list("pk", flat=True))
    stored = []
    for action in actions:
        idea_id, project_id = _target_idea_id(scope, action), _target_project_id(scope, action)
        if action.type == ACTION_ADD_FEATURE and idea_id not in visible_ids:
            continue  # the model named an idea outside this conversation
        if action.type == ACTION_LINK_PROJECT and (idea_id not in owned_idea_ids or project_id not in owned_project_ids):
            continue  # the model invented an id, or one that is not the user's
        if action.type == ACTION_NEW_IDEA and project_id not in owned_project_ids:
            project_id = None
        stored.append(
            {"type": action.type, "text": action.text, "idea_id": idea_id, "project_id": project_id, "status": ACTION_PENDING}
        )
    return stored


def _target_idea_id(scope: ChatScope, action: ChatAction) -> int | None:
    if action.type in (ACTION_ADD_FEATURE, ACTION_LINK_PROJECT) and scope.idea:
        return scope.idea.pk
    return action.idea_id


def _target_project_id(scope: ChatScope, action: ChatAction) -> int | None:
    if action.type in (ACTION_NEW_IDEA, ACTION_LINK_PROJECT) and scope.project:
        return scope.project.pk
    return action.project_id if action.type in (ACTION_NEW_IDEA, ACTION_LINK_PROJECT) else None


def decide_action(message: ChatMessage, index: int, apply: bool) -> None:
    """Applies or dismisses one proposed action. Decided actions are left untouched (idempotent)."""
    action = message.actions[index]
    if action["status"] != ACTION_PENDING:
        return
    if apply:
        _apply(ChatScope.of(message.conversation), action)
    action["status"] = ACTION_APPLIED if apply else ACTION_DISMISSED
    message.save(update_fields=["actions"])


def _apply(scope: ChatScope, action: dict) -> None:
    if action["type"] == ACTION_ADD_FEATURE:
        idea = _idea_in_scope(scope, action["idea_id"])
        Feature.objects.create(idea=idea, text=action["text"])
    elif action["type"] == ACTION_LINK_PROJECT:
        idea = _owned_idea(scope, action["idea_id"])
        _owned_project(scope, action.get("project_id")).ideas.add(idea)
    elif action["type"] == ACTION_NEW_IDEA:
        # Messages stored before link_project existed carry no project_id; a project chat still files into its project.
        project_id = action.get("project_id") or (scope.project.pk if scope.project else None)
        project = _owned_project(scope, project_id) if project_id else None
        idea = Idea.objects.create(owner=scope.owner, body=action["text"])
        if project:
            idea.projects.add(project)


def _owned_idea(scope: ChatScope, idea_id: int | None) -> Idea:
    idea = Idea.objects.owned_by(scope.owner).filter(pk=idea_id).first() if idea_id else None
    if idea is None:
        raise ActionNotApplicable("Target idea is no longer available")
    return idea


def _owned_project(scope: ChatScope, project_id: int | None) -> Project:
    project = Project.objects.filter(owner=scope.owner, pk=project_id).first() if project_id else None
    if project is None:
        raise ActionNotApplicable("Target project is no longer available")
    return project


def _idea_in_scope(scope: ChatScope, idea_id: int | None) -> Idea:
    idea = scope.visible_ideas().filter(pk=idea_id).first() if idea_id else None
    if idea is None:
        raise ActionNotApplicable("Target idea is no longer available")
    return idea
