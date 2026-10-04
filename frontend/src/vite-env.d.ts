/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_API_URL?: string;
  readonly VITE_MAPBOX_TOKEN?: string;
  readonly VITE_MAP_PROVIDER?: 'auto' | 'mapbox' | 'maplibre';
  readonly VITE_TITILER_URL?: string;
  readonly VITE_MARTIN_URL?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
