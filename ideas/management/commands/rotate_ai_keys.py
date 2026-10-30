from django.core.management.base import BaseCommand

from ideas import key_vault
from ideas.models import AIModel


class Command(BaseCommand):
    help = "Re-seals every stored AI key with the current KEYS_ENCRYPTION_KEY (use after changing the secret)."

    def handle(self, *args, **options):
        resealed = unreadable = 0
        for model in AIModel.objects.exclude(api_key_sealed=""):
            if not key_vault.needs_rotation(model.api_key_sealed):
                continue
            try:
                plain = key_vault.unseal(model.api_key_sealed, model.owner_id)
            except key_vault.KeyUnreadable:
                unreadable += 1
                self.stderr.write(f"Model {model.pk} ({model.label}): cannot be decrypted; its owner must enter the key again.")
                continue
            model.api_key_sealed = key_vault.seal(plain, model.owner_id)
            model.save(update_fields=["api_key_sealed"])
            resealed += 1
        self.stdout.write(f"Re-sealed {resealed} key(s); {unreadable} could not be read.")
