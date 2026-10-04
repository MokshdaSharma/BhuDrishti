# ParcelAI

> **Preliminary** — AI-Based Automated Urban Parcel Mapping Platform.
> All output is subject to field verification and not for legal or cadastral use.

---

## Quick start

```bash
# 1. Clone and copy environment files
git clone <repo-url>
cd BhuDrishti

cp .env.example .env
cp frontend/.env.example frontend/.env

# 2. Edit .env — change POSTGRES_PASSWORD at minimum
# Optionally set VITE_MAPBOX_TOKEN in frontend/.env (see docs)

# 3. Start all services
docker compose up -d --build

# 4. Verify
curl http://localhost:8000/api/v1/health   # → {"status":"ok",...}
open http://localhost:5173                 # → blank MapLibre map
```

## Services

| Service | URL | Purpose |
|---|---|---|
| api | http://localhost:8000 | FastAPI backend |
| frontend | http://localhost:5173 | React map UI |
| titiler | http://localhost:8080 | COG raster tiles |
| martin | http://localhost:3000 | PostGIS vector tiles |
| postgis | localhost:5432 | PostgreSQL + PostGIS |
| redis | localhost:6379 | Celery broker |

API docs: http://localhost:8000/api/docs

## Make targets

```bash
make up          # start all services (detached)
make down        # stop services
make clean       # stop + remove volumes (full reset)
make test        # run pytest inside api container
make lint        # ruff + black check
make fmt         # auto-format Python
make typecheck   # mypy
make check       # lint + typecheck + test
make demo        # (Phase 12) seed demo data + E2E
```

## Environment variables

See [`.env.example`](.env.example) (backend) and [`frontend/.env.example`](frontend/.env.example).  
Keys needed per phase:

| Key | Phase | Required |
|---|---|---|
| `POSTGRES_PASSWORD` | 0 | Yes |
| `VITE_MAPBOX_TOKEN` | 9 | No (MapLibre fallback works without it) |
| `ENABLE_GEE` + GEE keys | 8 | No (gracefully disabled) |

## Phase status

See [`docs/progress.md`](docs/progress.md).

## Specification

See [`AGENTS.md`](AGENTS.md) — the complete project specification.

## Data privacy

No private data (drone imagery, DSM/DTM, parcels, GNSS) ever leaves the machine.  
External network calls: Mapbox tile/basemap display only; GEE bounding box + public dataset IDs only.  
See Ground Rules in AGENTS.md §2.
