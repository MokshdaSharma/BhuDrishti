/**
 * Typed REST API client for ParcelAI backend (Section 7.9).
 */

import type {
  AccuracyReport,
  CompareSummary,
  ContextStatusResponse,
  HealthResponse,
  IssueCollection,
  IssueFeature,
  JobStatusResponse,
  ParcelCollection,
  ParcelFeature,
  ParcelUpdate,
  Project,
  ProjectCreate,
  TilesResponse,
  ValidationSummary,
} from './types';

const BASE_URL = import.meta.env.VITE_API_URL ?? 'http://localhost:8000';
const API_PREFIX = `${BASE_URL}/api/v1`;

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const url = `${API_PREFIX}${path}`;
  const headers = new Headers(options.headers || {});
  if (!headers.has('Content-Type') && !(options.body instanceof FormData)) {
    headers.set('Content-Type', 'application/json');
  }

  const res = await fetch(url, { ...options, headers });
  if (!res.ok) {
    let errorDetail = res.statusText;
    try {
      const errJson = await res.json();
      errorDetail = errJson.detail || errorDetail;
    } catch {
      // Keep statusText
    }
    throw new Error(`API Error [${res.status}]: ${errorDetail}`);
  }

  if (res.status === 204) {
    return {} as T;
  }

  return res.json();
}

export const api = {
  // System Health
  async getHealth(): Promise<HealthResponse> {
    return request<HealthResponse>('/health');
  },

  // Projects
  async listProjects(): Promise<Project[]> {
    return request<Project[]>('/projects');
  },

  async getProject(id: number): Promise<Project> {
    return request<Project>(`/projects/${id}`);
  },

  async createProject(payload: ProjectCreate): Promise<Project> {
    return request<Project>('/projects', {
      method: 'POST',
      body: JSON.stringify(payload),
    });
  },

  async deleteProject(id: number): Promise<void> {
    await request<void>(`/projects/${id}`, { method: 'DELETE' });
  },

  // File Upload
  async uploadData(projectId: number, kind: string, file: File): Promise<{ message: string; filename: string }> {
    const formData = new FormData();
    formData.append('kind', kind);
    formData.append('file', file);
    return request<{ message: string; filename: string }>(`/projects/${projectId}/upload`, {
      method: 'POST',
      body: formData,
    });
  },

  // Pipeline Execution & Jobs
  async runPipeline(projectId: number): Promise<{ job_id: string; status: string }> {
    return request<{ job_id: string; status: string }>(`/projects/${projectId}/run`, {
      method: 'POST',
    });
  },

  async getJobStatus(jobId: string): Promise<JobStatusResponse> {
    return request<JobStatusResponse>(`/jobs/${jobId}`);
  },

  // Parcels
  async getParcels(projectId: number, status?: string, minConfidence?: number): Promise<ParcelCollection> {
    const params = new URLSearchParams();
    if (status) params.set('status', status);
    if (minConfidence !== undefined) params.set('min_confidence', minConfidence.toString());
    const query = params.toString() ? `?${params.toString()}` : '';
    return request<ParcelCollection>(`/projects/${projectId}/parcels${query}`);
  },

  async updateParcel(parcelId: number, payload: ParcelUpdate): Promise<ParcelFeature> {
    return request<ParcelFeature>(`/parcels/${parcelId}`, {
      method: 'PUT',
      body: JSON.stringify(payload),
    });
  },

  async deleteParcel(parcelId: number): Promise<void> {
    await request<void>(`/parcels/${parcelId}`, { method: 'DELETE' });
  },

  async mergeParcels(parcelIds: number[]): Promise<ParcelFeature> {
    return request<ParcelFeature>('/parcels/merge', {
      method: 'POST',
      body: JSON.stringify({ parcel_ids: parcelIds }),
    });
  },

  async splitParcel(parcelId: number, lineGeoJSON: any): Promise<ParcelFeature[]> {
    return request<ParcelFeature[]>(`/parcels/${parcelId}/split`, {
      method: 'POST',
      body: JSON.stringify({ line: lineGeoJSON }),
    });
  },

  // Topology Issues
  async validateTopology(projectId: number, autofix = true): Promise<ValidationSummary> {
    return request<ValidationSummary>(`/projects/${projectId}/validate?autofix=${autofix}`, {
      method: 'POST',
    });
  },

  async getIssues(projectId: number, severity?: string, resolved?: boolean): Promise<IssueCollection> {
    const params = new URLSearchParams();
    if (severity) params.set('severity', severity);
    if (resolved !== undefined) params.set('resolved', resolved.toString());
    const query = params.toString() ? `?${params.toString()}` : '';
    return request<IssueCollection>(`/projects/${projectId}/issues${query}`);
  },

  async patchIssue(issueId: number, patch: { resolved?: boolean; suggested_fix?: string }): Promise<IssueFeature> {
    return request<IssueFeature>(`/issues/${issueId}`, {
      method: 'PATCH',
      body: JSON.stringify(patch),
    });
  },

  // Metrics, Comparison, & Accuracy
  async getComparison(projectId: number): Promise<CompareSummary> {
    return request<CompareSummary>(`/projects/${projectId}/compare`);
  },

  async getAccuracy(projectId: number): Promise<AccuracyReport> {
    return request<AccuracyReport>(`/projects/${projectId}/accuracy`);
  },

  // Tiles
  async getTiles(projectId: number): Promise<TilesResponse> {
    return request<TilesResponse>(`/projects/${projectId}/tiles`);
  },

  // Context (GEE)
  async getContextStatus(projectId: number): Promise<ContextStatusResponse> {
    return request<ContextStatusResponse>(`/projects/${projectId}/context/status`);
  },

  // Export URLs
  getExportUrl(projectId: number, format: 'geojson' | 'gpkg' | 'shp' | 'kml', crs = 'EPSG:4326'): string {
    return `${API_PREFIX}/projects/${projectId}/export?format=${format}&crs=${encodeURIComponent(crs)}`;
  },

  getPdfReportUrl(projectId: number): string {
    return `${API_PREFIX}/projects/${projectId}/report/pdf`;
  },
};
