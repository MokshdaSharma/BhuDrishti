"""Multi-format GIS export service for ParcelAI (Section 7.8).

Responsibilities:
- Export project vector layers:
  - parcels (cadastral boundaries, confidence, area, LADM attributes)
  - buildings (footprints, confidence, parcel_id)
  - roads (corridor polygons, centerlines, width)
  - landuse (classified land use polygons)
  - issues (topology validation findings and suggested fixes)
- Supported Formats:
  - GeoJSON (.geojson or zipped multi-file archive)
  - GeoPackage (.gpkg with multiple named layers)
  - Shapefile (.zip containing ESRI shapefile bundles for each layer)
  - KML (.kml with organized folder hierarchy for Google Earth)
- Reprojection to target CRS (default EPSG:4326 / WGS 84).
"""

from __future__ import annotations

import contextlib
import json
import shutil
import tempfile
import zipfile
from pathlib import Path
from typing import Any

import geopandas as gpd
from geoalchemy2.shape import to_shape
from shapely.geometry import LineString, MultiLineString, Point, Polygon, mapping
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import ParcelAIError
from app.models.db_models import Building, Issue, LandUse, Parcel, Road


def _build_geodataframes(
    project_id: int,
    parcels: list[dict[str, Any]] | None = None,
    buildings: list[dict[str, Any]] | None = None,
    roads: list[dict[str, Any]] | None = None,
    landuse: list[dict[str, Any]] | None = None,
    issues: list[dict[str, Any]] | None = None,
    source_crs: str = "EPSG:32643",
    target_crs: str = "EPSG:4326",
) -> dict[str, gpd.GeoDataFrame]:
    """Convert raw feature lists into reprojected GeoDataFrames."""
    layers: dict[str, gpd.GeoDataFrame] = {}

    def _to_gdf(records: list[dict[str, Any]] | None) -> gpd.GeoDataFrame:
        if not records:
            return gpd.GeoDataFrame([], columns=["id", "geometry"], crs=source_crs)
        geoms = []
        rows = []
        for r in records:
            g = r.get("geom") or r.get("geometry")
            if g is not None:
                geoms.append(g)
                props = {k: v for k, v in r.items() if k not in ("geom", "geometry")}
                rows.append(props)
        if not geoms:
            return gpd.GeoDataFrame([], columns=["id", "geometry"], crs=source_crs)
        gdf = gpd.GeoDataFrame(rows, geometry=geoms, crs=source_crs)
        if source_crs != target_crs:
            with contextlib.suppress(Exception):
                gdf = gdf.to_crs(target_crs)
        return gdf

    if parcels is not None:
        layers["parcels"] = _to_gdf(parcels)
    if buildings is not None:
        layers["buildings"] = _to_gdf(buildings)
    if roads is not None:
        layers["roads"] = _to_gdf(roads)
    if landuse is not None:
        layers["landuse"] = _to_gdf(landuse)
    if issues is not None:
        layers["issues"] = _to_gdf(issues)

    return layers


def _load_features_from_db(
    project_id: int,
    db: Session,
) -> dict[str, list[dict[str, Any]]]:
    """Fetch all vector feature layers for a project from the database."""
    db_parcels = db.scalars(select(Parcel).where(Parcel.project_id == project_id)).all()
    db_bldgs = db.scalars(select(Building).where(Building.project_id == project_id)).all()
    db_roads = db.scalars(select(Road).where(Road.project_id == project_id)).all()
    db_lu = db.scalars(select(LandUse).where(LandUse.project_id == project_id)).all()
    db_issues = db.scalars(select(Issue).where(Issue.project_id == project_id)).all()

    parcels = [
        {
            "id": p.id,
            "geom": to_shape(p.geom),
            "confidence": p.confidence,
            "source": p.source.value,
            "status": p.status.value,
            "area_m2": p.area_m2,
            "ladm_attrs": json.dumps(p.ladm_attrs) if p.ladm_attrs else "{}",
        }
        for p in db_parcels
        if p.geom is not None
    ]

    buildings = [
        {
            "id": b.id,
            "geom": to_shape(b.geom),
            "confidence": b.confidence,
            "parcel_id": b.parcel_id,
        }
        for b in db_bldgs
        if b.geom is not None
    ]

    roads = [
        {
            "id": r.id,
            "geom": to_shape(r.geom),
            "width_m": r.width_m,
        }
        for r in db_roads
        if r.geom is not None
    ]

    landuse = [
        {
            "id": lu.id,
            "geom": to_shape(lu.geom),
            "landuse_class": lu.landuse_class.value,
            "confidence": lu.confidence,
        }
        for lu in db_lu
        if lu.geom is not None
    ]

    issues = [
        {
            "id": iss.id,
            "geom": to_shape(iss.geom) if iss.geom is not None else None,
            "issue_type": iss.issue_type.value,
            "severity": iss.severity.value,
            "suggested_fix": iss.suggested_fix,
            "resolved": iss.resolved,
        }
        for iss in db_issues
        if iss.geom is not None
    ]

    return {
        "parcels": parcels,
        "buildings": buildings,
        "roads": roads,
        "landuse": landuse,
        "issues": issues,
    }


def _export_geojson(
    layers: dict[str, gpd.GeoDataFrame],
    output_path: Path,
) -> Path:
    """Export single combined or zipped GeoJSON feature collections."""
    features_list = []
    for layer_name, gdf in layers.items():
        if gdf.empty:
            continue
        for idx, row in gdf.iterrows():
            geom = row.geometry
            if geom is None or geom.is_empty:
                continue
            props = {k: v for k, v in row.items() if k != "geometry"}
            props["layer"] = layer_name
            # Convert non-serializable objects
            for k, v in list(props.items()):
                if isinstance(v, (dict, list)):
                    props[k] = json.dumps(v)
            features_list.append(
                {
                    "type": "Feature",
                    "id": f"{layer_name}_{props.get('id', idx)}",
                    "geometry": mapping(geom),
                    "properties": props,
                }
            )

    geojson_dict = {
        "type": "FeatureCollection",
        "features": features_list,
    }

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(geojson_dict, f, indent=2)

    return output_path


def _export_gpkg(
    layers: dict[str, gpd.GeoDataFrame],
    output_path: Path,
) -> Path:
    """Export multi-layer GeoPackage."""
    if output_path.exists():
        output_path.unlink()

    for layer_name, gdf in layers.items():
        if not gdf.empty:
            gdf.to_file(output_path, layer=layer_name, driver="GPKG")

    # If all were empty, create empty GPKG
    if not output_path.exists():
        empty_gdf = gpd.GeoDataFrame([], columns=["id", "geometry"], crs="EPSG:4326")
        empty_gdf.to_file(output_path, layer="parcels", driver="GPKG")

    return output_path


def _export_shapefile_zip(
    layers: dict[str, gpd.GeoDataFrame],
    output_path: Path,
) -> Path:
    """Export zipped Shapefile archive containing shapefile sets for each layer."""
    temp_dir = Path(tempfile.mkdtemp(prefix="shp_export_"))
    try:
        for layer_name, gdf in layers.items():
            if not gdf.empty:
                # Shapefile column length limit = 10 chars
                renamed_gdf = gdf.copy()
                cols = {}
                for c in renamed_gdf.columns:
                    if c != "geometry":
                        cols[c] = c[:10]
                renamed_gdf.rename(columns=cols, inplace=True)
                layer_dir = temp_dir / layer_name
                layer_dir.mkdir(exist_ok=True)
                renamed_gdf.to_file(layer_dir / f"{layer_name}.shp", driver="ESRI Shapefile")

        # Create zip archive
        zip_path = output_path.with_suffix(".zip")
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zipf:
            for file_p in temp_dir.rglob("*"):
                if file_p.is_file():
                    zipf.write(file_p, arcname=file_p.relative_to(temp_dir))
        return zip_path
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def _export_kml(
    layers: dict[str, gpd.GeoDataFrame],
    output_path: Path,
    project_id: int,
) -> Path:
    """Export Google Earth compatible KML XML file."""
    kml_lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<kml xmlns="http://www.opengis.net/kml/2.2">',
        f'<Document><name>ParcelAI_Project_{project_id}</name>',
        '<description>Preliminary cadastral parcel boundaries, buildings, roads, and land-use.</description>',
    ]

    for layer_name, gdf in layers.items():
        if gdf.empty:
            continue
        kml_lines.append(f'<Folder><name>{layer_name.capitalize()}</name>')
        for idx, row in gdf.iterrows():
            geom = row.geometry
            if geom is None or geom.is_empty:
                continue
            name = f"{layer_name}_{row.get('id', idx)}"
            kml_lines.append('<Placemark>')
            kml_lines.append(f'<name>{name}</name>')

            # Coordinates
            if isinstance(geom, Polygon):
                kml_lines.append('<Polygon><outerBoundaryIs><LinearRing><coordinates>')
                coords_str = " ".join(f"{x},{y},0" for x, y in geom.exterior.coords)
                kml_lines.append(coords_str)
                kml_lines.append('</coordinates></LinearRing></outerBoundaryIs></Polygon>')
            elif isinstance(geom, (LineString, MultiLineString)):
                kml_lines.append('<LineString><coordinates>')
                if isinstance(geom, LineString):
                    coords_str = " ".join(f"{x},{y},0" for x, y in geom.coords)
                else:
                    coords_str = " ".join(f"{x},{y},0" for line in geom.geoms for x, y in line.coords)
                kml_lines.append(coords_str)
                kml_lines.append('</coordinates></LineString>')
            elif isinstance(geom, Point):
                kml_lines.append(f'<Point><coordinates>{geom.x},{geom.y},0</coordinates></Point>')

            kml_lines.append('</Placemark>')
        kml_lines.append('</Folder>')

    kml_lines.append('</Document></kml>')

    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(kml_lines))

    return output_path


def export_dataset(
    project_id: int,
    fmt: str = "geojson",
    crs: str = "EPSG:4326",
    db: Session | None = None,
    output_dir: str | Path | None = None,
    parcels: list[dict[str, Any]] | None = None,
    buildings: list[dict[str, Any]] | None = None,
    roads: list[dict[str, Any]] | None = None,
    landuse: list[dict[str, Any]] | None = None,
    issues: list[dict[str, Any]] | None = None,
) -> Path:
    """Main export entrypoint supporting geojson, gpkg, shp, and kml."""
    fmt = fmt.lower()
    if fmt not in ("geojson", "gpkg", "shp", "kml"):
        raise ParcelAIError(f"Unsupported export format '{fmt}'. Supported: geojson, gpkg, shp, kml")

    out_dir = Path(output_dir) if output_dir else Path(tempfile.gettempdir()) / f"parcelai_export_{project_id}"
    out_dir.mkdir(parents=True, exist_ok=True)

    # 1. Fetch from DB if not provided explicitly
    if db is not None and parcels is None:
        raw = _load_features_from_db(project_id, db)
        parcels = raw["parcels"]
        buildings = raw["buildings"]
        roads = raw["roads"]
        landuse = raw["landuse"]
        issues = raw["issues"]

    # 2. Build GeoDataFrames
    layers = _build_geodataframes(
        project_id=project_id,
        parcels=parcels,
        buildings=buildings,
        roads=roads,
        landuse=landuse,
        issues=issues,
        target_crs=crs,
    )

    # 3. Export to requested format
    if fmt == "geojson":
        return _export_geojson(layers, out_dir / f"project_{project_id}_parcels.geojson")
    elif fmt == "gpkg":
        return _export_gpkg(layers, out_dir / f"project_{project_id}_cadastre.gpkg")
    elif fmt == "shp":
        return _export_shapefile_zip(layers, out_dir / f"project_{project_id}_shapefiles")
    elif fmt == "kml":
        return _export_kml(layers, out_dir / f"project_{project_id}_cadastre.kml", project_id)

    raise ParcelAIError(f"Unknown format: {fmt}")
