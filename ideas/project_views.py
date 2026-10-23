from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse_lazy
from django.views import View
from django.views.generic import CreateView, DeleteView, DetailView, ListView, UpdateView

from . import project_review
from .errors import ActionNotApplicable
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
        messages.success(self.request, "Proje kaydedildi.")
        return super().form_valid(form)


class ProjectUpdateView(UserFormKwargsMixin, OwnedProjectMixin, UpdateView):
    template_name = "ideas/project_form.html"
    form_class = ProjectForm

    def form_valid(self, form):
        messages.success(self.request, "Proje güncellendi.")
        return super().form_valid(form)


class ProjectDeleteView(OwnedProjectMixin, DeleteView):
    template_name = "ideas/project_confirm_delete.html"

    def form_valid(self, form):
        messages.success(self.request, "Proje silindi (fikirler silinmedi).")
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
            messages.error(request, "Önce projeye bir GitHub adresi ekle (Düzenle).")
        elif project_review.review_project(project):
            messages.success(request, "Proje incelendi.")
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
                messages.success(request, "Özellik yapıldı olarak işaretlendi." if apply else "Yoksayıldı.")
            except ActionNotApplicable:
                messages.error(request, "Bu özellik artık projenin bir parçası değil.")
        return redirect("ideas:project-detail", pk=project.pk)
