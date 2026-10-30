from django.contrib import messages
from django.utils.translation import gettext_lazy
from django.utils.translation import gettext as _
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import JsonResponse
from django.db.models import Count
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views import View

from . import ai_registry, chat_service
from .chat_context import ChatScope
from .models import ROLE_ASSISTANT, ChatMessage, Conversation, Idea, Project

MAX_USER_MESSAGE_CHARS = 4000
MAX_TITLE_CHARS = Conversation._meta.get_field("title").max_length
NO_ANSWER_MESSAGE = gettext_lazy("Hiçbir AI yanıt veremedi. Mesajın kaydedildi; başka bir AI seçip tekrar deneyebilirsin.")


def no_answer_message(conversation: Conversation) -> str:
    reason = getattr(conversation, "failure_reason", "")
    return _("{message} Sebep: {reason}").format(message=NO_ANSWER_MESSAGE, reason=reason) if reason else str(NO_ANSWER_MESSAGE)


def scope_chat_url(scope: ChatScope) -> str:
    """The page listing a scope's conversations."""
    if scope.idea:
        return reverse("ideas:idea-chat", args=[scope.idea.pk])
    if scope.project:
        return reverse("ideas:project-chat", args=[scope.project.pk])
    return reverse("ideas:chat")


def back_url(scope: ChatScope) -> str:
    if scope.idea:
        return reverse("ideas:detail", args=[scope.idea.pk])
    if scope.project:
        return reverse("ideas:project-detail", args=[scope.project.pk])
    return reverse("ideas:list")


def conversation_url(conversation: Conversation) -> str:
    return reverse("ideas:conversation", args=[conversation.pk])


def provider_label(name: str) -> str:
    return ai_registry.label_for(name)


def provider_choices(user) -> list[tuple[str, str]]:
    return ai_registry.choices(user)


def chosen_provider(request) -> str | None:
    """The picker value from the form; anything not currently configured means "automatic"."""
    name = request.POST.get("provider", "")
    return name if name in dict(ai_registry.choices(request.user)) else None


class ConversationListView(LoginRequiredMixin, View):
    """Lists the conversations of one scope (an idea, a project or the whole list) and starts new ones."""

    def get_scope(self, idea_pk=None, project_pk=None) -> ChatScope:
        user = self.request.user
        idea = get_object_or_404(Idea.objects.owned_by(user), pk=idea_pk) if idea_pk else None
        project = get_object_or_404(Project.objects.filter(owner=user), pk=project_pk) if project_pk else None
        return ChatScope(owner=user, idea=idea, project=project)

    def get(self, request, **kwargs):
        scope = self.get_scope(**kwargs)
        conversations = scope.conversations().annotate(message_count=Count("messages"))
        context = {
            "scope": scope,
            "conversations": conversations,
            "post_url": scope_chat_url(scope),
            "back_url": back_url(scope),
            "providers": provider_choices(request.user),
        }
        return render(request, "ideas/chat_list.html", context)

    def post(self, request, **kwargs):
        scope = self.get_scope(**kwargs)
        text = request.POST.get("text", "").strip()[:MAX_USER_MESSAGE_CHARS]
        if not text:
            return redirect(scope_chat_url(scope))
        conversation = chat_service.start_conversation(scope, text)
        if chat_service.ask_assistant(conversation, provider=chosen_provider(request)) is None:
            messages.error(request, no_answer_message(conversation))
        return redirect(conversation_url(conversation))


class ConversationView(LoginRequiredMixin, View):
    def get_conversation(self, pk: int) -> Conversation:
        return get_object_or_404(Conversation.objects.filter(owner=self.request.user), pk=pk)

    def get(self, request, pk):
        conversation = self.get_conversation(pk)
        scope = ChatScope.of(conversation)
        context = {
            "conversation": conversation,
            "scope": scope,
            "chat_messages": self._messages_with_action_views(conversation),
            "needs_reply": chat_service.needs_reply(conversation),
            "post_url": conversation_url(conversation),
            "list_url": scope_chat_url(scope),
            "providers": provider_choices(request.user),
        }
        return render(request, "ideas/chat.html", context)

    def post(self, request, pk):
        conversation = self.get_conversation(pk)
        text = request.POST.get("text", "").strip()[:MAX_USER_MESSAGE_CHARS]
        if text:
            chat_service.save_user_message(conversation, text)
        # An empty post is a "retry" of an unanswered message; otherwise there is nothing to do.
        needs_answer = chat_service.needs_reply(conversation)
        if needs_answer and chat_service.ask_assistant(conversation, provider=chosen_provider(request)) is None:
            messages.error(request, no_answer_message(conversation))
        return redirect(conversation_url(conversation))

    @staticmethod
    def _messages_with_action_views(conversation: Conversation) -> list[ChatMessage]:
        chat_messages = list(conversation.messages.all())
        idea_ids = {a["idea_id"] for m in chat_messages for a in m.actions if a.get("idea_id")}
        titles = {i.pk: i.display_title for i in Idea.objects.owned_by(conversation.owner).filter(pk__in=idea_ids)}
        project_ids = {a["project_id"] for m in chat_messages for a in m.actions if a.get("project_id")}
        project_names = dict(Project.objects.filter(owner=conversation.owner, pk__in=project_ids).values_list("pk", "name"))
        for message in chat_messages:
            message.action_views = [
                {
                    **action,
                    "index": index,
                    "target_title": titles.get(action.get("idea_id"), ""),
                    "project_name": project_names.get(action.get("project_id"), ""),
                }
                for index, action in enumerate(message.actions)
            ]
            message.provider_label = provider_label(message.provider) if message.provider else ""
            message.failed_labels = [provider_label(name) for name in message.failed_providers]
        return chat_messages


class ConversationDeleteView(LoginRequiredMixin, View):
    http_method_names = ["post"]

    def post(self, request, pk):
        conversation = get_object_or_404(Conversation.objects.filter(owner=request.user), pk=pk)
        list_url = scope_chat_url(ChatScope.of(conversation))
        conversation.delete()
        messages.success(request, _("Sohbet silindi."))
        return redirect(list_url)


class ConversationRenameView(LoginRequiredMixin, View):
    """Renames a conversation in place; answers with JSON so the page can update without reloading."""

    http_method_names = ["post"]

    def post(self, request, pk):
        conversation = get_object_or_404(Conversation.objects.filter(owner=request.user), pk=pk)
        title = " ".join(request.POST.get("title", "").split())[:MAX_TITLE_CHARS]
        if not title:
            return JsonResponse({"error": _("Sohbet adı boş olamaz.")}, status=400)
        conversation.title = title
        conversation.save(update_fields=["title"])
        return JsonResponse({"title": title})


class ChatActionView(LoginRequiredMixin, View):
    http_method_names = ["post"]

    def post(self, request, pk, index):
        message = get_object_or_404(
            ChatMessage, pk=pk, conversation__owner=request.user, role=ROLE_ASSISTANT
        )
        destination = conversation_url(message.conversation)
        if index >= len(message.actions):
            return redirect(destination)
        apply = request.POST.get("decision") == "apply"
        try:
            chat_service.decide_action(message, index, apply)
            messages.success(request, _("Eklendi.") if apply else _("Öneri yoksayıldı."))
        except chat_service.ActionNotApplicable:
            messages.error(request, _("Bu öneri artık uygulanamıyor (fikir silinmiş olabilir)."))
        return redirect(destination)
