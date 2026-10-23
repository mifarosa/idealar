from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.urls import reverse_lazy
from django.views.generic import CreateView, DeleteView, DetailView, ListView, UpdateView

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
