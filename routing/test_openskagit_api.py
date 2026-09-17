from unittest.mock import Mock, patch

from django.test import SimpleTestCase, override_settings

from .services.openskagit_api import OpenSkagitUnavailable, parcel_context


class OpenSkagitApiClientTests(SimpleTestCase):
    @override_settings(OPENSKAGIT_API_URL="https://openskagit.test", OPENSKAGIT_API_TOKEN="secret")
    @patch("routing.services.openskagit_api.requests.get")
    def test_requests_scoped_context_with_bearer_token(self, get):
        response = Mock()
        response.json.return_value = {"parcels": {"P123": {"centroid": None, "current_cycle_sale": None}}}
        get.return_value = response
        payload = parcel_context(["P123", "P123"])
        self.assertIn("P123", payload["parcels"])
        get.assert_called_once()
        self.assertEqual(get.call_args.kwargs["headers"], {"Authorization": "Bearer secret"})

    @override_settings(OPENSKAGIT_API_URL="", OPENSKAGIT_API_TOKEN="")
    def test_missing_configuration_is_unavailable(self):
        with self.assertRaises(OpenSkagitUnavailable):
            parcel_context(["P123"])
