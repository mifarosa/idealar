from datetime import timedelta

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied
from django.http import Http404
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views import View
from django.utils.translation import gettext as _

from .access import can_manage
from .forms import ReplyForm, StatusForm, TicketForm
from .models import ACTIVE_STATUSES, KIND_CHOICES, STATUS_CHOICES, STATUS_CLOSED, STATUS_DONE, STATUS_OPEN, Ticket, TicketMessage

MAX_TICKETS_PER_DAY = 10  # keeps one account from flooding the inbox


class ManagerRequiredMixin(LoginRequiredMixin):
    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated and not can_manage(request.user):
            raise PermissionDenied
        return super().dispatch(request, *args, **kwargs)


class TicketListView(LoginRequiredMixin, View):
    """The signed-in user's own tickets."""

    def get(self, request):
        tickets = Ticket.objects.filter(owner=request.user)
        return render(request, "support/ticket_list.html", {"tickets": tickets})


class TicketCreateView(LoginRequiredMixin, View):
    def get(self, request):
        return render(request, "support/ticket_form.html", {"form": TicketForm(initial={"kind": request.GET.get("tur", "")} if request.GET.get("tur") in dict(KIND_CHOICES) else None)})

    def post(self, request):
        since = timezone.now() - timedelta(days=1)
        if Ticket.objects.filter(owner=request.user, created_at__gte=since).count() >= MAX_TICKETS_PER_DAY:
            messages.error(request, _("Bugün çok fazla kayıt açtın; yarın tekrar yazabilirsin."))
            return redirect("support:list")
        form = TicketForm(request.POST)
        if not form.is_valid():
            return render(request, "support/ticket_form.html", {"form": form})
        ticket = form.save(commit=False)
        ticket.owner = request.user
        ticket.save()
        messages.success(request, _("Kaydın alındı, teşekkürler. Yanıt gelirse burada görürsün."))
        return redirect("support:detail", pk=ticket.pk)


class TicketDetailView(LoginRequiredMixin, View):
    """The thread. Its author and the site owner can read and reply; only the owner can change the status."""

    def get_ticket(self, request, pk) -> Ticket:
        tickets = Ticket.objects.select_related("owner")
        ticket = get_object_or_404(tickets, pk=pk)
        if ticket.owner_id != request.user.pk and not can_manage(request.user):
            raise Http404  # same answer as a missing ticket
        return ticket

    def render_detail(self, request, ticket, reply_form=None):
        manager = can_manage(request.user)
        context = {
            "ticket": ticket,
            "thread": ticket.messages.select_related("author"),
            "reply_form": reply_form or ReplyForm(),
            "status_form": StatusForm(initial={"status": ticket.status}) if manager else None,
            "manager": manager,
            "can_reply": manager or ticket.accepts_replies_from_author,
        }
        return render(request, "support/ticket_detail.html", context)

    def get(self, request, pk):
        return self.render_detail(request, self.get_ticket(request, pk))

    def post(self, request, pk):
        ticket = self.get_ticket(request, pk)
        manager = can_manage(request.user)
        if request.POST.get("action") == "status":
            return self._change_status(request, ticket, manager)
        if not (manager or ticket.accepts_replies_from_author):
            raise PermissionDenied
        form = ReplyForm(request.POST)
        if not form.is_valid():
            return self.render_detail(request, ticket, form)
        from_admin = manager and ticket.owner_id != request.user.pk
        TicketMessage.objects.create(ticket=ticket, author=request.user, from_admin=from_admin, body=form.cleaned_data["body"])
        if not from_admin and ticket.status == STATUS_DONE:
            ticket.status = STATUS_OPEN  # the author says it is not solved after all
        ticket.save(update_fields=["status", "updated_at"])
        messages.success(request, _("Yanıtın eklendi."))
        return redirect("support:detail", pk=ticket.pk)

    def _change_status(self, request, ticket, manager):
        if not manager:
            raise PermissionDenied
        form = StatusForm(request.POST)
        if form.is_valid():
            ticket.status = form.cleaned_data["status"]
            ticket.save(update_fields=["status", "updated_at"])
            messages.success(request, _("Durum güncellendi."))
        return redirect("support:detail", pk=ticket.pk)


class TicketDeleteView(LoginRequiredMixin, View):
    """The author may delete their own ticket (and its thread); the site owner may delete any."""

    http_method_names = ["post"]

    def post(self, request, pk):
        ticket = get_object_or_404(Ticket, pk=pk)
        if ticket.owner_id != request.user.pk and not can_manage(request.user):
            raise Http404
        by_owner_of_site = ticket.owner_id != request.user.pk
        ticket.delete()
        messages.success(request, _("Kayıt silindi."))
        return redirect("support:inbox" if by_owner_of_site else "support:list")


class InboxView(ManagerRequiredMixin, View):
    """Every ticket of every user, for the site owner."""

    def get(self, request):
        status = request.GET.get("durum", "aktif")
        kind = request.GET.get("tur", "")
        tickets = Ticket.objects.select_related("owner").annotate(reply_count=Count("messages"))
        if status == "aktif":
            tickets = tickets.filter(status__in=ACTIVE_STATUSES)
        elif status in dict(STATUS_CHOICES):
            tickets = tickets.filter(status=status)
        if kind in dict(KIND_CHOICES):
            tickets = tickets.filter(kind=kind)
        counts = Ticket.objects.aggregate(
            active=Count("pk", filter=Q(status__in=ACTIVE_STATUSES)),
            done=Count("pk", filter=Q(status=STATUS_DONE)),
            closed=Count("pk", filter=Q(status=STATUS_CLOSED)),
            total=Count("pk"),
        )
        context = {"tickets": tickets, "status": status, "kind": kind, "counts": counts, "kinds": KIND_CHOICES, "STATUS_OPEN": STATUS_OPEN}
        return render(request, "support/inbox.html", context)
