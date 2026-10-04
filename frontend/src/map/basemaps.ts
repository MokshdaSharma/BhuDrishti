/** Basemap definitions — Phase 9 will fill in Mapbox style URLs. */

export interface BasemapDef {
  id: string;
  label: string;
  /** Style URL (Mapbox) or null if not available for this provider. */
  mapboxStyle: string | null;
  /** MapLibre self-hosted style URL or null if using blank style. */
  maplibreStyle: string | null;
}

export const BASEMAPS: BasemapDef[] = [
  {
    id: 'satellite-streets',
    label: 'Satellite + Streets',
    mapboxStyle: 'mapbox://styles/mapbox/satellite-streets-v12',
    maplibreStyle: null,
  },
  {
    id: 'streets',
    label: 'Streets',
    mapboxStyle: 'mapbox://styles/mapbox/streets-v12',
    maplibreStyle: null,
  },
  {
    id: 'light',
    label: 'Light',
    mapboxStyle: 'mapbox://styles/mapbox/light-v11',
    maplibreStyle: null,
  },
  {
    id: 'none',
    label: 'No basemap',
    mapboxStyle: null,
    maplibreStyle: null,
  },
];
