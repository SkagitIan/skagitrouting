import os

import requests


def optimized_order(items, mode):
    """Return Valhalla's stop order and decoded-ready shape for one route."""
    base = os.getenv("VALHALLA_URL", "").rstrip("/")
    if not base or not items:
        return None, None
    locations = [{"lat": item["latitude"], "lon": item["longitude"]} for item in items]
    response = requests.post(
        f"{base}/optimized_route",
        json={"locations": locations, "costing": "pedestrian" if mode == "walking" else "auto", "units": "miles"},
        timeout=120,
    )
    response.raise_for_status()
    trip = response.json().get("trip") or {}
    ordered_locations = trip.get("locations") or []
    indexes = [location.get("original_index") for location in ordered_locations]
    if len(indexes) != len(items) or any(index is None for index in indexes):
        raise ValueError("Valhalla returned an incomplete optimized route.")
    shape = [leg.get("shape") for leg in trip.get("legs", []) if leg.get("shape")]
    return indexes, shape
