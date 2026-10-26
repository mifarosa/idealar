from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from .models import Feature, Idea, Project


def make_user(name: str):
    return get_user_model().objects.create_user(name, password="pw-for-tests-123")


class IdeaModelTests(TestCase):
    def setUp(self):
        self.owner = make_user("owner")

    def test_display_title_prefers_explicit_title(self):
        idea = Idea(owner=self.owner, title="Titled", body="body text")

        self.assertEqual(idea.display_title, "Titled")

    def test_display_title_falls_back_to_first_line_of_body(self):
        idea = Idea(owner=self.owner, body="first line\nsecond line")

        self.assertEqual(idea.display_title, "first line")

    def test_display_title_truncates_long_first_line(self):
        idea = Idea(owner=self.owner, body="x" * 200)

        self.assertEqual(len(idea.display_title), 60)
        self.assertTrue(idea.display_title.endswith("…"))

    def test_matching_searches_title_and_body_case_insensitively(self):
        Idea.objects.create(owner=self.owner, title="Budget app", body="track money")
        Idea.objects.create(owner=self.owner, body="Recipe MANAGER")
        Idea.objects.create(owner=self.owner, body="unrelated")

        self.assertEqual(Idea.objects.matching("budget").count(), 1)
        self.assertEqual(Idea.objects.matching("manager").count(), 1)
        self.assertEqual(Idea.objects.matching("   ").count(), 3)


class IdeaCrudTests(TestCase):
    def setUp(self):
        self.user = make_user("owner")
        self.client.force_login(self.user)

    def test_quick_capture_saves_body_only_idea_for_current_user(self):
        response = self.client.post(reverse("ideas:create"), {"body": "A habit tracker"})

        self.assertRedirects(response, f"{reverse('ideas:detail', args=[Idea.objects.get().pk])}?enrich=1", fetch_redirect_response=False)
        idea = Idea.objects.get()
        self.assertEqual((idea.owner, idea.title, idea.body), (self.user, "", "A habit tracker"))

    def test_full_form_saves_title_and_body(self):
        self.client.post(reverse("ideas:create"), {"title": "Habits", "body": "Track daily habits"})

        idea = Idea.objects.get()
        self.assertEqual((idea.title, idea.body), ("Habits", "Track daily habits"))

    def test_empty_body_is_rejected_and_nothing_saved(self):
        response = self.client.post(reverse("ideas:create"), {"body": "   "})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(Idea.objects.count(), 0)

    def test_list_shows_only_own_ideas_newest_first(self):
        Idea.objects.create(owner=self.user, body="older idea")
        Idea.objects.create(owner=self.user, body="newer idea")
        Idea.objects.create(owner=make_user("other"), body="secret idea")

        response = self.client.get(reverse("ideas:list"))

        self.assertEqual([i.body for i in response.context["ideas"]], ["newer idea", "older idea"])

    def test_list_search_filters_results(self):
        Idea.objects.create(owner=self.user, body="budget app")
        Idea.objects.create(owner=self.user, body="recipe app")

        response = self.client.get(reverse("ideas:list"), {"q": "budget"})

        self.assertEqual([i.body for i in response.context["ideas"]], ["budget app"])

    def test_update_changes_idea(self):
        idea = Idea.objects.create(owner=self.user, body="old")

        self.client.post(reverse("ideas:update", args=[idea.pk]), {"title": "New title", "body": "new"})

        idea.refresh_from_db()
        self.assertEqual((idea.title, idea.body), ("New title", "new"))

    def test_delete_requires_post_and_removes_idea(self):
        idea = Idea.objects.create(owner=self.user, body="bye")

        self.assertEqual(self.client.get(reverse("ideas:delete", args=[idea.pk])).status_code, 200)
        self.assertTrue(Idea.objects.filter(pk=idea.pk).exists())
        self.client.post(reverse("ideas:delete", args=[idea.pk]))

        self.assertFalse(Idea.objects.filter(pk=idea.pk).exists())


class IdeaIsolationTests(TestCase):
    def setUp(self):
        self.other_idea = Idea.objects.create(owner=make_user("other"), body="private")
        self.client.force_login(make_user("intruder"))

    def test_other_users_idea_cannot_be_viewed_edited_or_deleted(self):
        for name in ("ideas:update", "ideas:delete"):
            url = reverse(name, args=[self.other_idea.pk])
            self.assertEqual(self.client.get(url).status_code, 404)
            self.assertEqual(self.client.post(url, {"title": "x", "body": "hacked"}).status_code, 404)

        self.other_idea.refresh_from_db()
        self.assertEqual(self.other_idea.body, "private")

    def test_anonymous_cannot_create(self):
        self.client.logout()

        response = self.client.post(reverse("ideas:create"), {"body": "anon"})

        self.assertEqual(response.status_code, 302)
        self.assertEqual(Idea.objects.filter(body="anon").count(), 0)


def make_idea(owner, body="idea", **kwargs):
    return Idea.objects.create(owner=owner, body=body, **kwargs)


class ProgressTests(TestCase):
    def setUp(self):
        self.user = make_user("owner")

    def test_idea_progress_counts_done_features(self):
        idea = make_idea(self.user)
        Feature.objects.create(idea=idea, text="a", is_done=True)
        Feature.objects.create(idea=idea, text="b")

        progress = idea.progress

        self.assertEqual((progress.done, progress.total, progress.percent), (1, 2, 50))
        self.assertFalse(progress.is_complete)

    def test_idea_without_features_is_not_complete(self):
        self.assertFalse(make_idea(self.user).progress.is_complete)

    def test_finished_and_unfinished_querysets(self):
        finished = make_idea(self.user, "finished")
        Feature.objects.create(idea=finished, text="a", is_done=True)
        partial = make_idea(self.user, "partial")
        Feature.objects.create(idea=partial, text="a", is_done=True)
        Feature.objects.create(idea=partial, text="b")
        empty = make_idea(self.user, "empty")

        ideas = Idea.objects.with_progress()

        self.assertEqual(set(ideas.finished()), {finished})
        self.assertEqual(set(ideas.unfinished()), {partial, empty})

    def test_project_progress_sums_linked_ideas(self):
        project = Project.objects.create(owner=self.user, name="P")
        first, second = make_idea(self.user), make_idea(self.user)
        project.ideas.set([first, second])
        Feature.objects.create(idea=first, text="a", is_done=True)
        Feature.objects.create(idea=second, text="b")

        self.assertEqual((project.progress.done, project.progress.total), (1, 2))


class FeatureViewTests(TestCase):
    def setUp(self):
        self.user = make_user("owner")
        self.client.force_login(self.user)
        self.idea = make_idea(self.user, "with features")

    def test_add_feature_with_platform(self):
        response = self.client.post(
            reverse("ideas:feature-add", args=[self.idea.pk]), {"text": "Push notifications", "platform": "ios"}
        )

        feature = self.idea.features.get()
        self.assertEqual((feature.text, feature.platform, feature.is_done), ("Push notifications", "ios", False))
        self.assertRedirects(response, reverse("ideas:detail", args=[self.idea.pk]), fetch_redirect_response=False)

    def test_add_empty_feature_is_rejected(self):
        self.client.post(reverse("ideas:feature-add", args=[self.idea.pk]), {"text": "  ", "platform": ""})

        self.assertEqual(self.idea.features.count(), 0)

    def test_toggle_sets_state_and_returns_progress(self):
        feature = Feature.objects.create(idea=self.idea, text="a")
        Feature.objects.create(idea=self.idea, text="b")

        response = self.client.post(reverse("ideas:feature-toggle", args=[feature.pk]), {"done": "true"})

        feature.refresh_from_db()
        self.assertTrue(feature.is_done)
        self.assertEqual(response.json(), {"done": True, "done_count": 1, "total": 2})

    def test_toggle_is_idempotent_and_can_uncheck(self):
        feature = Feature.objects.create(idea=self.idea, text="a", is_done=True)
        url = reverse("ideas:feature-toggle", args=[feature.pk])

        self.client.post(url, {"done": "true"})
        self.client.post(url, {"done": "false"})

        feature.refresh_from_db()
        self.assertFalse(feature.is_done)

    def test_delete_feature(self):
        feature = Feature.objects.create(idea=self.idea, text="a")

        self.client.post(reverse("ideas:feature-delete", args=[feature.pk]))

        self.assertEqual(self.idea.features.count(), 0)

    def test_copy_creates_independent_unchecked_copies(self):
        source = Feature.objects.create(idea=self.idea, text="Login", platform="android", is_done=True)
        target = make_idea(self.user, "target")

        self.client.post(reverse("ideas:feature-copy", args=[source.pk]), {"ideas": [target.pk]})

        copy = target.features.get()
        self.assertEqual((copy.text, copy.platform, copy.is_done), ("Login", "android", False))
        copy.is_done = True
        copy.save()
        source.refresh_from_db()
        self.assertTrue(source.is_done)
        self.assertNotEqual(copy.pk, source.pk)

    def test_copy_form_excludes_source_idea(self):
        source = Feature.objects.create(idea=self.idea, text="Login")

        response = self.client.get(reverse("ideas:feature-copy", args=[source.pk]))

        self.assertNotIn(self.idea, response.context["form"].fields["ideas"].queryset)

    def test_toggle_requires_post(self):
        feature = Feature.objects.create(idea=self.idea, text="a")

        self.assertEqual(self.client.get(reverse("ideas:feature-toggle", args=[feature.pk])).status_code, 405)


class FeatureIsolationTests(TestCase):
    def setUp(self):
        other = make_user("other")
        self.other_idea = make_idea(other, "private")
        self.other_feature = Feature.objects.create(idea=self.other_idea, text="secret")
        self.mine = make_idea(make_user("intruder"), "mine")
        self.client.force_login(self.mine.owner)

    def test_cannot_touch_other_users_features(self):
        pk = self.other_feature.pk
        for name in ("feature-toggle", "feature-delete"):
            self.assertEqual(self.client.post(reverse(f"ideas:{name}", args=[pk]), {"done": "true"}).status_code, 404)
        self.assertEqual(self.client.get(reverse("ideas:feature-copy", args=[pk])).status_code, 404)
        self.other_feature.refresh_from_db()
        self.assertFalse(self.other_feature.is_done)

    def test_cannot_add_feature_to_other_users_idea(self):
        response = self.client.post(reverse("ideas:feature-add", args=[self.other_idea.pk]), {"text": "x", "platform": ""})

        self.assertEqual(response.status_code, 404)

    def test_cannot_copy_into_other_users_idea(self):
        own_feature = Feature.objects.create(idea=self.mine, text="mine")

        self.client.post(reverse("ideas:feature-copy", args=[own_feature.pk]), {"ideas": [self.other_idea.pk]})

        self.assertEqual(self.other_idea.features.count(), 1)


class IdeaListFilterTests(TestCase):
    def setUp(self):
        self.user = make_user("owner")
        self.client.force_login(self.user)
        self.finished = make_idea(self.user, "finished one")
        Feature.objects.create(idea=self.finished, text="a", is_done=True)
        self.open = make_idea(self.user, "open one")
        Feature.objects.create(idea=self.open, text="a")

    def ideas_for(self, **params):
        return set(self.client.get(reverse("ideas:list"), params).context["ideas"])

    def test_finished_filter(self):
        self.assertEqual(self.ideas_for(durum="biten"), {self.finished})

    def test_in_progress_filter(self):
        self.assertEqual(self.ideas_for(durum="devam"), {self.open})

    def test_detail_url_shows_that_idea_next_to_the_list(self):
        response = self.client.get(reverse("ideas:detail", args=[self.open.pk]))

        self.assertEqual((response.context["selected"], response.context["view_mode"]), (self.open, "detail"))
        self.assertContains(response, 'data-view="detail"')
        self.assertContains(response, f'id="row-{self.finished.pk}"')  # the list is still there for desktop

    def test_home_defaults_to_the_first_idea_and_the_list_view(self):
        response = self.client.get(reverse("ideas:list"))

        self.assertEqual((response.context["selected"], response.context["view_mode"]), (self.open, "list"))
        self.assertContains(response, 'data-view="list"')


class IdeaPlatformAndProjectLinkTests(TestCase):
    def setUp(self):
        self.user = make_user("owner")
        self.client.force_login(self.user)

    def test_idea_form_saves_platforms_and_projects(self):
        project = Project.objects.create(owner=self.user, name="P")

        self.client.post(
            reverse("ideas:create"),
            {"title": "T", "body": "B", "platforms": ["pwa", "ios"], "projects": [project.pk]},
        )

        idea = Idea.objects.get()
        self.assertEqual(idea.platforms, ["pwa", "ios"])
        self.assertEqual(idea.platform_labels, ["PWA", "iOS"])
        self.assertEqual(list(idea.projects.all()), [project])

    def test_idea_form_rejects_unknown_platform(self):
        response = self.client.post(reverse("ideas:create"), {"title": "T", "body": "B", "platforms": ["palm-os"]})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(Idea.objects.count(), 0)

    def test_idea_form_cannot_link_other_users_project(self):
        foreign = Project.objects.create(owner=make_user("other"), name="Foreign")

        response = self.client.post(reverse("ideas:create"), {"title": "T", "body": "B", "projects": [foreign.pk]})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(Idea.objects.count(), 0)


class ProjectViewTests(TestCase):
    def setUp(self):
        self.user = make_user("owner")
        self.client.force_login(self.user)

    def test_create_project_linking_ideas(self):
        idea = make_idea(self.user)

        self.client.post(reverse("ideas:project-create"), {"name": "Mobile", "description": "d", "ideas": [idea.pk]})

        project = Project.objects.get()
        self.assertEqual((project.owner, project.name), (self.user, "Mobile"))
        self.assertEqual(list(project.ideas.all()), [idea])

    def test_update_changes_linked_ideas(self):
        project = Project.objects.create(owner=self.user, name="P")
        first, second = make_idea(self.user, "first"), make_idea(self.user, "second")
        project.ideas.set([first])

        self.client.post(reverse("ideas:project-update", args=[project.pk]), {"name": "P", "ideas": [second.pk]})

        self.assertEqual(list(project.ideas.all()), [second])

    def test_project_form_lists_only_own_ideas(self):
        make_idea(make_user("other"), "not mine")
        mine = make_idea(self.user, "mine")
        project = Project.objects.create(owner=self.user, name="P")

        response = self.client.get(reverse("ideas:project-update", args=[project.pk]))

        self.assertEqual(list(response.context["form"].fields["ideas"].queryset), [mine])

    def test_delete_project_keeps_ideas(self):
        project = Project.objects.create(owner=self.user, name="P")
        idea = make_idea(self.user)
        project.ideas.add(idea)

        self.client.post(reverse("ideas:project-delete", args=[project.pk]))

        self.assertFalse(Project.objects.exists())
        self.assertTrue(Idea.objects.filter(pk=idea.pk).exists())

    def test_detail_and_list_render(self):
        project = Project.objects.create(owner=self.user, name="Visible")
        idea = make_idea(self.user, "linked idea")
        project.ideas.add(idea)
        Feature.objects.create(idea=idea, text="a", is_done=True)

        self.assertContains(self.client.get(reverse("ideas:project-list")), "Visible")
        self.assertContains(self.client.get(reverse("ideas:project-detail", args=[project.pk])), "linked idea")

    def test_other_users_project_is_404(self):
        foreign = Project.objects.create(owner=make_user("other"), name="Foreign")

        for name in ("project-detail", "project-update", "project-delete"):
            self.assertEqual(self.client.get(reverse(f"ideas:{name}", args=[foreign.pk])).status_code, 404)


class LayoutTests(TestCase):
    def test_signed_in_pages_have_sidebar_tabbar_and_theme_switch(self):
        self.client.force_login(make_user("viewer"))

        response = self.client.get(reverse("ideas:list"))

        for expected in ('class="sidebar"', 'class="tabbar"', 'data-set="gray"', 'localStorage.getItem("idealar.theme")'):
            self.assertContains(response, expected)

    def test_login_page_has_the_theme_switch_but_no_navigation(self):
        response = self.client.get(reverse("accounts:login"))

        self.assertContains(response, 'data-set="dark"')
        self.assertNotContains(response, 'class="sidebar"')
        self.assertNotContains(response, 'class="tabbar"')

    def test_navigation_marks_the_current_section_and_shows_counts(self):
        user = make_user("viewer")
        self.client.force_login(user)
        make_idea(user, "one"), make_idea(user, "two")
        Project.objects.create(owner=user, name="P")

        projects_page = self.client.get(reverse("ideas:project-list"))

        self.assertEqual(projects_page.context["nav_section"], "projects")
        self.assertEqual((projects_page.context["nav_idea_count"], projects_page.context["nav_project_count"]), (2, 1))
        sections = {"ideas:list": "ideas", "ideas:chat": "chat", "accounts:settings": "settings"}
        for name, section in sections.items():
            self.assertEqual(self.client.get(reverse(name)).context["nav_section"], section, name)

    def test_settings_page_requires_login_and_offers_theme_and_logout(self):
        self.assertEqual(self.client.get(reverse("accounts:settings")).status_code, 302)
        self.client.force_login(make_user("viewer"))

        response = self.client.get(reverse("accounts:settings"))

        self.assertContains(response, 'data-set="light"')
        self.assertContains(response, "Çıkış yap")


class IdeaDetailAndListControlsTests(TestCase):
    def setUp(self):
        self.user = make_user("owner")
        self.client.force_login(self.user)

    def test_other_users_idea_detail_is_404(self):
        theirs = make_idea(make_user("other"), "private")

        self.assertEqual(self.client.get(reverse("ideas:detail", args=[theirs.pk])).status_code, 404)

    def test_detail_shows_spec_note_features_and_actions(self):
        idea = make_idea(self.user, "line one\nline two", title="My idea", platforms=["pwa", "ios"], ai_summary="A summary.", ai_tags=["health"])
        project = Project.objects.create(owner=self.user, name="Health apps")
        idea.projects.add(project)
        Feature.objects.create(idea=idea, text="Login", is_done=True)

        response = self.client.get(reverse("ideas:detail", args=[idea.pk]))

        for expected in ("My idea", "A summary.", "PWA", "iOS", "#health", "Health apps", "line two", "Login", "1 / 1", "Sohbet", "Düzenle"):
            self.assertContains(response, expected)

    def test_rows_show_title_summary_platform_project_and_progress(self):
        idea = make_idea(self.user, "body", title="Row idea", platforms=["android"], ai_summary="Short summary")
        idea.projects.add(Project.objects.create(owner=self.user, name="Mobile"))
        Feature.objects.create(idea=idea, text="a", is_done=True)
        Feature.objects.create(idea=idea, text="b")

        response = self.client.get(reverse("ideas:list"))

        for expected in ("Row idea", "Short summary", "Android", "Mobile", "1/2"):
            self.assertContains(response, expected)

    def test_counts_cover_all_ideas_regardless_of_the_current_filter(self):
        done = make_idea(self.user, "done")
        Feature.objects.create(idea=done, text="a", is_done=True)
        make_idea(self.user, "open")

        context = self.client.get(reverse("ideas:list"), {"durum": "biten"}).context

        self.assertEqual((context["count_all"], context["count_finished"], context["count_in_progress"]), (2, 1, 1))

    def test_project_filter_limits_the_list_without_breaking_progress(self):
        project = Project.objects.create(owner=self.user, name="P")
        inside = make_idea(self.user, "inside")
        inside.projects.add(project)
        Feature.objects.create(idea=inside, text="a", is_done=True)
        make_idea(self.user, "outside")

        response = self.client.get(reverse("ideas:list"), {"proje": project.pk})

        self.assertEqual([i.pk for i in response.context["ideas"]], [inside.pk])
        self.assertEqual(response.context["ideas"][0].progress.total, 1)

    def test_sorting_by_progress_and_by_age(self):
        slow = make_idea(self.user, "slow")
        Feature.objects.create(idea=slow, text="a")
        fast = make_idea(self.user, "fast")
        Feature.objects.create(idea=fast, text="a", is_done=True)
        none = make_idea(self.user, "none")

        def order(sort):
            return [i.pk for i in self.client.get(reverse("ideas:list"), {"sirala": sort}).context["ideas"]]

        self.assertEqual(order("ilerleme")[0], fast.pk)
        self.assertEqual(order("yeni"), [none.pk, fast.pk, slow.pk])
        self.assertEqual(order("eski"), [slow.pk, fast.pk, none.pk])
        self.assertEqual(order("nonsense"), order("yeni"))

    def test_list_links_keep_the_active_filters(self):
        idea = make_idea(self.user, "x")

        response = self.client.get(reverse("ideas:list"), {"q": "x", "durum": "devam"})

        self.assertContains(response, f'href="{reverse("ideas:detail", args=[idea.pk])}?q=x&amp;durum=devam"')

    def test_empty_home_invites_the_first_idea(self):
        response = self.client.get(reverse("ideas:list"))

        self.assertIsNone(response.context["selected"])
        self.assertContains(response, "Henüz fikir yok")


class FeatureEditTests(TestCase):
    def setUp(self):
        self.user = make_user("owner")
        self.client.force_login(self.user)
        self.feature = Feature.objects.create(idea=make_idea(self.user, "x"), text="Old name", platform="ios")

    def test_rename_returns_the_saved_text_and_keeps_the_platform(self):
        response = self.client.post(reverse("ideas:feature-edit", args=[self.feature.pk]), {"text": "  New name "})

        self.feature.refresh_from_db()
        self.assertEqual(response.json(), {"text": "New name"})
        self.assertEqual((self.feature.text, self.feature.platform), ("New name", "ios"))

    def test_empty_name_is_rejected_and_nothing_changes(self):
        response = self.client.post(reverse("ideas:feature-edit", args=[self.feature.pk]), {"text": "   "})

        self.feature.refresh_from_db()
        self.assertEqual((response.status_code, self.feature.text), (400, "Old name"))

    def test_other_users_cannot_rename_and_get_requests_are_refused(self):
        url = reverse("ideas:feature-edit", args=[self.feature.pk])
        self.assertEqual(self.client.get(url).status_code, 405)
        self.client.force_login(make_user("intruder"))

        self.assertEqual(self.client.post(url, {"text": "hacked"}).status_code, 404)


class IdeaDisplayPropertiesTests(SimpleTestCase):
    def test_list_summary_prefers_ai_summary_then_note_when_a_title_exists(self):
        self.assertEqual(Idea(title="T", body="first\nsecond", ai_summary="AI").list_summary, "AI")
        self.assertEqual(Idea(title="T", body="first\nsecond").list_summary, "first")
        self.assertEqual(Idea(body="only a body").list_summary, "")

    def test_has_note_is_false_when_the_title_already_says_it_all(self):
        self.assertFalse(Idea(body="short idea").has_note)
        self.assertTrue(Idea(title="T", body="details").has_note)
        self.assertTrue(Idea(body="first\nsecond").has_note)
