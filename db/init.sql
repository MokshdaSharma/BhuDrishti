-- =============================================================================
-- ParcelAI — PostGIS initialisation
-- Runs once on first container start (mounted at /docker-entrypoint-initdb.d/)
-- Schema is managed via Alembic migrations.
-- =============================================================================

-- Enable PostGIS and spatial extensions
CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS postgis_raster;
CREATE EXTENSION IF NOT EXISTS postgis_topology;
CREATE EXTENSION IF NOT EXISTS fuzzystrmatch;        -- for Levenshtein / soundex
CREATE EXTENSION IF NOT EXISTS postgis_tiger_geocoder;

-- Ensure UUID support
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Helpful message
DO $$
BEGIN
    RAISE NOTICE 'ParcelAI PostGIS initialisation complete. Schema managed via Alembic in Phase 1.';
END $$;
