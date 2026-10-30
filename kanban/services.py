"""Board rules: which tasks make up a board and how a card moves between and within columns."""
from django.db import transaction

from .models import STATUS_TODO, STATUSES, Task


def board_tasks(owner, project):
    return Task.objects.filter(owner=owner, project=project).select_related("idea")


def columns(owner, project) -> dict[str, list[Task]]:
    """The board's cards by column. Project boards first mirror the project's ideas (see sync_project_board)."""
    if project is not None:
        sync_project_board(owner, project)
    # An idea that was deleted leaves its card behind; such a card means nothing.
    Task.objects.filter(owner=owner, mirrors_idea=True, idea__isnull=True).delete()
    grouped = {status: [] for status in STATUSES}
    for task in board_tasks(owner, project).prefetch_related("idea__features"):
        grouped[task.status].append(task)
    return grouped


def add_task(owner, project, title: str, status: str, idea=None, mirrors_idea: bool = False) -> Task:
    """Appends to the bottom of the column."""
    last = board_tasks(owner, project).filter(status=status).order_by("-position").first()
    return Task.objects.create(
        owner=owner, project=project, idea=idea, title=title, status=status, position=(last.position + 1) if last else 0,
        mirrors_idea=mirrors_idea,
    )


def add_idea_card(owner, project, idea) -> Task:
    """Puts an idea on a board as a card in "Yapılacak"; an idea has at most one card per board."""
    existing = board_tasks(owner, project).filter(mirrors_idea=True, idea=idea).first()
    if existing:
        return existing
    return add_task(owner, project, idea.display_title[:200], STATUS_TODO, idea=idea, mirrors_idea=True)


def sync_project_board(owner, project) -> None:
    """A project's board always has one card per linked idea (new ones start in "Yapılacak"), and none for unlinked ideas."""
    linked = {idea.pk: idea for idea in project.ideas.owned_by(owner)}
    cards = board_tasks(owner, project).filter(mirrors_idea=True)
    present = {card.idea_id for card in cards}
    cards.exclude(idea__in=linked).delete()
    for idea_id, idea in linked.items():
        if idea_id not in present:
            add_idea_card(owner, project, idea)


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
