from django import forms

from .models import Idea


class QuickIdeaForm(forms.ModelForm):
    """Capture form: only the raw thought, so saving takes seconds on a phone."""

    class Meta:
        model = Idea
        fields = ["body"]
        labels = {"body": "Fikir"}
        widgets = {
            "body": forms.Textarea(attrs={"rows": 3, "placeholder": "Aklına gelen fikri yaz…", "autofocus": True}),
        }


class IdeaForm(forms.ModelForm):
    class Meta:
        model = Idea
        fields = ["title", "body"]
        labels = {"title": "Başlık (isteğe bağlı)", "body": "Fikir"}
        widgets = {"body": forms.Textarea(attrs={"rows": 10})}
