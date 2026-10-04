-- =============================================================================
-- ParcelAI — Topology Validation Rules & Triggers (PostGIS)
-- Specifications: AGENTS.md Sections 6 & 7.6
-- =============================================================================

-- ── 1. Parcel Edit History Trigger ──────────────────────────────────────────
CREATE OR REPLACE FUNCTION log_parcel_edit_history()
RETURNS TRIGGER AS $$
BEGIN
    IF (TG_OP = 'INSERT') THEN
        INSERT INTO edit_history (feature_table, feature_id, action, old_geom, new_geom, "user", ts)
        VALUES ('parcels', NEW.id, 'insert', NULL, NEW.geom, NEW.created_by, NOW());
        RETURN NEW;
    ELSIF (TG_OP = 'UPDATE') THEN
        IF NOT (OLD.geom ~= NEW.geom) THEN
            INSERT INTO edit_history (feature_table, feature_id, action, old_geom, new_geom, "user", ts)
            VALUES ('parcels', NEW.id, 'update', OLD.geom, NEW.geom, NEW.created_by, NOW());
        END IF;
        NEW.updated_at = NOW();
        RETURN NEW;
    ELSIF (TG_OP = 'DELETE') THEN
        INSERT INTO edit_history (feature_table, feature_id, action, old_geom, new_geom, "user", ts)
        VALUES ('parcels', OLD.id, 'delete', OLD.geom, NULL, OLD.created_by, NOW());
        RETURN OLD;
    END IF;
    RETURN NULL;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_parcels_edit_history ON parcels;
CREATE TRIGGER trg_parcels_edit_history
    AFTER INSERT OR UPDATE OR DELETE ON parcels
    FOR EACH ROW EXECUTE FUNCTION log_parcel_edit_history();


-- ── 2. Topology Check: Invalid Geometry ─────────────────────────────────────
CREATE OR REPLACE FUNCTION check_invalid_geometries(p_project_id INTEGER)
RETURNS INTEGER AS $$
DECLARE
    v_count INTEGER := 0;
BEGIN
    INSERT INTO issues (project_id, type, severity, geom, suggested_fix, resolved)
    SELECT
        p.project_id,
        'invalid_geometry'::issue_type_enum,
        'error'::issue_severity,
        p.geom,
        'Run ST_MakeValid: ' || ST_IsValidReason(p.geom),
        FALSE
    FROM parcels p
    WHERE p.project_id = p_project_id
      AND NOT ST_IsValid(p.geom);

    GET DIAGNOSTICS v_count = ROW_COUNT;
    RETURN v_count;
END;
$$ LANGUAGE plpgsql;


-- ── 3. Topology Check: Overlaps ──────────────────────────────────────────────
CREATE OR REPLACE FUNCTION check_overlaps(p_project_id INTEGER, p_min_overlap_area FLOAT DEFAULT 1.0)
RETURNS INTEGER AS $$
DECLARE
    v_count INTEGER := 0;
BEGIN
    INSERT INTO issues (project_id, type, severity, geom, suggested_fix, resolved)
    SELECT
        a.project_id,
        'overlap'::issue_type_enum,
        'error'::issue_severity,
        ST_Intersection(a.geom, b.geom),
        'Merge overlap between parcel ' || a.id || ' and ' || b.id,
        FALSE
    FROM parcels a
    JOIN parcels b ON a.project_id = b.project_id
                  AND a.id < b.id
                  AND ST_Overlaps(a.geom, b.geom)
    WHERE a.project_id = p_project_id
      AND ST_Area(ST_Intersection(a.geom, b.geom)) >= p_min_overlap_area;

    GET DIAGNOSTICS v_count = ROW_COUNT;
    RETURN v_count;
END;
$$ LANGUAGE plpgsql;


-- ── 4. Topology Check: Gaps ──────────────────────────────────────────────────
CREATE OR REPLACE FUNCTION check_gaps(p_project_id INTEGER, p_max_gap_area FLOAT DEFAULT 50.0)
RETURNS INTEGER AS $$
DECLARE
    v_count INTEGER := 0;
BEGIN
    -- Detect interior holes / gaps within the parcel cluster
    WITH union_parcels AS (
        SELECT ST_Union(geom) AS geom
        FROM parcels
        WHERE project_id = p_project_id
    ),
    holes AS (
        SELECT (ST_Dump(ST_Difference(ST_ConvexHull(u.geom), u.geom))).geom AS geom
        FROM union_parcels u
    )
    INSERT INTO issues (project_id, type, severity, geom, suggested_fix, resolved)
    SELECT
        p_project_id,
        'gap'::issue_type_enum,
        'warning'::issue_severity,
        h.geom,
        'Fill or snap parcel boundary across detected gap',
        FALSE
    FROM holes h
    WHERE ST_Area(h.geom) <= p_max_gap_area;

    GET DIAGNOSTICS v_count = ROW_COUNT;
    RETURN v_count;
END;
$$ LANGUAGE plpgsql;


-- ── 5. Topology Check: Slivers ───────────────────────────────────────────────
CREATE OR REPLACE FUNCTION check_slivers(p_project_id INTEGER, p_max_area FLOAT DEFAULT 10.0, p_max_compactness FLOAT DEFAULT 0.05)
RETURNS INTEGER AS $$
DECLARE
    v_count INTEGER := 0;
BEGIN
    INSERT INTO issues (project_id, type, severity, geom, suggested_fix, resolved)
    SELECT
        p.project_id,
        'sliver'::issue_type_enum,
        'warning'::issue_severity,
        p.geom,
        'Merge sliver parcel ' || p.id || ' with adjacent parcel sharing longest boundary',
        FALSE
    FROM parcels p
    WHERE p.project_id = p_project_id
      AND p.area_m2 <= p_max_area
      AND (4.0 * PI() * ST_Area(p.geom) / NULLIF(ST_Perimeter(p.geom)^2, 0)) <= p_max_compactness;

    GET DIAGNOSTICS v_count = ROW_COUNT;
    RETURN v_count;
END;
$$ LANGUAGE plpgsql;


-- ── 6. Cross-Layer Check: Building Crosses Parcel ───────────────────────────
CREATE OR REPLACE FUNCTION check_building_crosses_parcel(p_project_id INTEGER)
RETURNS INTEGER AS $$
DECLARE
    v_count INTEGER := 0;
BEGIN
    INSERT INTO issues (project_id, type, severity, geom, suggested_fix, resolved)
    SELECT
        b.project_id,
        'building_crosses_parcel'::issue_type_enum,
        'error'::issue_severity,
        b.geom,
        'Building ' || b.id || ' straddles multiple parcels. Adjust parcel boundary or merge parcels.',
        FALSE
    FROM buildings b
    WHERE b.project_id = p_project_id
      AND (
          SELECT COUNT(DISTINCT p.id)
          FROM parcels p
          WHERE p.project_id = b.project_id
            AND ST_Intersects(b.geom, p.geom)
            AND ST_Area(ST_Intersection(b.geom, p.geom)) > 1.0
      ) > 1;

    GET DIAGNOSTICS v_count = ROW_COUNT;
    RETURN v_count;
END;
$$ LANGUAGE plpgsql;


-- ── 7. Cross-Layer Check: Building On Road (Encroachment) ───────────────────
CREATE OR REPLACE FUNCTION check_building_on_road(p_project_id INTEGER)
RETURNS INTEGER AS $$
DECLARE
    v_count INTEGER := 0;
BEGIN
    INSERT INTO issues (project_id, type, severity, geom, suggested_fix, resolved)
    SELECT
        b.project_id,
        'building_on_road'::issue_type_enum,
        'warning'::issue_severity,
        ST_Intersection(b.geom, r.geom),
        'Building ' || b.id || ' encroaches onto road ' || r.id,
        FALSE
    FROM buildings b
    JOIN roads r ON b.project_id = r.project_id AND ST_Intersects(b.geom, r.geom)
    WHERE b.project_id = p_project_id
      AND ST_Area(ST_Intersection(b.geom, r.geom)) > 0.5;

    GET DIAGNOSTICS v_count = ROW_COUNT;
    RETURN v_count;
END;
$$ LANGUAGE plpgsql;


-- ── 8. Access Check: Landlocked Parcel ──────────────────────────────────────
CREATE OR REPLACE FUNCTION check_landlocked_parcels(p_project_id INTEGER, p_buffer_m FLOAT DEFAULT 1.0)
RETURNS INTEGER AS $$
DECLARE
    v_count INTEGER := 0;
BEGIN
    INSERT INTO issues (project_id, type, severity, geom, suggested_fix, resolved)
    SELECT
        p.project_id,
        'landlocked_parcel'::issue_type_enum,
        'warning'::issue_severity,
        p.geom,
        'Parcel ' || p.id || ' does not touch any road or pathway',
        FALSE
    FROM parcels p
    WHERE p.project_id = p_project_id
      AND NOT EXISTS (
          SELECT 1
          FROM roads r
          WHERE r.project_id = p.project_id
            AND ST_DWithin(p.geom, r.geom, p_buffer_m)
      );

    GET DIAGNOSTICS v_count = ROW_COUNT;
    RETURN v_count;
END;
$$ LANGUAGE plpgsql;


-- ── 9. Auto-Fix Procedure for Trivial Topology Issues ────────────────────────
CREATE OR REPLACE FUNCTION autofix_project_topology(p_project_id INTEGER)
RETURNS INTEGER AS $$
DECLARE
    v_fixed INTEGER := 0;
BEGIN
    -- Auto-fix 1: ST_MakeValid on invalid geometries
    UPDATE parcels
    SET geom = ST_CollectionExtract(ST_MakeValid(geom), 3)
    WHERE project_id = p_project_id
      AND NOT ST_IsValid(geom);

    GET DIAGNOSTICS v_fixed = ROW_COUNT;

    -- Auto-fix 2: Remove duplicate / spike vertices with ST_SimplifyPreserveTopology
    UPDATE parcels
    SET geom = ST_SimplifyPreserveTopology(geom, 0.01)
    WHERE project_id = p_project_id;

    RETURN v_fixed;
END;
$$ LANGUAGE plpgsql;


-- ── 10. Main Orchestration Validation Function ──────────────────────────────
CREATE OR REPLACE FUNCTION validate_project_topology(p_project_id INTEGER, p_autofix BOOLEAN DEFAULT FALSE)
RETURNS TABLE (
    invalid_geometries INTEGER,
    overlaps INTEGER,
    gaps INTEGER,
    slivers INTEGER,
    building_crosses INTEGER,
    building_on_roads INTEGER,
    landlocked INTEGER,
    autofixed INTEGER
) AS $$
DECLARE
    v_autofixed INTEGER := 0;
    v_invalid INTEGER := 0;
    v_overlaps INTEGER := 0;
    v_gaps INTEGER := 0;
    v_slivers INTEGER := 0;
    v_bldg_cross INTEGER := 0;
    v_bldg_road INTEGER := 0;
    v_landlocked INTEGER := 0;
BEGIN
    -- Clean previous open issues for this project
    DELETE FROM issues WHERE project_id = p_project_id AND NOT resolved;

    IF p_autofix THEN
        v_autofixed := autofix_project_topology(p_project_id);
    END IF;

    v_invalid := check_invalid_geometries(p_project_id);
    v_overlaps := check_overlaps(p_project_id);
    v_gaps := check_gaps(p_project_id);
    v_slivers := check_slivers(p_project_id);
    v_bldg_cross := check_building_crosses_parcel(p_project_id);
    v_bldg_road := check_building_on_road(p_project_id);
    v_landlocked := check_landlocked_parcels(p_project_id);

    RETURN QUERY SELECT
        v_invalid,
        v_overlaps,
        v_gaps,
        v_slivers,
        v_bldg_cross,
        v_bldg_road,
        v_landlocked,
        v_autofixed;
END;
$$ LANGUAGE plpgsql;
