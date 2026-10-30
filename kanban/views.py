from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views import View
from django.utils.translation import gettext as _

from ideas.models import Idea, Project

from . import services
from .forms import TaskForm
from .models import STATUS_CHOICES, STATUS_TODO, STATUSES, Task


def board_url(project) -> str:
    return reverse("kanban:board") + (f"?proje={project.pk}" if project else "")


class BoardMixin(LoginRequiredMixin):
    def get_project(self, raw) -> Project | None:
        """None is the personal board; a project id must be one of the user's own."""
        if not raw:
            return None
        if not str(raw).isdigit():
            raise Http404
        return get_object_or_404(Project.objects.filter(owner=self.request.user), pk=int(raw))

    def get_task(self, pk) -> Task:
        return get_object_or_404(Task.objects.filter(owner=self.request.user).select_related("project"), pk=pk)


class BoardView(BoardMixin, View):
    def get(self, request):
        project = self.get_project(request.GET.get("proje"))
        grouped = services.columns(request.user, project)
        ideas = Idea.objects.owned_by(request.user)
        if project:
            ideas = ideas.exclude(projects=project)  # these can be added to the project
        else:
            ideas = ideas.exclude(tasks__project__isnull=True, tasks__mirrors_idea=True)  # not on the personal board yet
        context = {
            "project": project,
            "projects": Project.objects.filter(owner=request.user),
            "columns": [(value, label, grouped[value]) for value, label in STATUS_CHOICES],
            "ideas": ideas.distinct(),
            "status_choices": STATUS_CHOICES,
            "card_count": sum(len(cards) for cards in grouped.values()),
        }
        return render(request, "kanban/board.html", context)


class TaskAddView(BoardMixin, View):
    http_method_names = ["post"]

    def post(self, request):
        project = self.get_project(request.POST.get("proje"))
        form = TaskForm(request.POST)
        if form.is_valid():
            status = request.POST.get("status")
            services.add_task(request.user, project, form.cleaned_data["title"], status if status in STATUSES else STATUS_TODO)
        else:
            messages.error(request, _("Kartın bir başlığı olmalı."))
        return redirect(board_url(project))


class IdeaAddView(BoardMixin, View):
    """Adds one of the user's ideas to a board: a project board links the idea to the project, the personal one just lists it."""

    http_method_names = ["post"]

    def post(self, request):
        project = self.get_project(request.POST.get("proje"))
        raw = request.POST.get("idea", "")
        idea = Idea.objects.owned_by(request.user).filter(pk=int(raw)).first() if raw.isdigit() else None
        if idea is None:
            messages.error(request, _("Bu fikir bulunamadı."))
        else:
            if project:
                idea.projects.add(project)  # the board picks it up from the link
            services.add_idea_card(request.user, project, idea)
        return redirect(board_url(project))


class TaskMoveView(BoardMixin, View):
    """Drag and drop sends status+index (JSON answer); the arrow buttons send a direction (redirect)."""

    http_method_names = ["post"]

    def post(self, request, pk):
        task = self.get_task(pk)
        direction = request.POST.get("direction")
        if direction in ("left", "right"):
            services.step_task(task, -1 if direction == "left" else 1)
            return redirect(board_url(task.project))
        status, index = request.POST.get("status", ""), request.POST.get("index", "")
        if status not in STATUSES or not index.isdigit():
            return JsonResponse({"error": _("Geçersiz taşıma.")}, status=400)
        services.move_task(task, status, int(index))
        return JsonResponse({"ok": True})


class TaskRenameView(BoardMixin, View):
    http_method_names = ["post"]

    def post(self, request, pk):
        task = self.get_task(pk)
        title = request.POST.get("title", "").strip()
        if task.mirrors_idea:
            return JsonResponse({"error": _("Fikrin adını fikir sayfasından değiştirebilirsin.")}, status=400)
        if not title or len(title) > Task._meta.get_field("title").max_length:
            return JsonResponse({"error": _("Başlık boş olamaz ve çok uzun olmamalı.")}, status=400)
        task.title = title
        task.save(update_fields=["title"])
        return JsonResponse({"title": task.title})


class TaskDeleteView(BoardMixin, View):
    http_method_names = ["post"]

    def post(self, request, pk):
        task = self.get_task(pk)
        if task.mirrors_idea and task.project and task.idea:
            task.idea.projects.remove(task.project)  # otherwise the board would simply bring the card back
        task.delete()
        return redirect(board_url(task.project))
