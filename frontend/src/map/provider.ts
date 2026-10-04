/**
 * Map provider abstraction (Section 7.10).
 *
 * Both Mapbox GL JS and MapLibre GL JS implementations satisfy this
 * interface so that all map interactions go through a single API and the
 * provider can be swapped transparently.
 */

/** A source ID plus a TiTiler XYZ URL template. */
export interface RasterSourceSpec {
  id: string;
  url: string; // e.g. http://titiler:8000/cog/tiles/{z}/{x}/{y}
  attribution?: string;
  opacity?: number;
}

/** A source ID plus a Martin vector tile URL template. */
export interface VectorSourceSpec {
  id: string;
  url: string; // e.g. http://martin:3000/{source}/{z}/{x}/{y}
  sourceLayer: string;
}

/** GeoJSON source for client-side features (GT points, debug overlays). */
export interface GeoJSONSourceSpec {
  id: string;
  data: GeoJSON.FeatureCollection | GeoJSON.Feature | string | any;
}

/** Named basemap style. */
export type BasemapName = 'satellite-streets' | 'streets' | 'light' | 'none';

/** Options passed to init(). */
export interface ProviderInitOptions {
  container: string | HTMLElement;
  center: [number, number]; // [lng, lat]
  zoom: number;
  basemap?: BasemapName;
  onFallback?: (reason: string) => void;
}

/**
 * Map provider interface.
 * All coordinates are [lng, lat] (GeoJSON order).
 */
export interface MapProvider {
  /** Initialise the map and mount it to the DOM. */
  init(options: ProviderInitOptions): Promise<void>;

  /** Add a COG raster tile source (TiTiler). */
  addRasterSource(spec: RasterSourceSpec): void;

  /** Add a PostGIS vector tile source (Martin). */
  addVectorSource(spec: VectorSourceSpec): void;

  /** Add or update a GeoJSON source. */
  addGeoJSON(spec: GeoJSONSourceSpec): void;

  /** Switch the basemap style. */
  setBasemap(name: BasemapName): void;

  /** Fly the camera to a position. */
  flyTo(center: [number, number], zoom?: number): void;

  /** Fit the camera to a bounding box [minLng, minLat, maxLng, maxLat]. */
  fitBounds(bounds: [number, number, number, number], padding?: number): void;

  /** Set the opacity of a named layer (0–1). */
  setLayerOpacity(layerId: string, opacity: number): void;

  /** Toggle visibility of a named layer. */
  setLayerVisibility(layerId: string, visible: boolean): void;

  /**
   * Enable/disable 3D terrain (visual only — not survey DSM).
   * No-op on providers that do not support it.
   */
  enableTerrain(enabled: boolean): void;

  /** Return true if currently using Mapbox engine. */
  isMapbox(): boolean;

  /** Return the underlying map instance (mapboxgl.Map or maplibregl.Map). */
  getMapInstance(): unknown;

  /** Return a Terra Draw adapter compatible with this provider. */
  getDrawAdapter(): unknown | null;

  /** Subscribe to map events (click, moveend, etc.). */
  on(event: string, callback: (...args: any[]) => void): void;

  /** Unsubscribe from map events. */
  off(event: string, callback: (...args: any[]) => void): void;

  /** Remove the map and clean up all resources. */
  destroy(): void;
}
