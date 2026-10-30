from .access import can_manage
from .models import ACTIVE_STATUSES, Ticket


def support(request):
    """Lets the sidebar show the inbox (with its open count) to the site owner only."""
    if not can_manage(request.user):
        return {}
    return {"can_manage_tickets": True, "open_ticket_count": Ticket.objects.filter(status__in=ACTIVE_STATUSES).count()}
