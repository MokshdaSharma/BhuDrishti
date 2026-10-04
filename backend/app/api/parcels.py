"""Parcels API endpoints for querying and interactive Web-GIS editing (Section 7.9)."""

from __future__ import annotations

import contextlib
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from geoalchemy2.shape import from_shape, to_shape
from shapely.geometry import Polygon, mapping, shape
from shapely.ops import split as shapely_split
from shapely.ops import unary_union
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.models.db_models import EditAction, EditHistory, Parcel, ParcelSource, ParcelStatus
from app.models.schemas import ParcelMergeRequest, ParcelSplitRequest, ParcelUpdate

router = APIRouter(tags=["parcels"])


def _parcel_to_feature(p: Parcel) -> dict[str, Any]:
    geom_dict = None
    if p.geom is not None:
        try:
            geom_dict = mapping(to_shape(p.geom))
        except Exception:
            geom_dict = None

    return {
        "type": "Feature",
        "id": p.id,
        "geometry": geom_dict,
        "properties": {
            "id": p.id,
            "project_id": p.project_id,
            "confidence": round(p.confidence, 4) if p.confidence is not None else None,
            "source": p.source.value,
            "status": p.status.value,
            "area_m2": round(p.area_m2, 2) if p.area_m2 is not None else None,
            "ladm_attrs": p.ladm_attrs or {},
            "created_by": p.created_by,
            "updated_at": p.updated_at.isoformat() if p.updated_at else None,
        },
    }


@router.get("/projects/{project_id}/parcels")
def get_project_parcels(
    project_id: int,
    status_filter: str | None = Query(None, alias="status"),
    min_confidence: float | None = None,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Retrieve cadastral parcels for a project as a GeoJSON FeatureCollection."""
    query = select(Parcel).where(Parcel.project_id == project_id)
    if status_filter:
        with contextlib.suppress(ValueError):
            query = query.where(Parcel.status == ParcelStatus(status_filter))
    if min_confidence is not None:
        query = query.where(Parcel.confidence >= min_confidence)

    parcels = db.scalars(query.order_by(Parcel.id.asc())).all()

    return {
        "type": "FeatureCollection",
        "features": [_parcel_to_feature(p) for p in parcels if p.geom is not None],
    }


@router.get("/parcels/{parcel_id}")
def get_parcel(parcel_id: int, db: Session = Depends(get_db)) -> dict[str, Any]:
    """Retrieve details and geometry of a single parcel."""
    parcel = db.scalar(select(Parcel).where(Parcel.id == parcel_id))
    if not parcel:
        raise HTTPException(status_code=404, detail=f"Parcel #{parcel_id} not found")
    return _parcel_to_feature(parcel)


@router.put("/parcels/{parcel_id}")
def update_parcel(
    parcel_id: int,
    payload: ParcelUpdate,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Update parcel geometry or attributes with optimistic concurrency and audit logging."""
    parcel = db.scalar(select(Parcel).where(Parcel.id == parcel_id))
    if not parcel:
        raise HTTPException(status_code=404, detail=f"Parcel #{parcel_id} not found")

    old_geom = parcel.geom
    new_geom = old_geom

    if payload.geom is not None:
        try:
            shp = shape(payload.geom)
            if not shp.is_valid:
                from shapely.validation import make_valid
                shp = make_valid(shp)
            new_geom = from_shape(shp, srid=32643)
            parcel.geom = new_geom
            parcel.area_m2 = float(shp.area)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"Invalid geometry: {exc}") from exc

    if payload.confidence is not None:
        parcel.confidence = payload.confidence
    if payload.status is not None:
        parcel.status = payload.status
    if payload.ladm_attrs is not None:
        parcel.ladm_attrs = payload.ladm_attrs

    parcel.source = ParcelSource.edited
    parcel.updated_at = datetime.now(timezone.utc)

    # Log to edit history
    db.add(
        EditHistory(
            feature_table="parcels",
            feature_id=parcel.id,
            action=EditAction.update,
            old_geom=old_geom,
            new_geom=new_geom,
            user_name="surveyor",
            ts=datetime.now(timezone.utc),
        )
    )

    db.commit()
    db.refresh(parcel)
    return _parcel_to_feature(parcel)


@router.delete("/parcels/{parcel_id}", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
def delete_parcel(parcel_id: int, db: Session = Depends(get_db)) -> Response:
    """Delete a parcel and log the action in edit_history."""
    parcel = db.scalar(select(Parcel).where(Parcel.id == parcel_id))
    if not parcel:
        raise HTTPException(status_code=404, detail=f"Parcel #{parcel_id} not found")

    db.add(
        EditHistory(
            feature_table="parcels",
            feature_id=parcel.id,
            action=EditAction.delete,
            old_geom=parcel.geom,
            new_geom=None,
            user_name="surveyor",
            ts=datetime.now(timezone.utc),
        )
    )
    db.delete(parcel)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/parcels/merge", status_code=status.HTTP_201_CREATED)
def merge_parcels(payload: ParcelMergeRequest, db: Session = Depends(get_db)) -> dict[str, Any]:
    """Merge two or more selected parcels into a single unified parcel."""
    if len(payload.parcel_ids) < 2:
        raise HTTPException(status_code=400, detail="At least 2 parcel IDs required for merge")

    parcels = db.scalars(select(Parcel).where(Parcel.id.in_(payload.parcel_ids))).all()
    if len(parcels) < len(payload.parcel_ids):
        raise HTTPException(status_code=404, detail="One or more specified parcel IDs not found")

    project_id = parcels[0].project_id
    shapes = [to_shape(p.geom) for p in parcels if p.geom is not None]

    try:
        merged_shp = unary_union(shapes)
        if not merged_shp.is_valid:
            from shapely.validation import make_valid
            merged_shp = make_valid(merged_shp)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Failed to union geometries: {exc}") from exc

    # Create new merged parcel
    new_parcel = Parcel(
        project_id=project_id,
        geom=from_shape(merged_shp, srid=32643),
        confidence=float(sum(p.confidence or 0.8 for p in parcels) / len(parcels)),
        source=ParcelSource.edited,
        status=ParcelStatus.reviewed,
        area_m2=float(merged_shp.area),
        ladm_attrs={"merged_from": payload.parcel_ids, "operation": "merge"},
    )
    db.add(new_parcel)
    db.flush()

    # Log deletion of merged source parcels and remove them
    for p in parcels:
        db.add(
            EditHistory(
                feature_table="parcels",
                feature_id=p.id,
                action=EditAction.delete,
                old_geom=p.geom,
                new_geom=None,
                user_name="surveyor_merge",
                ts=datetime.now(timezone.utc),
            )
        )
        db.delete(p)

    db.commit()
    db.refresh(new_parcel)
    return _parcel_to_feature(new_parcel)


@router.post("/parcels/{parcel_id}/split", status_code=status.HTTP_201_CREATED)
def split_parcel(parcel_id: int, payload: ParcelSplitRequest, db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    """Split an existing parcel along a provided split line."""
    parcel = db.scalar(select(Parcel).where(Parcel.id == parcel_id))
    if not parcel:
        raise HTTPException(status_code=404, detail=f"Parcel #{parcel_id} not found")

    try:
        split_line = shape(payload.line)
        orig_shp = to_shape(parcel.geom)
        split_result = shapely_split(orig_shp, split_line)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Split operation failed: {exc}") from exc

    parts = [geom for geom in split_result.geoms if isinstance(geom, Polygon) and geom.area > 1.0]
    if len(parts) < 2:
        raise HTTPException(status_code=400, detail="Split line does not bisect the parcel polygon into 2+ parts")

    created_parcels = []
    for part in parts:
        new_p = Parcel(
            project_id=parcel.project_id,
            geom=from_shape(part, srid=32643),
            confidence=parcel.confidence,
            source=ParcelSource.edited,
            status=ParcelStatus.reviewed,
            area_m2=float(part.area),
            ladm_attrs={"split_from": parcel_id, "operation": "split"},
        )
        db.add(new_p)
        created_parcels.append(new_p)

    # Log old parcel deletion
    db.add(
        EditHistory(
            feature_table="parcels",
            feature_id=parcel.id,
            action=EditAction.delete,
            old_geom=parcel.geom,
            new_geom=None,
            user_name="surveyor_split",
            ts=datetime.now(timezone.utc),
        )
    )
    db.delete(parcel)
    db.commit()

    for p in created_parcels:
        db.refresh(p)

    return [_parcel_to_feature(p) for p in created_parcels]
