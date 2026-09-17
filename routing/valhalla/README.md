# Self-hosted Valhalla on Railway

This service supplies road-network travel-time matrices to the Django routing
app. It is intentionally separate from the web service and uses a persistent
volume so the Washington routing tiles survive redeploys.

## Railway service settings

Create a service named `valhalla` from `routing/valhalla/Dockerfile`:

```text
Repository-controlled Valhalla image
```

Set these variables:

```text
OSM_URL=https://data.bbbike.org/osm/pbf/region/north-america/us/washington.osm.pbf
OSM_FILE=/data/washington-latest.osm.pbf
CONFIG_FILE=/data/valhalla.json
TILES_DIR=/data/tiles
```

Attach a Railway volume at `/data`. The first deployment downloads the
Washington extract and builds Valhalla tiles; later deployments reuse them.
The service listens on port `8002` and should expose only Railway private
network access.

Set the web service variable to the private Valhalla service hostname:

```text
VALHALLA_URL=http://valhalla.railway.internal:8002
```

Confirm the service with `/status`. OpenStreetMap attribution is required in
the application. OSM data is licensed under ODbL.
