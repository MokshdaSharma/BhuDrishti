/**
 * IssuesPanel — Topology validation issues, auto-repair, and issue resolution (Section 7.10).
 */

import React, { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { api } from '../api/client';
import type { IssueFeature, IssueSeverity, ValidationSummary } from '../api/types';
import type { MapProvider } from '../map/provider';

interface IssuesPanelProps {
  projectId: number;
  provider: MapProvider | null;
  onRefreshParcels?: () => void;
}

export const IssuesPanel: React.FC<IssuesPanelProps> = ({
  projectId,
  provider,
  onRefreshParcels,
}) => {
  const { t } = useTranslation();
  const [issues, setIssues] = useState<IssueFeature[]>([]);
  const [loading, setLoading] = useState(false);
  const [autoFixing, setAutoFixing] = useState(false);
  const [severityFilter, setSeverityFilter] = useState<string>('all');
  const [showResolved, setShowResolved] = useState<boolean>(false);
  const [summary, setSummary] = useState<ValidationSummary | null>(null);

  const fetchIssues = async () => {
    if (!projectId) return;
    setLoading(true);
    try {
      const sevParam = severityFilter === 'all' ? undefined : severityFilter;
      const res = await api.getIssues(projectId, sevParam, showResolved ? undefined : false);
      setIssues(res.features);
    } catch (err) {
      console.error('Failed to load issues:', err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchIssues();
  }, [projectId, severityFilter, showResolved]);

  const handleAutoFix = async () => {
    setAutoFixing(true);
    try {
      const sum = await api.validateTopology(projectId, true);
      setSummary(sum);
      await fetchIssues();
      onRefreshParcels?.();
    } catch (err) {
      console.error('Auto-fix failed:', err);
    } finally {
      setAutoFixing(false);
    }
  };

  const handleToggleResolved = async (issue: IssueFeature) => {
    try {
      await api.patchIssue(issue.id, { resolved: !issue.properties.resolved });
      await fetchIssues();
    } catch (err) {
      console.error('Failed to patch issue:', err);
    }
  };

  const handleZoomToIssue = (issue: IssueFeature) => {
    if (!provider || !issue.geometry) return;
    try {
      if (issue.geometry.type === 'Point') {
        const [lng, lat] = issue.geometry.coordinates;
        provider.flyTo([lng, lat], 18);
      } else if (issue.geometry.type === 'Polygon') {
        const coords = issue.geometry.coordinates[0];
        let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
        coords.forEach(([x, y]) => {
          if (x < minX) minX = x;
          if (y < minY) minY = y;
          if (x > maxX) maxX = x;
          if (y > maxY) maxY = y;
        });
        provider.fitBounds([minX, minY, maxX, maxY], 60);
      }
    } catch (err) {
      console.warn('Could not zoom to geometry:', err);
    }
  };

  const getSeverityBadge = (sev: IssueSeverity) => {
    switch (sev) {
      case 'error':
        return <span className="px-2 py-0.5 rounded text-[10px] font-bold bg-red-900/60 text-red-300 border border-red-700/50">ERROR</span>;
      case 'warning':
        return <span className="px-2 py-0.5 rounded text-[10px] font-bold bg-amber-900/60 text-amber-300 border border-amber-700/50">WARNING</span>;
      case 'info':
        return <span className="px-2 py-0.5 rounded text-[10px] font-bold bg-blue-900/60 text-blue-300 border border-blue-700/50">INFO</span>;
    }
  };

  return (
    <div className="space-y-4 text-slate-200">
      {/* Top action bar */}
      <div className="flex items-center justify-between gap-2 p-3 bg-slate-800/60 rounded-xl border border-slate-700/60 shadow-lg">
        <div>
          <h3 className="text-xs font-semibold text-white">{t('issues.title')}</h3>
          <p className="text-[11px] text-slate-400">
            {issues.length} {t('issues.found')}
          </p>
        </div>
        <button
          onClick={handleAutoFix}
          disabled={autoFixing}
          className="px-3 py-1.5 text-xs font-semibold bg-gradient-to-r from-emerald-600 to-teal-600 hover:from-emerald-500 hover:to-teal-500 text-white rounded-lg shadow-md transition-all flex items-center gap-1.5 disabled:opacity-50"
        >
          {autoFixing ? (
            <span className="animate-spin text-xs">⟳</span>
          ) : (
            <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 10V3L4 14h7v7l9-11h-7z" />
            </svg>
          )}
          {t('issues.autofix')}
        </button>
      </div>

      {summary && (
        <div className="p-3 bg-emerald-950/40 border border-emerald-800/60 rounded-xl text-xs text-emerald-300 space-y-1">
          <p className="font-semibold text-white">Topology Auto-Fix Complete</p>
          <p>Autofixed {summary.autofixed_count} issues out of {summary.issues_found} detected.</p>
        </div>
      )}

      {/* Filters */}
      <div className="flex items-center justify-between gap-1 p-1 bg-slate-900/70 rounded-lg border border-slate-800 text-[11px]">
        {['all', 'error', 'warning', 'info'].map((f) => (
          <button
            key={f}
            onClick={() => setSeverityFilter(f)}
            className={`flex-1 py-1 rounded font-medium capitalize transition-colors ${
              severityFilter === f
                ? 'bg-cyan-500/20 text-cyan-300 border border-cyan-500/40'
                : 'text-slate-400 hover:text-white'
            }`}
          >
            {f === 'all' ? t('issues.filter_all') : f}
          </button>
        ))}
      </div>

      <div className="flex items-center justify-end px-1">
        <label className="flex items-center gap-1.5 text-[11px] text-slate-400 cursor-pointer">
          <input
            type="checkbox"
            checked={showResolved}
            onChange={(e) => setShowResolved(e.target.checked)}
            className="rounded bg-slate-800 border-slate-700 text-cyan-500 w-3 h-3"
          />
          Show resolved issues
        </label>
      </div>

      {/* Issues list */}
      {loading ? (
        <div className="p-6 text-center text-xs text-slate-400 animate-pulse">Loading validation issues...</div>
      ) : issues.length === 0 ? (
        <div className="p-6 text-center text-xs text-slate-500 bg-slate-900/30 rounded-xl border border-slate-800/60">
          No topology issues found matching filter.
        </div>
      ) : (
        <div className="space-y-2.5 max-h-[500px] overflow-y-auto pr-1">
          {issues.map((iss) => {
            const props = iss.properties;
            return (
              <div
                key={iss.id}
                className="p-3 bg-slate-900/60 hover:bg-slate-800/80 rounded-xl border border-slate-800/80 hover:border-slate-700 transition-all space-y-2"
              >
                <div className="flex items-start justify-between gap-2">
                  <div className="space-y-0.5">
                    <div className="flex items-center gap-2">
                      {getSeverityBadge(props.severity)}
                      <span className="text-xs font-semibold text-white font-mono uppercase">
                        {props.issue_type.replace(/_/g, ' ')}
                      </span>
                    </div>
                    {props.suggested_fix && (
                      <p className="text-[11px] text-slate-400 leading-tight">
                        <span className="text-cyan-400 font-medium">Fix:</span> {props.suggested_fix}
                      </p>
                    )}
                  </div>
                  <button
                    onClick={() => handleZoomToIssue(iss)}
                    className="p-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-300 hover:text-cyan-300 transition-colors"
                    title={t('issues.zoom_to')}
                  >
                    <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0zM10 7v3m0 0v3m0-3h3m-3 0H7" />
                    </svg>
                  </button>
                </div>

                <div className="pt-2 border-t border-slate-800/60 flex items-center justify-between text-[10px]">
                  <span className="text-slate-500">#{iss.id} • {new Date(props.created_at).toLocaleTimeString()}</span>
                  <button
                    onClick={() => handleToggleResolved(iss)}
                    className={`px-2 py-0.5 rounded font-semibold transition-colors ${
                      props.resolved
                        ? 'bg-emerald-900/40 text-emerald-400 hover:bg-emerald-900/60'
                        : 'bg-slate-800 text-slate-400 hover:text-white hover:bg-slate-700'
                    }`}
                  >
                    {props.resolved ? `✓ ${t('issues.resolved')}` : t('issues.mark_resolved')}
                  </button>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
};
