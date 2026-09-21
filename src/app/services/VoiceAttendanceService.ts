/**
 * VoiceAttendanceService.ts
 * ─────────────────────────────────────────────────────────────────────────────
 * Wraps the two backend voice-attendance endpoints:
 *
 *   POST /api/mobile/session/<id>/voice_search
 *   POST /api/mobile/session/<id>/voice_mark
 *
 * This service is deliberately thin — it only handles HTTP and exposes clean
 * typed results. All business logic (matching, safety guards) lives on the
 * backend. The modal drives the confirmation flow on top of these calls.
 * ─────────────────────────────────────────────────────────────────────────────
 */

import axios from 'axios';
import AsyncStorage from '@react-native-async-storage/async-storage';

const TOKEN_KEY = '@attendance_app/token';

async function authHeaders() {
  const token = await AsyncStorage.getItem(TOKEN_KEY);
  return token ? { Authorization: `Bearer ${token}` } : {};
}

// ─── Types ───────────────────────────────────────────────────────────────────

export interface VoiceCandidate {
  student_id: number;
  usn: string;
  name: string;
  current_status: 'present' | 'absent';
}

export interface VoiceSearchResult {
  /** 'exact'  — exactly one student matched, safe to show confirmation.
   *  'multiple' — faculty must pick from the list.
   *  'not_found' — no student matched. */
  status: 'exact' | 'multiple' | 'not_found';
  parsed: { type: 'usn' | 'roll' | 'name' | 'unknown'; value: string };
  matches: VoiceCandidate[];
}

export interface VoiceMarkResult {
  student_id: number;
  usn: string;
  name: string;
  status: 'present' | 'absent';
  method: string;
}

export interface VoiceBatchMarkResult {
  success: boolean;
  marked_count: number;
  marked: Array<{
    student_id: number;
    usn: string;
    name: string;
    status: 'present' | 'absent';
    marked_at: string;
  }>;
  marked_at: string;
}

// ─── API calls ───────────────────────────────────────────────────────────────

/**
 * Send the raw STT transcript to the backend for safe roster-scoped lookup.
 * This call is READ-ONLY — it never writes attendance.
 */
export async function voiceSearch(
  baseUrl: string,
  sessionId: number,
  transcript: string,
): Promise<VoiceSearchResult> {
  const headers = await authHeaders();
  const res = await axios.post(
    `${baseUrl}/api/mobile/session/${sessionId}/voice_search`,
    { transcript },
    { headers, timeout: 10000 },
  );
  if (!res.data.success) {
    throw new Error(res.data.message ?? 'voice_search failed');
  }
  return {
    status:  res.data.status,
    parsed:  res.data.parsed,
    matches: res.data.matches ?? [],
  };
}

/**
 * Mark a CONFIRMED student present / absent.
 * Faculty must have already reviewed the voice_search result and tapped
 * Confirm before this is called.
 */
export async function voiceMark(
  baseUrl: string,
  sessionId: number,
  studentId: number,
  status: 'present' | 'absent' = 'present',
): Promise<VoiceMarkResult> {
  const headers = await authHeaders();
  const res = await axios.post(
    `${baseUrl}/api/mobile/session/${sessionId}/voice_mark`,
    { student_id: studentId, status },
    { headers, timeout: 10000 },
  );
  if (!res.data.success) {
    throw new Error(res.data.message ?? 'voice_mark failed');
  }
  return {
    student_id: res.data.student_id,
    usn:        res.data.usn,
    name:       res.data.name,
    status:     res.data.status,
    method:     res.data.method,
  };
}

/**
 * Perform continuous multi-student voice attendance marking across roster.
 * Supports Mode 1 (bulk_present), Mode 2 (bulk_absent), and Mode 3 (name_status).
 */
export async function voiceBatchMark(
  baseUrl: string,
  sessionId: number,
  transcript: string,
  defaultStatus: 'present' | 'absent' = 'present',
  voiceMode: 'bulk_present' | 'bulk_absent' | 'name_status' = 'name_status',
): Promise<VoiceBatchMarkResult> {
  const headers = await authHeaders();
  const res = await axios.post(
    `${baseUrl}/api/mobile/session/${sessionId}/voice_batch_mark`,
    {
      transcript,
      default_status: defaultStatus,
      voice_mode: voiceMode,
    },
    { headers, timeout: 10000 },
  );
  if (!res.data.success) {
    throw new Error(res.data.message ?? 'voice_batch_mark failed');
  }
  return res.data;
}

