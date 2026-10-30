from django.conf import settings
from django.core.checks import Error, Warning, register


@register()
def key_encryption_secret(app_configs, **kwargs):
    problems = []
    if settings.KEYS_ENCRYPTION_KEY and len(settings.KEYS_ENCRYPTION_KEY) < 32:
        problems.append(Error("KEYS_ENCRYPTION_KEY is too short.", hint="Use at least 32 random characters.", id="ideas.E001"))
    if not settings.DEBUG and not settings.KEYS_ENCRYPTION_KEY:
        problems.append(
            Warning(
                "KEYS_ENCRYPTION_KEY is not set; users' AI keys are sealed with SECRET_KEY.",
                hint="Set a separate random KEYS_ENCRYPTION_KEY so either secret can change on its own.",
                id="ideas.W001",
            )
        )
    return problems
