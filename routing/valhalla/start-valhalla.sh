#!/bin/sh
set -eu

DATA_DIR="${DATA_DIR:-/data}"
OSM_URL="${OSM_URL:-https://data.bbbike.org/osm/pbf/region/north-america/us/washington.osm.pbf}"
OSM_FILE="${OSM_FILE:-${DATA_DIR}/washington-latest.osm.pbf}"
TILES_DIR="${TILES_DIR:-${DATA_DIR}/tiles}"
CONFIG_FILE="${CONFIG_FILE:-${DATA_DIR}/valhalla.json}"

mkdir -p "${DATA_DIR}" "${TILES_DIR}"

if [ ! -s "${OSM_FILE}" ]; then
  echo "Downloading OSM extract from ${OSM_URL}"
  curl -L --fail --retry 5 --retry-delay 5 -o "${OSM_FILE}.part" "${OSM_URL}"
  mv "${OSM_FILE}.part" "${OSM_FILE}"
fi

if [ ! -s "${CONFIG_FILE}" ]; then
  echo "Generating Valhalla configuration"
  valhalla_build_config --mjolnir-tile-dir "${TILES_DIR}" --mjolnir-tile-extract "${DATA_DIR}/tiles.tar" --mjolnir-timezone "${TILES_DIR}/timezones.sqlite" --mjolnir-admin "${TILES_DIR}/admins.sqlite" > "${CONFIG_FILE}.part"
  mv "${CONFIG_FILE}.part" "${CONFIG_FILE}"
fi

if ! find "${TILES_DIR}" -name '*.gph' -print -quit | grep -q .; then
  echo "Building Valhalla routing tiles"
  valhalla_build_tiles -c "${CONFIG_FILE}" "${OSM_FILE}"
fi

if [ ! -s "${DATA_DIR}/tiles.tar" ]; then
  echo "Building indexed Valhalla tile extract"
  valhalla_build_extract -c "${CONFIG_FILE}" -v
fi

echo "Starting Valhalla on port 8002"
exec valhalla_service "${CONFIG_FILE}"
