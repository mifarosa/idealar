from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Sets a user's e-mail so that Google sign-in with that address lands in this existing account."

    def add_arguments(self, parser):
        parser.add_argument("username")
        parser.add_argument("email")

    def handle(self, *args, username, email, **options):
        User = get_user_model()
        try:
            user = User.objects.get(username=username)
        except User.DoesNotExist as error:
            raise CommandError(f"No user named {username}") from error
        user.email = email.strip().lower()
        user.save(update_fields=["email"])
        self.stdout.write(f"{username} will be matched by Google account {user.email}")
