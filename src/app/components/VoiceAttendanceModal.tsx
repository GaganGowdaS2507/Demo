/**
 * VoiceAttendanceModal.tsx
 * ─────────────────────────────────────────────────────────────────────────────
 * Self-contained voice-attendance flow modal.
 *
 * Supports Multi-student Batch Voice Modes:
 *   1. Default Absent (Read Present) - 'bulk_present'
 *   2. Default Present (Read Absent) - 'bulk_absent'
 *   3. Spoken Name + Status         - 'name_status'
 *   4. Single Search & Confirm       - 'single'
 *
 * Uses @react-native-voice/voice for on-device STT.
 * Calls VoiceAttendanceService for backend batch voice evaluation & marking.
 * On success calls props.onMarked so AttendanceScreen updates its roster.
 * ─────────────────────────────────────────────────────────────────────────────
 */

import React, {
  useCallback,
  useEffect,
  useRef,
  useState,
} from 'react';
import {
  ActivityIndicator,
  Alert,
  FlatList,
  Modal,
  PermissionsAndroid,
  Platform,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  TouchableOpacity,
  View,
} from 'react-native';
import Voice, {
  SpeechResultsEvent,
  SpeechErrorEvent,
} from '@react-native-voice/voice';
import { colors, spacing, typography } from '../../theme/theme';
import {
  voiceSearch,
  voiceMark,
  voiceBatchMark,
  VoiceCandidate,
  VoiceBatchMarkResult,
} from '../services/VoiceAttendanceService';

const requestMicPermission = async (): Promise<boolean> => {
  if (Platform.OS === 'android') {
    try {
      const granted = await PermissionsAndroid.request(
        PermissionsAndroid.PERMISSIONS.RECORD_AUDIO,
        {
          title: 'Microphone Permission Needed',
          message: 'Voice Attendance requires microphone access to hear spoken student names.',
          buttonNeutral: 'Ask Me Later',
          buttonNegative: 'Cancel',
          buttonPositive: 'OK',
        },
      );
      return granted === PermissionsAndroid.RESULTS.GRANTED;
    } catch (err) {
      console.warn('Mic permission error:', err);
      return false;
    }
  }
  return true;
};

// ─── Props ───────────────────────────────────────────────────────────────────

export interface VoiceAttendanceModalProps {
  visible: boolean;
  sessionId: number;
  backendBaseUrl: string;
  onClose: () => void;
  /** Called after attendance is written so parent updates roster state */
  onMarked: (studentId: number, usn: string, name: string, status: 'present' | 'absent') => void;
}

export type VoiceMode = 'bulk_present' | 'bulk_absent' | 'name_status' | 'single';

type Phase =
  | 'idle'
  | 'listening'
  | 'processing'
  | 'confirming'
  | 'ambiguous'
  | 'notFound'
  | 'batchDone'
  | 'done';

// ─── Component ───────────────────────────────────────────────────────────────

export const VoiceAttendanceModal: React.FC<VoiceAttendanceModalProps> = ({
  visible,
  sessionId,
  backendBaseUrl,
  onClose,
  onMarked,
}) => {
  const [voiceMode, setVoiceMode]   = useState<VoiceMode>('bulk_present');
  const [phase, setPhase]           = useState<Phase>('idle');
  const [transcript, setTranscript] = useState('');
  const [candidates, setCandidates] = useState<VoiceCandidate[]>([]);
  const [selected, setSelected]     = useState<VoiceCandidate | null>(null);
  const [batchResult, setBatchResult] = useState<VoiceBatchMarkResult | null>(null);
  const [errorMsg, setErrorMsg]     = useState('');
  const [marking, setMarking]       = useState(false);

  const voiceSetup = useRef(false);

  const resetState = useCallback(() => {
    setPhase('idle');
    setTranscript('');
    setCandidates([]);
    setSelected(null);
    setBatchResult(null);
    setErrorMsg('');
    setMarking(false);
  }, []);

  // ── Register / remove Voice listeners ────────────────────────────────────

  useEffect(() => {
    if (!visible) {
      Voice.stop().catch(() => {});
      Voice.destroy().then(Voice.removeAllListeners).catch(() => {});
      resetState();
      voiceSetup.current = false;
      return;
    }

    if (voiceSetup.current) return;
    voiceSetup.current = true;

    const onResult = (e: SpeechResultsEvent) => {
      const heard = e.value?.[0] ?? '';
      if (heard) setTranscript(heard);
    };

    const onError = (e: SpeechErrorEvent) => {
      const code = String(e.error?.code ?? '');
      const msg = e.error?.message ?? 'Speech recognition error';

      if (code === '7') {
        setErrorMsg('Could not understand speech. Tap mic and try again.');
      } else if (code === '5') {
        setErrorMsg(
          'Mic Permission or Speech Engine Error (Error 5).\n' +
          'Please grant Microphone Permission in App Info settings.'
        );
      } else if (code === '9') {
        setErrorMsg('Insufficient permissions for microphone.');
      } else {
        setErrorMsg(`Mic error (${code}): ${msg}`);
      }
      setPhase('idle');
    };

    const onEnd = () => {
      setPhase((prev) => {
        if (prev === 'listening') return 'processing';
        return prev;
      });
    };

    Voice.onSpeechResults  = onResult;
    Voice.onSpeechError    = onError;
    Voice.onSpeechEnd      = onEnd;

    return () => {
      Voice.stop().catch(() => {});
      Voice.destroy().then(Voice.removeAllListeners).catch(() => {});
      voiceSetup.current = false;
    };
  }, [visible, resetState]);

  // ── Auto-process transcript once STT ends ────────────────────────────────

  useEffect(() => {
    if (phase !== 'processing') return;
    if (!transcript.trim()) {
      setErrorMsg('No speech detected. Tap the mic and try again.');
      setPhase('idle');
      return;
    }

    let cancelled = false;
    (async () => {
      try {
        if (voiceMode === 'single') {
          const result = await voiceSearch(backendBaseUrl, sessionId, transcript);
          if (cancelled) return;

          if (result.status === 'exact') {
            setSelected(result.matches[0]);
            setCandidates(result.matches);
            setPhase('confirming');
          } else if (result.status === 'multiple') {
            setCandidates(result.matches);
            setPhase('ambiguous');
          } else {
            setPhase('notFound');
          }
        } else {
          // Continuous Multi-student Batch Modes
          const defaultStatus = voiceMode === 'bulk_absent' ? 'present' : 'absent';
          const res = await voiceBatchMark(
            backendBaseUrl,
            sessionId,
            transcript,
            defaultStatus,
            voiceMode,
          );

          if (cancelled) return;

          if (res.marked && res.marked.length > 0) {
            setBatchResult(res);
            // Notify parent roster for each marked student
            res.marked.forEach((item) => {
              onMarked(item.student_id, item.usn, item.name, item.status);
            });
            setPhase('batchDone');
          } else {
            setPhase('notFound');
          }
        }
      } catch (err: any) {
        if (!cancelled) {
          setErrorMsg(err?.message ?? 'Server error during voice evaluation');
          setPhase('idle');
        }
      }
    })();

    return () => { cancelled = true; };
  }, [phase, transcript, backendBaseUrl, sessionId, voiceMode, onMarked]);

  // ── Mic controls ─────────────────────────────────────────────────────────

  const startListening = async () => {
    setErrorMsg('');
    setTranscript('');
    setCandidates([]);
    setSelected(null);
    setBatchResult(null);

    const hasPermission = await requestMicPermission();
    if (!hasPermission) {
      setErrorMsg('Microphone permission is required. Please grant permission in App Info settings.');
      return;
    }

    try {
      await Voice.stop().catch(() => {});
      await Voice.start('en-IN');
      setPhase('listening');
    } catch (err: any) {
      try {
        await Voice.start('en-US');
        setPhase('listening');
      } catch (fallbackErr: any) {
        setErrorMsg('Speech recognition engine failed to start on this device.');
      }
    }
  };

  const stopListening = async () => {
    try {
      await Voice.stop();
    } catch {}
  };

  // ── Single mode confirm button ───────────────────────────────────────────

  const confirmMark = async (student: VoiceCandidate) => {
    setMarking(true);
    try {
      const result = await voiceMark(backendBaseUrl, sessionId, student.student_id, 'present');
      onMarked(result.student_id, result.usn, result.name, result.status);
      setPhase('done');
      setTimeout(() => {
        onClose();
        resetState();
      }, 1200);
    } catch (err: any) {
      Alert.alert('Error', err?.message ?? 'Failed to mark attendance');
      setMarking(false);
    }
  };

  const pickCandidate = (student: VoiceCandidate) => {
    setSelected(student);
    setPhase('confirming');
  };

  // ── Render Voice Mode Selector Header ─────────────────────────────────────

  const renderModeSelector = () => (
    <View style={styles.modeSelectorContainer}>
      <Text style={styles.modeLabel}>VOICE ATTENDANCE MODE:</Text>
      <ScrollView horizontal showsHorizontalScrollIndicator={false} style={styles.modeScroll}>
        <TouchableOpacity
          style={[styles.modeChip, voiceMode === 'bulk_present' && styles.activeModeChip]}
          onPress={() => { if (phase === 'idle') setVoiceMode('bulk_present'); }}>
          <Text style={[styles.modeChipText, voiceMode === 'bulk_present' && styles.activeModeChipText]}>
            📋 Default Absent (Read Present)
          </Text>
        </TouchableOpacity>

        <TouchableOpacity
          style={[styles.modeChip, voiceMode === 'bulk_absent' && styles.activeModeChip]}
          onPress={() => { if (phase === 'idle') setVoiceMode('bulk_absent'); }}>
          <Text style={[styles.modeChipText, voiceMode === 'bulk_absent' && styles.activeModeChipText]}>
            📝 Default Present (Read Absent)
          </Text>
        </TouchableOpacity>

        <TouchableOpacity
          style={[styles.modeChip, voiceMode === 'name_status' && styles.activeModeChip]}
          onPress={() => { if (phase === 'idle') setVoiceMode('name_status'); }}>
          <Text style={[styles.modeChipText, voiceMode === 'name_status' && styles.activeModeChipText]}>
            🗣️ Name + Status
          </Text>
        </TouchableOpacity>

        <TouchableOpacity
          style={[styles.modeChip, voiceMode === 'single' && styles.activeModeChip]}
          onPress={() => { if (phase === 'idle') setVoiceMode('single'); }}>
          <Text style={[styles.modeChipText, voiceMode === 'single' && styles.activeModeChipText]}>
            🔍 Single Match
          </Text>
        </TouchableOpacity>
      </ScrollView>
    </View>
  );

  // ── Render Phase Body ─────────────────────────────────────────────────────

  const renderPhase = () => {
    switch (phase) {
      case 'idle':
        return (
          <View style={styles.centerBlock}>
            <TouchableOpacity style={styles.micBtn} onPress={startListening}>
              <Text style={styles.micIcon}>🎤</Text>
            </TouchableOpacity>

            {voiceMode === 'bulk_present' && (
              <Text style={styles.hintText}>
                Read Present Students continuously:{'\n'}
                <Text style={styles.hintExample}>"Deepthi N, User 1, User 2, Gagan Gowda"</Text>
              </Text>
            )}

            {voiceMode === 'bulk_absent' && (
              <Text style={styles.hintText}>
                Read Absent Students continuously:{'\n'}
                <Text style={styles.hintExample}>"User 3, User 5, User 12"</Text>
              </Text>
            )}

            {voiceMode === 'name_status' && (
              <Text style={styles.hintText}>
                Read Students with their Status:{'\n'}
                <Text style={styles.hintExample}>"Deepthi Present, User 1 Absent, User 2 Present"</Text>
              </Text>
            )}

            {voiceMode === 'single' && (
              <Text style={styles.hintText}>
                Say a single student name, USN, or roll number:{'\n'}
                <Text style={styles.hintExample}>"Mark Gagan Gowda present"</Text>
              </Text>
            )}

            {!!errorMsg && (
              <Text style={styles.errorText}>{errorMsg}</Text>
            )}
          </View>
        );

      case 'listening':
        return (
          <View style={styles.centerBlock}>
            <TouchableOpacity style={[styles.micBtn, styles.micBtnActive]} onPress={stopListening}>
              <Text style={styles.micIcon}>🎙️</Text>
            </TouchableOpacity>
            <Text style={[styles.hintText, { color: colors.accent }]}>Listening… Speak now</Text>
            {!!transcript && (
              <Text style={styles.transcriptPreview}>"{transcript}"</Text>
            )}
          </View>
        );

      case 'processing':
        return (
          <View style={styles.centerBlock}>
            <ActivityIndicator size="large" color={colors.accent} />
            <Text style={styles.hintText}>Evaluating roster & marking attendance…</Text>
            <Text style={styles.transcriptPreview}>"{transcript}"</Text>
          </View>
        );

      case 'batchDone':
        return (
          <View style={styles.fullBlock}>
            <Text style={styles.doneIcon}>✅</Text>
            <Text style={[styles.sectionTitle, { color: colors.success }]}>
              {batchResult?.marked_count ?? 0} Students Marked!
            </Text>
            <Text style={styles.transcriptPreview}>Spoken: "{transcript}"</Text>

            <FlatList
              data={batchResult?.marked ?? []}
              keyExtractor={(item) => String(item.student_id)}
              renderItem={({ item }) => (
                <View style={styles.candidateRow}>
                  <View>
                    <Text style={styles.candidateName}>{item.name}</Text>
                    <Text style={styles.candidateUsn}>{item.usn}</Text>
                  </View>
                  <Text style={[
                    styles.candidateStatus,
                    { color: item.status === 'present' ? colors.success : colors.danger },
                  ]}>
                    {item.status.toUpperCase()}
                  </Text>
                </View>
              )}
              style={{ maxHeight: 200, marginVertical: spacing.sm }}
            />

            <View style={styles.actionRow}>
              <TouchableOpacity
                style={[styles.actionBtn, styles.cancelBtn]}
                onPress={() => { resetState(); onClose(); }}>
                <Text style={styles.actionBtnText}>Done</Text>
              </TouchableOpacity>
              <TouchableOpacity
                style={[styles.actionBtn, { backgroundColor: colors.accent }]}
                onPress={resetState}>
                <Text style={styles.actionBtnText}>🎤 Continue Voice</Text>
              </TouchableOpacity>
            </View>
          </View>
        );

      case 'confirming': {
        const s = selected!;
        return (
          <View style={styles.centerBlock}>
            <Text style={styles.sectionTitle}>Confirm Attendance</Text>
            <View style={styles.studentCard}>
              <Text style={styles.studentName}>{s.name}</Text>
              <Text style={styles.studentUsn}>{s.usn}</Text>
              {s.current_status === 'present' && (
                <Text style={styles.alreadyPresent}>⚠️  Already marked present</Text>
              )}
            </View>
            <Text style={styles.transcriptPreview}>Heard: "{transcript}"</Text>

            <View style={styles.actionRow}>
              <TouchableOpacity
                style={[styles.actionBtn, styles.cancelBtn]}
                onPress={() => { setPhase('idle'); setSelected(null); }}>
                <Text style={styles.actionBtnText}>✕  Cancel</Text>
              </TouchableOpacity>
              <TouchableOpacity
                style={[styles.actionBtn, styles.confirmBtn, marking && styles.disabledBtn]}
                disabled={marking}
                onPress={() => confirmMark(s)}>
                {marking
                  ? <ActivityIndicator color="#fff" />
                  : <Text style={styles.actionBtnText}>✓  Mark Present</Text>}
              </TouchableOpacity>
            </View>
          </View>
        );
      }

      case 'ambiguous':
        return (
          <View style={styles.fullBlock}>
            <Text style={styles.sectionTitle}>Multiple students found</Text>
            <Text style={styles.hintText}>Heard: "{transcript}"</Text>
            <FlatList
              data={candidates}
              keyExtractor={(c) => String(c.student_id)}
              renderItem={({ item }) => (
                <TouchableOpacity style={styles.candidateRow} onPress={() => pickCandidate(item)}>
                  <View>
                    <Text style={styles.candidateName}>{item.name}</Text>
                    <Text style={styles.candidateUsn}>{item.usn}</Text>
                  </View>
                  <Text style={[
                    styles.candidateStatus,
                    { color: item.current_status === 'present' ? colors.success : colors.textSecondary },
                  ]}>
                    {item.current_status.toUpperCase()}
                  </Text>
                </TouchableOpacity>
              )}
              style={{ maxHeight: 220 }}
            />
            <TouchableOpacity
              style={[styles.actionBtn, styles.cancelBtn, { marginTop: spacing.sm }]}
              onPress={() => setPhase('idle')}>
              <Text style={styles.actionBtnText}>✕  Try Again</Text>
            </TouchableOpacity>
          </View>
        );

      case 'notFound':
        return (
          <View style={styles.centerBlock}>
            <Text style={styles.notFoundIcon}>🔍</Text>
            <Text style={[styles.sectionTitle, { color: colors.danger }]}>
              No matching students found
            </Text>
            <Text style={styles.transcriptPreview}>Heard: "{transcript}"</Text>
            <Text style={styles.hintText}>
              Please check the names / USNs and speak again.
            </Text>
            <TouchableOpacity
              style={[styles.actionBtn, { backgroundColor: colors.accent, marginTop: spacing.sm }]}
              onPress={() => setPhase('idle')}>
              <Text style={styles.actionBtnText}>🎤  Try Again</Text>
            </TouchableOpacity>
          </View>
        );

      case 'done':
        return (
          <View style={styles.centerBlock}>
            <Text style={styles.doneIcon}>✅</Text>
            <Text style={[styles.sectionTitle, { color: colors.success }]}>
              Attendance Marked!
            </Text>
            {selected && (
              <Text style={styles.studentUsn}>{selected.name} ({selected.usn})</Text>
            )}
          </View>
        );

      default:
        return null;
    }
  };

  return (
    <Modal
      visible={visible}
      transparent
      animationType="slide"
      onRequestClose={onClose}>
      <View style={styles.overlay}>
        <View style={styles.sheet}>
          {/* Header */}
          <View style={styles.header}>
            <Text style={styles.headerTitle}>🎤 Voice Attendance</Text>
            <Pressable onPress={onClose} style={styles.closeBtn} hitSlop={10}>
              <Text style={styles.closeBtnText}>✕</Text>
            </Pressable>
          </View>

          {/* Mode selector */}
          {renderModeSelector()}

          {/* Body */}
          {renderPhase()}
        </View>
      </View>
    </Modal>
  );
};

// ─── Styles ───────────────────────────────────────────────────────────────────

const styles = StyleSheet.create({
  overlay: {
    flex: 1,
    backgroundColor: 'rgba(0,0,0,0.65)',
    justifyContent: 'flex-end',
  },
  sheet: {
    backgroundColor: colors.surface,
    borderTopLeftRadius: 20,
    borderTopRightRadius: 20,
    paddingBottom: 34,
    borderWidth: 1,
    borderColor: colors.border,
    minHeight: 380,
  },
  header: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingHorizontal: spacing.lg,
    paddingTop: spacing.md,
    paddingBottom: spacing.xs,
    borderBottomWidth: 1,
    borderBottomColor: colors.border,
  },
  headerTitle: {
    ...typography.subtitle,
    color: colors.accent,
  },
  closeBtn: {
    padding: 4,
  },
  closeBtnText: {
    color: colors.textSecondary,
    fontSize: 18,
    fontWeight: '700',
  },
  modeSelectorContainer: {
    paddingHorizontal: spacing.md,
    paddingTop: spacing.xs,
    paddingBottom: spacing.xs,
    borderBottomWidth: 1,
    borderBottomColor: colors.border,
  },
  modeLabel: {
    fontSize: 10,
    fontWeight: '700',
    color: colors.textSecondary,
    marginBottom: 4,
    letterSpacing: 0.5,
  },
  modeScroll: {
    flexDirection: 'row',
  },
  modeChip: {
    paddingHorizontal: 12,
    paddingVertical: 6,
    borderRadius: 16,
    backgroundColor: colors.surfaceAlt,
    borderWidth: 1,
    borderColor: colors.border,
    marginRight: 6,
  },
  activeModeChip: {
    backgroundColor: colors.accent,
    borderColor: colors.accent,
  },
  modeChipText: {
    fontSize: 12,
    fontWeight: '600',
    color: colors.textSecondary,
  },
  activeModeChipText: {
    color: '#ffffff',
    fontWeight: '700',
  },
  centerBlock: {
    alignItems: 'center',
    paddingHorizontal: spacing.lg,
    paddingTop: spacing.md,
  },
  fullBlock: {
    paddingHorizontal: spacing.lg,
    paddingTop: spacing.md,
    alignItems: 'center',
  },
  micBtn: {
    width: 76,
    height: 76,
    borderRadius: 38,
    backgroundColor: colors.accent,
    justifyContent: 'center',
    alignItems: 'center',
    marginBottom: spacing.sm,
    shadowColor: colors.accent,
    shadowOpacity: 0.5,
    shadowRadius: 12,
    elevation: 8,
  },
  micBtnActive: {
    backgroundColor: colors.danger,
    shadowColor: colors.danger,
  },
  micIcon: {
    fontSize: 32,
  },
  hintText: {
    ...typography.body,
    textAlign: 'center',
    lineHeight: 20,
    marginTop: spacing.xs,
  },
  hintExample: {
    color: colors.accent,
    fontStyle: 'italic',
    fontWeight: '600',
  },
  transcriptPreview: {
    ...typography.body,
    color: colors.textPrimary,
    textAlign: 'center',
    marginTop: spacing.xs,
    fontStyle: 'italic',
    paddingHorizontal: spacing.sm,
  },
  errorText: {
    color: colors.danger,
    fontSize: 13,
    textAlign: 'center',
    marginTop: spacing.sm,
  },
  sectionTitle: {
    ...typography.subtitle,
    marginBottom: spacing.xs,
    textAlign: 'center',
  },
  studentCard: {
    backgroundColor: colors.surfaceAlt,
    borderRadius: 10,
    padding: spacing.md,
    width: '100%',
    alignItems: 'center',
    borderWidth: 1,
    borderColor: colors.accent,
    marginBottom: spacing.xs,
  },
  studentName: {
    fontSize: 18,
    fontWeight: '700',
    color: colors.textPrimary,
  },
  studentUsn: {
    ...typography.body,
    marginTop: 4,
    color: colors.textSecondary,
  },
  alreadyPresent: {
    color: colors.warning,
    fontSize: 12,
    marginTop: spacing.xs,
    fontWeight: '600',
  },
  actionRow: {
    flexDirection: 'row',
    gap: spacing.sm,
    marginTop: spacing.sm,
    width: '100%',
  },
  actionBtn: {
    flex: 1,
    paddingVertical: spacing.md,
    borderRadius: 10,
    alignItems: 'center',
    justifyContent: 'center',
  },
  cancelBtn: {
    backgroundColor: colors.surfaceAlt,
    borderWidth: 1,
    borderColor: colors.border,
  },
  confirmBtn: {
    backgroundColor: colors.success,
  },
  disabledBtn: {
    opacity: 0.5,
  },
  actionBtnText: {
    color: colors.textPrimary,
    fontWeight: '700',
    fontSize: 14,
  },
  candidateRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    paddingVertical: spacing.xs,
    paddingHorizontal: spacing.sm,
    borderBottomWidth: 1,
    borderBottomColor: colors.border,
    width: '100%',
  },
  candidateName: {
    ...typography.body,
    color: colors.textPrimary,
    fontWeight: '600',
  },
  candidateUsn: {
    ...typography.body,
    fontSize: 12,
    color: colors.textSecondary,
  },
  candidateStatus: {
    fontSize: 11,
    fontWeight: '700',
  },
  notFoundIcon: {
    fontSize: 36,
    marginBottom: spacing.xs,
  },
  doneIcon: {
    fontSize: 40,
    marginBottom: spacing.xs,
  },
});
