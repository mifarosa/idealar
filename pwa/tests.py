import json

from django.test import TestCase
from django.urls import reverse


class ManifestTests(TestCase):
    def test_manifest_is_valid_installable_json(self):
        response = self.client.get(reverse("pwa:manifest"))

        manifest = json.loads(response.content)
        self.assertEqual(response["Content-Type"], "application/manifest+json")
        self.assertEqual(manifest["display"], "standalone")
        sizes = {icon["sizes"] for icon in manifest["icons"]}
        self.assertTrue({"192x192", "512x512"} <= sizes)
        self.assertEqual(manifest["start_url"], reverse("ideas:list"))


class ServiceWorkerTests(TestCase):
    def test_service_worker_is_served_from_root_as_javascript_without_caching(self):
        response = self.client.get("/sw.js")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "text/javascript")
        self.assertEqual(response["Cache-Control"], "no-cache")

    def test_service_worker_precaches_offline_page(self):
        body = self.client.get("/sw.js").content.decode()

        self.assertIn(reverse("pwa:offline"), body)
        self.assertIn("/static/css/app.css", body)

    def test_offline_page_is_public(self):
        self.assertEqual(self.client.get(reverse("pwa:offline")).status_code, 200)
