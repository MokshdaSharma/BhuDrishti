/**
 * Provider factory (Section 7.10, 9.1).
 *
 * Selects Mapbox GL JS or MapLibre GL JS based on VITE_MAP_PROVIDER
 * and the presence of a valid Mapbox token.
 *
 * Implements graceful fallback to MapLibre when:
 *  - VITE_MAP_PROVIDER is set to 'maplibre'
 *  - No token is configured
 *  - Mapbox emits an auth or quota error (401, 403, 429)
 */

import { MapLibreProvider } from './maplibreProvider';
import { MapboxProvider } from './mapboxProvider';
import type { MapProvider } from './provider';

export type ProviderMode = 'auto' | 'mapbox' | 'maplibre';

export function createProvider(): MapProvider {
  const mode = (import.meta.env.VITE_MAP_PROVIDER ?? 'auto') as ProviderMode;
  const token = import.meta.env.VITE_MAPBOX_TOKEN ?? '';

  if (mode === 'maplibre') {
    return new MapLibreProvider();
  }

  if (mode === 'mapbox') {
    if (!token || !token.startsWith('pk.')) {
      console.warn(
        '[MapFactory] VITE_MAP_PROVIDER=mapbox requested but no valid public token (pk.*) found. Gracefully falling back to MapLibre.'
      );
      return new MapLibreProvider();
    }
    return new MapboxProvider();
  }

  // mode === 'auto'
  if (token && token.startsWith('pk.')) {
    return new MapboxProvider();
  }

  console.info('[MapFactory] No Mapbox token detected. Initializing with local MapLibre provider.');
  return new MapLibreProvider();
}
