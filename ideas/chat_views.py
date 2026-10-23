from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views import View

from . import chat_service
from .chat_context import ChatScope
from .models import ROLE_ASSISTANT, ChatMessage, Idea, Project

MAX_USER_MESSAGE_CHARS = 4000


def chat_url(scope: ChatScope) -> str:
    if scope.idea:
        return reverse("ideas:idea-chat", args=[scope.idea.pk])
    if scope.project:
        return reverse("ideas:project-chat", args=[scope.project.pk])
    return reverse("ideas:chat")


def back_url(scope: ChatScope) -> str:
    if scope.idea:
        return f"{reverse('ideas:list')}?open={scope.idea.pk}#idea-{scope.idea.pk}"
    if scope.project:
        return reverse("ideas:project-detail", args=[scope.project.pk])
    return reverse("ideas:list")


class ChatView(LoginRequiredMixin, View):
    """One conversation per scope: a single idea, a single project, or the whole idea list."""

    def get_scope(self, idea_pk=None, project_pk=None) -> ChatScope:
        user = self.request.user
        idea = get_object_or_404(Idea.objects.owned_by(user), pk=idea_pk) if idea_pk else None
        project = get_object_or_404(Project.objects.filter(owner=user), pk=project_pk) if project_pk else None
        return ChatScope(owner=user, idea=idea, project=project)

    def get(self, request, **kwargs):
        scope = self.get_scope(**kwargs)
        context = {
            "scope": scope,
            "chat_messages": self._messages_with_action_views(scope),
            "needs_reply": chat_service.needs_reply(scope),
            "chat_url": chat_url(scope),
            "back_url": back_url(scope),
        }
        return render(request, "ideas/chat.html", context)

    def post(self, request, **kwargs):
        scope = self.get_scope(**kwargs)
        if "clear" in request.POST:
            scope.messages().delete()
            return redirect(chat_url(scope))
        text = request.POST.get("text", "").strip()[:MAX_USER_MESSAGE_CHARS]
        if text:
            chat_service.save_user_message(scope, text)
        # An empty post is a "retry" of an unanswered message; otherwise there is nothing to do.
        if chat_service.needs_reply(scope) and chat_service.ask_assistant(scope) is None:
            messages.error(request, "AI şu an yanıt veremedi. Mesajın kaydedildi, tekrar deneyebilirsin.")
        return redirect(chat_url(scope))

    @staticmethod
    def _messages_with_action_views(scope: ChatScope) -> list[ChatMessage]:
        chat_messages = list(scope.messages())
        idea_ids = {a["idea_id"] for m in chat_messages for a in m.actions if a.get("idea_id")}
        titles = {i.pk: i.display_title for i in Idea.objects.owned_by(scope.owner).filter(pk__in=idea_ids)}
        for message in chat_messages:
            message.action_views = [
                {**action, "index": index, "target_title": titles.get(action.get("idea_id"), "")}
                for index, action in enumerate(message.actions)
            ]
        return chat_messages


class ChatActionView(LoginRequiredMixin, View):
    http_method_names = ["post"]

    def post(self, request, pk, index):
        message = get_object_or_404(ChatMessage, pk=pk, owner=request.user, role=ROLE_ASSISTANT)
        if index >= len(message.actions):
            return redirect(chat_url(ChatScope(request.user, message.idea, message.project)))
        apply = request.POST.get("decision") == "apply"
        try:
            chat_service.decide_action(message, index, apply)
            messages.success(request, "Eklendi." if apply else "Öneri yoksayıldı.")
        except chat_service.ActionNotApplicable:
            messages.error(request, "Bu öneri artık uygulanamıyor (fikir silinmiş olabilir).")
        return redirect(chat_url(ChatScope(request.user, message.idea, message.project)))
