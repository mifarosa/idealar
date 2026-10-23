from django.urls import reverse


class UserFormKwargsMixin:
    """Passes the signed-in user to forms that limit their choices to the user's own records."""

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["user"] = self.request.user
        return kwargs


def idea_panel_url(idea_pk: int) -> str:
    """List URL that opens the given idea's card."""
    return f"{reverse('ideas:list')}?open={idea_pk}#idea-{idea_pk}"

