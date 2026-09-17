import os

import requests


def travel_matrix(items, mode):
    base = os.getenv("VALHALLA_URL", "").rstrip("/")
    if not base or not items:
        return None
    locations = [{"lat": item["latitude"], "lon": item["longitude"]} for item in items]
    try:
        response = requests.post(f"{base}/sources_to_targets", json={"sources": locations, "targets": locations, "costing": "pedestrian" if mode == "walking" else "auto"}, timeout=90)
        response.raise_for_status()
    except requests.RequestException:
        # A saved cluster must still be usable if Valhalla is restarting or
        # rejects a point; optimization can fall back to geographic distance.
        return None
    matrix = response.json().get("sources_to_targets")
    if not matrix or len(matrix) != len(items):
        raise ValueError("Valhalla returned an invalid travel-time matrix.")
    return [[cell.get("time") if cell else None for cell in row] for row in matrix]
