from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy

STATUS_TODO, STATUS_DOING, STATUS_DONE = "todo", "doing", "done"
STATUS_CHOICES = [(STATUS_TODO, gettext_lazy("Yapılacak")), (STATUS_DOING, gettext_lazy("Yapılıyor")), (STATUS_DONE, gettext_lazy("Bitti"))]
STATUSES = [value for value, _ in STATUS_CHOICES]


class Task(models.Model):
    """A card on a board. project=None is the owner's personal board; otherwise it sits on that project's board."""

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="tasks")
    project = models.ForeignKey("ideas.Project", null=True, blank=True, on_delete=models.CASCADE, related_name="tasks")
    idea = models.ForeignKey("ideas.Idea", null=True, blank=True, on_delete=models.SET_NULL, related_name="tasks")
    title = models.CharField(max_length=200)
    # True for cards that stand for an idea: they show the idea's own title and progress, and cannot be renamed here.
    mirrors_idea = models.BooleanField(default=False)
    status = models.CharField(max_length=6, choices=STATUS_CHOICES, default=STATUS_TODO)
    position = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["position", "id"]
        indexes = [models.Index(fields=["owner", "project", "status", "position"])]
        constraints = [
            models.UniqueConstraint(fields=["owner", "project", "idea"], condition=models.Q(mirrors_idea=True), name="one_card_per_idea_per_board")
        ]

    def __str__(self) -> str:
        return self.title
