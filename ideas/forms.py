from django import forms
from django.utils.translation import gettext_lazy, gettext as _

from .github_repo import GitHubError, parse_repo_url
from .models import PLATFORM_CHOICES, Feature, Idea, Project


class QuickIdeaForm(forms.ModelForm):
    """Capture form: only the raw thought, so saving takes seconds on a phone."""

    class Meta:
        model = Idea
        fields = ["body"]
        widgets = {
            "body": forms.Textarea(attrs={"rows": 1, "placeholder": gettext_lazy("Yeni fikir…"), "aria-label": gettext_lazy("Yeni fikir")}),
        }

    def __init__(self, *args, user=None, **kwargs):
        # `user` is accepted so the create view can pass the same kwargs to either form.
        super().__init__(*args, **kwargs)


class IdeaForm(forms.ModelForm):
    platforms = forms.MultipleChoiceField(
        label=gettext_lazy("Platformlar"), choices=PLATFORM_CHOICES, required=False, widget=forms.CheckboxSelectMultiple
    )

    class Meta:
        model = Idea
        fields = ["title", "body", "platforms", "projects"]
        labels = {"title": gettext_lazy("Başlık (isteğe bağlı)"), "body": gettext_lazy("Açıklama"), "projects": gettext_lazy("Projeler")}
        widgets = {"body": forms.Textarea(attrs={"rows": 8}), "projects": forms.CheckboxSelectMultiple}

    def __init__(self, *args, user, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["projects"].queryset = Project.objects.filter(owner=user)
        self.fields["projects"].required = False


class FeatureForm(forms.ModelForm):
    class Meta:
        model = Feature
        fields = ["text", "platform"]
        widgets = {
            "text": forms.TextInput(attrs={"placeholder": gettext_lazy("Yeni özellik ekle…"), "aria-label": gettext_lazy("Yeni özellik")}),
            "platform": forms.Select(attrs={"class": "select", "aria-label": gettext_lazy("Platform")}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["platform"].choices = [("", _("Tümü"))] + list(PLATFORM_CHOICES)


class ProjectForm(forms.ModelForm):
    ideas = forms.ModelMultipleChoiceField(
        label=gettext_lazy("Bağlı fikirler"), queryset=Idea.objects.none(), required=False, widget=forms.CheckboxSelectMultiple
    )

    class Meta:
        model = Project
        fields = ["name", "description", "github_url"]
        labels = {"name": gettext_lazy("Proje adı"), "description": gettext_lazy("Açıklama"), "github_url": gettext_lazy("GitHub adresi (isteğe bağlı)")}
        widgets = {
            "description": forms.Textarea(attrs={"rows": 5}),
            "github_url": forms.URLInput(attrs={"placeholder": "https://github.com/sahip/depo"}),
        }

    def clean_github_url(self):
        url = self.cleaned_data["github_url"]
        if url:
            try:
                parse_repo_url(url)
            except GitHubError as error:
                raise forms.ValidationError(str(error)) from error
        return url

    def __init__(self, *args, user, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["ideas"].queryset = Idea.objects.owned_by(user)
        if self.instance.pk:
            self.fields["ideas"].initial = self.instance.ideas.all()

    def save(self, commit=True):
        project = super().save(commit=commit)
        if commit:
            project.ideas.set(self.cleaned_data["ideas"])
        return project


class CopyFeatureForm(forms.Form):
    ideas = forms.ModelMultipleChoiceField(
        label=gettext_lazy("Hangi fikirlere kopyalansın?"), queryset=Idea.objects.none(), widget=forms.CheckboxSelectMultiple
    )

    def __init__(self, *args, user, source_idea, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["ideas"].queryset = Idea.objects.owned_by(user).exclude(pk=source_idea.pk)
