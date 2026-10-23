from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.urls import reverse_lazy
from django.views.generic import CreateView, DeleteView, ListView, UpdateView

from .forms import FeatureForm, IdeaForm, QuickIdeaForm
from .mixins import UserFormKwargsMixin
from .models import Idea

FILTER_IN_PROGRESS = "devam"
FILTER_FINISHED = "biten"


class OwnedIdeaMixin(LoginRequiredMixin):
    """Restricts every query to the signed-in user's ideas; other users' ideas are simply 404."""

    model = Idea
    success_url = reverse_lazy("ideas:list")

    def get_queryset(self):
        return Idea.objects.owned_by(self.request.user)


class IdeaListView(OwnedIdeaMixin, ListView):
    template_name = "ideas/idea_list.html"
    context_object_name = "ideas"
    paginate_by = 30

    def get_queryset(self):
        ideas = super().get_queryset().with_progress().matching(self.search_text)
        if self.status_filter == FILTER_FINISHED:
            ideas = ideas.finished()
        elif self.status_filter == FILTER_IN_PROGRESS:
            ideas = ideas.unfinished()
        return ideas.prefetch_related("features", "projects")

    @property
    def search_text(self) -> str:
        return self.request.GET.get("q", "")

    @property
    def status_filter(self) -> str:
        return self.request.GET.get("durum", "")

    @property
    def open_idea_id(self) -> int | None:
        raw = self.request.GET.get("open", "")
        return int(raw) if raw.isdigit() else None

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(
            search_text=self.search_text,
            status_filter=self.status_filter,
            open_idea_id=self.open_idea_id,
            quick_form=QuickIdeaForm(),
            feature_form=FeatureForm(),
        )
        return context


class IdeaCreateView(UserFormKwargsMixin, OwnedIdeaMixin, CreateView):
    """Accepts both the one-field quick form and the full form; the quick form posts here too."""

    template_name = "ideas/idea_form.html"

    def get_form_class(self):
        is_quick_capture = self.request.method == "POST" and "title" not in self.request.POST
        return QuickIdeaForm if is_quick_capture else IdeaForm

    def form_valid(self, form):
        form.instance.owner = self.request.user
        messages.success(self.request, "Fikir kaydedildi.")
        return super().form_valid(form)


class IdeaUpdateView(UserFormKwargsMixin, OwnedIdeaMixin, UpdateView):
    template_name = "ideas/idea_form.html"
    form_class = IdeaForm

    def form_valid(self, form):
        messages.success(self.request, "Fikir güncellendi.")
        return super().form_valid(form)


class IdeaDeleteView(OwnedIdeaMixin, DeleteView):
    template_name = "ideas/idea_confirm_delete.html"

    def form_valid(self, form):
        messages.success(self.request, "Fikir silindi.")
        return super().form_valid(form)
