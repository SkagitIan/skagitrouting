from pathlib import Path

from django.test import SimpleTestCase


class RoutingParityTests(SimpleTestCase):
    def test_standalone_uses_routing_prefix_for_route_planner(self):
        javascript = (Path(__file__).parent.parent / "static" / "routing" / "routing.js").read_text(encoding="utf-8")
        template = (Path(__file__).parent / "templates" / "routing" / "routes.html").read_text(encoding="utf-8")
        self.assertIn("/routing/routes/", javascript)
        self.assertNotIn("/field/routes/", javascript)
        self.assertIn("Route planner", template)
