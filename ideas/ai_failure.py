"""Turns an AI failure into a short Turkish sentence the user can act on (never includes a key)."""
import re
from django.utils.translation import gettext_lazy
from django.utils.translation import gettext as _

from ai.errors import AIError, AINotConfiguredError, AIProviderError, AIRateLimitError, AIResponseError, AllProvidersFailed

from . import ai_registry

NO_MODEL = gettext_lazy("Çalışan bir AI modelin yok. Ayarlar → AI modellerimi yönet sayfasından bir model ve anahtarı ekle.")
HTTP_STATUS = re.compile(r"HTTP (\d{3})")
STATUS_REASONS = {
    400: gettext_lazy("isteği reddetti (400); model adı yanlış olabilir"),
    401: gettext_lazy("anahtarı reddetti (401); anahtar yanlış ya da iptal edilmiş olabilir"),
    402: gettext_lazy("ödeme gerekli (402); hesabında bakiye yok gibi görünüyor"),
    403: gettext_lazy("erişimi reddetti (403); anahtarın bu modele yetkisi olmayabilir"),
    404: gettext_lazy("modeli bulamadı (404); model adını kontrol et, \"Modeller\" tuşu geçerli adları listeler"),
}


def _reason(error: AIError) -> str:
    if isinstance(error, AIRateLimitError):
        return _("kullanım limiti doldu, biraz sonra tekrar dene")
    if isinstance(error, AINotConfiguredError):
        return _("anahtar eksik")
    if isinstance(error, AIResponseError):
        return _("geçerli bir cevap vermedi")
    if isinstance(error, AIProviderError):
        status = HTTP_STATUS.search(str(error))
        if status:
            code = int(status.group(1))
            known = STATUS_REASONS.get(code)
            if known:
                return str(known)
            return _("şu an çalışmıyor ({code})").format(code=code) if code >= 500 else _("hata verdi ({code})").format(code=code)
        return _("ulaşılamadı")
    return _("hata verdi")


def describe(error: AIError, owner=None) -> str:
    """`owner` lets "nothing is configured" say which of the user's models are unusable and why."""
    if isinstance(error, AllProvidersFailed):
        return "; ".join(f"{ai_registry.label_for(name)}: {_reason(failure)}" for name, failure in error.failures)
    if isinstance(error, AINotConfiguredError):
        problems = ai_registry.diagnose(owner) if owner is not None else []
        if problems:
            return _("Modellerin var ama hiçbiri kullanılamıyor.") + " " + "; ".join(f"{label}: {why}" for label, why in problems) + "."
        return str(NO_MODEL)
    return _reason(error).capitalize()
