import csv
import io
import re
import zipfile
import xml.etree.ElementTree as ElementTree

from pyproj import Transformer


WGS84 = Transformer.from_crs("EPSG:2926", "EPSG:4326", always_xy=True)
ALIASES = {
    "parcelid": "parcel_id", "parcel_id": "parcel_id", "parcelnumber": "parcel_id",
    "situsstno": "street_number", "street_number": "street_number",
    "situsstname": "street_name", "street_name": "street_name",
    "situscsz": "city_state_zip", "address": "address",
    "xcoordinate": "x", "x": "x", "longitude": "longitude", "lon": "longitude",
    "ycoordinate": "y", "y": "y", "latitude": "latitude", "lat": "latitude",
}


def clean_header(value):
    return re.sub(r"[^a-z0-9_]", "", str(value or "").strip().lower())


def read_upload(upload):
    raw = upload.read()
    name = upload.name.lower()
    if name.endswith(".csv"):
        text = raw.decode("utf-8-sig", errors="replace")
        reader = csv.DictReader(io.StringIO(text))
        headers = reader.fieldnames or []
        return headers, [dict(row) for row in reader], "csv"
    if name.endswith(".xlsx"):
        # The export is a simple worksheet. Reading the OOXML package directly
        # avoids adding a heavyweight spreadsheet dependency to Railway.
        with zipfile.ZipFile(io.BytesIO(raw)) as workbook:
            ns = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
            shared = []
            if "xl/sharedStrings.xml" in workbook.namelist():
                shared = ["".join(text.text or "" for text in item.findall(".//m:t", ns)) for item in ElementTree.fromstring(workbook.read("xl/sharedStrings.xml")).findall("m:si", ns)]
            sheet = ElementTree.fromstring(workbook.read("xl/worksheets/sheet1.xml"))
            values = []
            for row in sheet.findall(".//m:sheetData/m:row", ns):
                current = []
                for cell in row.findall("m:c", ns):
                    value = cell.find("m:v", ns)
                    text = "" if value is None else value.text or ""
                    if cell.get("t") == "s" and text:
                        text = shared[int(text)]
                    current.append(text)
                values.append(current)
        headers = [str(value or "").strip() for value in (values[0] if values else [])]
        return headers, [dict(zip(headers, row)) for row in values[1:] if any(value not in (None, "") for value in row)], "xlsx"
    raise ValueError("Upload a CSV or XLSX file.")


def _number(value):
    try:
        return float(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def infer_street_side(value):
    """Infer the common odd/even side convention from a street number."""
    match = re.search(r"\d+", str(value or ""))
    if not match:
        return ""
    return "odd" if int(match.group()) % 2 else "even"


def normalize_row(source):
    normalized = {ALIASES.get(clean_header(key), clean_header(key)): value for key, value in source.items()}
    x = _number(normalized.get("x"))
    y = _number(normalized.get("y"))
    lon = _number(normalized.get("longitude"))
    lat = _number(normalized.get("latitude"))
    coordinate_source = "wgs84" if lon is not None and lat is not None else "epsg2926"
    if lon is None and lat is None and x is not None and y is not None:
        lon, lat = WGS84.transform(x, y)
    parcel_id = str(normalized.get("parcel_id") or "").strip()
    address = str(normalized.get("address") or "").strip()
    if not address:
        address = " ".join(str(normalized.get(key) or "").strip() for key in ("street_number", "street_name")).strip()
    notes = []
    if not parcel_id:
        notes.append("missing_parcel_id")
    if lon is None or lat is None:
        notes.append("missing_coordinates")
    elif not (-123.5 < lon < -120.0 and 47.0 < lat < 49.5):
        notes.append("coordinates_outside_skagit_area")
    return {
        "parcel_id": parcel_id, "address": address, "source_x": x, "source_y": y,
        "longitude": lon, "latitude": lat, "coordinate_source": coordinate_source,
        "street_name": str(normalized.get("street_name") or "").strip(),
        "street_side": infer_street_side(normalized.get("street_number") or normalized.get("address")),
        "validation_status": "valid" if not notes else "review",
        "validation_notes": notes,
        "source_data": source,
    }
