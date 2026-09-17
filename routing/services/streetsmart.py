"""Cyclomedia StreetSmart Panorama Rendering API integration."""

from __future__ import annotations

import os
import re
import tempfile
import xml.etree.ElementTree as ElementTree
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urljoin

import requests


DEFAULT_BASE_URL = "https://atlasapi.cyclomedia.com/api/PanoramaRendering/"
DEFAULT_TIMEOUT = 25


class StreetSmartError(Exception):
    """A safe, user-facing StreetSmart integration error."""


class StreetSmartConfigurationError(StreetSmartError):
    pass


class StreetSmartNoRecordingError(StreetSmartError):
    pass


@dataclass(frozen=True)
class StreetSmartConfig:
    base_url: str
    api_key: str
    username: str
    password: str

    @property
    def api_configured(self):
        return bool(self.api_key and self.username and self.password)

def get_config():
    return StreetSmartConfig(
        base_url=(os.getenv("CYCLOMEDIA_BASE_URL") or DEFAULT_BASE_URL).rstrip("/") + "/",
        api_key=os.getenv("CYCLOMEDIA_API_KEY", "").strip(),
        username=os.getenv("CYCLOMEDIA_USERNAME", "").strip(),
        password=os.getenv("CYCLOMEDIA_PASSWORD", ""),
    )


def _require_api_config(config):
    if not config.api_configured:
        raise StreetSmartConfigurationError(
            "StreetSmart is not configured yet. Add CYCLOMEDIA_API_KEY, "
            "CYCLOMEDIA_USERNAME, and CYCLOMEDIA_PASSWORD to the local environment."
        )


def _fault_message(content):
    try:
        root = ElementTree.fromstring(content)
    except ElementTree.ParseError:
        return "Cyclomedia returned an unreadable error response."
    values = []
    for node in root.iter():
        name = node.tag.rsplit("}", 1)[-1].lower()
        if name in {"detail", "faultstring"} and (node.text or "").strip():
            values.append(node.text.strip())
    return " — ".join(dict.fromkeys(values)) or "Cyclomedia rejected the request."


def _request(method, path, config, **kwargs):
    params = dict(kwargs.pop("params", {}))
    params["apiKey"] = config.api_key
    try:
        response = requests.request(
            method,
            urljoin(config.base_url, path.lstrip("/")),
            params=params,
            auth=(config.username, config.password),
            timeout=DEFAULT_TIMEOUT,
            **kwargs,
        )
    except requests.RequestException as exc:
        raise StreetSmartError("Cyclomedia could not be reached.") from exc
    if not response.ok:
        detail = _fault_message(response.content)
        raise StreetSmartError(f"Cyclomedia request failed ({response.status_code}): {detail}")
    return response


def _float_attribute(attributes, *names):
    for name in names:
        value = attributes.get(name)
        if value not in (None, ""):
            try:
                return float(value)
            except (TypeError, ValueError):
                return None
    return None


def list_recordings(x, y, srs="2926", include_historic=False):
    config = get_config()
    _require_api_config(config)
    response = _request(
        "GET",
        f"ListByLocation2D/{srs}/{x}/{y}/",
        config,
        params={"IncludeHistoricRecordings": str(bool(include_historic)).lower()},
    )
    try:
        root = ElementTree.fromstring(response.content)
    except ElementTree.ParseError as exc:
        raise StreetSmartError("Cyclomedia returned invalid recording metadata.") from exc

    recordings = []
    for node in root.iter():
        if node.tag.rsplit("}", 1)[-1].lower() != "imagedirection":
            continue
        attributes = {key.rsplit("}", 1)[-1].lower(): value for key, value in node.attrib.items()}
        recording_id = attributes.get("recording-id") or attributes.get("recordingid")
        if not recording_id:
            continue
        recordings.append(
            {
                "recording_id": recording_id,
                "recording_date": attributes.get("recording-date", ""),
                "viewing_direction": _float_attribute(attributes, "viewing-direction", "viewingdirection"),
            }
        )
    if not recordings:
        raise StreetSmartNoRecordingError("No StreetSmart recording was found near this parcel.")
    return recordings


def render_recording(recording_id, yaw=0, width=1600, height=1200, hfov=90, pitch=0, srs_name="EPSG:2926"):
    config = get_config()
    _require_api_config(config)
    if not re.fullmatch(r"[A-Za-z0-9_-]+", str(recording_id or "")):
        raise StreetSmartError("The StreetSmart recording ID is not valid.")
    response = _request(
        "GET",
        f"Render/{recording_id}/",
        config,
        params={
            "width": int(width),
            "height": int(height),
            "srsName": srs_name,
            "yaw": float(yaw),
            "pitch": float(pitch),
            "hfov": float(hfov),
        },
    )
    if not response.content or not response.content.startswith(b"\xff\xd8"):
        raise StreetSmartError("Cyclomedia did not return a JPG image.")
    return {
        "content": response.content,
        "recording_id": response.headers.get("Recording-Id", recording_id),
        "recording_date": response.headers.get("Recording-Date", ""),
        "width": response.headers.get("Render-Width", str(width)),
        "height": response.headers.get("Render-Height", str(height)),
        "yaw": response.headers.get("Render-Yaw", str(yaw)),
        "pitch": response.headers.get("Render-Pitch", str(pitch)),
        "hfov": response.headers.get("Render-HFov", str(hfov)),
    }


def render_by_location(x, y, srs="2926", index=1, width=1600, height=1200, hfov=90):
    """Render a nearby recording automatically aimed at a target location."""
    config = get_config()
    _require_api_config(config)
    if str(index) not in {"0", "1", "2"}:
        raise StreetSmartError("The StreetSmart alternate view must be 0, 1, or 2.")
    try:
        x = float(x)
        y = float(y)
        width = int(width)
        height = int(height)
        hfov = float(hfov)
    except (TypeError, ValueError) as exc:
        raise StreetSmartError("The StreetSmart target coordinates or render settings are not valid.") from exc
    response = _request(
        "GET",
        f"RenderByLocation2D/{srs}/{x}/{y}/",
        config,
        params={"index": int(index), "width": width, "height": height, "hfov": hfov},
    )
    if not response.content or not response.content.startswith(b"\xff\xd8"):
        raise StreetSmartError("Cyclomedia did not return a JPG image.")
    return {
        "content": response.content,
        "recording_id": response.headers.get("Recording-Id", ""),
        "recording_date": response.headers.get("Recording-Date", ""),
        "width": response.headers.get("Render-Width", str(width)),
        "height": response.headers.get("Render-Height", str(height)),
        "yaw": response.headers.get("Render-Yaw", "0"),
        "pitch": response.headers.get("Render-Pitch", "0"),
        "hfov": response.headers.get("Render-HFov", str(hfov)),
    }


def safe_parcel_filename(parcel_id):
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(parcel_id or "").strip().upper()).strip("._")
    if not safe:
        raise StreetSmartError("A valid parcel ID is required to save the StreetSmart image.")
    return f"{safe}.jpg"


def save_jpg(parcel_id, content, image_root):
    if not str(image_root or "").strip():
        raise StreetSmartConfigurationError("StreetSmart image storage is not configured. Set the save directory in Workspace tools.")
    root = Path(str(image_root).strip())
    filename = safe_parcel_filename(parcel_id)
    try:
        root.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=root, prefix=".streetsmart-", suffix=".tmp", delete=False) as temporary:
            temporary.write(content)
            temporary_path = Path(temporary.name)
        destination = root / filename
        os.replace(temporary_path, destination)
    except OSError as exc:
        try:
            temporary_path.unlink(missing_ok=True)
        except (UnboundLocalError, OSError):
            pass
        raise StreetSmartError("The StreetSmart image could not be saved to the configured work drive.") from exc
    return filename
