from django.urls import reverse


class UserFormKwargsMixin:
    """Passes the signed-in user to forms that limit their choices to the user's own records."""

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["user"] = self.request.user
        return kwargs


def idea_panel_url(idea_pk: int) -> str:
    """The page that shows the given idea (list + detail on desktop, detail screen on phones)."""
    return reverse("ideas:detail", args=[idea_pk])

