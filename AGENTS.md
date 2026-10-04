# AGENTS.md — ParcelAI: AI-Based Automated Urban Parcel Mapping Platform

This file is the COMPLETE specification of the project. Read all of it before writing any code. Implementation is done phase by phase (Section 11), but every phase must be written against the interfaces and rules defined here so that later phases plug in without rewrites.

---

## 1. Project brief

Build **ParcelAI**, a web platform that takes drone data (orthorectified imagery/ORI, DSM, DTM) and produces a *preliminary* urban cadastral map: building footprints, roads and access corridors, land-use classes and parcel polygons. It validates topology automatically, compares results with an existing GIS parcel layer, computes accuracy against GNSS/CORS and ground-truth (GT) points, and gives surveyors a Web-GIS interface (Mapbox-based, with MapLibre fallback) to review, edit and export. Google Earth Engine (GEE) provides public context layers for sanity checks and baselines.

Mandatory capabilities (from the problem statement):
1. Parcel boundary extraction into closed parcel polygons.
2. Building footprint extraction with regularized geometry.
3. Road, pathway and access-corridor detection (polygons + centerlines).
4. Urban land-use classification.
5. AI image segmentation for parcel delineation; deep-learning feature extraction/object detection.
6. Automated topology generation and parcel polygon creation.
7. Detection of overlapping or inconsistent geometries (topology validation module).
8. Web-GIS visualization and editing interface, and a dashboard (stats, layers, validation reports).
9. Inputs: ORI, DSM/DTM, existing GIS parcels, GT data, GNSS/CORS survey points.
10. GIS-ready outputs: GeoJSON, GeoPackage, Shapefile (plus KML and PDF report).
11. Support for ground truthing and field verification.

USPs to implement: nDSM (DSM−DTM) height-aware AI; hybrid AI + rule-based parcel builder; per-parcel confidence score and review queue; comparison with existing parcel layer (new/missing/changed); GNSS accuracy report; active-learning loop from manual edits; PDF survey report; LADM-aligned attributes; English/Hindi/Punjabi UI; GEE context checks; private on-premise processing.

## 2. Ground rules (non-negotiable)

1. **Zero cost for the prototype.** Open-source software and free tiers only. Everything runs locally with `docker compose up`. Mapbox and GEE use free tiers and must degrade gracefully (Sections 9.1, 9.2).
2. **Private data stays local.** Drone imagery, DSM/DTM, parcels, GT and GNSS data must NEVER be uploaded to Mapbox, GEE or any third-party service. External services receive only: map view requests (Mapbox tiles), search text (Mapbox geocoding), and a project bounding box plus public dataset IDs (GEE).
3. **Never use Mapbox imagery or tiles as training data, model input, or export content.** They are for on-screen display only.
4. **No paid AI APIs.** Use pretrained open models fine-tuned by us (PyTorch, segmentation_models_pytorch, TorchGeo, SAM via segment-geospatial).
5. **CRS.** Store and process in the project CRS (default EPSG:32643, UTM 43N, configurable). Serve web tiles in EPSG:3857 via tile servers.
6. **Preliminary output.** UI, exports and reports must state "Preliminary — subject to field verification".
7. **Runs without trained weights.** `MOCK_MODEL=true` uses classical CV (nDSM thresholds, edge detection) so the app is demoable before training. Runs on CPU.
8. **Runs without external keys.** No Mapbox token → MapLibre view. No GEE credentials → GEE features hidden/disabled, nothing else breaks.
9. Code quality: Python 3.11+, type hints, docstrings, pytest tests, ruff + black; TypeScript strict on the frontend; small modules; no secrets in git; use latest stable dependency versions and pin them after install.
10. Verify third-party API details (route formats, dataset IDs, package names) against current official docs before coding; they change.

## 3. Architecture and data flow

```
Drone images → WebODM (external) → ORI + DSM + DTM (GeoTIFF)
        │
        ▼
[ingest] validate CRS → reproject → resample to ORI grid → nDSM → COG → 512px tiles
        │
        ▼
[inference] multi-task model (or MOCK_MODEL) → probability COGs: building, road, boundary, landuse
        │
        ▼
[vectorize] polygons, regularization, road skeleton/centerlines → buildings, roads, landuse tables
        │
        ▼
[parcels] watershed + polygonize + rules + snapping + confidence → parcels table
        │
        ▼
[topology] PostGIS rules + auto-fix → issues table
[compare] vs existing parcels
[gee_context] vs Dynamic World prior, Open Buildings baseline (optional)
[accuracy] vs GNSS/CORS + GT
        │
        ▼
[API: FastAPI + Celery] ─ TiTiler (raster tiles) ─ Martin (vector tiles)
        │
        ▼
[Frontend: React + Mapbox GL JS (fallback MapLibre) + Terra Draw]
        │
        ▼
[export] GeoJSON / GPKG / SHP / KML / PDF   ⇄   [field loop] QField GPKG → sync → GT → retraining
```

## 4. Repository layout

```
parcelai/
├── AGENTS.md  PROMPTS.md  README.md  Makefile
├── docker-compose.yml  .env.example
├── backend/
│   ├── app/
│   │   ├── main.py
│   │   ├── api/         projects.py upload.py jobs.py parcels.py issues.py accuracy.py export.py context.py field.py
│   │   ├── core/        config.py db.py logging.py errors.py
│   │   ├── models/      db_models.py schemas.py
│   │   ├── services/    ingest.py inference.py vectorize.py parcels.py topology.py compare.py
│   │   │                accuracy.py export.py report.py gee_context.py field_sync.py
│   │   └── workers/     celery_app.py tasks.py
│   ├── tests/  requirements.txt  Dockerfile
├── ml/
│   ├── configs/  datasets/  train.py  infer.py  export_weights.py  notebooks/kaggle_train.ipynb
├── frontend/
│   ├── src/
│   │   ├── map/         provider.ts mapboxProvider.ts maplibreProvider.ts basemaps.ts layers.ts
│   │   ├── editor/      terraDrawFactory.ts tools.ts
│   │   ├── panels/      Layers Issues ReviewQueue Stats Compare Accuracy Context UploadWizard Export
│   │   ├── i18n/        en.json hi.json pa.json
│   │   └── api/         client.ts types.ts
│   ├── package.json  Dockerfile  .env.example
├── db/          init.sql  topology_rules.sql
├── data/sample/ (tiny demo dataset)
├── scripts/     download_datasets.py make_sample_data.py build_finetune_set.py seed_demo.py
└── docs/        architecture.md api.md field_workflow.md demo_script.md progress.md decisions.md
```

## 5. Tech stack

| Layer | Choice |
|---|---|
| Backend | FastAPI, Uvicorn, SQLAlchemy 2 + GeoAlchemy2, Alembic, Celery + Redis |
| Geo | GDAL, rasterio, GeoPandas, Shapely 2, pyproj, pyogrio, scikit-image, OpenCV, networkx |
| ML | PyTorch, segmentation_models_pytorch, TorchGeo, albumentations, transformers (SegFormer, optional), segment-geospatial (optional), MLflow (local) |
| DB | PostgreSQL + PostGIS |
| Tiles | TiTiler (COG raster), Martin (PostGIS vector tiles) |
| Maps | Mapbox GL JS v3 (primary when token present), MapLibre GL JS (fallback), Terra Draw for editing |
| Frontend | React + Vite + TypeScript, Tailwind, Chart.js, react-i18next |
| Context | earthengine-api (+ optional geemap) |
| Reports | WeasyPrint or ReportLab |
| Field | QField / QFieldSync with GeoPackage |
| Drone processing | WebODM/OpenDroneMap, run separately |

## 6. Data model (PostGIS)

All geometry columns have GIST indexes. `project_id` foreign key on every feature table.

- `projects(id, name, crs, extent, status, created_at)`
- `rasters(id, project_id, kind[ori|dsm|dtm|ndsm|prob_building|prob_road|prob_boundary|prob_landuse], path, resolution, crs)`
- `parcels(id, project_id, geom Polygon, confidence, source[ai|edited|field|existing], status[draft|reviewed|verified], area_m2, ladm_attrs jsonb, created_by, updated_at)`
- `buildings(id, project_id, geom Polygon, confidence, parcel_id)`
- `roads(id, project_id, geom Polygon, centerline LineString, width_m)`
- `landuse(id, project_id, geom Polygon, class, confidence)`
- `issues(id, project_id, type, severity[info|warning|error], geom, suggested_fix, resolved, created_at)`
- `gt_points(id, project_id, geom Point, source[gnss|cors|field], accuracy_m, photo_url, note)`
- `edit_history(id, feature_table, feature_id, action, old_geom, new_geom, user, ts)`
- `gee_cache(id, project_id, dataset, params_hash, result_path_or_json, created_at, expires_at)`

Land-use classes: `built_up, road, vegetation, water, open_land, other`.
Issue types: `invalid_geometry, overlap, gap, sliver, spike, building_crosses_parcel, building_on_road, landlocked_parcel, new_parcel, missing_parcel, changed_parcel, landuse_prior_mismatch, low_confidence`.

## 7. Module specifications and interfaces

Keep these signatures stable across phases.

### 7.1 ingest (`services/ingest.py`)
`prepare_project(project_id) -> PreparedData(ori_cog, dsm_cog, dtm_cog, ndsm_cog, tiles: list[TileWindow])`
- Accept GeoTIFF for ORI/DSM/DTM; GeoPackage/Shapefile/GeoJSON for existing parcels and GT/GNSS points.
- Validate CRS, resolution, extent (rasterio); clear error messages on failure.
- Reproject to project CRS; resample DSM/DTM to ORI grid; `nDSM = clip(DSM − DTM, 0, None)` float32; convert to COG.
- Tile ORI+nDSM into 512×512 windows, configurable overlap (default 25%).
- If no DTM: if GEE enabled, offer coarse DEM fallback (clearly flagged); else derive a rough ground surface by morphological opening of DSM and flag it as approximate.

### 7.2 ML training (`ml/`)
- One shared encoder (default resnet34, imagenet weights, `in_channels` 3 or 4) with four heads: building (BCE+Dice), road (BCE+Dice+clDice), boundary (weighted BCE on thin edge map derived from masks), land-use (CE+Dice).
- Dataset loaders: INRIA Aerial, WHU Building, DeepGlobe roads, LoveDA/OpenEarthMap land-use, generic "local" loader (image tiles + vector labels rasterized on the fly, optional nDSM channel).
- Masked losses so samples with labels for only some heads still train.
- albumentations: flips, rotations, scale, brightness, blur. Mixed precision, checkpoint every epoch, resume, YAML configs, MLflow logging.
- Metrics: IoU, F1, precision, recall, boundary F-score.
- `kaggle_train.ipynb` runs end-to-end on Kaggle; `export_weights.py` writes one `.pt` plus JSON (class map, normalization stats). `--smoke-test` trains 2 steps on synthetic data.

### 7.3 inference (`services/inference.py`)
`run_inference(project_id, tiles) -> ProbRasters`
- Load weights from `MODEL_PATH`; tiled inference; average probabilities in overlaps; write COGs.
- `MOCK_MODEL=true`: buildings = nDSM > 2.5 m + morphological cleanup; roads = low-nDSM, low-saturation connected corridors; boundary = Sobel/Canny on ORI blended with building/road edges; land-use = greenness + height rules.

### 7.4 vectorize (`services/vectorize.py`)
`extract_features(project_id, probs) -> FeatureSet`
- Threshold → `rasterio.features.shapes` → min-area filter → morphological cleanup → shapely simplify.
- Building regularization: snap to dominant orientation / minimum rotated rectangle when rectangularity is high.
- Roads: polygons plus centerlines (skimage skeletonize → networkx graph → prune short spurs), estimate width.
- Confidence = mean probability inside each polygon. Write to PostGIS.

### 7.5 parcels (`services/parcels.py`)
`build_parcels(project_id) -> int`
1. Barrier raster from boundary probability + road polygons.
2. Watershed (skimage) seeded by building clusters → candidate regions.
3. Linework (predicted boundary edges, road edges) → `shapely.polygonize` faces.
4. Reconcile: prefer polygonize faces containing exactly one building cluster; else watershed regions.
5. Rules: a parcel must not cut through a building; merge tiny fragments into the neighbor with the longest shared edge; parcels should touch a road/access corridor where possible; configurable minimum area.
6. Snap edges (`shapely.snap`) and enforce shared vertices between neighbors.
7. Confidence = 0.5·mean boundary probability along edges + 0.2·shape regularity + 0.15·building-containment consistency + 0.15·IoU with existing layer (if present; else redistribute weight).
Also return a debug GeoJSON of intermediate steps.

### 7.6 topology and comparison (`db/topology_rules.sql`, `services/topology.py`, `compare.py`)
`validate(project_id, autofix=True) -> ValidationSummary`; `compare_with_existing(project_id) -> CompareSummary`
- Checks: invalid geometry (`ST_IsValid`, `ST_IsValidReason`, `ST_MakeValid`); overlaps above area threshold; gaps (union minus hull, holes below threshold); slivers (area/perimeter, min width); duplicate vertices/spikes; building crossing parcel boundary; building on road (encroachment); landlocked parcels; comparison with existing layer (IoU, area difference %, Hausdorff distance → new/missing/changed/unchanged).
- Write each finding to `issues` with severity and suggested fix. Auto-fix trivial cases (tiny gaps, slivers, duplicate vertices) and log in `edit_history`.

### 7.7 accuracy (`services/accuracy.py`)
`compute(project_id) -> AccuracyReport`: positional RMSE and mean horizontal error vs GNSS/CORS checkpoints; IoU/F1/precision/recall vs GT polygons; parcel counts (correct/merged/split).

### 7.8 export and report (`services/export.py`, `report.py`)
`export(project_id, fmt, crs) -> Path` for geojson, gpkg, shp, kml. `build_pdf(project_id) -> Path`: disclaimer, counts and areas, accuracy stats, top issues, map snapshot (rendered server-side from vector data, not from Mapbox).

### 7.9 API (FastAPI, all under `/api/v1`)
```
GET  /health
POST /projects                         GET /projects  GET /projects/{id}
POST /projects/{id}/upload             (multipart; kind=ori|dsm|dtm|parcels|gt)
POST /projects/{id}/run                → job id (ingest→inference→vectorize→parcels→validate→compare→[gee])
GET  /jobs/{id}                        (status, progress, logs)
GET  /projects/{id}/parcels            PUT/DELETE /parcels/{id}   POST /parcels/merge  POST /parcels/split
POST /projects/{id}/validate           GET /projects/{id}/issues   PATCH /issues/{id}
GET  /projects/{id}/compare
GET  /projects/{id}/accuracy
GET  /projects/{id}/tiles              (returns TiTiler/Martin URL templates)
GET  /projects/{id}/context/status     (GEE enabled? authenticated?)
GET  /projects/{id}/context/landcover  GET .../context/open-buildings  GET .../context/dem  GET .../context/sentinel
POST /projects/{id}/context/refresh
GET  /projects/{id}/export?format=geojson|gpkg|shp|kml|pdf&crs=EPSG:4326
GET  /projects/{id}/field-package      POST /projects/{id}/field-sync
```
Parcel edits write to `edit_history` and use optimistic concurrency (`updated_at`).

### 7.10 Frontend (`frontend/`)
- Map provider abstraction (`map/provider.ts`) with two implementations (Mapbox GL JS, MapLibre GL JS) behind one interface: `init`, `addRasterSource`, `addVectorSource`, `addGeoJSON`, `setBasemap`, `flyTo`, `setLayerOpacity`, `enableTerrain`, `getDrawAdapter`. Provider chosen by `VITE_MAP_PROVIDER` (`auto` = Mapbox if token present, else MapLibre).
- Layers: ORI, DSM hillshade, nDSM (TiTiler); parcels, buildings, roads, landuse, issues, existing parcels, GT points (Martin); GEE context layers (Sentinel-2 tiles, Dynamic World) as raster sources.
- Panels: Layers (toggle/opacity), Issues (filter, click-to-zoom, resolve), Review Queue (ascending confidence), Stats (counts, area, land-use pie, confidence histogram), Compare (swipe AI vs existing + changed list), Accuracy (RMSE, IoU/F1), Context (GEE checks and baselines), Upload/Run wizard with job progress, Export menu.
- Editing with Terra Draw: select, move vertex, add/delete vertex, draw polygon, split by line, merge selected, delete, undo/redo. Adapter selected in `terraDrawFactory.ts` (`TerraDrawMapboxGLAdapter` or `TerraDrawMapLibreGLAdapter`). Every save calls the API.
- Search box (Mapbox Geocoding, only when Mapbox enabled) to fly to a place.
- i18n: English, Hindi, Punjabi. Visible "Preliminary — requires field verification" banner. Keyboard accessible, responsive. No dependence on browser storage for data.

### 7.11 Field loop (`services/field_sync.py`, `scripts/build_finetune_set.py`)
- `GET /projects/{id}/field-package`: GeoPackage for QField with flagged/low-confidence parcels (form fields: verified yes/no, note, photo, surveyor, timestamp) and a GNSS checkpoint point layer.
- `POST /projects/{id}/field-sync`: ingest returned GeoPackage; set parcel status `verified` or flag for edit; store photos; insert `gt_points`.
- `build_finetune_set.py`: convert edited/verified parcels into training tiles + masks in the "local" loader format (active learning).

## 8. Datasets (for training and testing; verify each licence)

Training: INRIA Aerial, WHU Building, SpaceNet 1/2/3, DeepGlobe (roads, land cover), LoveDA, OpenEarthMap, ISPRS Potsdam/Vaihingen (imagery + height), Open Cities AI Challenge (drone). Test/demo: OpenDroneMap sample datasets, OpenAerialMap. Reference: Microsoft and Google building footprints, OSM. No public Indian cadastral-parcel dataset exists: parcels come from the existing GIS layer, boundary evidence and surveyor corrections. `scripts/download_datasets.py` lists sources and licences and downloads what is freely accessible (SpaceNet via AWS `--no-sign-request`).

## 9. Integrations

### 9.1 Mapbox (integrated, with fallback)

Purpose: satellite/street basemap context under our ORI layer, place search, optional 3D terrain view, and Mapbox GL JS as the primary rendering engine.

**Setup steps for the developer**
1. Create a free account at mapbox.com. In the account's Access tokens page create a **public** token (starts with `pk.`) with default public scopes. For deployment, add URL restrictions to it.
2. Put it in `frontend/.env` as `VITE_MAPBOX_TOKEN=pk...`. Never commit it. Do not use a secret (`sk.`) token in the frontend.
3. `npm i mapbox-gl terra-draw terra-draw-mapbox-gl-adapter terra-draw-maplibre-gl-adapter maplibre-gl`.

**Implementation requirements**
- `mapboxProvider.ts`: set `mapboxgl.accessToken` from env; import `mapbox-gl/dist/mapbox-gl.css`; use style `mapbox://styles/mapbox/satellite-streets-v12` as default basemap with a switcher for `streets-v12` and `light-v11`; keep default attribution and logo visible.
- Add TiTiler ORI as an XYZ raster source above the basemap with an opacity slider; add Martin sources as `vector` sources; add GEE tile URLs as raster sources.
- Terrain (optional toggle, visual only): raster-dem source `mapbox://mapbox.mapbox-terrain-dem-v1` with `setTerrain`. Label it "visual terrain, not survey DSM".
- Search: Mapbox Geocoding API (v6 forward geocoding). Use results only to fly the map; do not store them.
- Swipe compare: use the plugin that matches the provider (`mapbox-gl-compare` or `@maplibre/maplibre-gl-compare`) or a clip-path implementation.
- **Fallback:** if the token is missing, or the map emits a 401/403/429 error, switch automatically to `maplibreProvider.ts` with no external basemap (local layers only) and show a small notice. Nothing else may break.
- Do NOT use Mapbox styles/tiles inside MapLibre (terms of service). Do NOT cache, download or export Mapbox tiles, and do NOT use them as ML input.
- Free-tier quotas and pricing change: check current Mapbox pricing before demos with many viewers.

### 9.2 Google Earth Engine (integrated, optional at runtime)

Purpose: public context only — land-cover prior checks, building baseline, coarse DEM fallback and satellite context tiles. **Never upload any project data to GEE.** Only the project bounding box (optionally rounded via `GEE_BBOX_PRECISION` decimals) and public dataset IDs are sent.

**Setup steps for the developer**
1. Create a Google Cloud project. Register it for Earth Engine (non-commercial/research use is free; check the current terms and eligibility).
2. Enable the Earth Engine API. Create a service account, register it for Earth Engine access and grant the roles the current Earth Engine docs require for reading public data. Download its JSON key.
3. Mount the key as a Docker secret (e.g. `./secrets/gee-key.json`). Set in `.env`: `ENABLE_GEE=true`, `GEE_PROJECT`, `GEE_SERVICE_ACCOUNT`, `GEE_KEY_FILE`.
4. Local dev alternative: run `earthengine authenticate` once and set only `GEE_PROJECT`.

**Implementation requirements (`services/gee_context.py`, `api/context.py`)**
```python
import ee, os
def init_gee() -> bool:
    """Initialize Earth Engine; return False (never raise) if disabled or unauthenticated."""
    if os.getenv("ENABLE_GEE", "false").lower() != "true": return False
    try:
        if os.getenv("GEE_KEY_FILE"):
            creds = ee.ServiceAccountCredentials(os.environ["GEE_SERVICE_ACCOUNT"], os.environ["GEE_KEY_FILE"])
            ee.Initialize(creds, project=os.environ["GEE_PROJECT"])
        else:
            ee.Initialize(project=os.environ["GEE_PROJECT"])
        return True
    except Exception:
        return False
```
Functions (each returns `None` when GEE is unavailable; cache results in `gee_cache`; use timeouts and retries):
- `land_cover_prior(bbox, start, end)`: `GOOGLE/DYNAMICWORLD/V1`, `label` band mode over dates and bbox. Map classes (0 water, 1 trees, 2 grass, 3 flooded vegetation, 4 crops, 5 shrub and scrub, 6 built, 7 bare, 8 snow/ice) to our classes. Use only for **area-level** consistency checks (10 m resolution): compare class proportions with our land-use output and raise `landuse_prior_mismatch` issues for large regions that disagree strongly. Never use it to overwrite parcel-level results.
- `open_buildings_baseline(bbox, min_conf=0.7)`: `GOOGLE/Research/open-buildings/v3/polygons`, filtered by bounds and confidence; export via `getDownloadURL` as GeoJSON for small areas. Compute recall/precision of our buildings against this baseline and show it in the Context panel (as a sanity benchmark, not ground truth).
- `coarse_dem(bbox)`: `COPERNICUS/DEM/GLO30` as a fallback only when no DTM is uploaded; label clearly as coarse and not suitable for parcel-level heights.
- `sentinel_tiles(bbox, start, end)`: `COPERNICUS/S2_SR_HARMONIZED` median composite → `image.getMapId(vis)` → return `tile_fetcher.url_format` for use as a raster source. These URLs expire, so provide a refresh route and handle 4xx by refreshing.
- `dynamic_world_tiles(bbox, start, end)`: same pattern, for a land-cover overlay.
- Verify dataset IDs and band names in the Earth Engine data catalog before coding.
- Frontend: Context panel shows GEE status, a toggle for each context layer, baseline metrics and mismatch issues. If `context/status` says disabled, hide the panel with a short "Earth Engine not configured" note.

### 9.3 WebODM/OpenDroneMap
Run separately with Docker. Generate ORI, DSM, DTM (`--dsm --dtm --orthophoto-resolution 3`). Our platform ingests the GeoTIFFs. Optional "Import from WebODM" endpoint using WebODM's REST API (`WEBODM_URL`, `WEBODM_TOKEN`).

### 9.4 TiTiler and Martin
TiTiler serves COGs (configure CORS for the frontend origin; verify the route format of the installed version). Martin publishes PostGIS tables/functions as vector tiles; use function sources with a `project_id` parameter, keep GIST indexes, and expose 4326/3857-compatible views.

### 9.5 Training and weights
Download open datasets locally → upload as private Kaggle datasets → run `kaggle_train.ipynb` → download weights + JSON → place in `backend/models_store/`, set `MODEL_PATH`, set `MOCK_MODEL=false`. Fine-tune later with `build_finetune_set.py`.

### 9.6 QField
Install QGIS + QFieldSync, open the exported GeoPackage, configure forms, package for mobile; after field work sync back and call `/field-sync`. Document in `docs/field_workflow.md`.

## 10. Environment variables

```
# backend/.env
POSTGRES_USER=parcel
POSTGRES_PASSWORD=change_me
POSTGRES_DB=parcelai
DATABASE_URL=postgresql+psycopg://parcel:change_me@postgis:5432/parcelai
REDIS_URL=redis://redis:6379/0
DEFAULT_CRS=EPSG:32643
DATA_DIR=/data
MODEL_PATH=/models/parcelai_v1.pt
MOCK_MODEL=true
TITILER_URL=http://titiler:8000
MARTIN_URL=http://martin:3000
CORS_ORIGINS=http://localhost:5173
# GEE (optional)
ENABLE_GEE=false
GEE_PROJECT=
GEE_SERVICE_ACCOUNT=
GEE_KEY_FILE=/run/secrets/gee-key.json
GEE_BBOX_PRECISION=3
# WebODM (optional)
WEBODM_URL=
WEBODM_TOKEN=

# frontend/.env
VITE_API_URL=http://localhost:8000
VITE_MAP_PROVIDER=auto        # auto | mapbox | maplibre
VITE_MAPBOX_TOKEN=            # public pk. token only
```

## 11. Phase plan (implement one phase per request)

| Phase | Scope | Spec sections | Done when |
|---|---|---|---|
| 0 | Scaffold, Docker Compose, health check, blank map | 3, 4, 5, 10 | `docker compose up` runs all services; `/health` OK; blank map shows |
| 1 | DB schema, migrations | 6 | Schema tests pass; one row per table inserts |
| 2 | Ingestion + nDSM + tiling + sample-data generator | 7.1 | Synthetic dataset ingests; nDSM correct; tests pass |
| 3 | ML training code + Kaggle notebook | 7.2, 8, 9.5 | `--smoke-test` passes; notebook runs on synthetic data |
| 4 | Inference + vectorization (with MOCK_MODEL) | 7.3, 7.4 | Building IoU > 0.8 on synthetic data in MOCK mode |
| 5 | Parcel builder | 7.5 | Parcels generated with confidence; debug GeoJSON works |
| 6 | Topology validation + comparison | 7.6 | Every rule detects its seeded error; auto-fixes logged |
| 7 | API, jobs, exports, accuracy, PDF report | 7.7, 7.8, 7.9 | Full chained job runs; all export formats open in QGIS |
| 8 | GEE context service + API | 9.2, 7.9 | With credentials: all context calls work; without: graceful disabled status |
| 9 | Frontend map: provider abstraction (Mapbox/MapLibre), layers, basemaps, search | 7.10, 9.1 | Both providers render the same layers; fallback works with no token |
| 10 | Frontend editing, panels, i18n, swipe compare, Context panel | 7.10 | Edits persist; issues, stats, compare, accuracy panels work; 3 languages |
| 11 | Field loop + active learning | 7.11, 9.6 | GPKG round-trip works; fine-tune set builds |
| 12 | Hardening, seed demo, E2E test, docs | all | `make demo` works from a clean clone; Playwright E2E passes |

## 12. Working agreement for the AI coding assistant

- Implement **only the phase requested**, but code against the interfaces in Sections 6–7 so later phases plug in. Do not leave TODO stubs inside the requested phase's scope.
- Before coding a phase: restate its scope, list the files you will create or change, and note any assumption. If the spec is ambiguous, choose the simplest option and record it in `docs/decisions.md`.
- After each phase: run tests and linters, update `docs/progress.md` (what is done, what is next, known issues), and never break earlier tests.
- Never hard-code secrets or tokens. Never send project data to external services (Rule 2).
- Verify third-party APIs against current docs; if something in this spec is outdated, say so and adapt.
- Keep functions small and tested; prefer clear code over clever code.

## 13. Definition of done (whole project)

- [ ] `docker compose up` starts all services; `make test` passes.
- [ ] Upload sample ORI/DSM/DTM → Run → buildings, roads, land-use and parcels appear on the map.
- [ ] Every parcel has a confidence; the review queue is sorted lowest first.
- [ ] Topology validator finds seeded overlaps, gaps, slivers, building-on-road and landlocked parcels; auto-fixes trivial ones.
- [ ] Comparison with an existing layer shows new/missing/changed with a swipe view.
- [ ] Editing (move vertex, draw, split, merge, delete) persists with history.
- [ ] Accuracy panel shows RMSE and IoU/F1.
- [ ] Exports: GeoJSON, GeoPackage, Shapefile, KML, PDF.
- [ ] Field GeoPackage round-trip with QField works.
- [ ] Mapbox basemap, search and terrain work with a token; MapLibre fallback works without one.
- [ ] GEE context layers and baseline metrics work with credentials; the app works fully without them.
- [ ] UI available in English, Hindi and Punjabi.
- [ ] Works offline with `MOCK_MODEL=true` and no external keys.
- [ ] No private data leaves the machine; no paid service is required.
