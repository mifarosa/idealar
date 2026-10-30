"""Board rules: which tasks make up a board and how a card moves between and within columns."""
from django.db import transaction

from .models import STATUSES, Task


def board_tasks(owner, project):
    return Task.objects.filter(owner=owner, project=project).select_related("idea")


def columns(owner, project) -> dict[str, list[Task]]:
    grouped = {status: [] for status in STATUSES}
    for task in board_tasks(owner, project):
        grouped[task.status].append(task)
    return grouped


def add_task(owner, project, title: str, status: str, idea=None) -> Task:
    """Appends to the bottom of the column."""
    last = board_tasks(owner, project).filter(status=status).order_by("-position").first()
    return Task.objects.create(
        owner=owner, project=project, idea=idea, title=title, status=status, position=(last.position + 1) if last else 0
    )


def move_task(task: Task, status: str, index: int) -> None:
    """Puts the card at `index` of column `status` (clamped to the column) and renumbers that column."""
    if status not in STATUSES:
        raise ValueError(f"Unknown status {status!r}")
    with transaction.atomic():
        others = list(board_tasks(task.owner, task.project).filter(status=status).exclude(pk=task.pk))
        index = max(0, min(index, len(others)))
        others.insert(index, task)
        task.status = status
        for position, card in enumerate(others):
            if card.pk == task.pk or card.position != position:
                card.position = position
                card.status = status
                card.save(update_fields=["status", "position"])


def step_task(task: Task, direction: int) -> None:
    """Moves the card to the neighbouring column (-1 left, +1 right), at the bottom of it."""
    target = STATUSES.index(task.status) + direction
    if 0 <= target < len(STATUSES):
        move_task(task, STATUSES[target], index=10**6)
