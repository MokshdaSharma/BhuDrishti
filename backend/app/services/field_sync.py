"""Field synchronization and mobile survey package service (Section 7.11 & 9.6).

Responsibilities:
- Generate lightweight multi-layer GeoPackage tailored for QField mobile field app:
  - parcels (with editable surveyor status, verification boolean, notes, photo URLs)
  - gt_points (GNSS/CORS/field ground-truth checkpoints)
  - buildings & roads (spatial reference context)
  - issues (flagged topology issues requiring field verification)
- Ingest returned surveyed GeoPackages from QField:
  - Update parcel verification status to 'verified' and source to 'field'
  - Ingest modified boundary geometries with area recomputation
  - Record complete audit log in edit_history table
  - Import newly surveyed GNSS/field ground truth points
"""

from __future__ import annotations

import contextlib
import datetime
import json
import sqlite3
import tempfile
from pathlib import Path
from typing import Any

import geopandas as gpd
from geoalchemy2.shape import from_shape, to_shape
from shapely.geometry import Point, Polygon
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.errors import ParcelAIError
from app.models.db_models import (
    Building,
    EditAction,
    EditHistory,
    GtPoint,
    GTPointSource,
    Issue,
    Parcel,
    ParcelSource,
    ParcelStatus,
    Project,
    Road,
)


def generate_field_package(
    project_id: int,
    output_path: Path | str | None = None,
    target_crs: str = "EPSG:4326",
    db: Session | None = None,
) -> Path:
    """Export a multi-layer GeoPackage formatted for QField mobile survey app."""
    if db is None:
        db = next(get_db())

    project = db.scalar(select(Project).where(Project.id == project_id))
    if not project:
        raise ParcelAIError(f"Project #{project_id} not found", status_code=404)

    if output_path is None:
        temp_dir = Path(tempfile.gettempdir()) / "parcelai_field"
        temp_dir.mkdir(parents=True, exist_ok=True)
        pkg_path = temp_dir / f"project_{project_id}_qfield.gpkg"
    else:
        pkg_path = Path(output_path)
        pkg_path.parent.mkdir(parents=True, exist_ok=True)

    if pkg_path.exists():
        pkg_path.unlink()

    # 1. Parcels layer
    db_parcels = db.scalars(select(Parcel).where(Parcel.project_id == project_id)).all()
    parcel_rows: list[dict[str, Any]] = []
    parcel_geoms: list[Polygon] = []

    for p in db_parcels:
        geom = to_shape(p.geom)
        if geom is None or geom.is_empty:
            continue
        ladm = p.ladm_attrs if isinstance(p.ladm_attrs, dict) else {}
        is_verified = 1 if p.status == ParcelStatus.verified else 0

        parcel_rows.append(
            {
                "id": p.id,
                "project_id": p.project_id,
                "confidence": round(p.confidence, 4) if p.confidence is not None else 0.0,
                "status": p.status.value,
                "source": p.source.value,
                "area_m2": round(p.area_m2, 2) if p.area_m2 is not None else round(geom.area, 2),
                "verified": is_verified,
                "surveyor": str(ladm.get("surveyor") or p.created_by or ""),
                "survey_note": str(ladm.get("notes") or ladm.get("note") or ""),
                "photo_url": str(ladm.get("photo_url") or ""),
                "survey_time": (
                    p.updated_at.isoformat()
                    if p.updated_at
                    else datetime.datetime.now(datetime.timezone.utc).isoformat()
                ),
                "ladm_attrs": json.dumps(ladm) if ladm else "{}",
            }
        )
        parcel_geoms.append(geom)

    if parcel_geoms:
        gdf_parcels = gpd.GeoDataFrame(parcel_rows, geometry=parcel_geoms, crs=project.crs)
        if project.crs != target_crs:
            with contextlib.suppress(Exception):
                gdf_parcels = gdf_parcels.to_crs(target_crs)
        gdf_parcels.to_file(pkg_path, layer="parcels", driver="GPKG")
    else:
        empty_gdf = gpd.GeoDataFrame([], columns=["id", "geometry"], crs=target_crs)
        empty_gdf.to_file(pkg_path, layer="parcels", driver="GPKG")

    # 2. GT Points / GNSS Checkpoints layer
    db_points = db.scalars(select(GtPoint).where(GtPoint.project_id == project_id)).all()
    pt_rows: list[dict[str, Any]] = []
    pt_geoms: list[Point] = []

    for pt in db_points:
        geom = to_shape(pt.geom)
        if geom is None or geom.is_empty:
            continue
        pt_rows.append(
            {
                "id": pt.id,
                "project_id": pt.project_id,
                "source": pt.source.value,
                "accuracy_m": pt.accuracy_m or 0.05,
                "photo_url": pt.photo_url or "",
                "note": pt.note or "",
            }
        )
        pt_geoms.append(geom)

    if pt_geoms:
        gdf_points = gpd.GeoDataFrame(pt_rows, geometry=pt_geoms, crs=project.crs)
        if project.crs != target_crs:
            with contextlib.suppress(Exception):
                gdf_points = gdf_points.to_crs(target_crs)
        gdf_points.to_file(pkg_path, layer="gt_points", driver="GPKG")
    else:
        empty_pt_gdf = gpd.GeoDataFrame([], columns=["id", "geometry"], crs=target_crs)
        empty_pt_gdf.to_file(pkg_path, layer="gt_points", driver="GPKG")

    # 3. Buildings reference layer
    db_bldgs = db.scalars(select(Building).where(Building.project_id == project_id)).all()
    bldg_rows: list[dict[str, Any]] = []
    bldg_geoms: list[Polygon] = []

    for b in db_bldgs:
        geom = to_shape(b.geom)
        if geom is None or geom.is_empty:
            continue
        bldg_rows.append(
            {
                "id": b.id,
                "project_id": b.project_id,
                "confidence": round(b.confidence, 4) if b.confidence is not None else 0.0,
                "parcel_id": b.parcel_id or -1,
            }
        )
        bldg_geoms.append(geom)

    if bldg_geoms:
        gdf_bldgs = gpd.GeoDataFrame(bldg_rows, geometry=bldg_geoms, crs=project.crs)
        if project.crs != target_crs:
            with contextlib.suppress(Exception):
                gdf_bldgs = gdf_bldgs.to_crs(target_crs)
        gdf_bldgs.to_file(pkg_path, layer="buildings", driver="GPKG")

    # 4. Roads reference layer
    db_roads = db.scalars(select(Road).where(Road.project_id == project_id)).all()
    road_rows: list[dict[str, Any]] = []
    road_geoms = []

    for r in db_roads:
        geom = to_shape(r.geom)
        if geom is None or geom.is_empty:
            continue
        road_rows.append(
            {
                "id": r.id,
                "project_id": r.project_id,
                "width_m": r.width_m or 4.0,
            }
        )
        road_geoms.append(geom)

    if road_geoms:
        gdf_roads = gpd.GeoDataFrame(road_rows, geometry=road_geoms, crs=project.crs)
        if project.crs != target_crs:
            with contextlib.suppress(Exception):
                gdf_roads = gdf_roads.to_crs(target_crs)
        gdf_roads.to_file(pkg_path, layer="roads", driver="GPKG")

    # 5. Issues layer
    db_issues = db.scalars(
        select(Issue).where(Issue.project_id == project_id, Issue.resolved.is_(False))
    ).all()
    issue_rows: list[dict[str, Any]] = []
    issue_geoms = []

    for iss in db_issues:
        if iss.geom is None:
            continue
        geom = to_shape(iss.geom)
        if geom is None or geom.is_empty:
            continue
        issue_rows.append(
            {
                "id": iss.id,
                "project_id": iss.project_id,
                "issue_type": iss.issue_type.value,
                "severity": iss.severity.value,
                "suggested_fix": iss.suggested_fix or "",
            }
        )
        issue_geoms.append(geom)

    if issue_geoms:
        gdf_issues = gpd.GeoDataFrame(issue_rows, geometry=issue_geoms, crs=project.crs)
        if project.crs != target_crs:
            with contextlib.suppress(Exception):
                gdf_issues = gdf_issues.to_crs(target_crs)
        gdf_issues.to_file(pkg_path, layer="issues", driver="GPKG")

    return pkg_path


def _list_gpkg_layers(gpkg_path: Path | str) -> list[str]:
    """List available layers in a GeoPackage using pyogrio or sqlite3."""
    try:
        import pyogrio

        layers_info = pyogrio.list_layers(str(gpkg_path))
        return [layer[0] for layer in layers_info]
    except Exception:
        pass

    try:
        conn = sqlite3.connect(str(gpkg_path))
        cursor = conn.cursor()
        cursor.execute("SELECT table_name FROM gpkg_contents")
        rows = cursor.fetchall()
        conn.close()
        return [r[0] for r in rows]
    except Exception:
        return []


def sync_field_package(
    project_id: int,
    gpkg_path: Path | str,
    db: Session,
    file_name: str | None = None,
) -> dict[str, Any]:
    """Ingest surveyed GeoPackage from QField, applying verifications and geometry updates."""
    gpkg_p = Path(gpkg_path)
    if not gpkg_p.exists():
        raise ParcelAIError(f"Field package file not found: {gpkg_path}", status_code=400)

    project = db.scalar(select(Project).where(Project.id == project_id))
    if not project:
        raise ParcelAIError(f"Project #{project_id} not found", status_code=404)

    layers = _list_gpkg_layers(str(gpkg_p))


    verified_count = 0
    geom_updated_count = 0
    imported_points_count = 0
    errors: list[str] = []

    # 1. Process parcels layer
    if "parcels" in layers:
        try:
            gdf_parcels = gpd.read_file(str(gpkg_p), layer="parcels")
            # If layer CRS is different from project CRS, reproject
            if gdf_parcels.crs and project.crs and str(gdf_parcels.crs) != project.crs:
                with contextlib.suppress(Exception):
                    gdf_parcels = gdf_parcels.to_crs(project.crs)

            for _, row in gdf_parcels.iterrows():
                p_id = row.get("id")
                if p_id is None:
                    continue
                with contextlib.suppress(ValueError, TypeError):
                    p_id = int(p_id)

                parcel = db.scalar(
                    select(Parcel).where(Parcel.id == p_id, Parcel.project_id == project_id)
                )
                if not parcel:
                    continue

                # Verification flag check
                raw_v = row.get("verified")
                raw_status = str(row.get("status", "")).lower()
                is_verified = (
                    raw_v in (True, 1, "1", "true", "True", "yes", "YES")
                    or raw_status == "verified"
                )

                surveyor = str(row.get("surveyor") or "").strip()
                note = str(row.get("survey_note") or row.get("note") or "").strip()
                photo_url = str(row.get("photo_url") or "").strip()

                old_shape = to_shape(parcel.geom)
                new_shape = row.geometry

                geom_changed = False
                if (
                    new_shape is not None
                    and not new_shape.is_empty
                    and hasattr(new_shape, "equals_exact")
                    and not old_shape.equals_exact(new_shape, tolerance=1e-3)
                ):
                    geom_changed = True

                # Update parcel attributes
                ladm = dict(parcel.ladm_attrs) if isinstance(parcel.ladm_attrs, dict) else {}
                if surveyor:
                    ladm["surveyor"] = surveyor
                if note:
                    ladm["survey_notes"] = note
                if photo_url:
                    ladm["photo_url"] = photo_url
                if is_verified:
                    ladm["verified_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()

                parcel.ladm_attrs = ladm

                if geom_changed:
                    parcel.geom = from_shape(new_shape, srid=32643)
                    with contextlib.suppress(Exception):
                        parcel.area_m2 = round(new_shape.area, 2)
                    geom_updated_count += 1

                if is_verified and parcel.status != ParcelStatus.verified:
                    parcel.status = ParcelStatus.verified
                    parcel.source = ParcelSource.field
                    verified_count += 1
                elif is_verified:
                    parcel.source = ParcelSource.field
                    verified_count += 1

                # Record edit history if changed
                if geom_changed or is_verified:
                    history = EditHistory(
                        feature_table="parcels",
                        feature_id=parcel.id,
                        action=EditAction.update,
                        old_geom=from_shape(old_shape, srid=32643) if old_shape else None,
                        new_geom=from_shape(new_shape, srid=32643) if new_shape else None,
                        user_name=surveyor or "field_surveyor",
                        ts=datetime.datetime.now(datetime.timezone.utc),
                    )
                    db.add(history)

        except Exception as exc:
            errors.append(f"Parcels sync error: {exc}")

    # 2. Process GT points / GNSS checkpoints layer
    if "gt_points" in layers:
        try:
            gdf_pts = gpd.read_file(str(gpkg_p), layer="gt_points")
            if gdf_pts.crs and project.crs and str(gdf_pts.crs) != project.crs:
                with contextlib.suppress(Exception):
                    gdf_pts = gdf_pts.to_crs(project.crs)

            existing_pt_ids = set(
                db.scalars(
                    select(GtPoint.id).where(GtPoint.project_id == project_id)
                ).all()
            )

            for _, row in gdf_pts.iterrows():
                pt_geom = row.geometry
                if pt_geom is None or pt_geom.is_empty or not isinstance(pt_geom, Point):
                    continue

                raw_id = row.get("id")
                is_new = True
                if raw_id is not None:
                    with contextlib.suppress(ValueError, TypeError):
                        if int(raw_id) in existing_pt_ids:
                            is_new = False

                if is_new:
                    src_val = str(row.get("source", "field")).lower()
                    gt_source = (
                        GTPointSource.field
                        if src_val not in GTPointSource._value2member_map_
                        else GTPointSource(src_val)
                    )

                    new_pt = GtPoint(
                        project_id=project_id,
                        geom=from_shape(pt_geom, srid=32643),
                        source=gt_source,
                        accuracy_m=float(row.get("accuracy_m", 0.05)),
                        photo_url=str(row.get("photo_url") or "") or None,
                        note=str(row.get("note") or "") or None,
                    )
                    db.add(new_pt)
                    db.flush()

                    history = EditHistory(
                        feature_table="gt_points",
                        feature_id=new_pt.id,
                        action=EditAction.insert,
                        new_geom=from_shape(pt_geom, srid=32643),
                        user_name="field_surveyor",
                        ts=datetime.datetime.now(datetime.timezone.utc),
                    )
                    db.add(history)
                    imported_points_count += 1

        except Exception as exc:
            errors.append(f"GT Points sync error: {exc}")

    db.commit()

    return {
        "project_id": project_id,
        "status": "synced",
        "file_name": file_name or gpkg_p.name,
        "verified_parcels": verified_count,
        "updated_geometries": geom_updated_count,
        "imported_checkpoints": imported_points_count,
        "errors": errors,
        "disclaimer": "Preliminary — subject to field verification",
    }
