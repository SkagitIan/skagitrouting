import requests
from django.conf import settings


class OpenSkagitUnavailable(Exception):
    pass


def parcel_context(parcel_ids):
    ids = []
    for value in parcel_ids:
        value = str(value or "").strip()
        if value and value not in ids:
            ids.append(value)
    if len(ids) > 2000:
        raise ValueError("Too many parcels in one lookup.")
    if not ids:
        return {"parcels": {}, "cycle_start": None, "cycle_end": None}
    if not settings.OPENSKAGIT_API_URL or not settings.OPENSKAGIT_API_TOKEN:
        raise OpenSkagitUnavailable("OpenSkagit parcel API is not configured.")
    try:
        response = requests.get(
            f"{settings.OPENSKAGIT_API_URL}/api/v1/routing/parcels/context/",
            params=[("parcel_id", value) for value in ids],
            headers={"Authorization": f"Bearer {settings.OPENSKAGIT_API_TOKEN}"},
            timeout=settings.OPENSKAGIT_API_TIMEOUT,
        )
        response.raise_for_status()
        payload = response.json()
    except (requests.RequestException, ValueError) as exc:
        raise OpenSkagitUnavailable("OpenSkagit parcel API is unavailable.") from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("parcels"), dict):
        raise OpenSkagitUnavailable("OpenSkagit returned an invalid parcel response.")
    return payload
