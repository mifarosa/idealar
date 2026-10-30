from django import forms

from .models import KIND_CHOICES, MAX_TEXT_CHARS, STATUS_CHOICES, Ticket


class TicketForm(forms.ModelForm):
    kind = forms.ChoiceField(label="Ne bildirmek istiyorsun?", choices=KIND_CHOICES)

    class Meta:
        model = Ticket
        fields = ["kind", "title", "body"]
        labels = {"title": "Kısaca konu", "body": "Ayrıntı"}
        widgets = {"body": forms.Textarea(attrs={"rows": 7, "placeholder": "Neyi, nerede, nasıl yaşadığını yaz. Hata ise ne yapınca olduğunu da yaz."})}


class ReplyForm(forms.Form):
    body = forms.CharField(label="Yanıtın", max_length=MAX_TEXT_CHARS, widget=forms.Textarea(attrs={"rows": 4}))


class StatusForm(forms.Form):
    status = forms.ChoiceField(choices=STATUS_CHOICES)
