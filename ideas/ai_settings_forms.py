import re

from django import forms

from ai.providers import KINDS

from .models import AIModel

KEY_VARIABLE = re.compile(r"[A-Z][A-Z0-9_]*_API_KEY")


class AIModelForm(forms.ModelForm):
    kind = forms.ChoiceField(label="Sağlayıcı", choices=[(kind, info.label) for kind, info in KINDS.items()])

    class Meta:
        model = AIModel
        fields = ["kind", "label", "model_name", "base_url", "key_env", "enabled"]
        labels = {
            "label": "Görünen ad",
            "model_name": "Model adı",
            "base_url": "Adres",
            "key_env": "Anahtarın .env adı",
            "enabled": "Kullanımda",
        }
        help_texts = {
            "label": "Boş bırakırsan sağlayıcı adı kullanılır.",
            "base_url": "Yalnızca Ollama ve \"Diğer\" için. Ollama: http://host.docker.internal:11434 · LM Studio: http://host.docker.internal:1234/v1",
            "key_env": "Anahtarın kendisini buraya yazma; .env dosyasındaki değişkenin adını yaz (örn. GROQ_API_KEY). Yerel modellerde boş kalabilir.",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["label"].required = False  # falls back to the provider name

    def clean_model_name(self) -> str:
        return self.cleaned_data["model_name"].strip()

    def clean_key_env(self) -> str:
        name = self.cleaned_data["key_env"].strip()
        # Only *_API_KEY names: a free-form name could be pointed at SECRET_KEY and sent to a custom address.
        if name and not KEY_VARIABLE.fullmatch(name):
            raise forms.ValidationError("Değişken adı BÜYÜK_HARFLE yazılmalı ve _API_KEY ile bitmeli (örn. GROQ_API_KEY).")
        return name

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
        if not cleaned.get("key_env"):
            cleaned["key_env"] = info.key_env
        if info.needs_key and not info.key_env:
            self.add_error("key_env", "Bu sağlayıcı için anahtar değişkeni gerekli.")
        if kind in ("ollama", "custom"):
            url = cleaned.get("base_url", "")
            if not re.fullmatch(r"https?://[^\s/]+(/\S*)?", url):
                self.add_error("base_url", "http:// veya https:// ile başlayan bir adres yaz.")
        else:
            cleaned["base_url"] = ""  # fixed endpoint; nothing user-supplied can reach the request
        return cleaned
