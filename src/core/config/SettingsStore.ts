/**
 * =============================================================================
 * SettingsStore
 * =============================================================================
 * Lightweight persisted app settings (active model, threshold, etc.) using
 * AsyncStorage. Deliberately separate from the SQLite Database layer: these
 * are simple key-value UI preferences, not benchmarking data — no need to
 * pull in the SQLite layer for a handful of settings.
 * =============================================================================
 */
import AsyncStorage from '@react-native-async-storage/async-storage';
import type { AppSettings } from '../types';
import { DEFAULT_MODEL_ID } from './ModelCatalog';

const SETTINGS_KEY = '@face_recognition_playground/settings';

export const DEFAULT_SETTINGS: AppSettings = {
  activeModelId: DEFAULT_MODEL_ID,
  similarityThreshold: 0.45,
  saveDebugCrops: true,
  cameraFacing: 'front',
  detectorPerformanceMode: 'accurate',
  backendBaseUrl: 'http://127.0.0.1:5000',
  esp32StreamUrl: '192.168.4.1',
  attendanceCooldownMinutes: 0,
  autoSyncOnReconnect: true,
};

export async function loadSettings(): Promise<AppSettings> {
  try {
    const raw = await AsyncStorage.getItem(SETTINGS_KEY);
    if (!raw) return DEFAULT_SETTINGS;
    return { ...DEFAULT_SETTINGS, ...JSON.parse(raw) };
  } catch {
    return DEFAULT_SETTINGS;
  }
}

export async function saveSettings(settings: AppSettings): Promise<void> {
  await AsyncStorage.setItem(SETTINGS_KEY, JSON.stringify(settings));
}

export async function updateSetting<K extends keyof AppSettings>(
  key: K,
  value: AppSettings[K],
): Promise<AppSettings> {
  const current = await loadSettings();
  const updated = { ...current, [key]: value };
  await saveSettings(updated);
  return updated;
}
