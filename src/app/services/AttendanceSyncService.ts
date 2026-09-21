import NetInfo from '@react-native-community/netinfo';
import { syncAttendance } from '../api/BackendClient';
import { getPendingAttendance, markSynced } from '../db/AttendanceDatabase';

let unsubscribe: (() => void) | null = null;

export async function pushPendingAttendance(backendBaseUrl: string, facultyUserId: number) {
  const pending = await getPendingAttendance(facultyUserId);
  if (pending.length === 0) return { success: true, inserted: 0, skipped: 0, errors: [] as string[] };

  const records = pending.map((r: any) => ({
    session_id: r.session_id,
    student_id: r.student_id,
    usn: r.usn,
    match_score: r.match_score,
    captured_at: r.captured_at,
    status: r.status,
    method: r.method,
    fingerprint_score: r.fingerprint_score,
  }));

  const res = await syncAttendance(backendBaseUrl, records);
  if (res.success && (res.inserted > 0 || res.skipped > 0)) {
    // Mark records as synced so they don't remain in queue indefinitely if backend accepted or processed them
    await markSynced(
      pending.map((r: any) => ({ session_id: r.session_id, student_id: r.student_id })),
      facultyUserId,
    );
  }
  return res;
}

export function startAutoSync(
  getBackendBaseUrl: () => string,
  enabled: () => boolean,
  getFacultyUserId: () => number | null,
) {
  if (unsubscribe) return;
  let wasOffline = false;
  unsubscribe = NetInfo.addEventListener((state) => {
    const online = !!state.isConnected && !!state.isInternetReachable;
    const facultyUserId = getFacultyUserId();
    if (online && wasOffline && enabled() && facultyUserId != null) {
      pushPendingAttendance(getBackendBaseUrl(), facultyUserId).catch((e) =>
        console.warn('[AttendanceSyncService] auto-sync failed', e?.message ?? e),
      );
    }
    wasOffline = !online;
  });
}

export function stopAutoSync() {
  if (unsubscribe) { unsubscribe(); unsubscribe = null; }
}