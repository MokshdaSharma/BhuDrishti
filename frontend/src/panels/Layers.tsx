/**
 * LayersPanel — Layer visibility, opacity sliders, and basemap selector (Section 7.10).
 */

import React from 'react';
import { useTranslation } from 'react-i18next';
import { BASEMAPS } from '../map/basemaps';
import { LAYER_CATALOG, type LayerMetadata } from '../map/layers';
import type { BasemapName, MapProvider } from '../map/provider';

interface LayersPanelProps {
  provider: MapProvider | null;
  currentBasemap: BasemapName;
  onBasemapChange: (basemap: BasemapName) => void;
  layerStates: Record<string, { visible: boolean; opacity: number }>;
  onLayerChange: (layerId: string, visible: boolean, opacity: number) => void;
  terrainEnabled: boolean;
  onTerrainToggle: (enabled: boolean) => void;
}

export const LayersPanel: React.FC<LayersPanelProps> = ({
  provider,
  currentBasemap,
  onBasemapChange,
  layerStates,
  onLayerChange,
  terrainEnabled,
  onTerrainToggle,
}) => {
  const { t } = useTranslation();

  const categories: Array<{ key: LayerMetadata['category']; label: string }> = [
    { key: 'drone_rasters', label: t('layers.drone_rasters') },
    { key: 'ai_vectors', label: t('layers.ai_vectors') },
    { key: 'cadastral_rules', label: t('layers.cadastral_rules') },
    { key: 'ground_truth', label: t('layers.ground_truth') },
    { key: 'context', label: t('layers.context') },
  ];

  return (
    <div className="space-y-6 text-slate-200">
      {/* Basemap Selection */}
      <div className="rounded-xl bg-slate-800/60 p-4 border border-slate-700/60 shadow-lg backdrop-blur-md">
        <h3 className="text-xs font-semibold uppercase tracking-wider text-cyan-400 mb-3 flex items-center gap-2">
          <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 20l-5.447-2.724A1 1 0 013 16.382V5.618a1 1 0 011.447-.894L9 7m0 13l6-3m-6 3V7m6 10l4.553 2.276A1 1 0 0021 18.382V7.618a1 1 0 00-.553-.894L15 4m0 13V4m0 0L9 7" />
          </svg>
          {t('layers.basemap')}
        </h3>
        <div className="grid grid-cols-2 gap-2">
          {BASEMAPS.map((bm) => (
            <button
              key={bm.id}
              onClick={() => onBasemapChange(bm.id as BasemapName)}
              className={`px-3 py-2 text-xs rounded-lg font-medium transition-all text-left border ${
                currentBasemap === bm.id
                  ? 'bg-cyan-500/20 border-cyan-400 text-cyan-200 shadow-[0_0_12px_rgba(6,182,212,0.3)]'
                  : 'bg-slate-900/60 border-slate-700 text-slate-400 hover:text-slate-200 hover:border-slate-600'
              }`}
            >
              {bm.label}
            </button>
          ))}
        </div>

        {/* 3D Terrain Toggle */}
        <div className="mt-4 pt-3 border-t border-slate-700/60 flex items-center justify-between">
          <span className="text-xs text-slate-300 font-medium flex items-center gap-2">
            <svg className="w-4 h-4 text-emerald-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 10V3L4 14h7v7l9-11h-7z" />
            </svg>
            {t('layers.terrain_3d')}
          </span>
          <button
            onClick={() => onTerrainToggle(!terrainEnabled)}
            className={`w-10 h-5 rounded-full transition-colors relative flex items-center px-0.5 ${
              terrainEnabled ? 'bg-cyan-500' : 'bg-slate-700'
            }`}
          >
            <div
              className={`w-4 h-4 rounded-full bg-white transition-transform ${
                terrainEnabled ? 'translate-x-5' : 'translate-x-0'
              }`}
            />
          </button>
        </div>
      </div>

      {/* Layer Groups */}
      {categories.map((cat) => {
        const layers = LAYER_CATALOG.filter((l) => l.category === cat.key);
        if (layers.length === 0) return null;

        return (
          <div
            key={cat.key}
            className="rounded-xl bg-slate-800/60 p-4 border border-slate-700/60 shadow-lg backdrop-blur-md space-y-3"
          >
            <h4 className="text-xs font-semibold uppercase tracking-wider text-slate-400">
              {cat.label}
            </h4>
            <div className="space-y-3">
              {layers.map((layer) => {
                const state = layerStates[layer.id] ?? {
                  visible: layer.defaultVisible,
                  opacity: layer.defaultOpacity,
                };

                return (
                  <div key={layer.id} className="space-y-1.5 p-2 rounded-lg bg-slate-900/40 border border-slate-800/60">
                    <div className="flex items-center justify-between">
                      <label className="flex items-center gap-2 cursor-pointer text-xs font-medium text-slate-200">
                        <input
                          type="checkbox"
                          checked={state.visible}
                          onChange={(e) => {
                            const newVis = e.target.checked;
                            onLayerChange(layer.id, newVis, state.opacity);
                            provider?.setLayerVisibility(layer.id, newVis);
                          }}
                          className="rounded bg-slate-800 border-slate-600 text-cyan-500 focus:ring-cyan-400 focus:ring-offset-slate-900 w-3.5 h-3.5"
                        />
                        {layer.name}
                      </label>
                      <span className="text-[10px] font-mono text-slate-400">
                        {Math.round(state.opacity * 100)}%
                      </span>
                    </div>

                    {state.visible && (
                      <div className="flex items-center gap-2 pt-1">
                        <span className="text-[10px] text-slate-500">{t('layers.opacity')}</span>
                        <input
                          type="range"
                          min="0"
                          max="1"
                          step="0.05"
                          value={state.opacity}
                          onChange={(e) => {
                            const newOp = parseFloat(e.target.value);
                            onLayerChange(layer.id, state.visible, newOp);
                            provider?.setLayerOpacity(layer.id, newOp);
                          }}
                          className="flex-1 h-1 bg-slate-700 rounded-lg appearance-none cursor-pointer accent-cyan-400"
                        />
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          </div>
        );
      })}
    </div>
  );
};
