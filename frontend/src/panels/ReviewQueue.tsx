/**
 * ReviewQueuePanel — Parcels sorted by confidence ascending for rapid surveyor review (Section 7.10).
 */

import React, { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { api } from '../api/client';
import type { ParcelFeature, ParcelStatus } from '../api/types';
import type { MapProvider } from '../map/provider';

interface ReviewQueuePanelProps {
  projectId: number;
  provider: MapProvider | null;
  onParcelSelected?: (parcel: ParcelFeature) => void;
}

export const ReviewQueuePanel: React.FC<ReviewQueuePanelProps> = ({
  projectId,
  provider,
  onParcelSelected,
}) => {
  const { t } = useTranslation();
  const [parcels, setParcels] = useState<ParcelFeature[]>([]);
  const [loading, setLoading] = useState(false);
  const [selectedId, setSelectedId] = useState<number | null>(null);

  const fetchQueue = async () => {
    if (!projectId) return;
    setLoading(true);
    try {
      const res = await api.getParcels(projectId);
      // Sort ascending by confidence (lowest confidence first)
      const sorted = [...res.features].sort((a, b) => {
        const confA = a.properties.confidence ?? 0;
        const confB = b.properties.confidence ?? 0;
        return confA - confB;
      });
      setParcels(sorted);
    } catch (err) {
      console.error('Failed to load review queue:', err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchQueue();
  }, [projectId]);

  const handleUpdateStatus = async (parcel: ParcelFeature, status: ParcelStatus) => {
    try {
      const updated = await api.updateParcel(parcel.id, { status });
      setParcels((prev) =>
        prev.map((p) => (p.id === parcel.id ? { ...p, properties: { ...p.properties, status: updated.properties.status } } : p))
      );
    } catch (err) {
      console.error('Failed to update parcel status:', err);
    }
  };

  const handleZoomToParcel = (parcel: ParcelFeature) => {
    setSelectedId(parcel.id);
    onParcelSelected?.(parcel);
    if (!provider || !parcel.geometry) return;

    try {
      const coords = (parcel.geometry as GeoJSON.Polygon).coordinates[0];
      let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
      coords.forEach(([x, y]) => {
        if (x < minX) minX = x;
        if (y < minY) minY = y;
        if (x > maxX) maxX = x;
        if (y > maxY) maxY = y;
      });
      provider.fitBounds([minX, minY, maxX, maxY], 70);
    } catch (err) {
      console.warn('Could not zoom to parcel bounds:', err);
    }
  };

  const getConfidenceBadge = (conf: number | null) => {
    if (conf === null) return <span className="text-slate-500 font-mono text-xs">N/A</span>;
    const pct = Math.round(conf * 100);
    if (conf >= 0.75) {
      return <span className="px-2 py-0.5 rounded text-[10px] font-bold bg-emerald-900/60 text-emerald-300 border border-emerald-700/50">{pct}% CONF</span>;
    } else if (conf >= 0.45) {
      return <span className="px-2 py-0.5 rounded text-[10px] font-bold bg-sky-900/60 text-sky-300 border border-sky-700/50">{pct}% CONF</span>;
    }
    return <span className="px-2 py-0.5 rounded text-[10px] font-bold bg-amber-900/60 text-amber-300 border border-amber-700/50 animate-pulse">{pct}% LOW</span>;
  };

  return (
    <div className="space-y-4 text-slate-200">
      <div className="p-3 bg-slate-800/60 rounded-xl border border-slate-700/60 shadow-lg">
        <h3 className="text-xs font-semibold text-white">{t('review.title')}</h3>
        <p className="text-[11px] text-slate-400 mt-1">{t('review.desc')}</p>
      </div>

      {loading ? (
        <div className="p-6 text-center text-xs text-slate-400 animate-pulse">Loading review queue...</div>
      ) : parcels.length === 0 ? (
        <div className="p-6 text-center text-xs text-slate-500 bg-slate-900/30 rounded-xl border border-slate-800/60">
          No parcels available in this project.
        </div>
      ) : (
        <div className="space-y-2.5 max-h-[500px] overflow-y-auto pr-1">
          {parcels.map((p) => {
            const props = p.properties;
            const isSelected = selectedId === p.id;
            return (
              <div
                key={p.id}
                onClick={() => handleZoomToParcel(p)}
                className={`p-3 rounded-xl border cursor-pointer transition-all space-y-2.5 ${
                  isSelected
                    ? 'bg-slate-800 border-cyan-400 shadow-[0_0_15px_rgba(6,182,212,0.2)]'
                    : 'bg-slate-900/60 hover:bg-slate-800/80 border-slate-800/80 hover:border-slate-700'
                }`}
              >
                <div className="flex items-center justify-between">
                  <span className="text-xs font-bold text-white font-mono">Parcel #{p.id}</span>
                  {getConfidenceBadge(props.confidence)}
                </div>

                <div className="grid grid-cols-2 gap-2 text-[11px]">
                  <div className="p-1.5 rounded bg-slate-950/50 border border-slate-800 text-slate-400">
                    <span className="text-[10px] text-slate-500 block">{t('review.area')}</span>
                    <span className="font-mono text-slate-200 font-medium">
                      {props.area_m2 ? `${Math.round(props.area_m2)} m²` : '—'}
                    </span>
                  </div>
                  <div className="p-1.5 rounded bg-slate-950/50 border border-slate-800 text-slate-400">
                    <span className="text-[10px] text-slate-500 block">{t('review.status')}</span>
                    <span className="font-mono text-cyan-300 font-medium capitalize">{props.status}</span>
                  </div>
                </div>

                <div className="pt-2 border-t border-slate-800/60 flex items-center justify-between gap-2">
                  <button
                    onClick={(e) => {
                      e.stopPropagation();
                      handleUpdateStatus(p, 'verified');
                    }}
                    className="flex-1 py-1 text-[10px] font-semibold bg-emerald-950/60 hover:bg-emerald-900 border border-emerald-700/60 text-emerald-300 rounded-lg transition-colors text-center"
                  >
                    ✓ {t('review.verify')}
                  </button>
                  <button
                    onClick={(e) => {
                      e.stopPropagation();
                      handleUpdateStatus(p, 'draft');
                    }}
                    className="flex-1 py-1 text-[10px] font-semibold bg-amber-950/60 hover:bg-amber-900 border border-amber-700/60 text-amber-300 rounded-lg transition-colors text-center"
                  >
                    ⚠ {t('review.flag_edit')}
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
