from pathlib import Path
import json
from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.contrib.auth import get_user_model
from django.test import Client, RequestFactory, SimpleTestCase, TestCase

from .models import PreinspectionWorkspace
from .services.importers import infer_street_side, normalize_row, read_upload
from .services.optimization import cluster_and_order
from .services.openskagit_api import OpenSkagitUnavailable
from .services.streetsmart import (
    StreetSmartConfigurationError,
    list_recordings,
    render_by_location,
    render_recording,
    safe_parcel_filename,
    save_jpg,
)


class StreetSmartServiceTests(SimpleTestCase):
    @patch("routing.views.parcel_context")
    def test_sales_cycle_returns_valid_priced_sales(self, context):
        context.return_value = {"cycle_start": "2026-05-01", "cycle_end": "2027-04-30", "parcels": {"P2492": {"current_cycle_sale": {"count": 2, "latest_sale_date": "2026-06-15", "latest_sale_price": 450000.0}}}}
        request = RequestFactory().get("/routing/sales-cycle/", [("parcel_id", "P2492"), ("parcel_id", "P2492")])
        request.user = SimpleNamespace(is_authenticated=True, is_active=True)

        from .views import sales_cycle

        response = sales_cycle(request)
        payload = json.loads(response.content)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload["parcels"]["P2492"], {"count": 2, "latest_sale_date": "2026-06-15", "latest_sale_price": 450000.0})
        context.assert_called_once_with(["P2492"])

    @patch("routing.views.parcel_context", side_effect=OpenSkagitUnavailable("database connection unavailable"))
    def test_sales_cycle_database_interface_failure_is_degraded_not_internal_error(self, context):
        request = RequestFactory().get("/routing/sales-cycle/", {"parcel_id": "P2492"})
        request.user = SimpleNamespace(is_authenticated=True, is_active=True)

        from .views import sales_cycle

        response = sales_cycle(request)
        self.assertEqual(response.status_code, 503)
        self.assertIn(b"database connection unavailable", response.content)

    @patch("routing.views._street_smart_coordinates", return_value=(1288931.1, 518163.8, "2926"))
    @patch("routing.views.get_streetsmart_config")
    def test_interactive_viewer_config_uses_basic_auth_without_client_id(self, get_config, coordinates):
        get_config.return_value = SimpleNamespace(
            api_configured=True,
            api_key="test-api-key",
            username="test-user",
            password="test-password",
        )
        request = RequestFactory().get("/routing/parcel/P123/streetsmart/")
        request.user = SimpleNamespace(is_authenticated=True, is_active=True)

        from .views import parcel_streetsmart

        response = parcel_streetsmart(request, "P123")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Cache-Control"], "no-store, private")
        viewer_config = json.loads(response.content)["viewer_config"]
        self.assertEqual(viewer_config, {
            "api_key": "test-api-key",
            "username": "test-user",
            "password": "test-password",
        })
        self.assertNotIn("client_id", viewer_config)

    @patch.dict("os.environ", {
        "CYCLOMEDIA_API_KEY": "key",
        "CYCLOMEDIA_USERNAME": "user",
        "CYCLOMEDIA_PASSWORD": "password",
    }, clear=False)
    @patch("routing.services.streetsmart.requests.request")
    def test_lists_recordings_and_parses_viewing_direction(self, request):
        request.return_value = Mock(
            ok=True,
            content=b'<imagedirection_list><imagedirection recording-id="ABC123" recording-date="2026-01-02" viewing-direction="145.5" /></imagedirection_list>',
        )
        recordings = list_recordings(1288931.1, 518163.8, include_historic=True)
        self.assertEqual(recordings[0]["recording_id"], "ABC123")
        self.assertEqual(recordings[0]["viewing_direction"], 145.5)
        self.assertIn("ListByLocation2D/2926/1288931.1/518163.8/", request.call_args.args[1])
        self.assertEqual(request.call_args.kwargs["params"]["apiKey"], "key")
        self.assertEqual(request.call_args.kwargs["params"]["IncludeHistoricRecordings"], "true")
        self.assertEqual(request.call_args.kwargs["auth"], ("user", "password"))

    @patch.dict("os.environ", {
        "CYCLOMEDIA_API_KEY": "key",
        "CYCLOMEDIA_USERNAME": "user",
        "CYCLOMEDIA_PASSWORD": "password",
    }, clear=False)
    @patch("routing.services.streetsmart.requests.request")
    def test_renders_jpg_with_requested_yaw(self, request):
        request.return_value = Mock(ok=True, content=b"\xff\xd8street-smart-jpg", headers={"Recording-Id": "ABC123"})
        rendered = render_recording("ABC123", yaw=180, pitch=-10, hfov=45, width=2048, height=1536, srs_name="EPSG:2926")
        self.assertEqual(rendered["content"], b"\xff\xd8street-smart-jpg")
        params = request.call_args.kwargs["params"]
        self.assertEqual(params["yaw"], 180.0)
        self.assertEqual(params["pitch"], -10.0)
        self.assertEqual(params["hfov"], 45.0)
        self.assertEqual(params["width"], 2048)
        self.assertEqual(params["height"], 1536)
        self.assertEqual(params["srsName"], "EPSG:2926")

    @patch.dict("os.environ", {
        "CYCLOMEDIA_API_KEY": "key",
        "CYCLOMEDIA_USERNAME": "user",
        "CYCLOMEDIA_PASSWORD": "password",
    }, clear=False)
    @patch("routing.services.streetsmart.requests.request")
    def test_renders_by_location_and_uses_alternate_view_index(self, request):
        request.return_value = Mock(
            ok=True,
            content=b"\xff\xd8street-smart-jpg",
            headers={"Recording-Id": "XYZ789", "Recording-Date": "2026-06-23", "Render-Yaw": "142.5"},
        )
        rendered = render_by_location(1288931.1, 518163.8, srs="2926", index=0)
        self.assertEqual(rendered["recording_id"], "XYZ789")
        self.assertEqual(rendered["yaw"], "142.5")
        self.assertIn("RenderByLocation2D/2926/1288931.1/518163.8/", request.call_args.args[1])
        self.assertEqual(request.call_args.kwargs["params"]["index"], 0)

    def test_streetsmart_requires_credentials(self):
        with patch.dict("os.environ", {}, clear=True):
            with self.assertRaises(StreetSmartConfigurationError):
                list_recordings(1, 2)

    def test_saves_one_sanitized_jpg_per_parcel(self):
        with self.subTest("filename"):
            self.assertEqual(safe_parcel_filename("p/123 test"), "P_123_TEST.jpg")
        with self.subTest("save"):
            with self.assertRaises(StreetSmartConfigurationError):
                save_jpg("P123", b"\xff\xd8jpg", "")


class ImporterTests(TestCase):
    def test_normalizes_state_plane_coordinates_to_wgs84(self):
        row = normalize_row({"PARCELID": "P1", "XCoordinate": "1288931.1465", "YCoordinate": "518163.804", "SitusStName": "ALPINE VIEW PLACE"})
        self.assertEqual(row["parcel_id"], "P1")
        self.assertAlmostEqual(row["longitude"], -122.280654, places=5)
        self.assertAlmostEqual(row["latitude"], 48.411445, places=5)
        self.assertEqual(row["validation_status"], "valid")

    def test_reads_the_provided_xlsx_without_openpyxl(self):
        path = Path(r"C:\Users\ian\Downloads\Export (13).xlsx")
        if not path.exists():
            self.skipTest("sample export is not present")
        upload = SimpleNamespace(name=path.name, read=path.read_bytes)
        headers, rows, file_type = read_upload(upload)
        self.assertEqual(file_type, "xlsx")
        self.assertEqual(len(headers), 70)
        self.assertEqual(len(rows), 310)

    def test_infers_common_odd_even_street_side(self):
        self.assertEqual(infer_street_side("1612"), "even")
        self.assertEqual(infer_street_side("1630 ALPINE VIEW DRIVE"), "even")
        self.assertEqual(infer_street_side("1613"), "odd")


class OptimizationTests(TestCase):
    def test_clusters_are_capacity_bounded(self):
        items = [{"id": i, "parcel_id": str(i), "longitude": -122.35 + (i % 30) * .001, "latitude": 48.42 + (i // 30) * .001, "street_name": "MAIN"} for i in range(291)]
        groups = cluster_and_order(items, target=60)
        self.assertEqual(sum(map(len, groups)), 291)
        self.assertEqual([len(group) for group in groups], [59, 58, 58, 58, 58])
        self.assertTrue(all(50 <= len(group) <= 75 for group in groups))


class PreinspectionWorkspaceTests(TestCase):
    def test_streetsmart_review_uses_server_side_endpoints_and_keeps_assessor_image(self):
        template = (Path(__file__).parent / "templates" / "routing" / "preinspection_workspace.html").read_text(encoding="utf-8")
        self.assertIn("function openStreetSmartCompare(pid)", template)
        self.assertIn("/streetsmart/", template)
        self.assertIn("/streetsmart/save/", template)
        self.assertIn("skagitPhotoImageUrl(pid)", template)
        self.assertIn("Save StreetSmart JPG", template)
        self.assertIn('data-streetsmart-view="zoom-in"', template)
        self.assertIn("loadStreetSmartSdk()", template)
        self.assertIn(".streetsmart-placeholder[hidden]{display:none!important}", template)
        self.assertIn("function openGoogleSearchPreview(address,pid)", template)
        self.assertIn('return "https://www.google.com/search?q="', template)
        self.assertIn('window.open(googleSearchUrl(address||"Skagit County, WA"),"_blank","noopener,noreferrer");', template)
        self.assertNotIn('https://www.google.com/search?igu=1&q=', template)
        self.assertIn("clearTimeout(workspaceSaveTimer);\n  saveWorkspaceNow();", template)
        self.assertIn('data-google-search-pid="${escapeAttr(pid)}"', template)
        self.assertIn('height:100%;min-height:0;', template)
        self.assertIn('#map{height:100%;min-height:0;background:#dde5ea}', template)
        self.assertNotIn("showSaveFilePicker", template)
        self.assertIn("link.download=`${pid}.jpg`", template)
        self.assertIn("const streetSmartScriptPromises=new Map()", template)
        self.assertIn("for(const src of scripts)await loadStreetSmartScript(src)", template)
        self.assertNotIn("warmStreetSmartSdkWhenIdle()", template)
        self.assertIn("ensureStreetSmartSession", template)
        self.assertIn("streetSmartRecordingCache", template)
        self.assertIn("STREETSMART_SESSION_IDLE_TTL", template)
        self.assertIn("timings.session_reused", template)
        self.assertIn("const [payload,api]=await Promise.all([configPromise,sdkPromise])", template)
        self.assertIn('[StreetSmart load timing]', template)
        self.assertIn("loginOauth:false", template)
        self.assertIn("api.open({coordinate:[Number(payload.x),Number(payload.y)]}", template)
        self.assertIn("viewer.lookAtCoordinate?.([Number(payload.x),Number(payload.y)]", template)
        self.assertIn("viewer?.getOrientation?.()", template)
        self.assertIn("viewer?.getRecording?.()", template)
        self.assertIn("Saving high-resolution JPG", template)
        self.assertIn('data-streetsmart-step="-1"', template)
        self.assertIn('data-streetsmart-step="1"', template)
        self.assertIn("movePanoramaWithArrowKeys", template)
        self.assertIn('new KeyboardEvent("keydown"', template)
        self.assertIn("activateViewerForCaptureNavigation()", template)
        self.assertIn('new MouseEvent("mouseover"', template)
        self.assertIn("document.dispatchEvent(event)", template)
        self.assertNotIn("viewer.rotateLeft(15)", template)
        self.assertNotIn("viewer.rotateRight(15)", template)
        self.assertIn('data-streetsmart-view="zoom-in"', template)
        self.assertIn('data-streetsmart-view="zoom-out"', template)
        self.assertNotIn("streetsmartStepCount", template)
        self.assertNotIn("streetsmartAimIndex", template)

    def test_sales_checker_runs_daily_for_assignment_and_flags_routes(self):
        template = (Path(__file__).parent / "templates" / "routing" / "preinspection_workspace.html").read_text(encoding="utf-8")
        self.assertIn('const SALES_CHECK_CACHE_KEY=', template)
        self.assertIn('function salesAssignmentFingerprint(ids)', template)
        self.assertIn('lastAttemptDate', template)
        self.assertIn('refreshRecentSales();', template)
        self.assertIn('salesForParcel(pid)', template)
        self.assertIn('recent-sale-route-badge', template)
        self.assertIn('retry tomorrow', template)
        self.assertNotIn('sales-cycle lookup paused', template)

    def test_aerial_notes_are_saved_on_input_and_before_modal_close(self):
        template = (Path(__file__).parent / "templates" / "routing" / "preinspection_workspace.html").read_text(encoding="utf-8")
        self.assertIn("function saveInspectionNotes(pid,value)", template)
        self.assertIn('if(notesInput) saveInspectionNotes(pid,notesInput.value);', template)
        self.assertIn('["input","change","blur"]', template)

    def test_sketch_button_uses_a_leaflet_map_not_the_click_event(self):
        template = (Path(__file__).parent / "templates" / "routing" / "preinspection_workspace.html").read_text(encoding="utf-8")
        self.assertIn("let activeSketchMap=current;", template)
        self.assertIn("if(!(targetMap instanceof L.Map)) targetMap=activeSketchMap || current;", template)
        self.assertIn('sketchButton.addEventListener("click",()=>toggleSketch(activeSketchMap || current));', template)
        self.assertIn('id="imagerySketchRail"', template)
        self.assertIn('id="sketchRotation"', template)
        self.assertIn('data-sketch-action="scale-up"', template)
        self.assertIn('sketchRotation=Math.max(-180,sketchRotation-15)', template)
        self.assertNotIn('sketchButton.addEventListener("click",toggleSketch);', template)

    def test_preinspection_tracks_and_advances_active_parcel(self):
        template = (Path(__file__).parent / "templates" / "routing" / "preinspection_workspace.html").read_text(encoding="utf-8")
        self.assertIn('if(!Object.prototype.hasOwnProperty.call(state,"activeParcel")) state.activeParcel="";', template)
        self.assertIn("function advanceActiveParcelFrom(pid)", template)
        self.assertIn('if(shouldAdvance) advanceActiveParcelFrom(pid);', template)
        self.assertIn('tr.classList.add("active-parcel");', template)
        self.assertIn('row.scrollIntoView({behavior:"smooth",block:"center"});', template)
        self.assertIn(".preinspection-table tbody tr.complete:not(.active-parcel){opacity:.45}", template)

    def test_preinspection_supports_persisted_list_and_card_views(self):
        template = (Path(__file__).parent / "templates" / "routing" / "preinspection_workspace.html").read_text(encoding="utf-8")
        self.assertIn('data-pre-view-mode="list"', template)
        self.assertIn('data-pre-view-mode="cards"', template)
        self.assertIn("const PREINSPECTION_VIEW_MODE_KEY", template)
        self.assertIn("function loadPreinspectionViewMode()", template)
        self.assertIn('localStorage.setItem(PREINSPECTION_VIEW_MODE_KEY,preinspectionViewMode)', template)
        self.assertIn('table.classList.toggle("cards-mode",preinspectionViewMode==="cards")', template)
        self.assertIn('class="preinspection-card"', template)
        for attribute in ('data-photo', 'data-compare', 'data-google-search', 'data-change', 'data-unassign', 'data-copy-address'):
            self.assertIn(attribute, template)
        self.assertIn('class="empty-row"', template)

    def test_field_routes_keep_appraisal_routes_and_support_ordered_copy(self):
        template = (Path(__file__).parent / "templates" / "routing" / "preinspection_workspace.html").read_text(encoding="utf-8")
        self.assertIn('data-view="fieldRoutes"', template)
        self.assertIn('state.fieldRoutes={};', template)
        self.assertIn('function addYesParcelToFieldRoute(pid)', template)
        self.assertIn('if(next==="yes") addYesParcelToFieldRoute(pid);', template)
        self.assertIn('function moveFieldParcel(pid,targetRoute,insertIndex=null)', template)
        self.assertIn('const text=values.join("\\n");', template)
        self.assertIn('String(pid).replace(/^P/i,"")', template)
        self.assertIn('id="fieldRouteMap"', template)
        self.assertIn('data-field-pid', template)
        self.assertIn('data-field-route-drop', template)
        self.assertIn('const targetRoute=stop?.dataset.fieldRoute || drop?.dataset.fieldRouteDrop;', template)

    def test_field_route_map_renders_only_selected_route_and_legacy_yes_parcels_seed(self):
        template = (Path(__file__).parent / "templates" / "routing" / "preinspection_workspace.html").read_text(encoding="utf-8")
        self.assertIn('const route=state.fieldRoutes[routeName];', template)
        self.assertIn('(route?.parcels||[]).forEach((pid,index)=>', template)
        self.assertIn('state.parcelGeoJSON?.features||[]', template)
        self.assertIn('addRoutingBasemap(fieldRouteMap)', template)
        self.assertIn('const legacyYes=state.assignment.map(a=>a.PARCELID).filter(pid=>inspection(pid).changes==="yes");', template)
        self.assertIn('state.fieldRoutes[legacyRoute].parcels=[...new Set(legacyYes)];', template)

    def test_cama_print_sheets_preserve_route_orders_and_include_notes_and_field_flags(self):
        template = (Path(__file__).parent / "templates" / "routing" / "preinspection_workspace.html").read_text(encoding="utf-8")
        self.assertIn('id="printCamaRoute"', template)
        self.assertIn('id="printFieldRoute"', template)
        self.assertIn('rows=walkingOrderForRoute(route.parcels||[])', template)
        self.assertIn('rows=(route.parcels||[]).map(pid=>assignmentMap().get(pid)).filter(Boolean)', template)
        self.assertIn('inspectionData.changes==="yes"', template)
        self.assertIn('inspectionData.notes||""', template)

    def test_aerial_comparison_uses_fixed_2019_and_2025_tiles_without_fallback(self):
        template = (Path(__file__).parent / "templates" / "routing" / "preinspection_workspace.html").read_text(encoding="utf-8")
        self.assertIn('Current · 2025', template)
        self.assertIn('Historical · 2019', template)
        self.assertIn('const currentAerial=aerialLayer(`${pictometryBase}/PICT-WASKAG25-qSfR3O1lit/default/GoogleMapsCompatible/{z}/{x}/{y}.png`,"Pictometry/Cyclomedia · 2025",22).addTo(current);', template)
        self.assertIn('const historicalAerial=aerialLayer("https://geo.skagitcountywa.gov/server/rest/services/Images/SkagitCounty2019_9inch/ImageServer/tile/{z}/{y}/{x}","Skagit County GIS · 2019",21).addTo(historic);', template)
        self.assertNotIn('PICT-WASKAG19-MJtGoV8oof', template)
        self.assertNotIn('skagitImageLayer', template)
        self.assertNotIn('currentFallback', template)
        self.assertNotIn('historicFallback', template)
        self.assertNotIn('exportImage?', template)
        self.assertNotIn('tileerror', template)
        self.assertIn('current.invalidateSize(false);', template)
        self.assertIn('historic.invalidateSize(false);', template)
        self.assertNotIn('HISTORICAL_AERIAL_LAYERS', template)
        self.assertNotIn('id="imageryHistoricYear"', template)
        self.assertNotIn('setHistoricalLayer', template)
        self.assertIn('bbox:[bounds.getWest(),bounds.getSouth(),bounds.getEast(),bounds.getNorth()].join(",")', template)


class WorkspaceApiTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.alice = User.objects.create_user(username="alice", password="test-password")
        self.bob = User.objects.create_user(username="bob", password="test-password")
        self.admin = User.objects.create_superuser(username="admin", password="test-password", email="admin@example.com")
        self.state = {
            "version": 2,
            "year": 2026,
            "assignment": [{"PARCELID": "P123"}],
            "parcelGeoJSON": None,
            "routes": {},
            "inspections": {"P123": {"changes": "yes", "notes": "field visit"}},
            "fieldRoutes": {"Field Route 1": {"parcels": ["P123"]}},
            "fieldUnassigned": [],
            "activeParcel": "P123",
            "activeFieldRoute": "Field Route 1",
        }

    def test_authenticated_users_can_create_and_reload_private_workspaces(self):
        client = Client()
        self.assertEqual(client.get("/routing/").status_code, 302)
        self.assertTrue(client.login(username="alice", password="test-password"))
        self.assertEqual(client.get("/routing/").status_code, 200)
        created = client.post("/routing/api/workspaces/", data={"name": "Alice 2026", "state": self.state}, content_type="application/json")
        self.assertEqual(created.status_code, 201)
        workspace_id = created.json()["id"]
        loaded = client.get(f"/routing/api/workspaces/{workspace_id}/")
        self.assertEqual(loaded.status_code, 200)
        self.assertEqual(loaded.json()["state"]["fieldRoutes"]["Field Route 1"]["parcels"], ["P123"])

    def test_workspace_records_are_isolated_between_users(self):
        owner_client = Client()
        self.assertTrue(owner_client.login(username="alice", password="test-password"))
        created = owner_client.post("/routing/api/workspaces/", data={"name": "Private", "state": self.state}, content_type="application/json")
        workspace_id = created.json()["id"]

        other_client = Client()
        self.assertTrue(other_client.login(username="bob", password="test-password"))
        self.assertEqual(other_client.get("/routing/api/workspaces/").json()["workspaces"], [])
        self.assertEqual(other_client.get(f"/routing/api/workspaces/{workspace_id}/").status_code, 404)
        self.assertEqual(other_client.put(f"/routing/api/workspaces/{workspace_id}/state/", data={"revision": 1, "state": self.state}, content_type="application/json").status_code, 404)

    def test_revision_conflict_does_not_overwrite_newer_workspace_state(self):
        client = Client()
        self.assertTrue(client.login(username="alice", password="test-password"))
        created = client.post("/routing/api/workspaces/", data={"name": "Revision test", "state": self.state}, content_type="application/json").json()
        changed = {**self.state, "activeParcel": "P999"}
        first = client.put(f"/routing/api/workspaces/{created['id']}/state/", data={"revision": created["revision"], "state": changed}, content_type="application/json")
        self.assertEqual(first.status_code, 200)
        stale = client.put(f"/routing/api/workspaces/{created['id']}/state/", data={"revision": created["revision"], "state": self.state}, content_type="application/json")
        self.assertEqual(stale.status_code, 409)
        self.assertEqual(PreinspectionWorkspace.objects.get(pk=created["id"]).state["activeParcel"], "P999")

    def test_superuser_can_list_other_users_workspaces(self):
        owner_client = Client()
        self.assertTrue(owner_client.login(username="alice", password="test-password"))
        owner_client.post("/routing/api/workspaces/", data={"name": "Visible to admin", "state": self.state}, content_type="application/json")
        admin_client = Client()
        self.assertTrue(admin_client.login(username="admin", password="test-password"))
        payload = admin_client.get("/routing/api/workspaces/").json()
        self.assertEqual(len(payload["workspaces"]), 1)

    def test_staff_can_review_users_but_regular_users_cannot(self):
        staff = get_user_model().objects.create_user(username="staff", password="test-password", is_staff=True)
        staff_client = Client()
        self.assertTrue(staff_client.login(username="staff", password="test-password"))
        response = staff_client.get("/routing/admin/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "alice")
        self.assertNotContains(response, "Add user")

        user_client = Client()
        self.assertTrue(user_client.login(username="alice", password="test-password"))
        self.assertEqual(user_client.get("/routing/admin/").status_code, 302)

    def test_only_superusers_can_create_regular_users(self):
        staff = get_user_model().objects.create_user(username="staff", password="test-password", is_staff=True)
        staff_client = Client()
        self.assertTrue(staff_client.login(username="staff", password="test-password"))
        self.assertEqual(staff_client.get("/routing/admin/users/new/").status_code, 403)

        admin_client = Client()
        self.assertTrue(admin_client.login(username="admin", password="test-password"))
        response = admin_client.post(
            "/routing/admin/users/new/",
            data={
                "username": "new-worker",
                "email": "worker@example.com",
                "first_name": "New",
                "last_name": "Worker",
                "is_active": "on",
                "password": "new-worker-password",
            },
        )
        self.assertRedirects(response, "/routing/admin/")
        created = get_user_model().objects.get(username="new-worker")
        self.assertTrue(created.check_password("new-worker-password"))
        self.assertTrue(created.is_active)
        self.assertFalse(created.is_staff)
        self.assertFalse(created.is_superuser)

    def test_admin_user_detail_reports_read_only_workspace_progress(self):
        workspace = PreinspectionWorkspace.objects.create(
            owner=self.alice,
            created_by=self.alice,
            name="Alice progress",
            state={
                **self.state,
                "routes": {"Route 1": {"parcels": ["P123"]}},
            },
        )
        admin_client = Client()
        self.assertTrue(admin_client.login(username="admin", password="test-password"))
        response = admin_client.get(f"/routing/admin/users/{self.alice.id}/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Alice progress")
        self.assertContains(response, "Assignment parcels")
        self.assertContains(response, "100%")
        self.assertEqual(PreinspectionWorkspace.objects.get(pk=workspace.id).revision, 1)
