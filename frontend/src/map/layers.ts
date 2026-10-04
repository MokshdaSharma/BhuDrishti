/**
 * Layer definitions, IDs, and visual styling properties (Section 7.10).
 *
 * Provides curated, harmonious theme styling for dark-mode Web-GIS visualization.
 */

export const LAYER_IDS = {
  // Raster layers (TiTiler & GEE)
  ORI: 'parcelai-ori',
  DSM: 'parcelai-dsm',
  NDSM: 'parcelai-ndsm',
  SENTINEL: 'parcelai-sentinel',
  DYN_WORLD: 'parcelai-dynamic-world',

  // Vector & GeoJSON layers
  LANDUSE: 'parcelai-landuse',
  PARCELS_FILL: 'parcelai-parcels-fill',
  PARCELS_LINE: 'parcelai-parcels-line',
  PARCELS_LABEL: 'parcelai-parcels-label',
  BUILDINGS_FILL: 'parcelai-buildings-fill',
  BUILDINGS_LINE: 'parcelai-buildings-line',
  ROADS_FILL: 'parcelai-roads-fill',
  ROADS_CENTERLINE: 'parcelai-roads-centerline',
  ISSUES: 'parcelai-issues',
  ISSUES_HEATMAP: 'parcelai-issues-heatmap',
  EXISTING_PARCELS: 'parcelai-existing-parcels',
  GT_POINTS: 'parcelai-gt-points',
} as const;

export type LayerId = (typeof LAYER_IDS)[keyof typeof LAYER_IDS];

export interface LayerMetadata {
  id: string;
  name: string;
  category: 'drone_rasters' | 'ai_vectors' | 'cadastral_rules' | 'ground_truth' | 'context';
  defaultVisible: boolean;
  defaultOpacity: number;
}

export const LAYER_CATALOG: LayerMetadata[] = [
  { id: LAYER_IDS.ORI, name: 'Orthorectified Imagery (ORI)', category: 'drone_rasters', defaultVisible: true, defaultOpacity: 1.0 },
  { id: LAYER_IDS.NDSM, name: 'Normalized DSM (nDSM Height)', category: 'drone_rasters', defaultVisible: false, defaultOpacity: 0.75 },
  { id: LAYER_IDS.DSM, name: 'Surface Model (DSM Hillshade)', category: 'drone_rasters', defaultVisible: false, defaultOpacity: 0.6 },
  { id: LAYER_IDS.PARCELS_FILL, name: 'Cadastral Parcels', category: 'ai_vectors', defaultVisible: true, defaultOpacity: 0.6 },
  { id: LAYER_IDS.BUILDINGS_FILL, name: 'Building Footprints', category: 'ai_vectors', defaultVisible: true, defaultOpacity: 0.8 },
  { id: LAYER_IDS.ROADS_FILL, name: 'Roads & Access Corridors', category: 'ai_vectors', defaultVisible: true, defaultOpacity: 0.7 },
  { id: LAYER_IDS.LANDUSE, name: 'Land-Use Classification', category: 'ai_vectors', defaultVisible: false, defaultOpacity: 0.5 },
  { id: LAYER_IDS.ISSUES, name: 'Topology & Encroachment Issues', category: 'cadastral_rules', defaultVisible: true, defaultOpacity: 1.0 },
  { id: LAYER_IDS.EXISTING_PARCELS, name: 'Existing GIS Cadastre', category: 'cadastral_rules', defaultVisible: false, defaultOpacity: 0.85 },
  { id: LAYER_IDS.GT_POINTS, name: 'GNSS / CORS Ground Truth', category: 'ground_truth', defaultVisible: true, defaultOpacity: 1.0 },
  { id: LAYER_IDS.SENTINEL, name: 'Sentinel-2 Context Composite', category: 'context', defaultVisible: false, defaultOpacity: 0.8 },
  { id: LAYER_IDS.DYN_WORLD, name: 'Dynamic World 10m Prior', category: 'context', defaultVisible: false, defaultOpacity: 0.6 },
];

/** Land-use class palette */
export const LANDUSE_COLORS: Record<string, string> = {
  built_up: '#e11d48',    // Rose
  road: '#64748b',        // Slate
  vegetation: '#16a34a',  // Emerald
  water: '#0284c7',       // Sky/Ocean
  open_land: '#d97706',   // Amber
  other: '#94a3b8',       // Muted slate
};

/** Topology issue colors by severity */
export const ISSUE_COLORS = {
  error: '#ef4444',       // Crimson red
  warning: '#f59e0b',     // Amber
  info: '#3b82f6',        // Electric blue
};
