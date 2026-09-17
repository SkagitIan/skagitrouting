import io
import hashlib
import json
import re
import requests
from PIL import Image, ImageChops
from django.contrib.auth import get_user_model
from django.contrib.auth.views import redirect_to_login
from django.core.cache import cache
from django.db import transaction
from django.http import HttpResponse, HttpResponseForbidden, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_GET, require_http_methods

from .forms import AdminUserCreationForm
from .models import AuditEvent, PreinspectionWorkspace, RoutingImport, RoutingImportRow, RoutingPlan, RoutingPlanRevision, RoutingRoute, RoutingStop, RoutingUserSettings
from .services.exports import route_csv, single_route_csv
from .services.importers import infer_street_side, normalize_row, read_upload
from .services.optimization import cluster_and_order, distance
from .services.matrices import travel_matrix
from .services.streetsmart import (
    StreetSmartConfigurationError,
    StreetSmartError,
    StreetSmartNoRecordingError,
    get_config as get_streetsmart_config,
    list_recordings,
    render_by_location,
    render_recording,
    safe_parcel_filename,
)
from .services.valhalla import optimized_order
from .services.audit import record_event, record_workspace_revision
from .services.openskagit_api import OpenSkagitUnavailable, parcel_context


def _staff(request):
    return bool(request.user.is_authenticated and request.user.is_active and request.user.is_staff)


def _staff_write(request):
    return _staff(request) and not request.user.groups.filter(name="Routing Auditors").exists()


def _workspace_user(request):
    return bool(request.user.is_authenticated and request.user.is_active)


def _forbidden(request):
    return redirect_to_login(request.get_full_path(), "/login/")


@require_GET
def routes_page(request):
    if not _staff(request):
        return _forbidden(request)
    return render(request, "routing/routes.html", {"imports": RoutingImport.objects.all()[:20], "plans": RoutingPlan.objects.select_related("import_file")[:30]})


@require_GET
@ensure_csrf_cookie
def workspace_page(request):
    if not _workspace_user(request):
        return _forbidden(request)
    return render(request, "routing/preinspection_workspace.html")


def oversight_page(request):
    if not _staff(request):
        return _forbidden(request)
    workspaces = []
    for workspace in PreinspectionWorkspace.objects.select_related("owner").all():
        summary = _workspace_summary(workspace)
        summary["owner"] = workspace.owner.get_username()
        workspaces.append(summary)
    return render(request, "routing/oversight.html", {"workspaces": workspaces})


def oversight_workspace(request, workspace_id):
    if not _staff(request):
        return _forbidden(request)
    workspace = get_object_or_404(PreinspectionWorkspace.objects.select_related("owner"), pk=workspace_id)
    revisions = workspace.revisions.select_related("actor")[:100]
    events = AuditEvent.objects.filter(object_type="PreinspectionWorkspace", object_id=str(workspace.id)).select_related("actor")[:100]
    return render(request, "routing/oversight_workspace.html", {"workspace": workspace, "revisions": revisions, "events": events, "summary": _workspace_summary(workspace)})


def _user_progress(user):
    workspaces = [_workspace_summary(workspace) for workspace in user.preinspection_workspaces.all()]
    assignment_count = sum(item["assignment_count"] for item in workspaces)
    assigned_count = sum(item["assigned_count"] for item in workspaces)
    complete_count = sum(item["complete_count"] for item in workspaces)
    return {
        "workspaces": workspaces,
        "workspace_count": len(workspaces),
        "assignment_count": assignment_count,
        "assigned_count": assigned_count,
        "unassigned_count": assignment_count - assigned_count,
        "complete_count": complete_count,
    }


def admin_dashboard(request):
    if not _staff(request):
        return _forbidden(request)
    users = []
    for account in get_user_model().objects.prefetch_related("preinspection_workspaces").order_by("username"):
        users.append({"account": account, "progress": _user_progress(account)})
    return render(request, "routing/admin_dashboard.html", {"users": users})


def admin_user_detail(request, user_id):
    if not _staff(request):
        return _forbidden(request)
    account = get_object_or_404(get_user_model(), pk=user_id)
    return render(request, "routing/admin_user_detail.html", {"account": account, "progress": _user_progress(account)})


@require_http_methods(["GET", "POST"])
def admin_user_create(request):
    if not _staff(request):
        return _forbidden(request)
    if not request.user.is_superuser:
        return HttpResponseForbidden("Only superusers can create users.")
    form = AdminUserCreationForm(request.POST or None)
    if form.is_valid():
        form.save()
        return redirect("routing:admin_dashboard")
    return render(request, "routing/admin_user_form.html", {"form": form})


DEFAULT_WORKSPACE_STATE = {
    "version": 2,
    "year": 2026,
    "assignment": [],
    "parcelGeoJSON": None,
    "routes": {},
    "inspections": {},
    "fieldRoutes": {},
    "fieldUnassigned": [],
    "activeParcel": "",
    "activeFieldRoute": "",
}
MAX_WORKSPACE_STATE_BYTES = 15 * 1024 * 1024


def _workspace_queryset(request):
    if request.user.is_superuser:
        return PreinspectionWorkspace.objects.all()
    return PreinspectionWorkspace.objects.filter(owner=request.user)


def _workspace_summary(workspace):
    state = workspace.state or {}
    assignment = state.get("assignment") or []
    assignment_ids = {str(row.get("PARCELID", "")).strip() for row in assignment if isinstance(row, dict) and str(row.get("PARCELID", "")).strip()}
    assigned_ids = {
        str(parcel_id).strip()
        for route in (state.get("routes") or {}).values()
        if isinstance(route, dict)
        for parcel_id in (route.get("parcels") or [])
        if str(parcel_id).strip() in assignment_ids
    }
    inspections = state.get("inspections") or {}
    complete = sum(
        1
        for row in assignment
        if isinstance(row, dict)
        and (inspections.get(str(row.get("PARCELID", ""))) or {}).get("changes") in {"yes", "no"}
    )
    return {
        "id": workspace.id,
        "name": workspace.name,
        "year": workspace.year,
        "revision": workspace.revision,
        "assignment_count": len(assignment),
        "assigned_count": len(assigned_ids),
        "unassigned_count": max(0, len(assignment_ids) - len(assigned_ids)),
        "created_at": workspace.created_at.isoformat(),
        "updated_at": workspace.updated_at.isoformat(),
        "last_opened_at": workspace.last_opened_at.isoformat() if workspace.last_opened_at else None,
        "parcel_count": len(assignment),
        "complete_count": complete,
        "completion_percent": round((complete / len(assignment)) * 100) if assignment else 0,
    }


def _workspace_payload(workspace, include_state=False):
    payload = _workspace_summary(workspace)
    if include_state:
        payload["state"] = workspace.state or dict(DEFAULT_WORKSPACE_STATE)
    return payload


def _json_body(request):
    try:
        return json.loads(request.body or "{}")
    except (TypeError, json.JSONDecodeError):
        return None


def _valid_workspace_state(value):
    if not isinstance(value, dict):
        return None
    state = dict(DEFAULT_WORKSPACE_STATE)
    state.update(value)
    state["version"] = 2
    if not isinstance(state.get("assignment"), list) or not isinstance(state.get("routes"), dict) or not isinstance(state.get("inspections"), dict):
        return None
    if not isinstance(state.get("fieldRoutes"), dict) or not isinstance(state.get("fieldUnassigned"), list):
        return None
    return state


@require_http_methods(["GET", "POST"])
def workspace_collection(request):
    if not _workspace_user(request):
        return JsonResponse({"error": "Sign-in is required."}, status=401)
    if request.method == "GET":
        return JsonResponse({"workspaces": [_workspace_summary(workspace) for workspace in _workspace_queryset(request)]})

    body = _json_body(request)
    if body is None:
        return JsonResponse({"error": "Request body must be valid JSON."}, status=400)
    state = _valid_workspace_state(body.get("state") or dict(DEFAULT_WORKSPACE_STATE))
    if state is None:
        return JsonResponse({"error": "Workspace state has an invalid shape."}, status=400)
    encoded = json.dumps(state, separators=(",", ":"))
    if len(encoded.encode("utf-8")) > MAX_WORKSPACE_STATE_BYTES:
        return JsonResponse({"error": "Workspace data is too large to save."}, status=413)
    name = str(body.get("name") or "Untitled workspace").strip()[:160] or "Untitled workspace"
    year = body.get("year", state.get("year", 2026))
    try:
        year = max(2000, min(2100, int(year)))
    except (TypeError, ValueError):
        return JsonResponse({"error": "Year must be a valid number."}, status=400)
    workspace = PreinspectionWorkspace.objects.create(owner=request.user, created_by=request.user, name=name, year=year, state=state)
    record_workspace_revision(workspace, request.user, "created")
    record_event(request.user, "workspace_created", workspace, {"name": workspace.name})
    return JsonResponse(_workspace_payload(workspace, include_state=True), status=201)


@require_http_methods(["GET", "PATCH"])
def workspace_detail(request, workspace_id):
    if not _workspace_user(request):
        return JsonResponse({"error": "Sign-in is required."}, status=401)
    workspace = get_object_or_404(_workspace_queryset(request), pk=workspace_id)
    if request.method == "PATCH":
        body = _json_body(request)
        if body is None:
            return JsonResponse({"error": "Request body must be valid JSON."}, status=400)
        name = str(body.get("name") or "").strip()[:160]
        if not name:
            return JsonResponse({"error": "Workspace name cannot be empty."}, status=400)
        workspace.name = name
        workspace.save(update_fields=["name", "updated_at"])
        return JsonResponse(_workspace_payload(workspace))
    workspace.last_opened_at = timezone.now()
    workspace.save(update_fields=["last_opened_at"])
    return JsonResponse(_workspace_payload(workspace, include_state=True))


@require_http_methods(["PUT", "PATCH", "DELETE"])
def workspace_state(request, workspace_id):
    if not _workspace_user(request):
        return JsonResponse({"error": "Sign-in is required."}, status=401)
    workspace = get_object_or_404(_workspace_queryset(request), pk=workspace_id)
    if request.method == "DELETE":
        workspace.delete()
        return JsonResponse({"deleted": True})

    body = _json_body(request)
    if body is None:
        return JsonResponse({"error": "Request body must be valid JSON."}, status=400)
    state = _valid_workspace_state(body.get("state"))
    if state is None:
        return JsonResponse({"error": "Workspace state has an invalid shape."}, status=400)
    encoded = json.dumps(state, separators=(",", ":"))
    if len(encoded.encode("utf-8")) > MAX_WORKSPACE_STATE_BYTES:
        return JsonResponse({"error": "Workspace data is too large to save."}, status=413)
    try:
        expected_revision = int(body.get("revision"))
    except (TypeError, ValueError):
        return JsonResponse({"error": "A workspace revision is required."}, status=400)
    with transaction.atomic():
        locked = _workspace_queryset(request).select_for_update().get(pk=workspace.id)
        if locked.revision != expected_revision:
            return JsonResponse({"error": "This workspace changed in another tab or session.", "revision": locked.revision}, status=409)
        locked.state = state
        locked.year = int(state.get("year") or locked.year)
        locked.revision += 1
        locked.save(update_fields=["state", "year", "revision", "updated_at"])
        record_workspace_revision(locked, request.user, "state_updated")
        record_event(request.user, "workspace_state_updated", locked, {"revision": locked.revision})
        workspace = locked
    return JsonResponse(_workspace_payload(workspace))


@require_http_methods(["GET", "PATCH"])
def routing_user_settings(request):
    if not _workspace_user(request):
        return JsonResponse({"error": "Sign-in is required."}, status=401)
    settings_obj, _ = RoutingUserSettings.objects.get_or_create(owner=request.user)
    if request.method == "GET":
        return JsonResponse({"streetsmart_image_root": settings_obj.streetsmart_image_root})
    body = _json_body(request)
    if body is None:
        return JsonResponse({"error": "Request body must be valid JSON."}, status=400)
    image_root = str(body.get("streetsmart_image_root") or "").strip()
    if len(image_root) > 1024:
        return JsonResponse({"error": "The StreetSmart save directory is too long."}, status=400)
    settings_obj.streetsmart_image_root = image_root
    settings_obj.save(update_fields=["streetsmart_image_root", "updated_at"])
    return JsonResponse({"saved": True, "streetsmart_image_root": image_root})


# The current assessment cycle is May 1, 2026 through April 30, 2027.
# Keep the end bound exclusive so ISO date and timestamp values are both handled.
SALES_CYCLE_START = "2026-05-01"
SALES_CYCLE_END_EXCLUSIVE = "2027-05-01"
SALES_CYCLE_END_LABEL = "2027-04-30"


@require_GET
def sales_cycle(request):
    """Return current-cycle sale flags for the parcels shown in the workspace."""
    if not _workspace_user(request):
        return JsonResponse({"error": "Sign-in is required."}, status=403)

    parcel_ids = []
    for value in request.GET.getlist("parcel_id"):
        normalized = str(value or "").strip()
        if normalized and normalized not in parcel_ids:
            parcel_ids.append(normalized)
    if len(parcel_ids) > 2000:
        return JsonResponse({"error": "Too many parcels in one lookup."}, status=400)

    try:
        payload = parcel_context(parcel_ids)
    except ValueError as exc:
        return JsonResponse({"error": str(exc)}, status=400)
    except OpenSkagitUnavailable as exc:
        return JsonResponse({"error": str(exc)}, status=503)
    return JsonResponse({"cycle_start": payload.get("cycle_start") or SALES_CYCLE_START, "cycle_end": payload.get("cycle_end") or SALES_CYCLE_END_LABEL, "parcels": {key: value.get("current_cycle_sale") or {} for key, value in payload.get("parcels", {}).items()}})


def _assessor_sketch_url(parcel_id):
    normalized = str(parcel_id or "").strip().upper()
    if not normalized:
        return normalized, None, None
    response = requests.post(
        "https://www.skagitcounty.net/search/property/Webservice.asmx/fillPage",
        headers={
            "Content-Type": "application/json; charset=UTF-8",
            "X-Requested-With": "XMLHttpRequest",
            "Referer": "https://www.skagitcounty.net/search/property/",
        },
        json={"sValue": normalized, "ResultType": "Improvements"},
        timeout=20,
    )
    response.raise_for_status()
    payload = response.json()
    markup = str(payload.get("d") or "") if isinstance(payload, dict) else ""
    match = re.search(r'href=["\'](?P<path>/assessor/images/photos/[^"\']+\.(?:jpg|jpeg|png))["\']', markup, re.IGNORECASE)
    return normalized, ("https://www.skagitcounty.net" + match.group("path") if match else None), response


def _trim_sketch(image_bytes):
    image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    background = Image.new("RGB", image.size, "white")
    difference = ImageChops.difference(image, background).convert("L")
    # Ignore near-white anti-aliasing/noise, then retain a small visual margin.
    bbox = difference.point(lambda value: 255 if value > 28 else 0).getbbox()
    if bbox:
        left, top, right, bottom = bbox
        pad = max(12, int(min(image.size) * 0.025))
        bbox = (max(0, left - pad), max(0, top - pad), min(image.width, right + pad), min(image.height, bottom + pad))
        image = image.crop(bbox)
    output = io.BytesIO()
    image.save(output, format="JPEG", quality=94, optimize=True)
    return output.getvalue()


@require_GET
def parcel_sketch(request, parcel_id):
    if not _workspace_user(request):
        return JsonResponse({"error": "Sign-in is required."}, status=403)
    normalized = str(parcel_id or "").strip().upper()
    if not normalized:
        return JsonResponse({"error": "A parcel ID is required."}, status=400)
    try:
        normalized, source_url, _ = _assessor_sketch_url(normalized)
    except (requests.RequestException, ValueError) as exc:
        return JsonResponse({"error": "The assessor sketch service is unavailable.", "detail": str(exc)}, status=502)
    if not source_url:
        return JsonResponse({"found": False, "parcel_id": normalized})
    return JsonResponse({
        "found": True,
        "parcel_id": normalized,
        "url": source_url,
        "image_url": f"/routing/parcel/{normalized}/sketch/image/",
    })


@require_GET
def parcel_sketch_image(request, parcel_id):
    if not _workspace_user(request):
        return JsonResponse({"error": "Sign-in is required."}, status=403)
    try:
        normalized, source_url, _ = _assessor_sketch_url(parcel_id)
        if not source_url:
            return JsonResponse({"error": "No assessor sketch found."}, status=404)
        response = requests.get(source_url, timeout=20)
        response.raise_for_status()
        content = _trim_sketch(response.content)
    except (requests.RequestException, ValueError, OSError) as exc:
        return JsonResponse({"error": "The assessor sketch image is unavailable.", "detail": str(exc)}, status=502)
    return HttpResponse(content, content_type="image/jpeg", headers={"Cache-Control": "private, max-age=3600"})


def _street_smart_coordinates(request, parcel_id, payload=None):
    payload = payload or {}
    raw_x = payload.get("x") if payload.get("x") not in (None, "") else request.GET.get("x")
    raw_y = payload.get("y") if payload.get("y") not in (None, "") else request.GET.get("y")
    if raw_x not in (None, "") and raw_y not in (None, ""):
        try:
            return float(raw_x), float(raw_y), "2926"
        except (TypeError, ValueError) as exc:
            raise StreetSmartError("The parcel coordinates are not valid for StreetSmart lookup.") from exc
    try:
        payload = parcel_context([parcel_id])
        centroid = (payload.get("parcels", {}).get(str(parcel_id).strip(), {}) or {}).get("centroid") or {}
        row = (centroid.get("x_2926"), centroid.get("y_2926"))
    except (OpenSkagitUnavailable, ValueError) as exc:
        raise StreetSmartError("The parcel location could not be looked up for StreetSmart.") from exc
    if not row or row[0] is None or row[1] is None:
        raise StreetSmartError("This parcel has no coordinates available for StreetSmart lookup.")
    return float(row[0]), float(row[1]), "2926"


def _street_smart_srs(value):
    value = str(value or "2926").strip()
    if not re.fullmatch(r"\d{4,6}", value):
        raise StreetSmartError("The StreetSmart spatial reference is not valid.")
    return value


def _street_smart_render_options(values, high_resolution=False):
    values = values or {}

    def number(name, default):
        raw = values.get(name, default)
        return float(default) if raw in (None, "") else float(raw)

    yaw = number("yaw", 0)
    pitch = max(-90, min(90, number("pitch", 0)))
    hfov = max(10, min(170, number("hfov", 90)))
    if high_resolution:
        width, height = 4096, 3072
    else:
        width = max(640, min(8192, int(number("width", 1600))))
        height = max(480, min(8192, int(number("height", 1200))))
    return {"yaw": yaw, "pitch": pitch, "hfov": hfov, "width": width, "height": height}


def _street_smart_cache_key(kind, values):
    serialized = json.dumps(values, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    digest = hashlib.sha256(serialized).hexdigest()
    return f"streetsmart:{kind}:{digest}"


def _street_smart_image_headers(rendered, cache_status):
    headers = {"Cache-Control": "private, max-age=1800", "X-StreetSmart-Cache": cache_status}
    if not isinstance(rendered, dict):
        return headers
    if rendered.get("recording_id"):
        headers["X-StreetSmart-Recording-Id"] = rendered["recording_id"]
    if rendered.get("recording_date"):
        headers["X-StreetSmart-Recording-Date"] = rendered["recording_date"]
    for field in ("yaw", "pitch", "hfov"):
        if rendered.get(field) is not None:
            headers[f"X-StreetSmart-{field.title()}"] = str(rendered[field])
    return headers


def _street_smart_error_response(exc):
    if isinstance(exc, StreetSmartConfigurationError):
        return JsonResponse({"available": False, "configured": False, "error": str(exc)}, status=503)
    if isinstance(exc, StreetSmartNoRecordingError):
        return JsonResponse({"available": False, "configured": True, "error": str(exc)}, status=200)
    return JsonResponse({"available": False, "configured": True, "error": str(exc)}, status=502)


@require_GET
def parcel_streetsmart(request, parcel_id):
    if not _workspace_user(request):
        return JsonResponse({"error": "Sign-in is required."}, status=403)
    try:
        x, y, srs = _street_smart_coordinates(request, parcel_id)
        config = get_streetsmart_config()
        if not config.api_configured:
            raise StreetSmartConfigurationError(
                "StreetSmart is not configured. Add the Cyclomedia API key and Basic-auth credentials to the local environment."
            )
        # The official Street Smart JavaScript SDK performs Basic authentication in
        # the browser. Return these values only on-demand to an authenticated user;
        # never render them into the static page or log this response.
        response = JsonResponse(
            {
                "available": True,
                "configured": True,
                "parcel_id": str(parcel_id).strip().upper(),
                "x": x,
                "y": y,
                "srs": srs,
                "viewer_config": {
                    "api_key": config.api_key,
                    "username": config.username,
                    "password": config.password,
                },
            }
        )
        response["Cache-Control"] = "no-store, private"
        response["Pragma"] = "no-cache"
        return response
    except (StreetSmartConfigurationError, StreetSmartNoRecordingError, StreetSmartError) as exc:
        return _street_smart_error_response(exc)


@require_GET
def parcel_streetsmart_image(request, parcel_id):
    if not _workspace_user(request):
        return JsonResponse({"error": "Sign-in is required."}, status=403)
    recording_id = request.GET.get("recording_id", "").strip()
    try:
        render_options = _street_smart_render_options(request.GET)
        view_mode = request.GET.get("mode", "recording").strip().lower()
        if view_mode == "location":
            x, y, srs = _street_smart_coordinates(request, parcel_id)
            index = request.GET.get("index", "1")
            cache_values = {
                "mode": view_mode,
                "x": x,
                "y": y,
                "index": index,
                "srs": srs,
                "width": render_options["width"],
                "height": render_options["height"],
                "hfov": render_options["hfov"],
            }
        elif view_mode == "recording":
            if not recording_id:
                return JsonResponse({"error": "A StreetSmart recording is required."}, status=400)
            cache_values = {
                "mode": view_mode,
                "recording_id": recording_id,
                "srs": _street_smart_srs(request.GET.get("srs", "2926")),
                **render_options,
            }
        else:
            return JsonResponse({"error": "The StreetSmart render mode is not valid."}, status=400)
        image_cache_key = _street_smart_cache_key("preview", cache_values)
        cached_render = cache.get(image_cache_key)
        if cached_render is not None:
            if not isinstance(cached_render, dict):  # tolerate cache entries from pre-metadata releases
                cached_render = {"content": cached_render}
            return HttpResponse(
                cached_render["content"],
                content_type="image/jpeg",
                headers=_street_smart_image_headers(cached_render, "HIT"),
            )
        if view_mode == "location":
            rendered = render_by_location(
                x,
                y,
                srs=srs,
                index=index,
                width=render_options["width"],
                height=render_options["height"],
                hfov=render_options["hfov"],
            )
        else:
            rendered = render_recording(
                recording_id,
                srs_name=f"EPSG:{cache_values['srs']}",
                **render_options,
            )
        cache.set(image_cache_key, rendered, 1800)
        return HttpResponse(
            rendered["content"],
            content_type="image/jpeg",
            headers=_street_smart_image_headers(rendered, "MISS"),
        )
    except (TypeError, ValueError):
        return JsonResponse({"error": "The StreetSmart view direction is not valid."}, status=400)
    except (StreetSmartConfigurationError, StreetSmartError) as exc:
        return _street_smart_error_response(exc)


@require_http_methods(["POST"])
def save_streetsmart_image(request, parcel_id):
    if not _workspace_user(request):
        return JsonResponse({"error": "Sign-in is required."}, status=403)
    payload = _json_body(request) or {}
    recording_id = str(payload.get("recording_id") or "").strip()
    try:
        if not recording_id:
            x, y, srs = _street_smart_coordinates(request, parcel_id, payload)
            recording = list_recordings(x, y, srs=srs)[0]
            recording_id = recording["recording_id"]
            payload = {**payload, "yaw": recording["viewing_direction"] or 0}
        render_options = _street_smart_render_options(payload, high_resolution=True)
        rendered = render_recording(recording_id, srs_name=f"EPSG:{_street_smart_srs(payload.get('srs', '2926'))}", **render_options)
        filename = safe_parcel_filename(parcel_id)
        response = HttpResponse(rendered["content"], content_type="image/jpeg")
        response["Content-Disposition"] = f'attachment; filename="{filename}"'
        response["X-StreetSmart-Recording-ID"] = recording_id
        return response
    except (TypeError, ValueError):
        return JsonResponse({"error": "The StreetSmart view direction is not valid."}, status=400)
    except (StreetSmartConfigurationError, StreetSmartNoRecordingError, StreetSmartError) as exc:
        return _street_smart_error_response(exc)


@require_http_methods(["POST"])
def import_file(request):
    if not _staff_write(request):
        return JsonResponse({"error": "Staff sign-in is required."}, status=403)
    upload = request.FILES.get("file")
    if not upload:
        return JsonResponse({"error": "Choose a CSV or XLSX file."}, status=400)
    try:
        headers, source_rows, file_type = read_upload(upload)
        normalized = [normalize_row(row) for row in source_rows]
    except ValueError as exc:
        return JsonResponse({"error": str(exc)}, status=400)
    unique = {}
    for row in normalized:
        key = (row["parcel_id"], row["longitude"], row["latitude"])
        if row["parcel_id"] and row["longitude"] is not None and key not in unique:
            unique[key] = row
    summary = {
        "blank_rows": sum(not row["parcel_id"] and row["longitude"] is None for row in normalized),
        "duplicate_rows": max(0, sum(bool(row["parcel_id"]) for row in normalized) - len(unique)),
        "missing_coordinates": sum("missing_coordinates" in row["validation_notes"] for row in normalized),
        "addressless_rows": sum(not row["address"] for row in normalized),
    }
    import_file_obj = RoutingImport.objects.create(
        created_by=request.user, filename=upload.name, file_type=file_type, row_count=len(normalized),
        unique_stop_count=len(unique), original_headers=headers, summary=summary,
    )
    RoutingImportRow.objects.bulk_create([
        RoutingImportRow(
            import_file=import_file_obj, source_row_number=index, parcel_id=row["parcel_id"],
            address=row["address"], source_x=row["source_x"], source_y=row["source_y"],
            longitude=row["longitude"], latitude=row["latitude"],
            point_geometry={"type": "Point", "coordinates": [row["longitude"], row["latitude"]]} if row["longitude"] is not None else None,
            source_data=row["source_data"], validation_status=row["validation_status"],
            validation_notes=row["validation_notes"], dedupe_key="|".join(map(str, (row["parcel_id"], row["longitude"], row["latitude"]))),
        ) for index, row in enumerate(normalized, start=2)
    ])
    record_event(request.user, "routing_import_created", import_file_obj, {"filename": upload.name, "row_count": len(normalized)})
    return JsonResponse({"import_id": import_file_obj.id, "filename": upload.name, "row_count": len(normalized), "unique_stop_count": len(unique), "summary": summary})


def _plan_payload(plan):
    routes = []
    for route in plan.routes.prefetch_related("stops__import_row"):
        stops = [{"id": stop.id, "import_row_id": stop.import_row_id, "sequence": stop.sequence, "parcel_id": stop.parcel_id, "address": stop.import_row.address, "longitude": stop.longitude, "latitude": stop.latitude, "street_name": stop.street_name, "street_side": stop.street_side, "confidence": stop.coordinate_confidence} for stop in route.stops.all()]
        routes.append({"id": route.id, "route_number": route.route_number, "mode": route.mode, "stop_count": route.stop_count, "geometry": route.geometry, "stops": stops})
    latest_revision = plan.revisions.first()
    assigned_ids = [stop["id"] for route in routes for stop in route["stops"]]
    return {"plan_id": plan.id, "name": plan.name, "import_id": plan.import_file_id, "status": plan.status, "revision": latest_revision.revision_number if latest_revision else 0, "mode": plan.mode, "target_stop_count": plan.target_stop_count, "route_count": plan.route_count, "summary": plan.summary, "routes": routes, "assigned_stop_ids": assigned_ids}


def _record_revision(plan, action):
    next_number = (plan.revisions.order_by("-revision_number").values_list("revision_number", flat=True).first() or 0) + 1
    RoutingPlanRevision.objects.create(plan=plan, revision_number=next_number, action=action, snapshot=_plan_payload(plan))


@require_GET
def plans_list(request):
    if not _staff(request):
        return JsonResponse({"error": "Staff sign-in is required."}, status=403)
    return JsonResponse({"plans": [{"id": plan.id, "name": plan.name, "filename": plan.import_file.filename, "mode": plan.mode, "status": plan.status, "route_count": plan.route_count, "created_at": plan.created_at.isoformat()} for plan in RoutingPlan.objects.select_related("import_file")[:30]]})


@require_http_methods(["POST"])
def create_plan(request):
    if not _staff_write(request):
        return JsonResponse({"error": "Staff sign-in is required."}, status=403)
    try:
        body = json.loads(request.body or "{}")
        import_obj = get_object_or_404(RoutingImport, pk=int(body["import_id"]))
        mode = body.get("mode", "driving")
        target = max(50, min(75, int(body.get("target_stop_count", 60))))
        name = str(body.get("name") or "").strip()[:160]
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        return JsonResponse({"error": "A valid import_id and target_stop_count are required."}, status=400)
    raw_items = list(import_obj.rows.filter(validation_status="valid").values("id", "parcel_id", "address", "longitude", "latitude", "source_data"))
    items_by_key = {}
    for item in raw_items:
        items_by_key.setdefault((item["parcel_id"], item["longitude"], item["latitude"]), item)
    items = list(items_by_key.values())
    for item in items:
        source = item.get("source_data") or {}
        item["street_name"] = str(source.get("SitusStName") or source.get("street_name") or "").strip()
        item["street_side"] = str(source.get("street_side") or infer_street_side(source.get("SitusStNo") or source.get("street_number") or source.get("address"))).strip().lower()
    groups = cluster_and_order(items, target=target, mode=mode)
    plan = RoutingPlan.objects.create(created_by=request.user, name=name or f"{mode.title()} clusters · {import_obj.filename}", import_file=import_obj, mode=mode, target_stop_count=target, route_count=len(groups), status="clustered", algorithm_version="cluster-v1", summary={"valid_stops": len(items), "unassigned_stops": import_obj.rows.exclude(validation_status="valid").count()})
    for route_number, group in enumerate(groups, start=1):
        total = sum(distance((a["longitude"], a["latitude"]), (b["longitude"], b["latitude"])) for a, b in zip(group, group[1:]))
        route = RoutingRoute.objects.create(plan=plan, route_number=route_number, mode=mode, stop_count=len(group), estimated_distance_meters=total)
        RoutingStop.objects.bulk_create([RoutingStop(route=route, import_row_id=item["id"], sequence=sequence, parcel_id=item["parcel_id"], longitude=item["longitude"], latitude=item["latitude"], street_name=item.get("street_name", ""), street_side=item.get("street_side", ""), coordinate_confidence="source_xy") for sequence, item in enumerate(group, start=1)])
    _record_revision(plan, "clustered")
    record_event(request.user, "routing_plan_created", plan, {"import_id": plan.import_file_id, "route_count": plan.route_count})
    return JsonResponse(_plan_payload(plan))


@require_http_methods(["POST"])
def optimize_plan(request, plan_id):
    if not _staff_write(request):
        return JsonResponse({"error": "Staff sign-in is required."}, status=403)
    plan = get_object_or_404(RoutingPlan, pk=plan_id)
    for route in plan.routes.prefetch_related("stops"):
        _optimize_route(route, plan)
    plan.status = "optimized"
    plan.algorithm_version = "valhalla-optimized-route-v1"
    plan.save(update_fields=["status", "algorithm_version"])
    _record_revision(plan, "optimized")
    return JsonResponse(_plan_payload(plan))


def _optimize_route(route, plan):
    stops = list(route.stops.all())
    items = [{"id": stop.id, "parcel_id": stop.parcel_id, "longitude": stop.longitude, "latitude": stop.latitude, "street_name": stop.street_name, "street_side": stop.street_side} for stop in stops]
    ordered = items
    shapes = []
    if items:
        try:
            indexes, shapes = optimized_order(items, route.mode)
            if indexes:
                ordered = [items[index] for index in indexes]
        except Exception:
            ordered = cluster_and_order(items, target=max(50, len(items)), mode=route.mode)[0]
            shapes = []
    for sequence, item in enumerate(ordered, start=1):
        RoutingStop.objects.filter(pk=item["id"]).update(sequence=sequence)
    route.geometry = {"encoded_polylines": shapes} if shapes else None
    route.save(update_fields=["geometry"])


def _set_route_order(route, stop_ids):
    stops = {stop.id: stop for stop in route.stops.all()}
    ordered = [stops[stop_id] for stop_id in stop_ids if stop_id in stops]
    ordered += [stop for stop in stops.values() if stop not in ordered]
    for offset, stop in enumerate(ordered, start=1):
        RoutingStop.objects.filter(pk=stop.id).update(sequence=offset + 10000)
    for sequence, stop in enumerate(ordered, start=1):
        RoutingStop.objects.filter(pk=stop.id).update(sequence=sequence)
    route.geometry = None
    route.save(update_fields=["geometry"])


def _renumber_route(route):
    stops = list(route.stops.order_by("sequence", "id"))
    for offset, stop in enumerate(stops, start=1):
        RoutingStop.objects.filter(pk=stop.pk).update(sequence=10000 + offset)
    for sequence, stop in enumerate(stops, start=1):
        RoutingStop.objects.filter(pk=stop.pk).update(sequence=sequence)


@require_http_methods(["POST"])
def optimize_route(request, plan_id, route_id):
    if not _staff_write(request):
        return JsonResponse({"error": "Staff sign-in is required."}, status=403)
    plan = get_object_or_404(RoutingPlan, pk=plan_id)
    route = get_object_or_404(RoutingRoute, pk=route_id, plan=plan)
    _optimize_route(route, plan)
    plan.status = "optimized"
    plan.algorithm_version = "valhalla-optimized-route-v1"
    plan.save(update_fields=["status", "algorithm_version"])
    _record_revision(plan, "route_optimized")
    return JsonResponse(_plan_payload(plan))


@require_http_methods(["POST"])
def set_route_mode(request, plan_id, route_id):
    if not _staff_write(request):
        return JsonResponse({"error": "Staff sign-in is required."}, status=403)
    plan = get_object_or_404(RoutingPlan, pk=plan_id)
    route = get_object_or_404(RoutingRoute, pk=route_id, plan=plan)
    try:
        mode = json.loads(request.body or "{}").get("mode")
    except json.JSONDecodeError:
        mode = None
    if mode not in {"driving", "walking"}:
        return JsonResponse({"error": "Mode must be driving or walking."}, status=400)
    if route.mode != mode:
        route.mode = mode
        route.geometry = None
        route.save(update_fields=["mode", "geometry"])
        plan.status = "clustered"
        plan.save(update_fields=["status"])
        _record_revision(plan, "route_mode_changed")
    return JsonResponse(_plan_payload(plan))


@require_http_methods(["POST"])
def reverse_route(request, plan_id, route_id):
    if not _staff_write(request):
        return JsonResponse({"error": "Staff sign-in is required."}, status=403)
    plan = get_object_or_404(RoutingPlan, pk=plan_id)
    route = get_object_or_404(RoutingRoute, pk=route_id, plan=plan)
    _set_route_order(route, [stop.id for stop in reversed(list(route.stops.all()))])
    plan.status = "clustered"
    plan.save(update_fields=["status"])
    _record_revision(plan, "route_reversed")
    return JsonResponse(_plan_payload(plan))


@require_http_methods(["POST"])
def reset_route(request, plan_id, route_id):
    if not _staff_write(request):
        return JsonResponse({"error": "Staff sign-in is required."}, status=403)
    plan = get_object_or_404(RoutingPlan, pk=plan_id)
    route = get_object_or_404(RoutingRoute, pk=route_id, plan=plan)
    first_revision = plan.revisions.order_by("revision_number").first()
    original = next((item for item in (first_revision.snapshot.get("routes", []) if first_revision else []) if item.get("id") == route.id), None)
    if not original:
        return JsonResponse({"error": "The original clustered order could not be found."}, status=409)
    _set_route_order(route, [stop["id"] for stop in original.get("stops", [])])
    plan.status = "clustered"
    plan.save(update_fields=["status"])
    _record_revision(plan, "route_reset")
    return JsonResponse(_plan_payload(plan))


@require_http_methods(["POST"])
def move_stop(request, plan_id):
    if not _staff_write(request):
        return JsonResponse({"error": "Staff sign-in is required."}, status=403)
    plan = get_object_or_404(RoutingPlan, pk=plan_id)
    try:
        body = json.loads(request.body or "{}")
        stop = get_object_or_404(RoutingStop, pk=int(body["stop_id"]), route__plan=plan)
        target_route = get_object_or_404(RoutingRoute, pk=int(body["target_route"]), plan=plan)
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        return JsonResponse({"error": "A valid stop_id and target_route are required."}, status=400)
    if stop.route_id == target_route.id:
        return JsonResponse(_plan_payload(plan))
    if target_route.stops.count() >= plan.target_stop_count:
        return JsonResponse({"error": f"Route {target_route.route_number} is already at the {plan.target_stop_count}-stop target."}, status=400)
    source_route = stop.route
    with transaction.atomic():
        stop.route = target_route
        stop.sequence = 100000
        stop.save(update_fields=["route", "sequence"])
        _renumber_route(source_route)
        _renumber_route(target_route)
    source_route.stop_count = source_route.stops.count()
    source_route.geometry = None
    source_route.save(update_fields=["stop_count", "geometry"])
    target_route.stop_count = target_route.stops.count()
    target_route.geometry = None
    target_route.save(update_fields=["stop_count", "geometry"])
    plan.status = "clustered"
    plan.save(update_fields=["status"])
    _record_revision(plan, "stop_moved")
    return JsonResponse(_plan_payload(plan))


@require_http_methods(["POST"])
def remove_stop(request, plan_id, stop_id):
    if not _staff_write(request):
        return JsonResponse({"error": "Staff sign-in is required."}, status=403)
    plan = get_object_or_404(RoutingPlan, pk=plan_id)
    stop = get_object_or_404(RoutingStop, pk=stop_id, route__plan=plan)
    route = stop.route
    stop.delete()
    route.stop_count = route.stops.count()
    route.geometry = None
    route.save(update_fields=["stop_count", "geometry"])
    plan.status = "clustered"
    plan.save(update_fields=["status"])
    _record_revision(plan, "stop_removed")
    return JsonResponse(_plan_payload(plan))


@require_http_methods(["POST"])
def add_stop(request, plan_id):
    if not _staff_write(request):
        return JsonResponse({"error": "Staff sign-in is required."}, status=403)
    plan = get_object_or_404(RoutingPlan, pk=plan_id)
    try:
        body = json.loads(request.body or "{}")
        row = get_object_or_404(RoutingImportRow, pk=int(body["import_row_id"]), import_file=plan.import_file, validation_status="valid")
        route = get_object_or_404(RoutingRoute, pk=int(body["target_route"]), plan=plan)
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        return JsonResponse({"error": "A valid import_row_id and target_route are required."}, status=400)
    if RoutingStop.objects.filter(route__plan=plan, import_row=row).exists():
        return JsonResponse({"error": "That stop is already assigned to this plan."}, status=400)
    if route.stops.count() >= plan.target_stop_count:
        return JsonResponse({"error": f"Route {route.route_number} is already at the {plan.target_stop_count}-stop target."}, status=400)
    source = row.source_data or {}
    stop = RoutingStop.objects.create(route=route, import_row=row, sequence=route.stops.count() + 1, parcel_id=row.parcel_id, longitude=row.longitude, latitude=row.latitude, street_name=str(source.get("SitusStName") or source.get("street_name") or "").strip(), street_side=infer_street_side(source.get("SitusStNo") or source.get("street_number") or source.get("address")), coordinate_confidence="source_xy")
    route.stop_count = route.stops.count()
    route.geometry = None
    route.save(update_fields=["stop_count", "geometry"])
    plan.status = "clustered"
    plan.save(update_fields=["status"])
    _record_revision(plan, "stop_added")
    return JsonResponse(_plan_payload(plan))


@require_GET
def available_stops(request, plan_id):
    if not _staff(request):
        return JsonResponse({"error": "Staff sign-in is required."}, status=403)
    plan = get_object_or_404(RoutingPlan, pk=plan_id)
    assigned = RoutingStop.objects.filter(route__plan=plan).values("import_row_id")
    rows = plan.import_file.rows.filter(validation_status="valid").exclude(id__in=assigned).order_by("parcel_id")[:1000]
    return JsonResponse({"stops": [{"id": row.id, "parcel_id": row.parcel_id, "address": row.address} for row in rows]})


@require_GET
def plan_detail(request, plan_id):
    if not _staff(request):
        return JsonResponse({"error": "Staff sign-in is required."}, status=403)
    return JsonResponse(_plan_payload(get_object_or_404(RoutingPlan, pk=plan_id)))


@require_GET
def export_plan(request, plan_id):
    if not _staff(request):
        return HttpResponse("Staff sign-in is required.", status=403)
    response = HttpResponse(route_csv(get_object_or_404(RoutingPlan, pk=plan_id)), content_type="text/csv")
    response["Content-Disposition"] = f'attachment; filename="route-plan-{plan_id}.csv"'
    return response


@require_GET
def export_route(request, plan_id, route_id):
    if not _staff(request):
        return HttpResponse("Staff sign-in is required.", status=403)
    route = get_object_or_404(RoutingRoute, pk=route_id, plan_id=plan_id)
    response = HttpResponse(single_route_csv(route), content_type="text/csv")
    response["Content-Disposition"] = f'attachment; filename="route-plan-{plan_id}-route-{route.route_number}.csv"'
    return response
