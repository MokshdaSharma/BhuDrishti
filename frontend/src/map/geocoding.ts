/**
 * Mapbox Geocoding API v6 search integration (Section 9.1).
 *
 * Used only to fly the map viewport to search results.
 * Ground rule 2: Private drone/cadastral data is never sent to external search APIs.
 */

export interface GeocodingResult {
  id: string;
  name: string;
  formatted_address: string;
  coordinates: [number, number]; // [lng, lat]
  bbox?: [number, number, number, number];
}

export async function searchPlaces(
  query: string,
  proximity?: [number, number]
): Promise<GeocodingResult[]> {
  const token = import.meta.env.VITE_MAPBOX_TOKEN;
  if (!token || !token.startsWith('pk.') || !query.trim()) {
    return [];
  }

  const endpoint = new URL('https://api.mapbox.com/search/geocode/v6/forward');
  endpoint.searchParams.set('q', query.trim());
  endpoint.searchParams.set('access_token', token);
  endpoint.searchParams.set('limit', '5');

  if (proximity) {
    endpoint.searchParams.set('proximity', `${proximity[0]},${proximity[1]}`);
  }

  try {
    const res = await fetch(endpoint.toString());
    if (!res.ok) {
      console.warn(`[Geocoding] Place search failed with status: ${res.status}`);
      return [];
    }
    const data = await res.json();
    if (!data.features) return [];

    return data.features.map((f: any) => ({
      id: f.id ?? f.properties?.mapbox_id ?? Math.random().toString(),
      name: f.properties?.name ?? f.properties?.name_preferred ?? 'Unknown',
      formatted_address: f.properties?.full_address ?? f.properties?.place_formatted ?? '',
      coordinates: f.geometry?.coordinates as [number, number],
      bbox: f.properties?.bbox as [number, number, number, number] | undefined,
    }));
  } catch (err) {
    console.warn('[Geocoding] Network error during place search:', err);
    return [];
  }
}
