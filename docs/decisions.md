# Design decisions log

All architectural choices that deviate from or extend the spec are recorded here.
Format: `## Decision N — Title`, date, context, choice, rationale, consequences.

---

## Decision A1 — Terra Draw adapter packages

**Date:** Phase 0  
**Context:** AGENTS.md §9.1 lists `terra-draw-mapbox-gl-adapter` and `terra-draw-maplibre-gl-adapter` as separate npm packages.  
**Finding:** As of terra-draw ≥1.0, both adapters ship inside the main `terra-draw` package; no separate packages exist on npm.  
**Choice:** Import `TerraDrawMapboxGLAdapter` and `TerraDrawMapLibreGLAdapter` directly from `terra-draw`.  
**Consequence:** One fewer dependency; adapter API matches current terra-draw docs.

---

## Decision A5 — report.py location

**Date:** Phase 0  
**Context:** Section 7.8 references `services/report.py` but Section 4's tree omits it.  
**Choice:** Create `backend/app/services/report.py` (Section 7.8 is authoritative).

---

## Decision A6 — Parcel merge/split route paths

**Date:** Phase 0  
**Context:** Section 7.9 lists `POST /parcels/merge` and `POST /parcels/split` without a project prefix.  
**Choice:** Use `/api/v1/projects/{id}/parcels/merge` and `/api/v1/projects/{id}/parcels/split` for consistency with all sibling endpoints.

---

## Decision A8 — PDF report library

**Date:** Phase 0  
**Context:** Section 5 lists "WeasyPrint or ReportLab" without choosing.  
**Choice:** **ReportLab** (pure Python wheel, no system GTK/cairo deps, works in a slim Docker image).  
**Consequence:** PDF output uses ReportLab's canvas API; HTML→PDF is not available without additional work.

---

## Decision A9 — Repo root mapping

**Date:** Phase 0  
**Context:** Section 4 shows the repo root as `parcelai/` but the workspace is `BhuDrishti/`.  
**Choice:** Treat the workspace root (`BhuDrishti/`) as the `parcelai/` root; all paths are relative to it.

---

## Decision A10 — Makefile `demo` stub

**Date:** Phase 0  
**Context:** Phase 0 creates the Makefile but `make demo` (seed_demo.py + Playwright E2E) is Phase 12 scope.  
**Choice:** `make demo` prints "Not yet implemented" in Phase 0. Phase 12 fills it in.
