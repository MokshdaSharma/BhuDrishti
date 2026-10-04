/**
 * ComparePanel — Cadastral comparison metrics, changed parcel list, and swipe curtain control (Section 7.10).
 */

import React, { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { api } from '../api/client';
import type { CompareSummary } from '../api/types';

interface ComparePanelProps {
  projectId: number;
  swipeActive: boolean;
  onToggleSwipe: () => void;
}

export const ComparePanel: React.FC<ComparePanelProps> = ({
  projectId,
  swipeActive,
  onToggleSwipe,
}) => {
  const { t } = useTranslation();
  const [summary, setSummary] = useState<CompareSummary | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!projectId) return;
    setLoading(true);
    api.getComparison(projectId)
      .then(setSummary)
      .catch(console.error)
      .finally(() => setLoading(false));
  }, [projectId]);

  return (
    <div className="space-y-4 text-slate-200">
      {/* Swipe Curtain Action */}
      <div className="p-4 bg-slate-800/60 rounded-xl border border-slate-700/60 shadow-lg space-y-3">
        <div className="flex items-center justify-between">
          <div>
            <h3 className="text-xs font-semibold text-white">{t('compare.title')}</h3>
            <p className="text-[11px] text-slate-400">Side-by-side AI vs existing GIS cadastre</p>
          </div>
          <button
            onClick={onToggleSwipe}
            className={`px-3 py-1.5 rounded-lg text-xs font-semibold transition-all shadow-md flex items-center gap-1.5 ${
              swipeActive
                ? 'bg-cyan-500 text-slate-950 font-bold shadow-[0_0_12px_rgba(6,182,212,0.4)]'
                : 'bg-slate-700 hover:bg-slate-600 text-white'
            }`}
          >
            <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 7h12m0 0l-4-4m4 4l-4 4m0 6H4m0 0l4 4m-4-4l4-4" />
            </svg>
            {t('compare.swipe_toggle')}
          </button>
        </div>
      </div>

      {/* Metric Tiles */}
      {summary && (
        <div className="grid grid-cols-2 gap-2.5 text-center">
          <div className="p-3 bg-emerald-950/40 rounded-xl border border-emerald-800/50">
            <span className="text-[10px] text-emerald-400 font-semibold uppercase">{t('compare.matched')}</span>
            <p className="text-xl font-bold text-white font-mono mt-0.5">{summary.matched_count}</p>
          </div>
          <div className="p-3 bg-amber-950/40 rounded-xl border border-amber-800/50">
            <span className="text-[10px] text-amber-400 font-semibold uppercase">{t('compare.changed')}</span>
            <p className="text-xl font-bold text-white font-mono mt-0.5">{summary.changed_count}</p>
          </div>
          <div className="p-3 bg-sky-950/40 rounded-xl border border-sky-800/50">
            <span className="text-[10px] text-sky-400 font-semibold uppercase">{t('compare.new')}</span>
            <p className="text-xl font-bold text-white font-mono mt-0.5">{summary.new_count}</p>
          </div>
          <div className="p-3 bg-rose-950/40 rounded-xl border border-rose-800/50">
            <span className="text-[10px] text-rose-400 font-semibold uppercase">{t('compare.missing')}</span>
            <p className="text-xl font-bold text-white font-mono mt-0.5">{summary.missing_count}</p>
          </div>
        </div>
      )}

      {/* Divergent / Changed List */}
      {loading ? (
        <div className="p-6 text-center text-xs text-slate-400 animate-pulse">Computing comparison metrics...</div>
      ) : summary?.details.length === 0 ? (
        <div className="p-6 text-center text-xs text-slate-500 bg-slate-900/30 rounded-xl border border-slate-800/60">
          No existing parcel layer provided or no boundary discrepancies detected.
        </div>
      ) : (
        <div className="space-y-2 max-h-[380px] overflow-y-auto pr-1">
          {summary?.details.map((d) => (
            <div
              key={d.id}
              className="p-3 bg-slate-900/60 rounded-xl border border-slate-800 text-xs space-y-1.5"
            >
              <div className="flex items-center justify-between">
                <span className="font-mono font-bold text-white">Parcel #{d.id}</span>
                <span
                  className={`px-1.5 py-0.5 rounded text-[10px] font-semibold uppercase ${
                    d.status === 'changed_parcel'
                      ? 'bg-amber-900/60 text-amber-300'
                      : d.status === 'new_parcel'
                      ? 'bg-sky-900/60 text-sky-300'
                      : 'bg-rose-900/60 text-rose-300'
                  }`}
                >
                  {d.status.replace(/_/g, ' ')}
                </span>
              </div>
              <div className="grid grid-cols-3 gap-1 text-[10px] font-mono text-slate-400 pt-1 border-t border-slate-800/60">
                <div>IoU: <span className="text-white">{(d.iou * 100).toFixed(1)}%</span></div>
                <div>Diff: <span className="text-white">{d.area_diff_pct.toFixed(1)}%</span></div>
                <div>Shift: <span className="text-white">{d.centroid_shift_m.toFixed(1)}m</span></div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
};
