/**
 * =============================================================================
 * RecognitionEngineProvider / useRecognitionEngine
 * =============================================================================
 * App-wide React context that owns the currently-active IRecognitionEngine
 * instance. This is the ONLY place UI code touches engine lifecycle
 * (initialize/dispose) — screens consume `engine` and `switchModel()` without
 * knowing whether they're talking to TFLite or ONNX underneath.
 *
 * Also owns the shared IFaceDetector and IDatabase singletons and exposes
 * app settings, since nearly every screen needs some combination of these.
 * =============================================================================
 */
import React, {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from 'react';
import type { AppSettings, IRecognitionEngine, ModelLoadStatus } from '../core/types';
import { createRecognitionEngine } from '../core/engine/RecognitionEngineFactory';
import { getModelById } from '../core/config/ModelCatalog';
import { loadSettings, saveSettings, DEFAULT_SETTINGS } from '../core/config/SettingsStore';
import { faceDetector } from '../core/detection/MLKitFaceDetector';

interface RecognitionEngineContextValue {
  engine: IRecognitionEngine | null;
  loadStatus: ModelLoadStatus | null;
  settings: AppSettings;
  isBootstrapping: boolean;
  switchModel: (modelId: string) => Promise<void>;
  updateSettings: (partial: Partial<AppSettings>) => Promise<void>;
}

const RecognitionEngineContext = createContext<RecognitionEngineContextValue | null>(null);

export const RecognitionEngineProvider: React.FC<{ children: React.ReactNode }> = ({
  children,
}) => {
  const [engine, setEngine] = useState<IRecognitionEngine | null>(null);
  const [loadStatus, setLoadStatus] = useState<ModelLoadStatus | null>(null);
  const [settings, setSettings] = useState<AppSettings>(DEFAULT_SETTINGS);
  const [isBootstrapping, setIsBootstrapping] = useState(true);

  const switchModel = useCallback(
    async (modelId: string) => {
      const metadata = getModelById(modelId);
      if (!metadata) {
        throw new Error(`useRecognitionEngine: unknown modelId "${modelId}"`);
      }

      // Dispose the previous engine before loading the new one to free native memory.
      if (engine) {
        await engine.dispose();
      }

      const { engine: newEngine, status } = await createRecognitionEngine(metadata);
      setEngine(newEngine);
      setLoadStatus(status);

      const updated = { ...settings, activeModelId: modelId };
      setSettings(updated);
      await saveSettings(updated);
    },
    [engine, settings],
  );

  const updateSettings = useCallback(
    async (partial: Partial<AppSettings>) => {
      const updated = { ...settings, ...partial };
      setSettings(updated);
      await saveSettings(updated);
    },
    [settings],
  );

  useEffect(() => {
    let cancelled = false;

    (async () => {
      try {
        console.log('[RecognitionEngine] Initializing face detector...');
        await faceDetector.initialize();

        console.log('[RecognitionEngine] Loading settings...');
        const loaded = await loadSettings();

        if (cancelled) return;
        setSettings(loaded);

        console.log('[RecognitionEngine] Active model:', loaded.activeModelId);

        const metadata = getModelById(loaded.activeModelId);

        if (metadata) {
          console.log('[RecognitionEngine] Creating engine...');
          const { engine: initialEngine, status } =
            await createRecognitionEngine(metadata);

          if (cancelled) return;

          setEngine(initialEngine);
          setLoadStatus(status);

          console.log('[RecognitionEngine] Engine initialized successfully.');
          console.log('[RecognitionEngine] Load status:', status);
          console.log('[RecognitionEngine] Metadata:', initialEngine.getMetadata());
          console.log('[RecognitionEngine] Ready:', initialEngine.isReady());
        } else {
          console.warn(
            '[RecognitionEngine] Model not found:',
            loaded.activeModelId,
          );
        }
      } catch (e) {
        console.error('[RecognitionEngine] Initialization failed:', e);
      } finally {
        if (!cancelled) {
          setIsBootstrapping(false);
        }
      }
    })();

    return () => {
      cancelled = true;
    };
  }, []);

  const value = useMemo(
    () => ({ engine, loadStatus, settings, isBootstrapping, switchModel, updateSettings }),
    [engine, loadStatus, settings, isBootstrapping, switchModel, updateSettings],
  );

  return (
    <RecognitionEngineContext.Provider value={value}>
      {children}
    </RecognitionEngineContext.Provider>
  );
};

export function useRecognitionEngine(): RecognitionEngineContextValue {
  const ctx = useContext(RecognitionEngineContext);
  if (!ctx) {
    throw new Error('useRecognitionEngine must be used within a RecognitionEngineProvider');
  }
  return ctx;
}
