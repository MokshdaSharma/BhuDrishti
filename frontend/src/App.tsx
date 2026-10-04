/**
 * Root Application Component — ParcelAI Web-GIS Platform (Section 7.10, Phase 10).
 */

import React, { useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { api } from './api/client';
import type { HealthResponse, ParcelFeature, Project } from './api/types';
import './i18n';
import { searchPlaces, type GeocodingResult } from './map/geocoding';
import { createProvider } from './map/factory';
import type { BasemapName, MapProvider } from './map/provider';
import { SwipeCompareController } from './map/swipeCompare';
import { AccuracyPanel } from './panels/Accuracy';
import { ComparePanel } from './panels/Compare';
import { ContextPanel } from './panels/Context';
import { ExportPanel } from './panels/Export';
import { IssuesPanel } from './panels/Issues';
import { LayersPanel } from './panels/Layers';
import { ReviewQueuePanel } from './panels/ReviewQueue';
import { StatsPanel } from './panels/Stats';
import { UploadWizard } from './panels/UploadWizard';

type ActiveTab = 'layers' | 'issues' | 'review' | 'stats' | 'compare' | 'accuracy' | 'context' | 'upload' | 'export' | null;

export default function App() {
  const { t, i18n } = useTranslation();
  const mapContainerRef = useRef<HTMLDivElement>(null);
  const providerRef = useRef<MapProvider | null>(null);
  const swipeRef = useRef<SwipeCompareController | null>(null);

  // App State
  const [currentProject, setCurrentProject] = useState<Project | null>(null);
  const [activeTab, setActiveTab] = useState<ActiveTab>('upload');
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [currentBasemap, setCurrentBasemap] = useState<BasemapName>('satellite-streets');
  const [terrainEnabled, setTerrainEnabled] = useState(false);
  const [swipeActive, setSwipeActive] = useState(false);
  const [layerStates, setLayerStates] = useState<Record<string, { visible: boolean; opacity: number }>>({});
  const [searchQuery, setSearchQuery] = useState('');
  const [searchResults, setSearchResults] = useState<GeocodingResult[]>([]);
  const [isSearching, setIsSearching] = useState(false);

  // Initialize Map Provider
  useEffect(() => {
    if (!mapContainerRef.current || providerRef.current) return;

    const provider = createProvider();
    providerRef.current = provider;

    provider
      .init({
        container: mapContainerRef.current,
        center: [76.7179, 30.7046], // Mohali / Punjab default survey coordinates
        zoom: 15,
        basemap: currentBasemap,
        onFallback: (reason) => {
          console.warn('[MapFallbackNotice]', reason);
        },
      })
      .then(() => {
        // Load initial project list
        api.listProjects()
          .then((list) => {
            if (list.length > 0) {
              setCurrentProject(list[0]);
              loadProjectData(list[0].id, provider);
            }
          })
          .catch(console.error);
      })
      .catch(console.error);

    // Initial health check
    api.getHealth().then(setHealth).catch(console.error);

    return () => {
      provider.destroy();
      providerRef.current = null;
    };
  }, []);

  const loadProjectData = async (projectId: number, provider: MapProvider) => {
    try {
      const parcelsData = await api.getParcels(projectId);
      provider.addGeoJSON({
        id: 'parcels',
        data: parcelsData,
      });

      const issuesData = await api.getIssues(projectId);
      provider.addGeoJSON({
        id: 'issues',
        data: issuesData,
      });

      // Fetch dynamic tile routes from backend
      try {
        const tiles = await api.getTiles(projectId);
        if (tiles.raster_tiles?.ori) {
          provider.addRasterSource({ id: 'parcelai-ori', url: tiles.raster_tiles.ori });
        }
      } catch {
        // Tiles optional if mock
      }
    } catch (err) {
      console.error('Failed to load project GeoJSON layers:', err);
    }
  };

  const handleBasemapChange = (bm: BasemapName) => {
    setCurrentBasemap(bm);
    providerRef.current?.setBasemap(bm);
  };

  const handleTerrainToggle = (enabled: boolean) => {
    setTerrainEnabled(enabled);
    providerRef.current?.enableTerrain(enabled);
  };

  const handleLayerChange = (layerId: string, visible: boolean, opacity: number) => {
    setLayerStates((prev) => ({ ...prev, [layerId]: { visible, opacity } }));
    providerRef.current?.setLayerVisibility(layerId, visible);
    providerRef.current?.setLayerOpacity(layerId, opacity);
  };

  const handleToggleSwipe = () => {
    if (!mapContainerRef.current) return;
    if (swipeActive) {
      swipeRef.current?.destroy();
      swipeRef.current = null;
      setSwipeActive(false);
    } else {
      swipeRef.current = new SwipeCompareController({
        container: mapContainerRef.current,
        initialPosition: 50,
      });
      setSwipeActive(true);
    }
  };

  const handleSearch = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!searchQuery.trim()) return;
    setIsSearching(true);
    try {
      const results = await searchPlaces(searchQuery);
      setSearchResults(results);
    } catch (err) {
      console.error('Search failed:', err);
    } finally {
      setIsSearching(false);
    }
  };

  const handleSelectSearchResult = (res: GeocodingResult) => {
    providerRef.current?.flyTo(res.coordinates, 16);
    setSearchResults([]);
    setSearchQuery(res.name);
  };

  const navItems: Array<{ key: ActiveTab; label: string; icon: string }> = [
    { key: 'layers', label: t('navigation.layers'), icon: 'M9 20l-5.447-2.724A1 1 0 013 16.382V5.618a1 1 0 011.447-.894L9 7m0 13l6-3m-6 3V7m6 10l4.553 2.276A1 1 0 0021 18.382V7.618a1 1 0 00-.553-.894L15 4m0 13V4m0 0L9 7' },
    { key: 'issues', label: t('navigation.issues'), icon: 'M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z' },
    { key: 'review', label: t('navigation.review_queue'), icon: 'M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2m-6 9l2 2 4-4' },
    { key: 'stats', label: t('navigation.stats'), icon: 'M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z' },
    { key: 'compare', label: t('navigation.compare'), icon: 'M8 7h12m0 0l-4-4m4 4l-4 4m0 6H4m0 0l4 4m-4-4l4-4' },
    { key: 'accuracy', label: t('navigation.accuracy'), icon: 'M9 12l2 2 4-4M7.835 4.697a3.42 3.42 0 001.946-.806 3.42 3.42 0 014.438 0 3.42 3.42 0 001.946.806 3.42 3.42 0 013.138 3.138 3.42 3.42 0 00.806 1.946 3.42 3.42 0 010 4.438 3.42 3.42 0 00-.806 1.946 3.42 3.42 0 01-3.138 3.138 3.42 3.42 0 00-1.946.806 3.42 3.42 0 01-4.438 0 3.42 3.42 0 00-1.946-.806 3.42 3.42 0 01-3.138-3.138 3.42 3.42 0 00-.806-1.946 3.42 3.42 0 010-4.438 3.42 3.42 0 00.806-1.946 3.42 3.42 0 013.138-3.138z' },
    { key: 'context', label: t('navigation.context'), icon: 'M3.055 11H5a2 2 0 012 2v1a2 2 0 002 2 2 2 0 012 2v2.945M8 3.935V5.5A2.5 2.5 0 0010.5 8h.5a2 2 0 012 2 2 2 0 104 0 2 2 0 012-2h1.064M15 20.488V18a2 2 0 012-2h3.064' },
    { key: 'upload', label: t('navigation.upload'), icon: 'M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12' },
    { key: 'export', label: t('navigation.export'), icon: 'M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4' },
  ];

  return (
    <div className="relative w-full h-full flex flex-col bg-slate-950 font-sans overflow-hidden">
      {/* ── Top Navbar ── */}
      <header className="z-30 h-14 bg-slate-900/90 backdrop-blur-md border-b border-slate-800/80 flex items-center justify-between px-4 shadow-xl">
        {/* Logo & Title */}
        <div className="flex items-center gap-3">
          <div className="w-8 h-8 rounded-xl bg-gradient-to-tr from-cyan-500 via-blue-600 to-indigo-600 flex items-center justify-center shadow-lg shadow-cyan-900/40">
            <svg viewBox="0 0 24 24" className="w-5 h-5 text-white fill-none stroke-current" strokeWidth="2">
              <polygon points="12 2 2 7 12 12 22 7 12 2" />
              <polyline points="2 17 12 22 22 17" />
              <polyline points="2 12 12 17 22 12" />
            </svg>
          </div>
          <div>
            <div className="flex items-center gap-2">
              <h1 className="text-sm font-bold text-white tracking-tight leading-none">BhuDrishti</h1>
              <span className="px-1.5 py-0.5 rounded text-[9px] font-bold bg-cyan-950/80 text-cyan-300 border border-cyan-700/60 uppercase">
                AI Cadastre
              </span>
            </div>
            <p className="text-[10px] text-slate-400 leading-none mt-1">
              {currentProject ? `${currentProject.name} (${currentProject.crs})` : t('app_subtitle')}
            </p>
          </div>
        </div>

        {/* Navigation Tabs Bar */}
        <nav className="flex items-center gap-1 bg-slate-950/70 p-1 rounded-xl border border-slate-800/80">
          {navItems.map((item) => {
            const isActive = activeTab === item.key;
            return (
              <button
                key={item.key}
                onClick={() => setActiveTab(isActive ? null : item.key)}
                className={`px-3 py-1.5 text-xs font-semibold rounded-lg transition-all flex items-center gap-1.5 ${
                  isActive
                    ? 'bg-gradient-to-r from-cyan-500/20 to-blue-500/20 text-cyan-300 border border-cyan-500/50 shadow-md shadow-cyan-950/50'
                    : 'text-slate-400 hover:text-slate-200 hover:bg-slate-800/60 border border-transparent'
                }`}
              >
                <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d={item.icon} />
                </svg>
                <span className="hidden lg:inline">{item.label}</span>
              </button>
            );
          })}
        </nav>

        {/* Right Tools (Search, Language, Status) */}
        <div className="flex items-center gap-2.5">
          {/* Geocoding Search */}
          <form onSubmit={handleSearch} className="relative hidden md:block">
            <input
              type="text"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder="Search place..."
              className="bg-slate-950 border border-slate-700/80 rounded-lg pl-8 pr-3 py-1 text-xs text-white placeholder-slate-500 focus:outline-none focus:border-cyan-400 w-44 font-medium"
            />
            <svg className="w-3.5 h-3.5 text-slate-400 absolute left-2.5 top-2" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
            </svg>
            {isSearching && <span className="absolute right-2 top-1.5 text-xs text-cyan-400 animate-spin">⟳</span>}

            {/* Search Dropdown */}
            {searchResults.length > 0 && (
              <div className="absolute top-8 left-0 right-0 z-50 bg-slate-900 border border-slate-700 rounded-xl shadow-2xl overflow-hidden animate-fade-in">
                {searchResults.map((sr) => (
                  <button
                    key={sr.id}
                    type="button"
                    onClick={() => handleSelectSearchResult(sr)}
                    className="w-full px-3 py-2 text-left text-xs hover:bg-slate-800 text-slate-200 border-b border-slate-800 last:border-0"
                  >
                    <p className="font-semibold text-white">{sr.name}</p>
                    <p className="text-[10px] text-slate-400 truncate">{sr.formatted_address}</p>
                  </button>
                ))}
              </div>
            )}
          </form>

          {/* Language Switcher */}
          <div className="flex items-center bg-slate-950 border border-slate-800 rounded-lg p-0.5 text-[11px] font-bold">
            {(['en', 'hi', 'pa'] as const).map((lang) => (
              <button
                key={lang}
                onClick={() => i18n.changeLanguage(lang)}
                className={`px-2 py-0.5 rounded uppercase transition-colors ${
                  i18n.language === lang ? 'bg-cyan-500/30 text-cyan-300 border border-cyan-500/40' : 'text-slate-400 hover:text-white'
                }`}
              >
                {lang}
              </button>
            ))}
          </div>

          {/* System Health Dot */}
          <div className="flex items-center gap-1.5 px-2 py-1 rounded-lg bg-slate-950 border border-slate-800 text-[10px] font-mono text-slate-400">
            <span className={`w-2 h-2 rounded-full ${health?.status === 'ok' ? 'bg-emerald-400 animate-pulse' : 'bg-red-400'}`} />
            <span>{providerRef.current?.isMapbox() ? 'Mapbox v3' : 'MapLibre'}</span>
          </div>
        </div>
      </header>

      {/* ── Main Map Canvas ── */}
      <div className="relative flex-1 w-full h-full overflow-hidden">
        <div ref={mapContainerRef} className="absolute inset-0 w-full h-full" id="map-container" />

        {/* ── Floating Interactive Panel Dock ── */}
        {activeTab && (
          <aside className="absolute left-4 top-4 bottom-14 z-20 w-80 md:w-96 bg-slate-900/90 backdrop-blur-xl border border-slate-800/90 rounded-2xl shadow-2xl flex flex-col overflow-hidden animate-fade-in">
            {/* Panel Header */}
            <div className="p-4 border-b border-slate-800/80 flex items-center justify-between bg-slate-950/40">
              <h2 className="text-xs font-bold uppercase tracking-wider text-cyan-300 flex items-center gap-2">
                {navItems.find((n) => n.key === activeTab)?.label}
              </h2>
              <button
                onClick={() => setActiveTab(null)}
                className="w-6 h-6 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-400 hover:text-white flex items-center justify-center text-xs transition-colors"
              >
                ✕
              </button>
            </div>

            {/* Panel Body */}
            <div className="flex-1 overflow-y-auto p-4 custom-scrollbar">
              {activeTab === 'layers' && (
                <LayersPanel
                  provider={providerRef.current}
                  currentBasemap={currentBasemap}
                  onBasemapChange={handleBasemapChange}
                  layerStates={layerStates}
                  onLayerChange={handleLayerChange}
                  terrainEnabled={terrainEnabled}
                  onTerrainToggle={handleTerrainToggle}
                />
              )}
              {activeTab === 'issues' && currentProject && (
                <IssuesPanel
                  projectId={currentProject.id}
                  provider={providerRef.current}
                  onRefreshParcels={() => providerRef.current && loadProjectData(currentProject.id, providerRef.current)}
                />
              )}
              {activeTab === 'review' && currentProject && (
                <ReviewQueuePanel
                  projectId={currentProject.id}
                  provider={providerRef.current}
                  onParcelSelected={(p: ParcelFeature) => console.log('Selected parcel:', p)}
                />
              )}
              {activeTab === 'stats' && currentProject && (
                <StatsPanel projectId={currentProject.id} />
              )}
              {activeTab === 'compare' && currentProject && (
                <ComparePanel
                  projectId={currentProject.id}
                  swipeActive={swipeActive}
                  onToggleSwipe={handleToggleSwipe}
                />
              )}
              {activeTab === 'accuracy' && currentProject && (
                <AccuracyPanel projectId={currentProject.id} />
              )}
              {activeTab === 'context' && currentProject && (
                <ContextPanel projectId={currentProject.id} />
              )}
              {activeTab === 'upload' && (
                <UploadWizard
                  currentProject={currentProject}
                  onProjectChange={(p) => {
                    setCurrentProject(p);
                    if (providerRef.current) loadProjectData(p.id, providerRef.current);
                  }}
                  onPipelineCompleted={() => {
                    if (currentProject && providerRef.current) {
                      loadProjectData(currentProject.id, providerRef.current);
                    }
                  }}
                />
              )}
              {activeTab === 'export' && currentProject && (
                <ExportPanel projectId={currentProject.id} />
              )}
            </div>
          </aside>
        )}
      </div>

      {/* ── Preliminary Output Warning Banner ── */}
      <footer className="z-20 h-9 bg-amber-950/85 backdrop-blur-md border-t border-amber-700/60 flex items-center justify-center px-4 shadow-lg shrink-0">
        <div className="flex items-center gap-2 text-amber-200 text-xs font-medium">
          <svg className="w-4 h-4 text-amber-400 shrink-0" fill="currentColor" viewBox="0 0 20 20">
            <path fillRule="evenodd" d="M8.485 2.495c.673-1.167 2.357-1.167 3.03 0l6.28 10.875c.673 1.167-.17 2.625-1.516 2.625H3.72c-1.347 0-2.189-1.458-1.515-2.625L8.485 2.495zM10 5a.75.75 0 01.75.75v3.5a.75.75 0 01-1.5 0v-3.5A.75.75 0 0110 5zm0 9a1 1 0 100-2 1 1 0 000 2z" clipRule="evenodd" />
          </svg>
          <span className="font-bold uppercase tracking-wider text-amber-300">Preliminary Output</span>
          <span>— {t('preliminary_warning')}</span>
        </div>
      </footer>
    </div>
  );
}
