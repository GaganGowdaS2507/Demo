/**
 * Esp32FingerprintService.ts
 * Communicates with the ESP32-CAM + Fingerprint Node control server on Port 80.
 * Handles mode switching (/set-attendance-mode) and last scan retrieval (/last-scan).
 */
import axios from 'axios';

function extractHost(raw: string): string | null {
  if (!raw) return null;
  let s = raw.trim();
  s = s.replace(/^[a-zA-Z][a-zA-Z0-9+.-]*:\/\//, '');
  s = s.replace(/^www\./i, '');
  s = s.split('/')[0];
  s = s.split('?')[0];
  s = s.split(':')[0];
  return s || null;
}

export type Esp32AttendanceMode = 'FACE_ONLY' | 'FINGERPRINT_ONLY' | 'DUAL_MODE';

export interface Esp32LastScanResult {
  matched: boolean;
  id?: number;
  confidence?: number;
  seq?: number;
  timestamp?: number;
  name?: string;
}

export async function setEsp32AttendanceMode(
  streamUrlOrHost: string,
  mode: Esp32AttendanceMode,
): Promise<{ success: boolean; message?: string }> {
  const host = extractHost(streamUrlOrHost);
  if (!host) return { success: false, message: 'Invalid host' };

  try {
    const res = await axios.get(`http://${host}:80/set-attendance-mode`, {
      params: { mode },
      timeout: 3000,
    });
    return { success: true, message: String(res.data) };
  } catch (e: any) {
    return { success: false, message: e?.message ?? String(e) };
  }
}

export async function fetchEsp32LastScan(
  streamUrlOrHost: string,
): Promise<Esp32LastScanResult | null> {
  const host = extractHost(streamUrlOrHost);
  if (!host) return null;

  try {
    const res = await axios.get(`http://${host}:80/last-scan`, {
      timeout: 1500,
    });
    if (res.status === 200 && res.data) {
      return res.data as Esp32LastScanResult;
    }
  } catch {
    // Network / timeout
  }
  return null;
}

export async function fetchEsp32DeviceStatus(
  streamUrlOrHost: string,
): Promise<{ ip: string; fingerReady: boolean; seq: number; enrolledCount: number } | null> {
  const host = extractHost(streamUrlOrHost);
  if (!host) return null;

  try {
    const res = await axios.get(`http://${host}:80/status`, {
      timeout: 2000,
    });
    if (res.status === 200 && res.data) {
      return res.data;
    }
  } catch {
    // Network / timeout
  }
  return null;
}
