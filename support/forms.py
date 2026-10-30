from django import forms
from django.utils.translation import gettext_lazy

from .models import KIND_CHOICES, MAX_TEXT_CHARS, STATUS_CHOICES, Ticket


class TicketForm(forms.ModelForm):
    kind = forms.ChoiceField(label=gettext_lazy("Ne bildirmek istiyorsun?"), choices=KIND_CHOICES)

    class Meta:
        model = Ticket
        fields = ["kind", "title", "body"]
        labels = {"title": gettext_lazy("Kısaca konu"), "body": gettext_lazy("Ayrıntı")}
        widgets = {"body": forms.Textarea(attrs={"rows": 7, "placeholder": gettext_lazy("Neyi, nerede, nasıl yaşadığını yaz. Hata ise ne yapınca olduğunu da yaz.")})}


class ReplyForm(forms.Form):
    body = forms.CharField(label=gettext_lazy("Yanıtın"), max_length=MAX_TEXT_CHARS, widget=forms.Textarea(attrs={"rows": 4}))


class StatusForm(forms.Form):
    status = forms.ChoiceField(choices=STATUS_CHOICES)
