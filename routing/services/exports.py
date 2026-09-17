import csv
import io


def route_csv(plan):
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["route_number", "stop_sequence", "parcel_id", "address", "longitude", "latitude", "street_side", "coordinate_confidence"])
    for route in plan.routes.prefetch_related("stops__import_row"):
        for stop in route.stops.all():
            row = stop.import_row
            writer.writerow([route.route_number, stop.sequence, stop.parcel_id, row.address, stop.longitude, stop.latitude, stop.street_side, stop.coordinate_confidence])
    return output.getvalue()


def single_route_csv(route):
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["route_number", "stop_sequence", "parcel_id", "address", "longitude", "latitude", "street_side", "coordinate_confidence"])
    for stop in route.stops.select_related("import_row").all():
        writer.writerow([route.route_number, stop.sequence, stop.parcel_id, stop.import_row.address, stop.longitude, stop.latitude, stop.street_side, stop.coordinate_confidence])
    return output.getvalue()
