import re

from django import forms

from ai.providers import KINDS

from . import key_vault
from .models import AIModel

MAX_KEY_CHARS = 400


class AIModelForm(forms.ModelForm):
    kind = forms.ChoiceField(label="Sağlayıcı", choices=[])
    api_key = forms.CharField(
        label="API anahtarı", required=False, max_length=MAX_KEY_CHARS,
        widget=forms.PasswordInput(render_value=False, attrs={"autocomplete": "off", "spellcheck": "false"}),
    )

    field_order = ["kind", "label", "model_name", "api_key", "base_url", "enabled"]

    class Meta:
        model = AIModel
        fields = ["kind", "label", "model_name", "base_url", "enabled"]
        labels = {"label": "Görünen ad", "model_name": "Model adı", "base_url": "Adres", "enabled": "Kullanımda"}
        help_texts = {
            "label": "Boş bırakırsan sağlayıcı adı kullanılır.",
            "model_name": "Boş bırakabilirsin: Groq, Gemini ve Claude için hazır bir model seçilir. Diğerlerinde kaydettikten sonra listedeki \"Modeller\" tuşundan seçersin.",
            "base_url": "Yalnızca Ollama ve \"Diğer\" için. Ollama: http://host.docker.internal:11434 · LM Studio: http://host.docker.internal:1234/v1",
        }

    def __init__(self, *args, user, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user
        self.fields["kind"].choices = [(kind, info.label) for kind, info in KINDS.items() if user.is_staff or not info.staff_only]
        self.fields["label"].required = False  # falls back to the provider name
        self.fields["model_name"].required = False  # falls back to the provider's default, or is picked from the list later
        saved = self.instance.pk and self.instance.key_hint
        self.fields["api_key"].help_text = (
            f"Kayıtlı anahtar: …{saved}. Değiştirmek istemiyorsan boş bırak."
            if saved
            else "Anahtar şifrelenip saklanır ve bir daha gösterilmez."
        )
        if not user.is_staff:
            del self.fields["base_url"]

    def clean_model_name(self) -> str:
        return self.cleaned_data["model_name"].strip()

    def clean_api_key(self) -> str:
        key = self.cleaned_data["api_key"].strip()
        if re.search(r"\s", key):
            raise forms.ValidationError("Anahtar boşluk içeremez; kopyalarken fazladan bir şey gelmiş olabilir.")
        return key

    def clean_base_url(self) -> str:
        return self.cleaned_data["base_url"].strip().rstrip("/")

    def clean(self):
        cleaned = super().clean()
        kind = cleaned.get("kind")
        if kind not in KINDS:
            return cleaned
        info = KINDS[kind]
        if not cleaned.get("label"):
            cleaned["label"] = info.label
        if not cleaned.get("model_name"):
            cleaned["model_name"] = info.default_model
        has_saved_key = bool(self.instance.pk and self.instance.api_key_sealed and self.instance.kind == kind)
        if info.needs_key and not cleaned.get("api_key") and not has_saved_key:
            self.add_error("api_key", "Bu sağlayıcı için API anahtarı gerekli.")
        if info.staff_only:
            url = cleaned.get("base_url", "")
            if not re.fullmatch(r"https?://[^\s/]+(/\S*)?", url):
                self.add_error("base_url", "http:// veya https:// ile başlayan bir adres yaz.")
        else:
            cleaned["base_url"] = ""  # fixed endpoint; nothing user-supplied can reach the request
        return cleaned

    def save(self, commit=True):
        kind_changed = "kind" in self.changed_data and bool(self.instance.pk)
        model = super().save(commit=False)
        model.owner = self.user
        key = self.cleaned_data.get("api_key")
        if key:
            model.api_key_sealed, model.key_hint = key_vault.seal(key, self.user.pk), key_vault.hint(key)
        elif kind_changed:
            # A key saved for one provider must never be sent to another one.
            model.api_key_sealed = model.key_hint = ""
        if "base_url" not in self.fields:
            model.base_url = ""
        if commit:
            model.save()
        return model
