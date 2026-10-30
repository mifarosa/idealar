"""Turns an AI failure into a short Turkish sentence the user can act on (never includes a key)."""
import re

from ai.errors import AIError, AINotConfiguredError, AIProviderError, AIRateLimitError, AIResponseError, AllProvidersFailed

from . import ai_registry

NO_MODEL = "Çalışan bir AI modelin yok. Ayarlar → AI modellerimi yönet sayfasından bir model ve anahtarı ekle."
HTTP_STATUS = re.compile(r"HTTP (\d{3})")
STATUS_REASONS = {
    400: "isteği reddetti (400); model adı yanlış olabilir",
    401: "anahtarı reddetti (401); anahtar yanlış ya da iptal edilmiş olabilir",
    402: "ödeme gerekli (402); hesabında bakiye yok gibi görünüyor",
    403: "erişimi reddetti (403); anahtarın bu modele yetkisi olmayabilir",
    404: "modeli bulamadı (404); model adını kontrol et, \"Modeller\" tuşu geçerli adları listeler",
}


def _reason(error: AIError) -> str:
    if isinstance(error, AIRateLimitError):
        return "kullanım limiti doldu, biraz sonra tekrar dene"
    if isinstance(error, AINotConfiguredError):
        return "anahtar eksik"
    if isinstance(error, AIResponseError):
        return "geçerli bir cevap vermedi"
    if isinstance(error, AIProviderError):
        status = HTTP_STATUS.search(str(error))
        if status:
            code = int(status.group(1))
            return STATUS_REASONS.get(code) or (f"şu an çalışmıyor ({code})" if code >= 500 else f"hata verdi ({code})")
        return "ulaşılamadı"
    return "hata verdi"


def describe(error: AIError) -> str:
    if isinstance(error, AllProvidersFailed):
        return "; ".join(f"{ai_registry.label_for(name)}: {_reason(failure)}" for name, failure in error.failures)
    if isinstance(error, AINotConfiguredError):
        return NO_MODEL
    return _reason(error).capitalize()
