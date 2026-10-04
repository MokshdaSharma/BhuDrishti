/**
 * ExportPanel — GIS data exports and PDF Cadastral Survey Report downloads (Section 7.10).
 */

import React from 'react';
import { useTranslation } from 'react-i18next';
import { api } from '../api/client';

interface ExportPanelProps {
  projectId: number;
}

export const ExportPanel: React.FC<ExportPanelProps> = ({ projectId }) => {
  const { t } = useTranslation();

  const handleDownload = (format: 'geojson' | 'gpkg' | 'shp' | 'kml') => {
    const url = api.getExportUrl(projectId, format);
    window.open(url, '_blank');
  };

  const handleDownloadPdf = () => {
    const url = api.getPdfReportUrl(projectId);
    window.open(url, '_blank');
  };

  return (
    <div className="space-y-4 text-slate-200">
      {/* Warning Disclaimer */}
      <div className="p-3 bg-amber-950/40 border border-amber-800/60 rounded-xl text-xs text-amber-200 flex items-start gap-2">
        <svg className="w-4 h-4 text-amber-400 shrink-0 mt-0.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
        </svg>
        <p className="font-medium">
          All exported files and survey reports are preliminary outputs subject to on-site field verification.
        </p>
      </div>

      <div className="p-4 bg-slate-800/60 rounded-xl border border-slate-700/60 shadow-lg space-y-3.5">
        <h3 className="text-xs font-semibold text-white uppercase tracking-wider">
          {t('export.title')}
        </h3>

        {/* GIS Vector Exports */}
        <div className="space-y-2.5">
          {/* GeoJSON */}
          <div className="p-3 bg-slate-900/60 rounded-xl border border-slate-800 flex items-center justify-between">
            <div>
              <p className="text-xs font-semibold text-white">{t('export.geojson')}</p>
              <p className="text-[10px] text-slate-400">Standard web RFC 7946 FeatureCollection (WGS84)</p>
            </div>
            <button
              onClick={() => handleDownload('geojson')}
              className="px-3 py-1.5 text-xs font-semibold bg-cyan-600 hover:bg-cyan-500 text-white rounded-lg transition-colors shadow-sm"
            >
              {t('export.download')}
            </button>
          </div>

          {/* GeoPackage */}
          <div className="p-3 bg-slate-900/60 rounded-xl border border-slate-800 flex items-center justify-between">
            <div>
              <p className="text-xs font-semibold text-white">{t('export.gpkg')}</p>
              <p className="text-[10px] text-slate-400">OGC SQLite GeoPackage with parcels, buildings, roads</p>
            </div>
            <button
              onClick={() => handleDownload('gpkg')}
              className="px-3 py-1.5 text-xs font-semibold bg-cyan-600 hover:bg-cyan-500 text-white rounded-lg transition-colors shadow-sm"
            >
              {t('export.download')}
            </button>
          </div>

          {/* Shapefile */}
          <div className="p-3 bg-slate-900/60 rounded-xl border border-slate-800 flex items-center justify-between">
            <div>
              <p className="text-xs font-semibold text-white">{t('export.shp')}</p>
              <p className="text-[10px] text-slate-400">ESRI Shapefile archive (.zip with .shp, .dbf, .prj)</p>
            </div>
            <button
              onClick={() => handleDownload('shp')}
              className="px-3 py-1.5 text-xs font-semibold bg-cyan-600 hover:bg-cyan-500 text-white rounded-lg transition-colors shadow-sm"
            >
              {t('export.download')}
            </button>
          </div>

          {/* Google Earth KML */}
          <div className="p-3 bg-slate-900/60 rounded-xl border border-slate-800 flex items-center justify-between">
            <div>
              <p className="text-xs font-semibold text-white">{t('export.kml')}</p>
              <p className="text-[10px] text-slate-400">Keyhole Markup Language for Google Earth & Web-GIS</p>
            </div>
            <button
              onClick={() => handleDownload('kml')}
              className="px-3 py-1.5 text-xs font-semibold bg-cyan-600 hover:bg-cyan-500 text-white rounded-lg transition-colors shadow-sm"
            >
              {t('export.download')}
            </button>
          </div>
        </div>

        {/* Official PDF Survey Report Card */}
        <div className="p-3.5 bg-gradient-to-r from-slate-900 to-slate-800 rounded-xl border border-indigo-700/50 flex items-center justify-between mt-4">
          <div className="space-y-0.5">
            <p className="text-xs font-bold text-white flex items-center gap-1.5">
              <svg className="w-4 h-4 text-indigo-400" fill="currentColor" viewBox="0 0 20 20">
                <path fillRule="evenodd" d="M4 4a2 2 0 012-2h4.586A2 2 0 0112 2.586L15.414 6A2 2 0 0116 7.414V16a2 2 0 01-2 2H6a2 2 0 01-2-2V4zm2 6a1 1 0 011-1h6a1 1 0 110 2H7a1 1 0 01-1-1zm1 3a1 1 0 100 2h6a1 1 0 100-2H7z" clipRule="evenodd" />
              </svg>
              {t('export.pdf_report')}
            </p>
            <p className="text-[10px] text-slate-400">Includes server-rendered vector map snapshot & GNSS stats</p>
          </div>
          <button
            onClick={handleDownloadPdf}
            className="px-3.5 py-1.5 text-xs font-bold bg-gradient-to-r from-indigo-600 to-blue-600 hover:from-indigo-500 hover:to-blue-500 text-white rounded-lg transition-all shadow-md"
          >
            PDF Report
          </button>
        </div>
      </div>
    </div>
  );
};
