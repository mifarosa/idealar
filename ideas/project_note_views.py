from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.translation import gettext as _
from django.views import View

from .forms import ProjectNoteForm
from .models import Project, ProjectNote


class ProjectNoteMixin(LoginRequiredMixin):
    """Every note is reached through its project, and the project must be the signed-in user's own."""

    def get_project(self, project_pk: int) -> Project:
        return get_object_or_404(Project.objects.filter(owner=self.request.user), pk=project_pk)

    def get_note(self, project: Project, note_pk: int) -> ProjectNote:
        return get_object_or_404(project.notes, pk=note_pk)

    @staticmethod
    def back_to_notes(project: Project):
        return redirect(f"{reverse('ideas:project-detail', args=[project.pk])}#notes")


class ProjectNoteAddView(ProjectNoteMixin, View):
    http_method_names = ["post"]

    def post(self, request, project_pk):
        project = self.get_project(project_pk)
        form = ProjectNoteForm(request.POST)
        if form.is_valid():
            ProjectNote.objects.create(project=project, body=form.cleaned_data["body"])
            messages.success(request, _("Not eklendi."))
        else:
            messages.error(request, _("Not boş olamaz ve çok uzun olmamalı."))
        return self.back_to_notes(project)


class ProjectNoteEditView(ProjectNoteMixin, View):
    def get(self, request, project_pk, note_pk):
        project = self.get_project(project_pk)
        note = self.get_note(project, note_pk)
        return render(request, "ideas/project_note_form.html", {"project": project, "form": ProjectNoteForm(instance=note), "note": note})

    def post(self, request, project_pk, note_pk):
        project = self.get_project(project_pk)
        note = self.get_note(project, note_pk)
        form = ProjectNoteForm(request.POST, instance=note)
        if not form.is_valid():
            return render(request, "ideas/project_note_form.html", {"project": project, "form": form, "note": note})
        form.save()
        messages.success(request, _("Not güncellendi."))
        return self.back_to_notes(project)


class ProjectNoteDeleteView(ProjectNoteMixin, View):
    http_method_names = ["post"]

    def post(self, request, project_pk, note_pk):
        project = self.get_project(project_pk)
        self.get_note(project, note_pk).delete()
        messages.success(request, _("Not silindi."))
        return self.back_to_notes(project)
