/**
 * MapLibre GL JS provider implementation (Section 7.10, 9.1).
 *
 * Used when:
 *  - VITE_MAP_PROVIDER=maplibre
 *  - VITE_MAP_PROVIDER=auto AND no Mapbox token is present
 *  - Mapbox token is present but emits 401/403/429 error
 *
 * Completely self-contained and operates with zero external network dependencies.
 */

import maplibregl from 'maplibre-gl';
import 'maplibre-gl/dist/maplibre-gl.css';

import { ISSUE_COLORS, LANDUSE_COLORS, LAYER_IDS } from './layers';
import type {
  BasemapName,
  GeoJSONSourceSpec,
  MapProvider,
  ProviderInitOptions,
  RasterSourceSpec,
  VectorSourceSpec,
} from './provider';

/** Minimal blank dark style — works fully offline with dark palette. */
const BLANK_DARK_STYLE: maplibregl.StyleSpecification = {
  version: 8,
  name: 'ParcelAI Blank Dark',
  sources: {},
  layers: [
    {
      id: 'background',
      type: 'background',
      paint: { 'background-color': '#090d16' },
    },
  ],
};

export class MapLibreProvider implements MapProvider {
  private map: maplibregl.Map | null = null;
  private isLoaded = false;
  private pendingActions: Array<() => void> = [];

  isMapbox(): boolean {
    return false;
  }

  getMapInstance(): maplibregl.Map | null {
    return this.map;
  }

  async init(options: ProviderInitOptions): Promise<void> {
    await new Promise<void>((resolve, reject) => {
      try {
        const m = new maplibregl.Map({
          container: options.container,
          style: BLANK_DARK_STYLE,
          center: options.center,
          zoom: options.zoom,
          attributionControl: { compact: true },
        });

        m.addControl(new maplibregl.NavigationControl(), 'top-right');
        m.addControl(new maplibregl.ScaleControl({ unit: 'metric' }), 'bottom-left');

        m.once('load', () => {
          this.map = m;
          this.isLoaded = true;
          this.pendingActions.forEach((fn) => fn());
          this.pendingActions = [];
          resolve();
        });

        m.once('error', (e) => {
          reject(e.error);
        });
      } catch (err) {
        reject(err);
      }
    });
  }

  private runWhenLoaded(action: () => void): void {
    if (this.isLoaded && this.map) {
      action();
    } else {
      this.pendingActions.push(action);
    }
  }

  addRasterSource(spec: RasterSourceSpec): void {
    this.runWhenLoaded(() => {
      if (!this.map) return;
      if (!this.map.getSource(spec.id)) {
        this.map.addSource(spec.id, {
          type: 'raster',
          tiles: [spec.url],
          tileSize: 256,
          attribution: spec.attribution ?? '',
        });
        this.map.addLayer({
          id: `${spec.id}-layer`,
          type: 'raster',
          source: spec.id,
          paint: { 'raster-opacity': spec.opacity ?? 1.0 },
        });
      }
    });
  }

  addVectorSource(spec: VectorSourceSpec): void {
    this.runWhenLoaded(() => {
      if (!this.map) return;
      if (!this.map.getSource(spec.id)) {
        this.map.addSource(spec.id, {
          type: 'vector',
          tiles: [spec.url],
        });
      }
    });
  }

  addGeoJSON(spec: GeoJSONSourceSpec): void {
    this.runWhenLoaded(() => {
      if (!this.map) return;
      const existing = this.map.getSource(spec.id) as maplibregl.GeoJSONSource | undefined;
      if (existing) {
        existing.setData(spec.data as GeoJSON.FeatureCollection);
      } else {
        this.map.addSource(spec.id, {
          type: 'geojson',
          data: spec.data as GeoJSON.FeatureCollection,
        });

        this._setupDefaultLayerStyles(spec.id);
      }
    });
  }

  private _setupDefaultLayerStyles(sourceId: string): void {
    if (!this.map) return;

    if (sourceId === LAYER_IDS.PARCELS_FILL || sourceId === 'parcels') {
      if (!this.map.getLayer(LAYER_IDS.PARCELS_FILL)) {
        this.map.addLayer({
          id: LAYER_IDS.PARCELS_FILL,
          type: 'fill',
          source: sourceId,
          paint: {
            'fill-color': [
              'case',
              ['>=', ['get', 'confidence'], 0.75],
              '#10b981',
              ['>=', ['get', 'confidence'], 0.45],
              '#38bdf8',
              '#f59e0b',
            ],
            'fill-opacity': 0.45,
          },
        });
      }
      if (!this.map.getLayer(LAYER_IDS.PARCELS_LINE)) {
        this.map.addLayer({
          id: LAYER_IDS.PARCELS_LINE,
          type: 'line',
          source: sourceId,
          paint: {
            'line-color': '#0284c7',
            'line-width': 2,
            'line-opacity': 0.9,
          },
        });
      }
    } else if (sourceId === LAYER_IDS.BUILDINGS_FILL || sourceId === 'buildings') {
      if (!this.map.getLayer(LAYER_IDS.BUILDINGS_FILL)) {
        this.map.addLayer({
          id: LAYER_IDS.BUILDINGS_FILL,
          type: 'fill',
          source: sourceId,
          paint: {
            'fill-color': '#6366f1',
            'fill-opacity': 0.75,
          },
        });
      }
      if (!this.map.getLayer(LAYER_IDS.BUILDINGS_LINE)) {
        this.map.addLayer({
          id: LAYER_IDS.BUILDINGS_LINE,
          type: 'line',
          source: sourceId,
          paint: {
            'line-color': '#4338ca',
            'line-width': 1.5,
          },
        });
      }
    } else if (sourceId === LAYER_IDS.ROADS_FILL || sourceId === 'roads') {
      if (!this.map.getLayer(LAYER_IDS.ROADS_FILL)) {
        this.map.addLayer({
          id: LAYER_IDS.ROADS_FILL,
          type: 'fill',
          source: sourceId,
          paint: {
            'fill-color': '#475569',
            'fill-opacity': 0.65,
          },
        });
      }
      if (!this.map.getLayer(LAYER_IDS.ROADS_CENTERLINE)) {
        this.map.addLayer({
          id: LAYER_IDS.ROADS_CENTERLINE,
          type: 'line',
          source: sourceId,
          paint: {
            'line-color': '#f59e0b',
            'line-width': 2,
            'line-dasharray': [3, 2],
          },
        });
      }
    } else if (sourceId === LAYER_IDS.LANDUSE || sourceId === 'landuse') {
      if (!this.map.getLayer(LAYER_IDS.LANDUSE)) {
        this.map.addLayer({
          id: LAYER_IDS.LANDUSE,
          type: 'fill',
          source: sourceId,
          paint: {
            'fill-color': [
              'match',
              ['get', 'landuse_class'],
              'built_up',
              LANDUSE_COLORS.built_up,
              'road',
              LANDUSE_COLORS.road,
              'vegetation',
              LANDUSE_COLORS.vegetation,
              'water',
              LANDUSE_COLORS.water,
              'open_land',
              LANDUSE_COLORS.open_land,
              LANDUSE_COLORS.other,
            ],
            'fill-opacity': 0.5,
          },
        });
      }
    } else if (sourceId === LAYER_IDS.ISSUES || sourceId === 'issues') {
      if (!this.map.getLayer(LAYER_IDS.ISSUES)) {
        this.map.addLayer({
          id: LAYER_IDS.ISSUES,
          type: 'circle',
          source: sourceId,
          paint: {
            'circle-color': [
              'match',
              ['get', 'severity'],
              'error',
              ISSUE_COLORS.error,
              'warning',
              ISSUE_COLORS.warning,
              ISSUE_COLORS.info,
            ],
            'circle-radius': 7,
            'circle-stroke-width': 2,
            'circle-stroke-color': '#ffffff',
          },
        });
      }
    } else if (sourceId === LAYER_IDS.GT_POINTS || sourceId === 'gt_points') {
      if (!this.map.getLayer(LAYER_IDS.GT_POINTS)) {
        this.map.addLayer({
          id: LAYER_IDS.GT_POINTS,
          type: 'circle',
          source: sourceId,
          paint: {
            'circle-color': '#06b6d4',
            'circle-radius': 6,
            'circle-stroke-width': 2,
            'circle-stroke-color': '#ffffff',
          },
        });
      }
    }
  }

  setBasemap(_name: BasemapName): void {
    console.info('[MapLibreProvider] Basemap switched; offline dark canvas maintained.');
  }

  flyTo(center: [number, number], zoom = 16): void {
    this.map?.flyTo({ center, zoom, duration: 1200, essential: true });
  }

  fitBounds(bounds: [number, number, number, number], padding = 40): void {
    if (!this.map) return;
    this.map.fitBounds(
      [
        [bounds[0], bounds[1]],
        [bounds[2], bounds[3]],
      ],
      { padding, duration: 1200 }
    );
  }

  setLayerOpacity(layerId: string, opacity: number): void {
    if (!this.map?.getLayer(layerId)) return;
    const layer = this.map.getLayer(layerId);
    const type = layer?.type;
    if (type === 'raster') {
      this.map.setPaintProperty(layerId, 'raster-opacity', opacity);
    } else if (type === 'fill') {
      this.map.setPaintProperty(layerId, 'fill-opacity', opacity);
    } else if (type === 'line') {
      this.map.setPaintProperty(layerId, 'line-opacity', opacity);
    } else if (type === 'circle') {
      this.map.setPaintProperty(layerId, 'circle-opacity', opacity);
    }
  }

  setLayerVisibility(layerId: string, visible: boolean): void {
    if (!this.map?.getLayer(layerId)) return;
    this.map.setLayoutProperty(layerId, 'visibility', visible ? 'visible' : 'none');
  }

  enableTerrain(_enabled: boolean): void {
    console.info('[MapLibreProvider] Visual terrain toggle not configured on local MapLibre.');
  }

  getDrawAdapter(): unknown | null {
    return null;
  }

  on(event: string, callback: (...args: any[]) => void): void {
    this.map?.on(event as any, callback as any);
  }

  off(event: string, callback: (...args: any[]) => void): void {
    this.map?.off(event as any, callback as any);
  }

  destroy(): void {
    this.map?.remove();
    this.map = null;
    this.isLoaded = false;
  }
}
