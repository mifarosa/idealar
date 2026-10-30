import os

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse_lazy
from django.views import View
from django.views.generic import CreateView, DeleteView, DetailView, ListView, UpdateView
from django.utils.translation import gettext as _, ngettext

from . import github_import, project_review
from .errors import ActionNotApplicable
from .github_repo import GitHubError
from .forms import ProjectForm
from .mixins import UserFormKwargsMixin
from .models import Project


class OwnedProjectMixin(LoginRequiredMixin):
    model = Project
    success_url = reverse_lazy("ideas:project-list")

    def get_queryset(self):
        return Project.objects.filter(owner=self.request.user)


class ProjectListView(OwnedProjectMixin, ListView):
    template_name = "ideas/project_list.html"
    context_object_name = "projects"

    def get_queryset(self):
        return super().get_queryset().prefetch_related("ideas")


class ProjectDetailView(OwnedProjectMixin, DetailView):
    template_name = "ideas/project_detail.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["ideas"] = self.object.ideas.with_progress().prefetch_related("features")
        return context


class ProjectCreateView(UserFormKwargsMixin, OwnedProjectMixin, CreateView):
    template_name = "ideas/project_form.html"
    form_class = ProjectForm

    def form_valid(self, form):
        form.instance.owner = self.request.user
        messages.success(self.request, _("Proje kaydedildi."))
        return super().form_valid(form)


class ProjectUpdateView(UserFormKwargsMixin, OwnedProjectMixin, UpdateView):
    template_name = "ideas/project_form.html"
    form_class = ProjectForm

    def form_valid(self, form):
        messages.success(self.request, _("Proje güncellendi."))
        return super().form_valid(form)


class ProjectDeleteView(OwnedProjectMixin, DeleteView):
    template_name = "ideas/project_confirm_delete.html"

    def form_valid(self, form):
        messages.success(self.request, _("Proje silindi (fikirler silinmedi)."))
        return super().form_valid(form)


class ProjectActionView(LoginRequiredMixin, View):
    http_method_names = ["post"]

    def get_project(self, pk: int) -> Project:
        return get_object_or_404(Project.objects.filter(owner=self.request.user), pk=pk)


class ProjectInspectView(ProjectActionView):
    """Reads the project's GitHub repository and has the AI review it."""

    def post(self, request, pk):
        project = self.get_project(pk)
        if not project.github_url:
            messages.error(request, _("Önce projeye bir GitHub adresi ekle (Düzenle)."))
        elif project_review.review_project(project):
            messages.success(request, _("Proje incelendi."))
        else:
            messages.error(request, project.repo_analysis_error)
        return redirect("ideas:project-detail", pk=project.pk)


class ProjectMatchDecideView(ProjectActionView):
    def post(self, request, pk, index):
        project = self.get_project(pk)
        if index < len(project.repo_analysis.get("matches", [])):
            apply = request.POST.get("decision") == "apply"
            try:
                project_review.decide_match(project, index, apply)
                messages.success(request, _("Özellik yapıldı olarak işaretlendi.") if apply else _("Yoksayıldı."))
            except ActionNotApplicable:
                messages.error(request, _("Bu özellik artık projenin bir parçası değil."))
        return redirect("ideas:project-detail", pk=project.pk)


class ProjectImportView(LoginRequiredMixin, View):
    """Lists the user's GitHub repositories and imports the ones they tick as projects."""

    template_name = "ideas/project_import.html"

    def get(self, request):
        if "kullanici" not in request.GET:
            return self._render(request, username=os.environ.get("GITHUB_USERNAME", ""), repos=None)
        username = request.GET["kullanici"]
        return self._render(request, username=username, repos=self._fetch(request, username))

    def post(self, request):
        username = request.POST.get("kullanici", "")
        repos = self._fetch(request, username)
        if repos is None:
            return self._render(request, username=username, repos=None)
        chosen = set(request.POST.getlist("repo"))
        # Only repositories the server just listed can be imported; anything else in the form is ignored.
        added = github_import.import_repos(request.user, [r for r in repos if r.full_name in chosen])
        messages.success(request, ngettext("{n} proje eklendi.", "{n} proje eklendi.", added).format(n=added) if added else _("Eklenecek yeni proje yoktu."))
        return redirect("ideas:project-list")

    @staticmethod
    def _fetch(request, username: str):
        client = project_review.build_github_client()
        try:
            return github_import.list_repos(client, username, has_token=bool(os.environ.get("GITHUB_TOKEN")))
        except GitHubError as error:
            messages.error(request, str(error))
            return None

    def _render(self, request, username: str, repos):
        known = github_import.already_imported_urls(request.user)
        rows = None if repos is None else [
            {"repo": repo, "already": github_import.normalize_url(repo.url) in known,
             "checked": not (repo.fork or repo.archived or github_import.normalize_url(repo.url) in known)}
            for repo in repos
        ]
        context = {"username": username, "rows": rows, "has_token": bool(os.environ.get("GITHUB_TOKEN"))}
        return render(request, self.template_name, context)
