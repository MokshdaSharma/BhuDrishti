/**
 * Shared API TypeScript interfaces matching backend Pydantic schemas (Section 6, 7.9).
 */

export type ProjectStatus = 'pending' | 'processing' | 'done' | 'error';
export type ParcelStatus = 'draft' | 'reviewed' | 'verified';
export type ParcelSource = 'ai' | 'edited' | 'field' | 'existing';
export type IssueSeverity = 'info' | 'warning' | 'error';

export interface Project {
  id: number;
  name: string;
  crs: string;
  extent?: any;
  status: ProjectStatus;
  created_at: string;
}

export interface ProjectCreate {
  name: string;
  crs?: string;
}

export interface ParcelProperties {
  id: number;
  project_id: number;
  confidence: number | null;
  source: ParcelSource;
  status: ParcelStatus;
  area_m2: number | null;
  ladm_attrs: Record<string, any>;
  created_by: string | null;
  updated_at: string | null;
}

export interface ParcelFeature {
  type: 'Feature';
  id: number;
  geometry: GeoJSON.Polygon | GeoJSON.MultiPolygon;
  properties: ParcelProperties;
}

export interface ParcelCollection {
  type: 'FeatureCollection';
  features: ParcelFeature[];
}

export interface ParcelUpdate {
  geom?: any;
  confidence?: number;
  status?: ParcelStatus;
  ladm_attrs?: Record<string, any>;
}

export interface IssueProperties {
  id: number;
  project_id: number;
  issue_type: string;
  severity: IssueSeverity;
  suggested_fix: string | null;
  resolved: boolean;
  created_at: string;
}

export interface IssueFeature {
  type: 'Feature';
  id: number;
  geometry: GeoJSON.Geometry | null;
  properties: IssueProperties;
}

export interface IssueCollection {
  type: 'FeatureCollection';
  features: IssueFeature[];
}

export interface ValidationSummary {
  project_id: number;
  total_parcels: number;
  valid_parcels: number;
  issues_found: number;
  autofixed_count: number;
  issues_by_type: Record<string, number>;
}

export interface ChangedParcelDetail {
  id: number;
  status: 'matched' | 'changed_parcel' | 'new_parcel' | 'missing_parcel';
  iou: number;
  area_diff_pct: number;
  hausdorff_m: number;
  centroid_shift_m: number;
}

export interface CompareSummary {
  project_id: number;
  matched_count: number;
  new_count: number;
  missing_count: number;
  changed_count: number;
  details: ChangedParcelDetail[];
}

export interface AccuracyReport {
  project_id: number;
  rmse_horizontal_m: number | null;
  mean_horizontal_error_m: number | null;
  iou_buildings: number | null;
  f1_buildings: number | null;
  iou_parcels: number | null;
  f1_parcels: number | null;
  correct_parcels: number;
  merged_parcels: number;
  split_parcels: number;
  disclaimer: string;
}

export interface JobStatusResponse {
  job_id: string;
  status: 'QUEUED' | 'PROGRESS' | 'SUCCESS' | 'FAILURE';
  progress: number;
  message?: string;
  result?: Record<string, any>;
  error?: string;
}

export interface TilesResponse {
  project_id: number;
  raster_tiles: Record<string, string>;
  vector_tiles: Record<string, string>;
}

export interface ContextStatusResponse {
  gee_enabled: boolean;
  authenticated: boolean;
  available_layers: string[];
}

export interface HealthResponse {
  status: string;
  version: string;
  disclaimer: string;
  checks: Record<string, string>;
  timestamp: number;
}
