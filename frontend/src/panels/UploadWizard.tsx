/**
 * UploadWizard — Project creation, raster/vector ingest, and live pipeline monitoring (Section 7.10).
 */

import React, { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { api } from '../api/client';
import type { JobStatusResponse, Project } from '../api/types';

interface UploadWizardProps {
  currentProject: Project | null;
  onProjectChange: (project: Project) => void;
  onPipelineCompleted: () => void;
}

export const UploadWizard: React.FC<UploadWizardProps> = ({
  currentProject,
  onProjectChange,
  onPipelineCompleted,
}) => {
  const { t } = useTranslation();
  const [projects, setProjects] = useState<Project[]>([]);
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [newProjectName, setNewProjectName] = useState('');
  const [newProjectCrs, setNewProjectCrs] = useState('EPSG:32643');
  const [isCreating, setIsCreating] = useState(false);

  // File states
  const [oriFile, setOriFile] = useState<File | null>(null);
  const [dsmFile, setDsmFile] = useState<File | null>(null);
  const [dtmFile, setDtmFile] = useState<File | null>(null);
  const [parcelsFile, setParcelsFile] = useState<File | null>(null);
  const [gtFile, setGtFile] = useState<File | null>(null);
  const [uploading, setUploading] = useState(false);
  const [uploadProgress, setUploadProgress] = useState<string | null>(null);

  // Job states
  const [currentJobId, setCurrentJobId] = useState<string | null>(null);
  const [jobStatus, setJobStatus] = useState<JobStatusResponse | null>(null);

  const fetchProjectsList = async () => {
    try {
      const list = await api.listProjects();
      setProjects(list);
      if (list.length > 0 && !currentProject) {
        onProjectChange(list[0]);
      }
    } catch (err) {
      console.error('Failed to list projects:', err);
    }
  };

  useEffect(() => {
    fetchProjectsList();
  }, []);

  // Poll active pipeline job
  useEffect(() => {
    if (!currentJobId) return;
    const interval = setInterval(async () => {
      try {
        const res = await api.getJobStatus(currentJobId);
        setJobStatus(res);
        if (res.status === 'SUCCESS' || res.status === 'FAILURE') {
          clearInterval(interval);
          if (res.status === 'SUCCESS') {
            onPipelineCompleted();
          }
        }
      } catch (err) {
        console.error('Job polling error:', err);
      }
    }, 2000);

    return () => clearInterval(interval);
  }, [currentJobId]);

  const handleCreateProject = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newProjectName.trim()) return;
    setIsCreating(true);
    try {
      const created = await api.createProject({
        name: newProjectName.trim(),
        crs: newProjectCrs.trim(),
      });
      setProjects((prev) => [created, ...prev]);
      onProjectChange(created);
      setShowCreateModal(false);
      setNewProjectName('');
    } catch (err) {
      console.error('Failed to create project:', err);
    } finally {
      setIsCreating(false);
    }
  };

  const handleUploadAll = async () => {
    if (!currentProject) return;
    setUploading(true);
    setUploadProgress('Uploading files...');

    try {
      if (oriFile) {
        setUploadProgress('Uploading ORI GeoTIFF...');
        await api.uploadData(currentProject.id, 'ori', oriFile);
      }
      if (dsmFile) {
        setUploadProgress('Uploading DSM GeoTIFF...');
        await api.uploadData(currentProject.id, 'dsm', dsmFile);
      }
      if (dtmFile) {
        setUploadProgress('Uploading DTM GeoTIFF...');
        await api.uploadData(currentProject.id, 'dtm', dtmFile);
      }
      if (parcelsFile) {
        setUploadProgress('Uploading reference GIS parcels...');
        await api.uploadData(currentProject.id, 'parcels', parcelsFile);
      }
      if (gtFile) {
        setUploadProgress('Uploading GNSS ground truth points...');
        await api.uploadData(currentProject.id, 'gt', gtFile);
      }
      setUploadProgress('All files uploaded successfully!');
    } catch (err: any) {
      console.error('Upload failed:', err);
      setUploadProgress(`Upload error: ${err.message}`);
    } finally {
      setUploading(false);
    }
  };

  const handleRunPipeline = async () => {
    if (!currentProject) return;
    try {
      const res = await api.runPipeline(currentProject.id);
      setCurrentJobId(res.job_id);
      setJobStatus({ job_id: res.job_id, status: 'QUEUED', progress: 5, message: 'Pipeline queued' });
    } catch (err) {
      console.error('Failed to trigger pipeline:', err);
    }
  };

  return (
    <div className="space-y-5 text-slate-200">
      {/* Project Selector Bar */}
      <div className="p-4 bg-slate-800/60 rounded-xl border border-slate-700/60 shadow-lg space-y-3">
        <div className="flex items-center justify-between">
          <label className="text-xs font-semibold text-white uppercase tracking-wider">
            {t('upload.select_project')}
          </label>
          <button
            onClick={() => setShowCreateModal(true)}
            className="px-2.5 py-1 text-xs font-semibold bg-cyan-600 hover:bg-cyan-500 text-white rounded-lg transition-colors flex items-center gap-1 shadow-sm"
          >
            <span>+</span> {t('upload.create_project')}
          </button>
        </div>

        <select
          value={currentProject?.id ?? ''}
          onChange={(e) => {
            const found = projects.find((p) => p.id === Number(e.target.value));
            if (found) onProjectChange(found);
          }}
          className="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-xs text-white focus:outline-none focus:border-cyan-400 font-medium"
        >
          {projects.map((p) => (
            <option key={p.id} value={p.id}>
              #{p.id} — {p.name} ({p.crs}) • {p.status.toUpperCase()}
            </option>
          ))}
        </select>
      </div>

      {/* Upload Inputs Card */}
      <div className="p-4 bg-slate-800/60 rounded-xl border border-slate-700/60 shadow-lg space-y-3.5">
        <h4 className="text-xs font-semibold uppercase tracking-wider text-slate-300">
          Drone Imagery & Vector Layers
        </h4>

        {/* ORI Upload */}
        <div className="space-y-1">
          <span className="text-[11px] font-medium text-slate-300 flex items-center gap-1">
            {t('upload.ori_label')} <span className="text-rose-400">*</span>
          </span>
          <input
            type="file"
            accept=".tif,.tiff"
            onChange={(e) => setOriFile(e.target.files?.[0] ?? null)}
            className="block w-full text-xs text-slate-400 file:mr-3 file:py-1.5 file:px-3 file:rounded-lg file:border-0 file:text-xs file:font-semibold file:bg-slate-700 file:text-cyan-300 hover:file:bg-slate-600 cursor-pointer bg-slate-900/60 rounded-lg border border-slate-800"
          />
        </div>

        {/* DSM Upload */}
        <div className="space-y-1">
          <span className="text-[11px] font-medium text-slate-300 flex items-center gap-1">
            {t('upload.dsm_label')} <span className="text-rose-400">*</span>
          </span>
          <input
            type="file"
            accept=".tif,.tiff"
            onChange={(e) => setDsmFile(e.target.files?.[0] ?? null)}
            className="block w-full text-xs text-slate-400 file:mr-3 file:py-1.5 file:px-3 file:rounded-lg file:border-0 file:text-xs file:font-semibold file:bg-slate-700 file:text-cyan-300 hover:file:bg-slate-600 cursor-pointer bg-slate-900/60 rounded-lg border border-slate-800"
          />
        </div>

        {/* DTM Upload */}
        <div className="space-y-1">
          <span className="text-[11px] font-medium text-slate-400">{t('upload.dtm_label')}</span>
          <input
            type="file"
            accept=".tif,.tiff"
            onChange={(e) => setDtmFile(e.target.files?.[0] ?? null)}
            className="block w-full text-xs text-slate-400 file:mr-3 file:py-1.5 file:px-3 file:rounded-lg file:border-0 file:text-xs file:font-semibold file:bg-slate-700 file:text-cyan-300 hover:file:bg-slate-600 cursor-pointer bg-slate-900/60 rounded-lg border border-slate-800"
          />
        </div>

        {/* Reference GIS Parcels Upload */}
        <div className="space-y-1">
          <span className="text-[11px] font-medium text-slate-400">{t('upload.parcels_label')}</span>
          <input
            type="file"
            accept=".geojson,.json,.gpkg,.shp,.zip"
            onChange={(e) => setParcelsFile(e.target.files?.[0] ?? null)}
            className="block w-full text-xs text-slate-400 file:mr-3 file:py-1.5 file:px-3 file:rounded-lg file:border-0 file:text-xs file:font-semibold file:bg-slate-700 file:text-cyan-300 hover:file:bg-slate-600 cursor-pointer bg-slate-900/60 rounded-lg border border-slate-800"
          />
        </div>

        {/* GNSS Ground Truth Upload */}
        <div className="space-y-1">
          <span className="text-[11px] font-medium text-slate-400">{t('upload.gt_label')}</span>
          <input
            type="file"
            accept=".geojson,.json,.gpkg,.csv"
            onChange={(e) => setGtFile(e.target.files?.[0] ?? null)}
            className="block w-full text-xs text-slate-400 file:mr-3 file:py-1.5 file:px-3 file:rounded-lg file:border-0 file:text-xs file:font-semibold file:bg-slate-700 file:text-cyan-300 hover:file:bg-slate-600 cursor-pointer bg-slate-900/60 rounded-lg border border-slate-800"
          />
        </div>

        <button
          onClick={handleUploadAll}
          disabled={uploading || (!oriFile && !dsmFile && !dtmFile && !parcelsFile && !gtFile)}
          className="w-full py-2 bg-slate-700 hover:bg-slate-600 text-white font-semibold text-xs rounded-lg transition-colors shadow-md disabled:opacity-40"
        >
          {uploading ? 'Uploading...' : t('upload.upload_btn')}
        </button>

        {uploadProgress && (
          <p className="text-[11px] font-mono text-cyan-300 text-center">{uploadProgress}</p>
        )}
      </div>

      {/* Pipeline Trigger & Live Monitor */}
      <div className="p-4 bg-gradient-to-br from-slate-800/80 to-slate-900/80 rounded-xl border border-cyan-800/40 shadow-xl space-y-3.5">
        <div className="flex items-center justify-between">
          <h4 className="text-xs font-semibold uppercase tracking-wider text-cyan-300 flex items-center gap-1.5">
            <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 10V3L4 14h7v7l9-11h-7z" />
            </svg>
            Automated Cadastral AI Pipeline
          </h4>
        </div>

        <button
          onClick={handleRunPipeline}
          disabled={!currentProject || !!currentJobId && jobStatus?.status === 'PROGRESS'}
          className="w-full py-2.5 bg-gradient-to-r from-cyan-500 to-blue-600 hover:from-cyan-400 hover:to-blue-500 text-slate-950 font-bold text-xs rounded-lg shadow-lg shadow-cyan-900/40 transition-all flex items-center justify-center gap-2 disabled:opacity-50"
        >
          {jobStatus?.status === 'PROGRESS' ? (
            <>
              <span className="animate-spin text-sm">⟳</span>
              {t('upload.pipeline_running')}
            </>
          ) : (
            <>
              <svg className="w-4 h-4" fill="currentColor" viewBox="0 0 20 20">
                <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zM9.555 7.168A1 1 0 008 8v4a1 1 0 001.555.832l3-2a1 1 0 000-1.664l-3-2z" clipRule="evenodd" />
              </svg>
              {t('upload.run_pipeline')}
            </>
          )}
        </button>

        {/* Live Progress Bar */}
        {jobStatus && (
          <div className="space-y-2 pt-2 border-t border-slate-700/60">
            <div className="flex items-center justify-between text-xs">
              <span className="font-semibold text-white capitalize">{jobStatus.status}</span>
              <span className="font-mono text-cyan-300 font-bold">{jobStatus.progress}%</span>
            </div>
            <div className="w-full h-2 bg-slate-800 rounded-full overflow-hidden border border-slate-700">
              <div
                className="h-full bg-gradient-to-r from-cyan-400 to-blue-500 transition-all duration-300 rounded-full"
                style={{ width: `${jobStatus.progress}%` }}
              />
            </div>
            {jobStatus.message && (
              <p className="text-[11px] text-slate-400 font-mono">{jobStatus.message}</p>
            )}
          </div>
        )}
      </div>

      {/* Create Project Modal */}
      {showCreateModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm p-4">
          <form
            onSubmit={handleCreateProject}
            className="w-full max-w-sm bg-slate-900 border border-slate-700 rounded-2xl p-5 shadow-2xl space-y-4 animate-fade-in"
          >
            <div className="flex items-center justify-between">
              <h3 className="text-sm font-bold text-white">{t('upload.create_project')}</h3>
              <button
                type="button"
                onClick={() => setShowCreateModal(false)}
                className="text-slate-400 hover:text-white text-base"
              >
                ✕
              </button>
            </div>

            <div className="space-y-1">
              <label className="text-xs text-slate-300 font-medium">{t('upload.project_name')}</label>
              <input
                type="text"
                required
                value={newProjectName}
                onChange={(e) => setNewProjectName(e.target.value)}
                placeholder="e.g. Sector 62 Urban Drone Survey"
                className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-xs text-white focus:outline-none focus:border-cyan-400"
              />
            </div>

            <div className="space-y-1">
              <label className="text-xs text-slate-300 font-medium">{t('upload.crs')}</label>
              <input
                type="text"
                value={newProjectCrs}
                onChange={(e) => setNewProjectCrs(e.target.value)}
                placeholder="EPSG:32643"
                className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-xs text-white focus:outline-none focus:border-cyan-400 font-mono"
              />
            </div>

            <div className="flex items-center justify-end gap-2 pt-2">
              <button
                type="button"
                onClick={() => setShowCreateModal(false)}
                className="px-3 py-1.5 text-xs text-slate-400 hover:text-white"
              >
                Cancel
              </button>
              <button
                type="submit"
                disabled={isCreating}
                className="px-4 py-1.5 text-xs font-semibold bg-cyan-600 hover:bg-cyan-500 text-white rounded-lg transition-colors shadow-md disabled:opacity-50"
              >
                {isCreating ? 'Creating...' : 'Create'}
              </button>
            </div>
          </form>
        </div>
      )}
    </div>
  );
};
