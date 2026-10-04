# ParcelAI — Progress Log

## Phase 0 — Scaffold ✅

**Completed:** 2026-09-29

### What was done
- Full repository layout from Section 4 created
- `docker-compose.yml` with all 7 services: postgis, redis, api, worker, titiler, martin, frontend
- `.env.example` (backend) and `frontend/.env.example` with all documented variables
- `Makefile` targets: up, down, clean, logs, psql, test, lint, fmt, typecheck, check, demo (stub)
- `.pre-commit-config.yaml` with ruff, black, detect-private-key
- `backend/pyproject.toml` with ruff, black, mypy, pytest config
- `backend/requirements.txt` (Docker) and `backend/requirements-local.txt` (Windows venv)
- All 28 packages installed and import-verified in local `env/` venv (Python 3.10)
- `backend/app/main.py` — FastAPI app with CORS, error handler, `GET /api/v1/health`
- `backend/app/core/` — config.py, logging.py, errors.py
- Stub modules: all API routers, all services, Celery app + tasks
- `backend/tests/test_health.py` — 6 tests for the health endpoint
- `db/init.sql` — PostGIS extension setup
- Frontend scaffold: Vite + React 18 + TypeScript strict + Tailwind
- `frontend/src/map/provider.ts` — stable MapProvider interface
- `frontend/src/map/maplibreProvider.ts` — full MapLibre implementation (blank dark style)
- `frontend/src/map/mapboxProvider.ts` — stub (Phase 9)
- `frontend/src/map/factory.ts` — provider factory (auto/mapbox/maplibre)
- `frontend/src/App.tsx` — blank map UI with branded navbar, collapsible status sidebar (pings /health), preliminary banner
- i18n JSON stubs: en, hi, pa
- Panel component stubs (Phase 10)
- `docs/decisions.md` with all spec deviation notes (A1–A10)
- ML, scripts, data directory stubs

### Known issues / notes
- Python 3.10 in local venv (spec requires 3.11+); Docker uses python:3.11-slim — not a blocker
- `GDAL` Python binding not installable in local venv on Windows without system GDAL; Docker handles it
- Mapbox provider is a Phase 9 stub; MapLibre fallback works fully
- `make demo` is a Phase 12 stub

### Definition of done (Phase 0)
- [x] `docker compose up` starts all services
- [x] `GET /api/v1/health` returns 200 with correct JSON
- [x] Blank map renders (MapLibre, dark style, navigation controls)
- [x] Tests pass: `pytest backend/tests/test_health.py -v`

---

## Phase 1 — DB schema ✅

**Completed:** 2026-09-29

### What was done
- `db/init.sql` — PostGIS and spatial extensions initialization
- `db/topology_rules.sql` — Complete PostGIS topology validation functions, triggers for `edit_history`, and auto-fix procedures
- `backend/app/models/db_models.py` — Complete SQLAlchemy 2.0 ORM models for all 10 tables:
  - `projects`, `rasters`, `parcels`, `buildings`, `roads`, `landuse`, `issues`, `gt_points`, `edit_history`, `gee_cache`
  - All foreign keys, cascade deletes, relationship declarations
  - GIST indexes declared on all geometry/spatial columns
  - Python enums for `ProjectStatus`, `RasterKind`, `ParcelSource`, `ParcelStatus`, `LanduseClass`, `IssueSeverity`, `IssueType`, `GTPointSource`, `EditAction`
  - Handled SQL reserved-word column mappings (`class` -> `landuse_class`, `type` -> `issue_type`, `user` -> `user_name`)
- `backend/app/models/schemas.py` — Full Pydantic v2 schemas for all CRUD requests/responses, merge/split operations, and summaries (`ValidationSummary`, `CompareSummary`, `AccuracyReport`)
- `backend/alembic.ini`, `backend/alembic/env.py`, `backend/alembic/script.py.mako` — Complete Alembic setup reading `DATABASE_URL` dynamically from app settings
- `backend/alembic/versions/0001_initial_schema.py` — Initial migration creating all 10 tables, enums, FKs, and GIST indexes
- `backend/tests/test_db_models.py` — Model and enum integrity tests
- `backend/tests/test_schemas.py` — Pydantic schema validation tests
- `backend/tests/test_sql_files.py` — Script and migration parity tests
- All 18 backend tests passing with ruff/black linting clean

### Definition of done (Phase 1)
- [x] All 10 tables, enums, FKs, and GIST indexes declared in ORM & Alembic
- [x] Alembic migration `0001_initial_schema.py` validates and generates clean SQL
- [x] Pydantic v2 request/response schemas created for all models and summaries
- [x] PostGIS topology rules and edit history triggers in `db/topology_rules.sql`
- [x] All 18 unit tests pass (`pytest backend/tests/ -v`)
- [x] Linters pass (`ruff check backend/`)

---

## Phase 2 — Ingest pipeline ✅

**Completed:** 2026-09-29

### What was done
- `backend/app/services/ingest.py` — Complete ingest pipeline with:
  - `validate_raster(file_path)`: checks GeoTIFF integrity, CRS, resolution, bounds, band count, and dimensions
  - `reproject_raster(src, dst, target_crs)`: reprojects any raster to project CRS (e.g. `EPSG:32643`)
  - `resample_to_grid(...)`: aligns DSM and DTM to the exact ORI pixel grid, CRS, resolution, and affine transform
  - `derive_approximate_dtm(...)`: uses morphological grey opening with disk structuring element to filter out elevated buildings/structures from DSM and produce an approximate ground surface (DTM) when no survey DTM is supplied
  - `compute_ndsm(...)`: calculates `nDSM = clip(DSM - DTM, 0, None)` as `float32` with nodata handling
  - `convert_to_cog(...)`: converts GeoTIFFs to Cloud-Optimized GeoTIFFs (COG) with 256x256 internal tiles, DEFLATE compression, and multi-level pyramid overviews
  - `generate_tiles(...)`: generates 512x512 tile windows with 25% overlap, computing exact geographic sub-transforms and bounding boxes
  - `prepare_project(...) -> PreparedData`: main entrypoint orchestrating validation, reprojection, grid alignment, nDSM computation, COG conversion, and tile generation
- `backend/app/core/errors.py` — Added `IngestError`, `InferenceError`, and `TopologyError`
- `backend/tests/test_ingest.py` — 9 unit and integration tests with synthetic GeoTIFF fixtures (ORI, DSM, DTM, CRS validation, nDSM height extraction, morphological opening fallback, and COG tiling)
- All 27 backend tests passing (`pytest backend/tests/ -v`)
- Linters clean (`ruff check backend/`)

### Definition of done (Phase 2)
- [x] Ingest pipeline validates CRS, resolution, and dimensions
- [x] Resampling and grid alignment matches DSM/DTM to ORI
- [x] `nDSM = clip(DSM - DTM, 0, None)` computed as float32
- [x] Morphological ground estimation fallback works when DTM is missing
- [x] COG conversion with pyramids and internal tiling
- [x] 512x512 windows generated with 25% overlap
- [x] All 27 tests pass with full synthetic raster fixtures

---

## Phase 3 — ML training & inference scaffolding ✅

**Completed:** 2026-09-29

### What was done
- `ml/model.py` — `MultiTaskUnet` architecture with shared encoder (ResNet34) and 4 multi-task segmentation heads:
  - Building footprint head: (B, 1, H, W) binary logits
  - Road network head: (B, 1, H, W) binary logits
  - Boundary / edge head: (B, 1, H, W) binary logits
  - Urban land-use head: (B, 6, H, W) multi-class logits
- `ml/losses.py` — `MultiTaskLoss` with BCE, Dice, soft clDice (centerline Dice for connected road topology), multi-class CrossEntropy, and masked losses for partially annotated datasets; metric functions for IoU, F1, precision, recall.
- `ml/datasets/dataset.py` — `LocalGeoDataset` and `SyntheticGeoDataset` with Albumentations data augmentation pipelines.
- `ml/train.py` — End-to-end multi-task training script with mixed precision, checkpointing, and `--smoke-test` capability.
- `ml/export_weights.py` — Weight export script creating `.pt` state dicts and `metadata.json`.
- `ml/configs/` — Training YAML configurations (`default.yaml`, `smoke_test.yaml`).
- `ml/notebooks/kaggle_train.ipynb` — Complete cloud GPU training notebook for Kaggle.
- `backend/app/services/inference.py` — `run_inference(...) -> ProbRasters`:
  - `MOCK_MODEL=true`: Deterministic classical CV engine (nDSM thresholds, greenness/water indices, Sobel/Canny edges) for zero-weight CPU runs.
  - `MOCK_MODEL=false`: Batched PyTorch inference on 512x512 tile windows with 2D Hann window blending over overlaps.
  - Outputs 4 Cloud-Optimized GeoTIFFs (COG): building, road, boundary, and land-use.
- `backend/tests/test_ml.py` — Unit tests for model architecture, loss masking, synthetic datasets, smoke test training, and export.
- `backend/tests/test_inference.py` — Integration tests for classical CV and deep learning inference pipelines.
- All 34 backend tests passing (`pytest backend/tests/ -v`).
- Linters clean (`ruff check backend/ ml/`).

### Definition of done (Phase 3)
- [x] Multi-task model architecture with 4 specialized decoder heads
- [x] Loss functions with soft clDice and masked loss support
- [x] Training pipeline with `--smoke-test` runs on synthetic data
- [x] Classical CV inference (`MOCK_MODEL=true`) executes on CPU without weights
- [x] Deep learning inference (`MOCK_MODEL=false`) runs with Hann blending
- [x] Probability COGs generated for buildings, roads, boundaries, and land-use
- [x] All 34 tests pass

---

## Phase 4 — Vectorization ✅

**Completed:** 2026-09-29

### What was done
- `backend/app/services/vectorize.py` — Complete feature extraction engine implementing `extract_features(project_id, probs: ProbRasters, ...) -> FeatureSet`:
  - `extract_buildings`: Thresholds building probability, extracts vector polygon shapes via `rasterio.features.shapes`, applies min-area filtering, morphological closing, Douglas-Peucker simplification, and geometry regularization: snaps footprints to minimum rotated rectangles when rectangularity $\ge 0.82$, computes mean internal confidence, and returns `BuildingFeature` dataclasses.
  - `extract_roads`: Binary road corridor extraction, morphological opening/closing, medial axis skeletonization (`skimage.morphology.skeletonize`), converts 8-connected skeleton pixels to a `networkx.Graph`, prunes dead-end spurs shorter than `min_spur_length_px`, decomposes the skeleton graph into continuous line strings (`shapely.geometry.LineString` / `MultiLineString`), and estimates average road width ($W = \text{Area} / \text{Length}$).
  - `extract_landuse`: 6-class argmax classification across multi-band land-use probability COG, polygonizes class masks, filters small isolated fragments, simplifies boundaries, and maps to `LanduseFeature` dataclasses.
  - `extract_features`: High-level service function combining building, road, and land-use extraction, with optional persistence to PostGIS tables (`buildings`, `roads`, `landuse`) if a database session is provided, and serializes clean GeoJSON feature collections (`FeatureSet`).
- `backend/tests/test_vectorize.py` — 4 comprehensive unit and integration tests with synthetic probability fixtures:
  - `test_extract_buildings`: Verifies regularized geometry, minimum bounding rectangle snapping, and confidence computation.
  - `test_extract_roads`: Verifies road polygon creation, skeleton graph centerline extraction, dead-end spur pruning, and width estimation.
  - `test_extract_landuse`: Verifies 6-class argmax polygonization and class mapping.
  - `test_extract_features_end_to_end`: Tests full feature extraction and GeoJSON dict serialization.
- All 38 backend tests passing (`pytest backend/tests/ -v`).
- Linters clean (`ruff check backend/ ml/`).

### Definition of done (Phase 4)
- [x] Building footprint extraction with geometry regularization (minimum rotated rectangle)
- [x] Road extraction with skeleton centerlines, dead-end spur pruning, and width estimation
- [x] Land-use polygonization from 6-class probability rasters
- [x] Mean internal confidence calculation for all extracted features
- [x] All 38 tests pass with zero errors

---

## Phase 5 — Hybrid Parcel Builder ✅

**Completed:** 2026-09-30

### What was done
- `backend/app/services/parcels.py` — Complete hybrid AI + rule-based parcel construction engine implementing `build_parcels(project_id, probs: ProbRasters, features_set: FeatureSet, ...) -> ParcelSet`:
  - **Barrier Surface Creation:** Blends predicted boundary probability and rasterized road corridor polygons into an impassable barrier cost surface.
  - **Watershed Seeding & Growing:** Generates seeds from building cluster centroids and open space local minima via distance transform; performs marker-controlled watershed segmentation (`skimage.segmentation.watershed`) to generate initial parcel region candidates.
  - **Linework Polygonization:** Extracts thin skeleton boundary linework and road boundary edges, unions them with outer project bounds, and generates planar topological faces via `shapely.ops.polygonize`.
  - **Reconciliation:** Merges watershed candidate polygons with polygonized linework faces, giving precedence to clean linework faces that contain single building clusters, and subtracting road corridor geometries.
  - **Cadastral Rules:**
    - **No Building Bisection:** Detects buildings split across multiple parcel boundaries and merges those parcels into unified parcels containing the entire building.
    - **Sliver Fragment Merging:** Iteratively merges tiny parcels (< `min_parcel_area`) into adjacent parcels with the longest shared boundary edge.
    - **Road Accessibility:** Assesses spatial proximity of parcels to road corridors and flags `touches_road` in LADM attributes.
  - **Topological Snapping:** Applies `shapely.ops.snap` with configurable tolerance to eliminate micro-gaps, overlaps, and enforce shared vertices between neighboring parcels.
  - **Multi-Factor Confidence Scoring:** Computes per-parcel confidence:
    $$\text{Conf} = 0.50 \times C_{\text{boundary}} + 0.20 \times C_{\text{regularity}} + 0.15 \times C_{\text{containment}} + 0.15 \times C_{\text{existing}}$$
    (Redistributed to $0.55 / 0.25 / 0.20$ when no reference layer is supplied).
  - **Debug GeoJSON Layers & Database Persistence:** Exports intermediate debug layers (seeds, watershed counts, linework face counts) and optionally persists parcels to PostGIS `parcels` table with LADM attributes.
- `backend/tests/test_parcels.py` — 7 comprehensive unit and integration tests covering:
  - `test_create_barrier_raster`: Boundary probability and road polygon blending.
  - `test_watershed_markers_and_containment`: Building seed generation and containment scoring.
  - `test_cadastral_rules_no_building_bisection`: Merging candidate regions bisecting buildings.
  - `test_merge_sliver_fragments`: Sliver merging along longest shared edge.
  - `test_snap_parcel_neighbors`: Topological snapping of neighboring parcel boundaries.
  - `test_parcel_confidence_scoring`: Multi-factor confidence calculation.
  - `test_build_parcels_end_to_end`: Full pipeline execution, GeoJSON serialization, and LADM attributes.
- All 45 backend tests passing (`pytest backend/tests/ -v`).
- Linters clean (`ruff check backend/ ml/`).

### Definition of done (Phase 5)
- [x] Barrier surface constructed from boundary probability and road corridors
- [x] Marker-controlled watershed seeded from building footprints and open space
- [x] Planar topological faces generated via `shapely.ops.polygonize`
- [x] Cadastral rules enforced: no building bisection, sliver fragment merging, road corridor accessibility
- [x] Topological snapping applied between adjacent parcel polygons
- [x] Multi-factor per-parcel confidence scoring
- [x] All 45 tests pass with zero errors

---

## Phase 6 — Topology Validation & Comparison ✅

**Completed:** 2026-09-30

### What was done
- `backend/app/services/topology.py` — Complete topology validation and auto-repair service implementing `validate(project_id, db=None, autofix=True) -> ValidationSummary`:
  - **Geometric Integrity:** `check_invalid_geometries` using `shapely.is_valid` / `is_valid_reason`.
  - **Overlaps:** `check_overlaps` detects overlapping parcel regions with area $\ge 0.5 \text{m}^2$.
  - **Interior Gaps:** `check_gaps` identifies interior holes inside parcel clusters by analyzing convex hull differences.
  - **Sliver Geometries:** `check_slivers` detects micro-polygons ($< \text{min\_area}$) and elongated shapes using the isoperimetric quotient ($4\pi A / P^2 < 0.15$).
  - **Cross-Layer Integrity:**
    - `check_building_crosses_parcel`: detects buildings bisected by multiple parcel boundaries.
    - `check_building_on_road`: flags building footprints encroaching on road network corridors.
    - `check_landlocked_parcels`: flags parcels isolated without road or access corridor frontage.
    - `check_low_confidence`: flags parcels with confidence $< 0.40$ for surveyor review.
  - **Auto-Fix Capabilities:** `autofix_parcels` applies `shapely.validation.make_valid`, simplifies duplicate vertices/micro-spikes, merges sliver fragments into adjacent neighbors with the longest shared edge, snaps boundaries, and logs operations into `edit_history`.
  - **Database Persistence:** Clears unresolved issues and persists findings to the `issues` table.
- `backend/app/services/compare.py` — Cadastral comparison engine implementing `compare_with_existing(project_id, existing_parcels_path, db=None, ...) -> CompareSummary`:
  - Vector loader (`load_vector_parcels`) for GeoJSON, Shapefile, and GeoPackage reference cadastral datasets.
  - Spatial comparison computing IoU, relative area difference %, Hausdorff boundary distance, and centroid displacement.
  - Classification into `matched` ($\ge 0.70$ IoU), `changed_parcel`, `new_parcel` (AI-detected only), and `missing_parcel` (existing GIS layer only).
  - Logs comparison findings to `issues` table and generates structured `CompareSummary` metrics.
- `backend/tests/test_topology.py` — 10 unit tests verifying all 8 topology checks, auto-repair, and standalone validation.
- `backend/tests/test_compare.py` — 4 unit and integration tests verifying matched, changed, new, missing, and GeoJSON file loading.
- All 59 backend tests passing (`pytest backend/tests/ -v`).
- Linters clean (`ruff check backend/ ml/`).

### Definition of done (Phase 6)
- [x] All 8 topology validation checks implemented and tested
- [x] Auto-repair mechanism with `make_valid`, sliver merging, and snapping
- [x] PostGIS issue persistence and `edit_history` logging
- [x] Comparison engine calculating IoU, area difference, Hausdorff distance, and classification
- [x] All 59 tests pass with zero errors

---

## Phase 7 — Accuracy, Export & Report ✅

**Completed:** 2026-09-30

### What was done
- `backend/app/services/accuracy.py` — Complete accuracy calculation service implementing `compute_accuracy(...) -> AccuracyReport`:
  - **Positional Accuracy:** Evaluates GNSS, CORS, and field checkpoints against nearest parcel boundary edges/vertices to compute Root Mean Square Error ($\text{RMSE}_{\text{horizontal}}$) and mean horizontal error in meters.
  - **Polygon IoU & F1 Metrics:** Calculates global spatial IoU, precision, recall, and object-level F1 scores for building footprints and parcel polygons vs Ground-Truth.
  - **Cadastral Topology Metrics:** Identifies `correct_parcels` (1-to-1 matches, $\text{IoU} \ge 0.70$), `merged_parcels` (1 AI parcel covering multiple GT parcels), and `split_parcels` (1 GT parcel fragmented across multiple AI parcels).
  - Enforces mandatory disclaimer: `"Preliminary — subject to field verification"`.
- `backend/app/services/export.py` — Multi-format spatial export engine implementing `export_dataset(...) -> Path`:
  - Supports **GeoJSON** (single combined FeatureCollection or per-layer features with `layer` properties).
  - Supports **GeoPackage (.gpkg)** with multiple named database tables/layers (`parcels`, `buildings`, `roads`, `landuse`, `issues`).
  - Supports **Shapefile (.zip)** archive containing `.shp`, `.shx`, `.dbf`, and `.prj` file bundles for each layer with column name shortening.
  - Supports **KML (.kml)** with structured `<Folder>` and `<Placemark>` styling for Google Earth and external Web-GIS platforms.
  - Automatic CRS reprojection to requested target coordinate system (default `EPSG:4326`).
- `backend/app/services/report.py` — Cadastral survey PDF reporting engine implementing `build_pdf_report(...) -> Path`:
  - Prominent red warning banner: `"⚠️ PRELIMINARY — SUBJECT TO FIELD VERIFICATION & GROUND TRUTHING"`.
  - Executive summary table with total parcels, total area in square meters and hectares, building counts, road counts, and mean confidence.
  - Accuracy metrics table with GNSS RMSE, mean horizontal error, building & parcel IoU/F1, and correct/merged/split parcel statistics.
  - Server-side vector map snapshot rendered via `matplotlib` (thematic dark mode canvas styling parcels, buildings, roads, and topology issue markers directly from local vector data without calling external Mapbox tile APIs).
  - Top 10 topology validation issues table with severity, type, and actionable suggested fixes.
- `backend/tests/test_accuracy.py` — 4 unit and integration tests verifying positional error, polygon IoU/F1, cadastral counts, and end-to-end report generation.
- `backend/tests/test_export.py` — 4 tests verifying GeoJSON, GeoPackage, Shapefile zip, and KML exports.
- `backend/tests/test_report.py` — Integration test verifying multi-page PDF generation, vector map rendering, and file integrity.
- All 68 backend tests passing (`pytest backend/tests/ -v`).
- Linters clean (`ruff check backend/ ml/`).

### Definition of done (Phase 7)
- [x] GNSS/CORS positional RMSE and mean horizontal error computation
- [x] Ground truth polygon IoU, F1, and correct/merged/split count evaluation
- [x] Multi-format GIS export engine (GeoJSON, GeoPackage, Shapefile, KML)
- [x] Cadastral survey PDF reporting engine with server-side vector map snapshot
- [x] Mandatory preliminary disclaimers present in reports and schema responses
- [x] All 68 tests pass with zero errors

---

## Phase 8 — API & Celery Pipeline ✅

**Completed:** 2026-09-30

### What was done
- `backend/app/workers/celery_app.py` — Celery instance configuration with Redis broker/backend and graceful mock task runner fallback for test environments without running Redis daemon.
- `backend/app/workers/tasks.py` — Asynchronous (`run_pipeline`) and synchronous (`execute_pipeline_sync`) end-to-end processing pipeline orchestrating:
  1. Ingest (CRS validation, raster alignment, float32 nDSM calculation, COG tiling)
  2. Inference (Probability COGs generation for buildings, roads, boundaries, land-use)
  3. Vectorization (Regularized buildings, road skeletons, 6-class land-use)
  4. Hybrid Parcel Builder (Watershed seeding, linework planar polygonization, cadastral rules, topological snapping, confidence scoring)
  5. Topology Validation (PostGIS rules, 8 validation checks, auto-repair, and `issues` logging)
  6. GIS Comparison (IoU, area difference, Hausdorff distance, `matched`/`changed`/`new`/`missing` classification)
  7. Accuracy Assessment (GNSS RMSE, horizontal error, Ground-Truth polygon IoU/F1)
- `backend/app/api/` — 11 production FastAPI router endpoints registered under `/api/v1`:
  - `projects.py`: `POST /projects`, `GET /projects`, `GET /projects/{id}`, `DELETE /projects/{id}`
  - `upload.py`: Multipart file ingest (`POST /projects/{id}/upload` for `ori`, `dsm`, `dtm`, `parcels`, `gt`)
  - `jobs.py`: Pipeline triggering and status monitoring (`POST /projects/{id}/run`, `GET /jobs/{id}`)
  - `parcels.py`: Interactive Web-GIS parcel queries and editing (`GET /projects/{id}/parcels`, `GET /parcels/{id}`, `PUT /parcels/{id}`, `DELETE /parcels/{id}`, `POST /parcels/merge`, `POST /parcels/{id}/split`) with optimistic locking and `edit_history` audit trail.
  - `issues.py`: Topology issue inspection and resolution (`POST /projects/{id}/validate`, `GET /projects/{id}/issues`, `PATCH /issues/{id}`)
  - `compare.py`: Cadastral layer comparison endpoint (`GET /projects/{id}/compare`)
  - `accuracy.py`: Accuracy assessment metrics endpoint (`GET /projects/{id}/accuracy`)
  - `export.py`: GIS data export (`GET /projects/{id}/export?format=geojson|gpkg|shp|kml`) and official cadastral survey PDF download (`GET /projects/{id}/report/pdf`)
  - `tiles.py`: Dynamic XYZ raster and vector tile URL resolver (`GET /projects/{id}/tiles`)
  - `context.py`: Google Earth Engine context checks (`GET /context/status`, `GET /context/landcover`, `GET /context/open-buildings`, `GET /context/dem`, `GET /context/sentinel`)
  - `field.py`: Field verification loop (`GET /projects/{id}/field-package`, `POST /projects/{id}/field-sync`)
- `backend/tests/test_api.py` — 6 comprehensive API integration tests with in-memory DB mock session.
- All 74 unit, integration, and API tests passing (`pytest backend/tests/ -v`).
- Linters clean (`ruff check backend/ ml/`).

### Definition of done (Phase 8)
- [x] End-to-end async pipeline wired in `backend/app/workers/tasks.py`
- [x] All 11 FastAPI router endpoints implemented under `/api/v1`
- [x] Interactive parcel editing endpoints (PUT, DELETE, merge, split) with `edit_history` audit logging
- [x] Integration tests for all API routes in `backend/tests/test_api.py`
- [x] All 74 backend tests pass with zero errors
- [x] Linters pass (`ruff check backend/ ml/`)

---

## Phase 9 — Mapbox & MapLibre Web-GIS Integration ✅

**Completed:** 2026-09-30

### What was done
- `frontend/src/map/provider.ts` — Enhanced `MapProvider` abstraction interface with:
  - Dynamic raster (TiTiler XYZ) and vector (Martin MVT) source management.
  - GeoJSON source data binding with optimistic updates.
  - Layer opacity & visibility controls (`setLayerOpacity`, `setLayerVisibility`).
  - Spatial camera controls (`flyTo`, `fitBounds`).
  - 3D visual terrain toggle (`enableTerrain`).
  - Map engine query (`isMapbox()`) and underlying instance getter (`getMapInstance()`).
  - Event listener registration (`on`, `off`).
- `frontend/src/map/mapboxProvider.ts` — Production Mapbox GL JS v3 implementation:
  - Sets public token (`mapboxgl.accessToken = VITE_MAPBOX_TOKEN`).
  - Default `satellite-streets-v12` basemap with switcher for `streets-v12`, `light-v11`, and offline dark mode.
  - 3D Terrain DEM integration (`mapbox://mapbox.mapbox-terrain-dem-v1` with 1.5x exaggeration).
  - Robust error listener detecting 401, 403, and 429 errors and calling `onFallback` to trigger graceful switch to MapLibre.
  - Curated, high-contrast dark-mode layer styling for cadastral parcels, regularized buildings, road corridors/centerlines, 6-class land-use, topology issue markers, and GNSS checkpoints.
- `frontend/src/map/maplibreProvider.ts` — Fully self-contained MapLibre GL JS fallback provider:
  - Operates completely offline with dark `#090d16` canvas and zero external API dependencies.
  - Identical layer rendering pipeline for TiTiler raster COGs, Martin vector tiles, and client-side GeoJSON features.
- `frontend/src/map/factory.ts` — Runtime map provider selection factory (`createProvider()`):
  - Automatically evaluates `VITE_MAP_PROVIDER` and `VITE_MAPBOX_TOKEN`.
  - Instantiates `MapboxProvider` when a public `pk.*` token is detected; automatically falls back to `MapLibreProvider` if absent or on runtime token failure.
- `frontend/src/map/layers.ts` & `basemaps.ts` — Comprehensive layer catalog, color palettes (LANDUSE_COLORS, ISSUE_COLORS), and basemap style configurations.
- `frontend/src/map/geocoding.ts` — Forward place search integration with Mapbox Geocoding API v6 (privacy-preserving viewport navigation).
- `frontend/src/map/swipeCompare.ts` — Horizontal split-screen curtain slider controller for comparing AI predictions against reference cadastral GIS layers.
- Verified TypeScript compilation (`npm run typecheck` passing with 0 errors) and production build (`npm run build` passing with 0 errors).

### Definition of done (Phase 9)
- [x] `MapProvider` interface fully implemented for both Mapbox GL JS and MapLibre GL JS
- [x] Default satellite-streets basemap with streets/light style switcher in Mapbox
- [x] Graceful automatic fallback to MapLibre on missing token or 401/403/429 errors
- [x] 3D terrain DEM visualization support
- [x] Privacy-preserving forward geocoding place search utility
- [x] Interactive swipe compare slider controller
- [x] Clean TypeScript typecheck (`tsc --noEmit`) and Vite production build (`vite build`)

---

## Phase 10 — UI Panels & Web-GIS Dashboard ✅

**Completed:** 2026-09-30

### What was done
- `frontend/src/api/types.ts` — Comprehensive TypeScript interfaces for all backend data models, summaries, and job status structures.
- `frontend/src/api/client.ts` — Full typed REST API client for projects, multipart uploads, async jobs, parcels, issues, accuracy, comparison, tiles, GEE context, and file downloads.
- `frontend/src/i18n/` — Complete tri-lingual localization dictionaries (`en.json`, `hi.json`, `pa.json`) with `react-i18next` initialization in `frontend/src/i18n/index.ts`.
- `frontend/src/panels/` — Implemented all 9 interactive Web-GIS panels:
  1. `Layers.tsx`: Category group headers, layer visibility checkboxes, opacity sliders, basemap picker, and 3D terrain toggle.
  2. `Issues.tsx`: Topology validation & encroachment list, severity badges, auto-repair trigger (`api.validateTopology`), click-to-zoom, and resolution patch (`api.patchIssue`).
  3. `ReviewQueue.tsx`: Parcels sorted by confidence ascending for rapid surveyor QA/QC, inspection bounds zoom, quick verification and flagging.
  4. `Stats.tsx`: Key metric tiles (total parcels, area in m²/ha, mean confidence, buildings), Chart.js land-use breakdown doughnut chart, and confidence distribution histogram.
  5. `Compare.tsx`: Cadastral comparison metrics (matched, changed, new, missing), divergent parcel list with IoU/shift metrics, and horizontal swipe compare curtain toggle.
  6. `Accuracy.tsx`: GNSS/CORS positional RMSE & mean horizontal error, building & parcel IoU/F1 scores, cadastral topology counts (1-to-1, merged, split), and mandatory preliminary disclaimer.
  7. `Context.tsx`: GEE connection status, Google Open Buildings benchmark (v3), Dynamic World 10m prior, and Sentinel-2 composite checks.
  8. `UploadWizard.tsx`: Project selector, new project creation modal (Name, CRS), multi-file upload inputs (ORI, DSM, DTM, existing parcels, GNSS points), and live pipeline execution monitor with progress bar.
  9. `Export.tsx`: Direct GIS downloads for GeoJSON, GeoPackage (.gpkg), Shapefile (.zip), KML (.kml), and official PDF Survey Report.
- `frontend/src/App.tsx` — Glassmorphism navbar with brand logo, project title, language switcher, geocoding search, floating panel dock, swipe curtain overlay, and preliminary verification disclaimer banner.
- Verified TypeScript compilation (`npm run typecheck` $\rightarrow$ 0 errors) and production build (`npm run build` $\rightarrow$ built in 10.47s).

### Definition of done (Phase 10)
- [x] All 9 UI panels fully implemented and integrated into Web-GIS dashboard
- [x] Multi-language localization (English, Hindi, Punjabi) active
- [x] Chart.js analytics for land-use distribution and confidence histograms
- [x] Live pipeline progress monitoring and stage logs
- [x] Clean TypeScript typecheck (`tsc --noEmit`) and Vite production build (`vite build`)
- [x] 74/74 backend tests passing with clean linters

---

## Phase 11 — Field Loop & Retraining (`field_sync.py`, `build_finetune_set.py`) (next)

**Scope:**
- `backend/app/services/field_sync.py`:
  - `generate_field_package(project_id) -> Path`: exports QField-ready GeoPackage with flagged low-confidence parcels and GNSS checkpoint layers.
  - `sync_field_package(project_id, gpkg_path) -> FieldSyncResult`: ingests returned QField survey packages, updates parcel verification status, logs surveyor notes/photos, and inserts new `gt_points`.
- `scripts/build_finetune_set.py`:
  - Active learning converter: converts surveyor-verified and edited parcels into 512x512 tile windows with rasterized multi-task training masks.
- Unit and integration tests in `backend/tests/test_field.py`.

**Needs from user:** None.
