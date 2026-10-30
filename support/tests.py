from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from support.access import can_manage
from support.models import MAX_TEXT_CHARS, Ticket, TicketMessage
from support.views import MAX_TICKETS_PER_DAY

OWNER_EMAIL = "boss@example.com"


def make_user(name, email=""):
    return get_user_model().objects.create_user(name, email=email)


def make_ticket(owner, **fields):
    fields = {"kind": "bug", "title": "Chat is broken", "body": "details", **fields}
    return Ticket.objects.create(owner=owner, **fields)


@override_settings(TICKET_ADMIN_EMAILS=[OWNER_EMAIL])
class AccessTests(TestCase):
    def test_only_the_listed_email_manages_tickets_regardless_of_case_or_staff_flag(self):
        self.assertTrue(can_manage(make_user("boss", "Boss@Example.com")))
        self.assertFalse(can_manage(make_user("staffer", "staff@example.com")))
        self.assertFalse(can_manage(get_user_model().objects.create_superuser("root", "root@example.com", "x")))
        self.assertFalse(can_manage(make_user("noemail", "")))

    @override_settings(TICKET_ADMIN_EMAILS=[])
    def test_nobody_manages_tickets_until_an_address_is_configured(self):
        self.assertFalse(can_manage(make_user("boss", OWNER_EMAIL)))
        self.assertFalse(can_manage(make_user("blank", "")))

    def test_anonymous_users_cannot_manage(self):
        from django.contrib.auth.models import AnonymousUser

        self.assertFalse(can_manage(AnonymousUser()))


@override_settings(TICKET_ADMIN_EMAILS=[OWNER_EMAIL])
class UserSideTests(TestCase):
    def setUp(self):
        self.user = make_user("ayse", "ayse@example.com")
        self.client.force_login(self.user)

    def test_anonymous_users_are_sent_to_login(self):
        self.client.logout()

        for name in ("support:list", "support:create", "support:inbox"):
            self.assertEqual(self.client.get(reverse(name)).status_code, 302, name)

    def test_creating_a_ticket_stores_it_and_shows_the_thread(self):
        response = self.client.post(reverse("support:create"), {"kind": "bug", "title": "Chat is broken", "body": "It says no AI answered"}, follow=True)

        ticket = Ticket.objects.get()
        self.assertEqual((ticket.owner, ticket.status, ticket.kind), (self.user, "open", "bug"))
        self.assertContains(response, "Kaydın alındı")
        self.assertContains(response, "It says no AI answered")

    def test_validation_errors_keep_the_form(self):
        response = self.client.post(reverse("support:create"), {"kind": "bug", "title": "", "body": ""})

        self.assertEqual(response.status_code, 200)
        self.assertFalse(Ticket.objects.exists())

    def test_overlong_text_is_rejected(self):
        response = self.client.post(reverse("support:create"), {"kind": "bug", "title": "x", "body": "y" * (MAX_TEXT_CHARS + 1)})

        self.assertFalse(Ticket.objects.exists())
        self.assertEqual(response.status_code, 200)

    def test_html_in_a_ticket_is_escaped(self):
        make_ticket(self.user, title="<script>alert(1)</script>")

        page = self.client.get(reverse("support:list"))

        self.assertNotContains(page, "<script>alert(1)</script>")

    def test_a_day_limit_stops_ticket_floods(self):
        for n in range(MAX_TICKETS_PER_DAY):
            make_ticket(self.user, title=f"t{n}")

        response = self.client.post(reverse("support:create"), {"kind": "bug", "title": "one more", "body": "x"}, follow=True)

        self.assertEqual(Ticket.objects.count(), MAX_TICKETS_PER_DAY)
        self.assertContains(response, "çok fazla kayıt")

    def test_the_limit_only_counts_the_last_24_hours(self):
        old = [make_ticket(self.user, title=f"t{n}") for n in range(MAX_TICKETS_PER_DAY)]
        Ticket.objects.filter(pk__in=[t.pk for t in old]).update(created_at=timezone.now() - timedelta(days=2))

        self.client.post(reverse("support:create"), {"kind": "bug", "title": "fresh", "body": "x"})

        self.assertTrue(Ticket.objects.filter(title="fresh").exists())

    def test_users_see_only_their_own_tickets_and_get_404_for_others(self):
        mine = make_ticket(self.user, title="Mine")
        theirs = make_ticket(make_user("other"), title="Theirs")

        self.assertContains(self.client.get(reverse("support:list")), "Mine")
        self.assertNotContains(self.client.get(reverse("support:list")), "Theirs")
        self.assertEqual(self.client.get(reverse("support:detail", args=[mine.pk])).status_code, 200)
        self.assertEqual(self.client.get(reverse("support:detail", args=[theirs.pk])).status_code, 404)
        self.assertEqual(self.client.post(reverse("support:detail", args=[theirs.pk]), {"body": "hi"}).status_code, 404)

    def test_users_cannot_open_the_inbox_or_change_a_status(self):
        mine = make_ticket(self.user)

        self.assertEqual(self.client.get(reverse("support:inbox")).status_code, 403)
        response = self.client.post(reverse("support:detail", args=[mine.pk]), {"action": "status", "status": "done"})
        self.assertEqual(response.status_code, 403)
        mine.refresh_from_db()
        self.assertEqual(mine.status, "open")

    def test_user_reply_is_added_and_reopens_a_solved_ticket(self):
        ticket = make_ticket(self.user, status="done")

        self.client.post(reverse("support:detail", args=[ticket.pk]), {"body": "Still broken"})

        ticket.refresh_from_db()
        self.assertEqual((ticket.status, ticket.messages.get().from_admin), ("open", False))

    def test_closed_tickets_take_no_more_replies_from_their_author(self):
        ticket = make_ticket(self.user, status="closed")

        response = self.client.post(reverse("support:detail", args=[ticket.pk]), {"body": "hello?"})

        self.assertEqual(response.status_code, 403)
        self.assertFalse(ticket.messages.exists())

    def test_the_inbox_link_is_hidden_from_regular_users(self):
        self.assertNotContains(self.client.get(reverse("support:list")), "Gelen kutusu")
        self.assertContains(self.client.get(reverse("support:list")), "Öneri &amp; şikayet")


@override_settings(TICKET_ADMIN_EMAILS=[OWNER_EMAIL])
class OwnerSideTests(TestCase):
    def setUp(self):
        self.boss = make_user("boss", OWNER_EMAIL)
        self.author = make_user("ayse", "ayse@example.com")
        self.client.force_login(self.boss)
        self.ticket = make_ticket(self.author, title="Chat is broken")

    def test_the_inbox_lists_every_users_tickets_with_author_and_filters_by_status_and_kind(self):
        make_ticket(make_user("deniz"), title="Old thing", status="done")
        make_ticket(make_user("can"), title="A wish", kind="suggestion")

        active = self.client.get(reverse("support:inbox"))
        done = self.client.get(reverse("support:inbox"), {"durum": "done"})
        wishes = self.client.get(reverse("support:inbox"), {"tur": "suggestion"})

        self.assertContains(active, "Chat is broken")
        self.assertContains(active, "ayse")
        self.assertNotContains(active, "Old thing")
        self.assertContains(done, "Old thing")
        self.assertContains(wishes, "A wish")
        self.assertNotContains(wishes, "Chat is broken")

    def test_the_owner_sees_the_authors_name_and_email_and_can_reply_as_support(self):
        detail = self.client.get(reverse("support:detail", args=[self.ticket.pk]))
        self.assertContains(detail, "ayse@example.com")

        self.client.post(reverse("support:detail", args=[self.ticket.pk]), {"body": "Looking into it"})

        reply = self.ticket.messages.get()
        self.assertTrue(reply.from_admin)
        self.client.force_login(self.author)
        page = self.client.get(reverse("support:detail", args=[self.ticket.pk]))
        self.assertContains(page, "Looking into it")
        self.assertContains(page, "Destek")
        self.assertNotContains(page, "boss@example.com")  # the author sees "Destek", not the owner's identity

    def test_the_owner_changes_the_status(self):
        self.client.post(reverse("support:detail", args=[self.ticket.pk]), {"action": "status", "status": "in_progress"})
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.status, "in_progress")

        self.client.post(reverse("support:detail", args=[self.ticket.pk]), {"action": "status", "status": "bogus"})
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.status, "in_progress")  # an invalid value changes nothing

    def test_the_owner_may_still_answer_a_closed_ticket(self):
        self.ticket.status = "closed"
        self.ticket.save()

        self.client.post(reverse("support:detail", args=[self.ticket.pk]), {"body": "Reopening soon"})

        self.assertEqual(self.ticket.messages.count(), 1)

    def test_the_owners_own_tickets_work_like_anyone_elses(self):
        own = make_ticket(self.boss, title="My own note")

        self.client.post(reverse("support:detail", args=[own.pk]), {"body": "self reply"})

        self.assertFalse(own.messages.get().from_admin)  # replying to yourself is not "Destek"

    def test_the_sidebar_shows_the_inbox_with_the_open_count(self):
        page = self.client.get(reverse("support:list"))

        self.assertContains(page, "Gelen kutusu")
        self.assertContains(page, '<span class="count">1</span>')

    def test_deleting_a_user_removes_their_tickets(self):
        TicketMessage.objects.create(ticket=self.ticket, author=self.author, body="x")

        self.author.delete()

        self.assertFalse(Ticket.objects.exists())
