from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Case, F, FloatField, Value, When
from django.shortcuts import get_object_or_404
from django.urls import reverse, reverse_lazy
from django.utils.http import urlencode
from django.views.generic import CreateView, DeleteView, ListView, UpdateView
from django.utils.translation import gettext_lazy, gettext as _

from .forms import FeatureForm, IdeaForm, QuickIdeaForm
from .mixins import UserFormKwargsMixin
from .models import Idea, Project

FILTER_IN_PROGRESS = "devam"
FILTER_FINISHED = "biten"

PROGRESS_RATIO = Case(
    When(total_features=0, then=Value(0.0)),
    default=F("done_features") * 1.0 / F("total_features"),
    output_field=FloatField(),
)
SORT_CHOICES = [("yeni", gettext_lazy("Yeni → eski")), ("eski", gettext_lazy("Eski → yeni")), ("guncel", gettext_lazy("Son güncellenen")), ("ilerleme", gettext_lazy("İlerleme"))]
SORT_ORDERINGS = {
    "yeni": ("-created_at", "-id"),
    "eski": ("created_at", "id"),
    "guncel": ("-updated_at", "-id"),
    "ilerleme": ("-progress_ratio", "-created_at"),
}
DEFAULT_SORT = "yeni"


class OwnedIdeaMixin(LoginRequiredMixin):
    """Restricts every query to the signed-in user's ideas; other users' ideas are simply 404."""

    model = Idea
    success_url = reverse_lazy("ideas:list")

    def get_queryset(self):
        return Idea.objects.owned_by(self.request.user)


class IdeaListView(OwnedIdeaMixin, ListView):
    """The master-detail home: the idea list plus the selected idea's detail (its own screen on phones)."""

    template_name = "ideas/idea_list.html"
    context_object_name = "ideas"
    paginate_by = 30

    def get_queryset(self):
        ideas = super().get_queryset()
        if self.project_filter:
            ideas = ideas.filter(projects__pk=self.project_filter)
        ideas = ideas.with_progress().annotate(progress_ratio=PROGRESS_RATIO).matching(self.search_text)
        if self.status_filter == FILTER_FINISHED:
            ideas = ideas.finished()
        elif self.status_filter == FILTER_IN_PROGRESS:
            ideas = ideas.unfinished()
        return ideas.order_by(*SORT_ORDERINGS[self.sort]).prefetch_related("projects")

    @property
    def search_text(self) -> str:
        return self.request.GET.get("q", "")

    @property
    def status_filter(self) -> str:
        return self.request.GET.get("durum", "")

    @property
    def project_filter(self) -> int | None:
        raw = self.request.GET.get("proje", "")
        return int(raw) if raw.isdigit() else None

    @property
    def sort(self) -> str:
        requested = self.request.GET.get("sirala", "")
        return requested if requested in SORT_ORDERINGS else DEFAULT_SORT

    def get_queryset_for_counts(self):
        return Idea.objects.owned_by(self.request.user).with_progress()

    def selected_idea(self, page_ideas) -> Idea | None:
        """The idea in the detail pane: the one in the URL, else the first of the page (desktop default)."""
        pk = self.kwargs.get("pk") or (page_ideas[0].pk if page_ideas else None)
        if pk is None:
            return None
        owned = Idea.objects.owned_by(self.request.user).prefetch_related("features", "projects")
        return get_object_or_404(owned, pk=pk)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        selected = self.selected_idea(context["ideas"])
        everything = self.get_queryset_for_counts()
        filter_params = {key: value for key, value in (("q", self.search_text), ("durum", self.status_filter), ("proje", self.project_filter), ("sirala", self.request.GET.get("sirala"))) if value}
        context.update(
            selected=selected,
            view_mode="detail" if self.kwargs.get("pk") else "list",
            enrich=self.request.GET.get("enrich") == "1",
            search_text=self.search_text,
            status_filter=self.status_filter,
            project_filter=self.project_filter,
            sort=self.sort,
            sort_choices=SORT_CHOICES,
            projects=Project.objects.filter(owner=self.request.user),
            count_all=everything.count(),
            count_finished=everything.finished().count(),
            count_in_progress=everything.unfinished().count(),
            filter_query=urlencode(filter_params),
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
        messages.success(self.request, _("Fikir kaydedildi."))
        return super().form_valid(form)

    def get_success_url(self):
        # The detail page then asks the AI to fill the new idea in the background (see app.js).
        return f"{reverse('ideas:detail', args=[self.object.pk])}?enrich=1"


class IdeaUpdateView(UserFormKwargsMixin, OwnedIdeaMixin, UpdateView):
    template_name = "ideas/idea_form.html"
    form_class = IdeaForm

    def form_valid(self, form):
        messages.success(self.request, _("Fikir güncellendi."))
        return super().form_valid(form)


class IdeaDeleteView(OwnedIdeaMixin, DeleteView):
    template_name = "ideas/idea_confirm_delete.html"

    def form_valid(self, form):
        messages.success(self.request, _("Fikir silindi."))
        return super().form_valid(form)
