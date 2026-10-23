from django import forms

from .github_repo import GitHubError, parse_repo_url
from .models import PLATFORM_CHOICES, Feature, Idea, Project


class QuickIdeaForm(forms.ModelForm):
    """Capture form: only the raw thought, so saving takes seconds on a phone."""

    class Meta:
        model = Idea
        fields = ["body"]
        widgets = {
            "body": forms.Textarea(attrs={"rows": 1, "placeholder": "Yeni fikir…", "aria-label": "Yeni fikir"}),
        }

    def __init__(self, *args, user=None, **kwargs):
        # `user` is accepted so the create view can pass the same kwargs to either form.
        super().__init__(*args, **kwargs)


class IdeaForm(forms.ModelForm):
    platforms = forms.MultipleChoiceField(
        label="Platformlar", choices=PLATFORM_CHOICES, required=False, widget=forms.CheckboxSelectMultiple
    )

    class Meta:
        model = Idea
        fields = ["title", "body", "platforms", "projects"]
        labels = {"title": "Başlık (isteğe bağlı)", "body": "Açıklama", "projects": "Projeler"}
        widgets = {"body": forms.Textarea(attrs={"rows": 8}), "projects": forms.CheckboxSelectMultiple}

    def __init__(self, *args, user, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["projects"].queryset = Project.objects.filter(owner=user)
        self.fields["projects"].required = False


class FeatureForm(forms.ModelForm):
    class Meta:
        model = Feature
        fields = ["text", "platform"]
        widgets = {"text": forms.TextInput(attrs={"placeholder": "Yeni özellik…", "aria-label": "Yeni özellik"})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["platform"].choices = [("", "Tümü")] + list(PLATFORM_CHOICES)


class ProjectForm(forms.ModelForm):
    ideas = forms.ModelMultipleChoiceField(
        label="Bağlı fikirler", queryset=Idea.objects.none(), required=False, widget=forms.CheckboxSelectMultiple
    )

    class Meta:
        model = Project
        fields = ["name", "description", "github_url"]
        labels = {"name": "Proje adı", "description": "Açıklama", "github_url": "GitHub adresi (isteğe bağlı)"}
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
        label="Hangi fikirlere kopyalansın?", queryset=Idea.objects.none(), widget=forms.CheckboxSelectMultiple
    )

    def __init__(self, *args, user, source_idea, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["ideas"].queryset = Idea.objects.owned_by(user).exclude(pk=source_idea.pk)
