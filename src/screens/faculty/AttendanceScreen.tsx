import React, { useRef, useState, useCallback, useEffect } from 'react';
import { View, Text, TextInput, StyleSheet, Alert, Pressable, RefreshControl, ScrollView } from 'react-native';
import { useRoute, useNavigation } from '@react-navigation/native';
import ImageResizer from '@bam.tech/react-native-image-resizer';
import { colors, spacing, typography } from '../../theme/theme';
import { PrimaryButton } from '../../components/PrimaryButton';
import { useRecognitionEngine } from '../../hooks/useRecognitionEngine';
import { faceDetector } from '../../core/detection/MLKitFaceDetector';
import { similarityCalculator } from '../../core/similarity/SimilarityCalculator';
import { Esp32StreamView, checkEsp32Reachable } from '../../app/components/Esp32StreamView';
import { PhoneCameraView } from '../../app/components/PhoneCameraView';
import {
  getGallery, GalleryEntry, queueAttendance, isAlreadyQueued,
  saveRoster, getRoster, getQueuedStatuses,
  lookupStudentByFingerprint, upsertFingerprintTemplates,
} from '../../app/db/AttendanceDatabase';
import { fetchSessionRoster, fetchFingerprintTemplates } from '../../app/api/BackendClient';
import { useAuth } from '../../app/auth/AuthContext';
import {
  setEsp32AttendanceMode, fetchEsp32LastScan, Esp32AttendanceMode,
} from '../../app/services/Esp32FingerprintService';
import { VoiceAttendanceModal } from '../../app/components/VoiceAttendanceModal';

const CAPTURE_INTERVAL_MS = 800;
const FP_POLL_INTERVAL_MS = 500;

interface FaceOverlayItem {
  box: { x: number; y: number; width: number; height: number };
  studentName?: string;
  usn?: string;
  score?: number;
  isUnknown?: boolean;
  statusType?: 'success' | 'warning' | 'prompt' | 'unknown';
  customLabel?: string;
}

interface FaceOverlaysState {
  items: FaceOverlayItem[];
  imageWidth: number;
  imageHeight: number;
  timestamp: number;
}

interface DualTargetState {
  studentId: number;
  usn: string;
  name: string;
  fpScore: number;
  expiresAt: number;
}

export const AttendanceScreen: React.FC = () => {
  const { engine, settings } = useRecognitionEngine();
  const { userId } = useAuth();
  const route = useRoute<any>();
  const navigation = useNavigation<any>();
  const { sessionId, sectionId, sectionLabel } = route.params ?? {};

  const streamRef = useRef<{ captureFrameUri(): Promise<string> } | null>(null);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const fpPollerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const countdownTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const busyRef = useRef(false);
  const galleryRef = useRef<GalleryEntry[]>([]);
  const lastScanSeqRef = useRef<number>(-1);
  const dualTargetRef = useRef<DualTargetState | null>(null);

  const [cameraSource, setCameraSource] = useState<'phone' | 'esp32'>('phone');
  const [phonePosition, setPhonePosition] = useState<'front' | 'back'>('front');
  const [esp32Mode, setEsp32Mode] = useState<Esp32AttendanceMode>('FACE_ONLY');
  const [cameraInput, setCameraInput] = useState(settings.esp32StreamUrl);
  const [connected, setConnected] = useState(false);
  const [running, setRunning] = useState(false);
  const [roster, setRoster] = useState<any[]>([]);
  const [loadingRoster, setLoadingRoster] = useState(true);
  const [refreshingRoster, setRefreshingRoster] = useState(false);
  const [dualTarget, setDualTarget] = useState<DualTargetState | null>(null);
  const [countdownSec, setCountdownSec] = useState<number>(0);
  const [deviceLogs, setDeviceLogs] = useState<string[]>(['[Ready] ESP32 node listener idle']);

  const [cameraLayout, setCameraLayout] = useState<{ width: number; height: number }>({ width: 340, height: 260 });
  const [activeOverlay, setActiveOverlay] = useState<FaceOverlaysState | null>(null);
  const [voiceModalOpen, setVoiceModalOpen] = useState(false);

  const addDeviceLog = useCallback((msg: string) => {
    const time = new Date().toLocaleTimeString();
    setDeviceLogs((prev) => [...prev.slice(-15), `[${time}] ${msg}`]);
  }, []);

  const clearDualTarget = useCallback((logReason?: string) => {
    setDualTarget(null);
    dualTargetRef.current = null;
    setCountdownSec(0);
    if (countdownTimerRef.current) {
      clearInterval(countdownTimerRef.current);
      countdownTimerRef.current = null;
    }
    if (logReason) {
      addDeviceLog(logReason);
    }
  }, [addDeviceLog]);

  const armDualTarget = useCallback((target: DualTargetState) => {
    if (countdownTimerRef.current) {
      clearInterval(countdownTimerRef.current);
      countdownTimerRef.current = null;
    }
    setDualTarget(target);
    dualTargetRef.current = target;
    setCountdownSec(10);

    countdownTimerRef.current = setInterval(() => {
      if (!dualTargetRef.current) {
        if (countdownTimerRef.current) clearInterval(countdownTimerRef.current);
        return;
      }
      const rem = Math.max(0, Math.ceil((dualTargetRef.current.expiresAt - Date.now()) / 1000));
      setCountdownSec(rem);
      if (rem <= 0) {
        clearDualTarget(`[Timed Out] 10s Dual Verification window expired for ${dualTargetRef.current.name}. Touch sensor again.`);
      }
    }, 1000);
  }, [clearDualTarget]);

  const updateRosterWithMarkedStudent = useCallback((
    prevRoster: any[],
    studentIdentifier: number | string,
    updates: { status: 'present' | 'absent'; method?: string }
  ) => {
    const targetIndex = prevRoster.findIndex(
      (r) => r.student_id === studentIdentifier || r.usn === studentIdentifier
    );
    if (targetIndex === -1) return prevRoster;

    const targetItem = {
      ...prevRoster[targetIndex],
      ...updates,
      marked_at: Date.now(),
    };

    const remaining = prevRoster.filter((_, idx) => idx !== targetIndex);

    if (updates.status === 'present') {
      // Bring the marked student to the very top (first of list)
      return [targetItem, ...remaining];
    } else {
      // If toggled to absent, place after all currently present students
      const presentItems = remaining.filter((r) => r.status === 'present');
      const absentItems = remaining.filter((r) => r.status !== 'present');
      return [...presentItems, targetItem, ...absentItems];
    }
  }, []);

  const saveAttendanceLocally = async () => {
    await saveRoster(sessionId, roster);
    Alert.alert('Saved', 'Attendance saved to this device. Use "Sync / Upload Attendance" on the Pending tab to send it to the server.');
  };

  const loadRoster = useCallback(async () => {
    setRefreshingRoster(true);
    let list: any[] = [];
    try {
      const res = await fetchSessionRoster(settings.backendBaseUrl, sessionId);
      list = res.roster;
      await saveRoster(sessionId, list);
    } catch {
      list = await getRoster(sessionId);
    }

    // Also auto-sync fingerprint templates for offline mapping
    try {
      const fpRes = await fetchFingerprintTemplates(settings.backendBaseUrl, sectionId);
      if (fpRes.success && fpRes.fingerprints) {
        await upsertFingerprintTemplates(fpRes.fingerprints);
      }
    } catch (fpErr) {
      console.warn('[AttendanceScreen] Fingerprint templates initial load warning:', fpErr);
    }

    const queuedStatuses = await getQueuedStatuses(sessionId);
    list = list.map((r: any) => ({
      ...r,
      status: queuedStatuses.get(r.student_id) ?? r.status ?? 'absent',
    }));

    list.sort((a, b) => {
      if (a.status === 'present' && b.status !== 'present') return -1;
      if (a.status !== 'present' && b.status === 'present') return 1;
      return (a.name || '').localeCompare(b.name || '');
    });

    setRoster(list);
    setLoadingRoster(false);
    setRefreshingRoster(false);
  }, [sessionId, sectionId, settings.backendBaseUrl]);

  useEffect(() => {
    loadRoster();
    getGallery().then((entries) => {
      galleryRef.current = entries;
    });
  }, [loadRoster]);

  // Keep dualTargetRef synced
  useEffect(() => {
    dualTargetRef.current = dualTarget;
  }, [dualTarget]);

  // =========================================================================
  // 1. UNTOUCHED: Standard Phone Camera Face Recognition
  // =========================================================================
  const processPhoneCameraFrame = useCallback(async () => {
    if (busyRef.current || !engine || !streamRef.current || !userId) return;
    busyRef.current = true;
    try {
      const rawUri = await streamRef.current.captureFrameUri();

      let normUri = rawUri;
      try {
        const resized = await ImageResizer.createResizedImage(
          rawUri,
          1080,
          1080,
          'JPEG',
          90,
          0,
          undefined,
          false,
          { mode: 'contain' },
        );
        normUri = resized.uri;
      } catch (err) {
        console.log('[Attendance] pre-process normalization fallback:', err);
      }

      const detection = await faceDetector.detectFaces(normUri);
      if (detection.faces.length === 0) {
        setActiveOverlay(null);
        return;
      }

      const overlayItems: FaceOverlayItem[] = [];

      for (const face of detection.faces) {
        try {
          const probe = await engine.generateEmbedding(normUri, face);
          const best = similarityCalculator.findBestMatch(
            probe.embedding,
            galleryRef.current.map((g) => ({ id: String(g.student_id), embedding: g.embedding })),
            settings.similarityThreshold ?? 0.45,
          );

          const matched = best ? galleryRef.current.find((g) => String(g.student_id) === best.id) : undefined;

          if (best && matched) {
            overlayItems.push({
              box: face.boundingBox,
              studentName: matched.name,
              usn: matched.usn,
              score: Math.round(best.result.score * 100),
              isUnknown: false,
              statusType: 'success',
            });

            await queueAttendance({
              session_id: sessionId,
              student_id: matched.student_id,
              usn: matched.usn,
              student_name: matched.name,
              match_score: best.result.score,
              captured_at: Date.now(),
              faculty_user_id: userId,
              status: 'present',
              method: 'face_recognition',
            });

            setRoster((prev) =>
              updateRosterWithMarkedStudent(prev, matched.student_id, { status: 'present', method: 'face' })
            );
          } else {
            overlayItems.push({
              box: face.boundingBox,
              isUnknown: true,
              statusType: 'unknown',
            });
          }
        } catch (faceErr) {
          console.log('[Attendance] Face recognition item skipped:', faceErr);
          overlayItems.push({
            box: face.boundingBox,
            isUnknown: true,
            statusType: 'unknown',
          });
        }
      }

      setActiveOverlay({
        items: overlayItems,
        imageWidth: detection.imageWidth,
        imageHeight: detection.imageHeight,
        timestamp: Date.now(),
      });
    } catch (e: any) {
      console.log('[Attendance] frame skipped:', e?.message ?? String(e));
    } finally {
      busyRef.current = false;
    }
  }, [engine, settings, sessionId, userId, updateRosterWithMarkedStudent]);

  // =========================================================================
  // 2. ESP32 CAMERA MODULE: 3 Automatic Modes (Face, Fingerprint, Dual)
  // =========================================================================

  // ---- ESP32 Fingerprint Hardware Poller (/last-scan) ----
  const pollEsp32Hardware = useCallback(async () => {
    if (!cameraInput || !userId) return;
    const scan = await fetchEsp32LastScan(cameraInput);
    if (!scan) return;

    const seq = scan.seq ?? -1;
    // Strictly require a NEW scan sequence to prevent re-triggering stale hardware memory
    if (scan.matched && seq > lastScanSeqRef.current) {
      lastScanSeqRef.current = seq;
      const templateId = scan.id;
      const confidence = scan.confidence ?? 0;

      if (!templateId) return;

      // Look up student from offline database (with on-the-fly backend fallback)
      let student = await lookupStudentByFingerprint(templateId);
      if (!student) {
        try {
          const fpRes = await fetchFingerprintTemplates(settings.backendBaseUrl, sectionId);
          if (fpRes.success && fpRes.fingerprints) {
            await upsertFingerprintTemplates(fpRes.fingerprints);
            student = await lookupStudentByFingerprint(templateId);
          }
        } catch (fpErr) {
          console.warn('[Attendance] fallback lookup error:', fpErr);
        }
      }

      if (student) {
        // Validate section roster
        const inRoster = roster.some((r) => r.student_id === student!.student_id || r.usn === student!.usn);
        if (!inRoster && roster.length > 0) {
          addDeviceLog(`Fingerprint rejected: ${student.name} (${student.usn}) not in this section`);
          return;
        }

        if (esp32Mode === 'FINGERPRINT_ONLY') {
          await queueAttendance({
            session_id: sessionId,
            student_id: student.student_id,
            usn: student.usn,
            student_name: student.name,
            match_score: 1.0,
            fingerprint_score: confidence,
            captured_at: Date.now(),
            faculty_user_id: userId,
            status: 'present',
            method: 'fingerprint',
          });

          setRoster((prev) =>
            updateRosterWithMarkedStudent(prev, student!.student_id, { status: 'present', method: 'fingerprint' })
          );
          addDeviceLog(`Marked Present (Fingerprint): ${student.name} (${student.usn}) [conf=${confidence}]`);
        } else if (esp32Mode === 'DUAL_MODE') {
          // NEW FINGERPRINT SCANNED! Arm 10s countdown for O(1) face check
          const target: DualTargetState = {
            studentId: student.student_id,
            usn: student.usn,
            name: student.name,
            fpScore: confidence,
            expiresAt: Date.now() + 10000,
          };
          armDualTarget(target);
          addDeviceLog(`👆 Fingerprint Verified: ${student.name}. Please show face to camera within 10s.`);
        }
      } else {
        addDeviceLog(`Unmapped Slot #${templateId} scanned on sensor`);
      }
    }
  }, [cameraInput, userId, sessionId, sectionId, roster, esp32Mode, settings.backendBaseUrl, addDeviceLog, armDualTarget, updateRosterWithMarkedStudent]);

  // ---- ESP32 Camera Stream Frame Processor (Face / Dual Mode) ----
  const processEsp32CameraFrame = useCallback(async () => {
    if (busyRef.current || !engine || !streamRef.current || !userId) return;
    busyRef.current = true;
    try {
      const rawUri = await streamRef.current.captureFrameUri();

      let normUri = rawUri;
      try {
        const resized = await ImageResizer.createResizedImage(
          rawUri,
          1080,
          1080,
          'JPEG',
          90,
          0,
          undefined,
          false,
          { mode: 'contain' },
        );
        normUri = resized.uri;
      } catch (err) {
        console.log('[Attendance] ESP32 pre-process normalization fallback:', err);
      }

      const detection = await faceDetector.detectFaces(normUri);
      if (detection.faces.length === 0) {
        setActiveOverlay(null);
        return;
      }

      const now = Date.now();
      const currentTarget = dualTargetRef.current;

      // Check if dual target has expired
      if (currentTarget && now > currentTarget.expiresAt) {
        clearDualTarget(`[Timed Out] 10s Dual Verification window expired for ${currentTarget.name}. Touch sensor again.`);
      }

      const overlayItems: FaceOverlayItem[] = [];

      // DUAL MODE BRANCH
      if (esp32Mode === 'DUAL_MODE') {
        if (!currentTarget || now > currentTarget.expiresAt) {
          // NO finger scanned yet: Draw neutral box guiding user to touch sensor.
          // NEVER match against full database and NEVER mark attendance on face alone!
          for (const face of detection.faces) {
            overlayItems.push({
              box: face.boundingBox,
              statusType: 'prompt',
              customLabel: 'Touch Sensor First',
            });
          }
        } else {
          // TARGET ARMED: Targeted O(1) face verification against ONLY currentTarget student
          const targetEntry = galleryRef.current.find((g) => g.student_id === currentTarget.studentId);

          for (const face of detection.faces) {
            if (targetEntry) {
              const probe = await engine.generateEmbedding(normUri, face);
              const score = similarityCalculator.cosineSimilarity(probe.embedding, targetEntry.embedding);
              const threshold = settings.similarityThreshold ?? 0.45;

              if (score >= threshold) {
                // Match confirmed!
                overlayItems.push({
                  box: face.boundingBox,
                  studentName: currentTarget.name,
                  usn: currentTarget.usn,
                  score: Math.round(score * 100),
                  statusType: 'success',
                  customLabel: `✓ ${currentTarget.name} Dual Verified`,
                });

                await queueAttendance({
                  session_id: sessionId,
                  student_id: currentTarget.studentId,
                  usn: currentTarget.usn,
                  student_name: currentTarget.name,
                  match_score: score,
                  fingerprint_score: currentTarget.fpScore,
                  captured_at: Date.now(),
                  faculty_user_id: userId,
                  status: 'present',
                  method: 'dual_verification',
                });

                setRoster((prev) =>
                  updateRosterWithMarkedStudent(prev, currentTarget.studentId, { status: 'present', method: 'dual' })
                );

                addDeviceLog(`✓ Dual Verified (Face + Fingerprint): ${currentTarget.name} (${currentTarget.usn})`);
                clearDualTarget();
              } else {
                overlayItems.push({
                  box: face.boundingBox,
                  statusType: 'warning',
                  customLabel: `Matching ${currentTarget.name}…`,
                });
              }
            } else {
              overlayItems.push({
                box: face.boundingBox,
                statusType: 'warning',
                customLabel: `No face enrolled for ${currentTarget.name}`,
              });
            }
          }
        }
      } else if (esp32Mode === 'FACE_ONLY') {
        // STANDARD FACE ONLY BRANCH (ESP32 CAMERA)
        for (const face of detection.faces) {
          try {
            const probe = await engine.generateEmbedding(normUri, face);
            const best = similarityCalculator.findBestMatch(
              probe.embedding,
              galleryRef.current.map((g) => ({ id: String(g.student_id), embedding: g.embedding })),
              settings.similarityThreshold ?? 0.45,
            );

            const matched = best ? galleryRef.current.find((g) => String(g.student_id) === best.id) : undefined;

            if (best && matched) {
              overlayItems.push({
                box: face.boundingBox,
                studentName: matched.name,
                usn: matched.usn,
                score: Math.round(best.result.score * 100),
                statusType: 'success',
              });

              await queueAttendance({
                session_id: sessionId,
                student_id: matched.student_id,
                usn: matched.usn,
                student_name: matched.name,
                match_score: best.result.score,
                captured_at: Date.now(),
                faculty_user_id: userId,
                status: 'present',
                method: 'face_recognition',
              });

              setRoster((prev) =>
                updateRosterWithMarkedStudent(prev, matched.student_id, { status: 'present', method: 'face' })
              );
            } else {
              overlayItems.push({
                box: face.boundingBox,
                isUnknown: true,
                statusType: 'unknown',
              });
            }
          } catch (faceErr) {
            overlayItems.push({
              box: face.boundingBox,
              isUnknown: true,
              statusType: 'unknown',
            });
          }
        }
      }

      setActiveOverlay({
        items: overlayItems,
        imageWidth: detection.imageWidth,
        imageHeight: detection.imageHeight,
        timestamp: Date.now(),
      });
    } catch (e: any) {
      console.log('[Attendance] ESP32 frame skipped:', e?.message ?? String(e));
    } finally {
      busyRef.current = false;
    }
  }, [engine, settings, sessionId, userId, esp32Mode, addDeviceLog, clearDualTarget, updateRosterWithMarkedStudent]);

  // Handle Mode Switch & Sync Hardware Sequence
  const handleModeSwitch = async (newMode: Esp32AttendanceMode) => {
    if (running) return;
    setEsp32Mode(newMode);
    clearDualTarget();
    if (cameraInput) {
      const scan = await fetchEsp32LastScan(cameraInput);
      if (scan && typeof scan.seq === 'number') {
        lastScanSeqRef.current = scan.seq;
      }
    }
  };

  // =========================================================================
  // Control Lifecycle (Start / Stop)
  // =========================================================================
  const start = async () => {
    if (cameraSource === 'esp32' && !connected) {
      Alert.alert('Not connected', 'Connect to the ESP32 camera first.');
      return;
    }
    setRunning(true);
    clearDualTarget();

    if (cameraSource === 'esp32' && cameraInput) {
      // Sync last scan sequence so previous fingerprint scans are IGNORED
      const initialScan = await fetchEsp32LastScan(cameraInput);
      lastScanSeqRef.current = (initialScan && typeof initialScan.seq === 'number') ? initialScan.seq : -1;
    } else {
      lastScanSeqRef.current = -1;
    }

    if (cameraSource === 'phone') {
      timerRef.current = setInterval(processPhoneCameraFrame, CAPTURE_INTERVAL_MS);
    } else {
      // Configure ESP32 attendance mode on hardware Port 80
      await setEsp32AttendanceMode(cameraInput, esp32Mode);
      addDeviceLog(`Hardware Mode set to ${esp32Mode}`);

      if (esp32Mode === 'FACE_ONLY') {
        timerRef.current = setInterval(processEsp32CameraFrame, CAPTURE_INTERVAL_MS);
      } else if (esp32Mode === 'FINGERPRINT_ONLY') {
        fpPollerRef.current = setInterval(pollEsp32Hardware, FP_POLL_INTERVAL_MS);
      } else if (esp32Mode === 'DUAL_MODE') {
        timerRef.current = setInterval(processEsp32CameraFrame, CAPTURE_INTERVAL_MS);
        fpPollerRef.current = setInterval(pollEsp32Hardware, FP_POLL_INTERVAL_MS);
      }
    }
  };

  const stop = async () => {
    setRunning(false);
    setActiveOverlay(null);
    clearDualTarget();
    if (timerRef.current) { clearInterval(timerRef.current); timerRef.current = null; }
    if (fpPollerRef.current) { clearInterval(fpPollerRef.current); fpPollerRef.current = null; }

    if (cameraSource === 'esp32' && connected) {
      await setEsp32AttendanceMode(cameraInput, 'FACE_ONLY');
      addDeviceLog('Hardware listener stopped');
    }
  };

  useEffect(() => () => {
    if (timerRef.current) clearInterval(timerRef.current);
    if (fpPollerRef.current) clearInterval(fpPollerRef.current);
  }, []);

  // ---- Manual marking (single + bulk) ----
  const commitManual = async (studentId: number, nextStatus: 'present' | 'absent') => {
    const student = roster.find((r) => r.student_id === studentId);
    if (!student || !userId) return;

    await queueAttendance({
      session_id: sessionId,
      student_id: studentId,
      usn: student.usn,
      student_name: student.name,
      match_score: 1.0,
      captured_at: Date.now(),
      faculty_user_id: userId,
      status: nextStatus,
      method: 'manual_individual',
    });
    setRoster((prev) =>
      updateRosterWithMarkedStudent(prev, studentId, { status: nextStatus, method: 'manual' })
    );
  };

  const requestManualToggle = (studentId: number) => {
    const s = roster.find((r) => r.student_id === studentId);
    if (!s) return;
    const nextStatus = s.status === 'present' ? 'absent' : 'present';
    commitManual(studentId, nextStatus);
  };

  const requestBulkMark = (targetStatus: 'present' | 'absent') => {
    Alert.alert(
      `Mark All ${targetStatus.toUpperCase()}?`,
      `Are you sure you want to mark all ${roster.length} students as ${targetStatus}?`,
      [
        { text: 'Cancel', style: 'cancel' },
        {
          text: 'Confirm',
          onPress: async () => {
            for (const r of roster) {
              await commitManual(r.student_id, targetStatus);
            }
          },
        },
      ],
    );
  };

  const testEsp32 = async () => {
    try {
      await checkEsp32Reachable(cameraInput);
      setConnected(true);
      clearDualTarget();
      // Sync last scan sequence so previous fingerprint scans are IGNORED upon connection
      const initialScan = await fetchEsp32LastScan(cameraInput);
      lastScanSeqRef.current = (initialScan && typeof initialScan.seq === 'number') ? initialScan.seq : -1;
      addDeviceLog(`Connected to ESP32 at ${cameraInput}`);
      Alert.alert('Connected', 'ESP32 Device Node is reachable.');
    } catch (e: any) {
      setConnected(false);
      Alert.alert('Connection Failed', `Could not reach ${cameraInput}: ${e?.message ?? String(e)}`);
    }
  };

  const presentCount = roster.filter((r) => r.status === 'present').length;
  const absentCount = roster.filter((r) => r.status === 'absent').length;
  const totalCount = roster.length;
  const presentPercent = totalCount > 0 ? Math.round((presentCount / totalCount) * 100) : 0;

  return (
    <ScrollView
      style={styles.container}
      contentContainerStyle={styles.contentContainer}
      keyboardShouldPersistTaps="handled"
      refreshControl={
        <RefreshControl refreshing={refreshingRoster} onRefresh={loadRoster} colors={[colors.accent]} />
      }>
      <Text style={typography.title}>Section: {sectionLabel ?? `Section #${sectionId}`}</Text>
      <Text style={typography.subtitle}>Session #{sessionId}</Text>

      <View style={styles.topActionRow}>
        <Pressable
          style={[styles.groupPhotoBtn, { flex: 1 }]}
          onPress={() => navigation.navigate('GroupPhoto', { sessionId, sectionId, sectionLabel })}>
          <Text style={styles.groupPhotoBtnText}>📸 Group Photo</Text>
        </Pressable>

        <Pressable
          style={[styles.voiceBtnTop, { flex: 1 }]}
          onPress={() => setVoiceModalOpen(true)}>
          <Text style={styles.voiceBtnText}>🎤 Voice Attendance</Text>
        </Pressable>
      </View>

      {/* Main Camera Source Selector Tabs */}
      <View style={styles.tabRow}>
        <Pressable
          style={[styles.tab, cameraSource === 'phone' && styles.activeTab]}
          onPress={() => { if (!running) setCameraSource('phone'); }}>
          <Text style={[styles.tabText, cameraSource === 'phone' && styles.activeTabText]}>📱 Phone Camera</Text>
        </Pressable>
        <Pressable
          style={[styles.tab, cameraSource === 'esp32' && styles.activeTab]}
          onPress={() => { if (!running) setCameraSource('esp32'); }}>
          <Text style={[styles.tabText, cameraSource === 'esp32' && styles.activeTabText]}>📡 ESP32 Device Node</Text>
        </Pressable>
      </View>

      {/* ========================================================================= */}
      {/* 1. UNTOUCHED: Phone Camera View */}
      {/* ========================================================================= */}
      {cameraSource === 'phone' ? (
        <View style={styles.cameraBox} onLayout={(e) => setCameraLayout(e.nativeEvent.layout)}>
          <PhoneCameraView
            ref={streamRef as any}
            position={phonePosition}
            isActive={true}
          />
          <View style={styles.cameraActionRow}>
            <Pressable
              style={styles.switchCamBtn}
              onPress={() => setPhonePosition((prev) => (prev === 'front' ? 'back' : 'front'))}>
              <Text style={styles.switchCamText}>🔄 Switch Lens ({phonePosition.toUpperCase()})</Text>
            </Pressable>
          </View>

          {/* Multi-Face Bounding Box Overlays */}
          {activeOverlay && (Date.now() - activeOverlay.timestamp < 3500) && activeOverlay.items.map((item, idx) => {
            const isMatched = !!item.studentName;
            const borderColor = isMatched ? colors.success : item.isUnknown ? '#ef4444' : '#f59e0b';
            const tagBg = isMatched ? colors.success : item.isUnknown ? '#ef4444' : '#f59e0b';
            const tagLabel = isMatched
              ? `✓ ${item.studentName} (${item.score}%)`
              : item.isUnknown
              ? '❓ Unknown'
              : 'Scanning…';

            return (
              <View
                key={`face-overlay-${idx}`}
                pointerEvents="none"
                style={[
                  styles.overlayBox,
                  {
                    left: (item.box.x * cameraLayout.width) / activeOverlay.imageWidth,
                    top: (item.box.y * 260) / activeOverlay.imageHeight,
                    width: (item.box.width * cameraLayout.width) / activeOverlay.imageWidth,
                    height: (item.box.height * 260) / activeOverlay.imageHeight,
                    borderColor: borderColor,
                  },
                ]}>
                <View style={[styles.overlayTag, { backgroundColor: tagBg }]}>
                  <Text style={styles.overlayTagText}>{tagLabel}</Text>
                </View>
              </View>
            );
          })}
        </View>
      ) : (
        /* ========================================================================= */
        /* 2. ESP32 RECOGNITION NODE: 3 Modes (Face, Fingerprint, Dual) */
        /* ========================================================================= */
        <View style={styles.cameraBox} onLayout={(e) => setCameraLayout(e.nativeEvent.layout)}>
          <TextInput
            style={styles.input}
            placeholder="ESP32 Stream URL / IP (e.g. 192.168.4.1)"
            placeholderTextColor={colors.textSecondary}
            value={cameraInput}
            onChangeText={setCameraInput}
            editable={!running}
          />

          {/* ESP32 3-Mode Sub-Tabs */}
          <View style={styles.modeSubTabRow}>
            <Pressable
              style={[styles.modeSubTab, esp32Mode === 'FACE_ONLY' && styles.activeModeSubTab]}
              onPress={() => handleModeSwitch('FACE_ONLY')}>
              <Text style={[styles.modeSubTabText, esp32Mode === 'FACE_ONLY' && styles.activeModeSubTabText]}>👤 Face Only</Text>
            </Pressable>
            <Pressable
              style={[styles.modeSubTab, esp32Mode === 'FINGERPRINT_ONLY' && styles.activeModeSubTab]}
              onPress={() => handleModeSwitch('FINGERPRINT_ONLY')}>
              <Text style={[styles.modeSubTabText, esp32Mode === 'FINGERPRINT_ONLY' && styles.activeModeSubTabText]}>👆 Fingerprint Only</Text>
            </Pressable>
            <Pressable
              style={[styles.modeSubTab, esp32Mode === 'DUAL_MODE' && styles.activeModeSubTab]}
              onPress={() => handleModeSwitch('DUAL_MODE')}>
              <Text style={[styles.modeSubTabText, esp32Mode === 'DUAL_MODE' && styles.activeModeSubTabText]}>🛡️ Dual Mode</Text>
            </Pressable>
          </View>

          {connected ? (
            esp32Mode === 'FINGERPRINT_ONLY' ? (
              /* Biometric Terminal Card for FINGERPRINT_ONLY mode */
              <View style={styles.biometricTerminalCard}>
                <View style={styles.biometricIconCircle}>
                  <Text style={styles.biometricIcon}>👆</Text>
                </View>
                <Text style={styles.biometricTitle}>Hardware Sensor Armed & Polling</Text>
                <Text style={styles.biometricSubtitle}>Have students touch the optical sensor on the ESP32 node.</Text>
                
                {/* Live Event Log Ticker */}
                <View style={styles.logTickerBox}>
                  {deviceLogs.map((log, idx) => (
                    <Text key={`log-${idx}`} style={styles.logTickerText}>{log}</Text>
                  ))}
                </View>
              </View>
            ) : (
              /* Camera Stream View for Face Only & Dual Mode */
              <View>
                {esp32Mode === 'DUAL_MODE' && (
                  <View style={[styles.dualModeBanner, dualTarget ? styles.dualModeBannerActive : null]}>
                    <Text style={styles.dualModeBannerText}>
                      {dualTarget
                        ? `⏱️ Verify Face: ${dualTarget.name} (${countdownSec}s remaining)`
                        : '🔒 Dual Mode: Touch Fingerprint Sensor First'}
                    </Text>
                  </View>
                )}
                <Esp32StreamView
                  ref={streamRef as any}
                  streamUrlOrHost={cameraInput}
                  onError={(e) => Alert.alert('Stream error', e.message)}
                />
              </View>
            )
          ) : (
            <PrimaryButton label="Connect to ESP32 Node" onPress={testEsp32} disabled={!cameraInput.trim()} />
          )}

          {/* Bounding Box Overlays for ESP32 (Face Only / Dual Mode) */}
          {connected && esp32Mode !== 'FINGERPRINT_ONLY' && activeOverlay && (Date.now() - activeOverlay.timestamp < 3500) && activeOverlay.items.map((item, idx) => {
            let borderColor = colors.success;
            let tagBg = colors.success;
            let tagLabel = item.customLabel || `✓ ${item.studentName} (${item.score}%)`;

            if (item.statusType === 'prompt') {
              borderColor = '#00c2ff';
              tagBg = '#00c2ff';
              tagLabel = item.customLabel || 'Touch Sensor First';
            } else if (item.statusType === 'warning') {
              borderColor = '#f59e0b';
              tagBg = '#f59e0b';
            } else if (item.statusType === 'unknown' || item.isUnknown) {
              borderColor = '#ef4444';
              tagBg = '#ef4444';
              tagLabel = '❓ Unknown';
            }

            return (
              <View
                key={`esp32-face-overlay-${idx}`}
                pointerEvents="none"
                style={[
                  styles.overlayBox,
                  {
                    left: (item.box.x * cameraLayout.width) / activeOverlay.imageWidth,
                    top: (item.box.y * 260) / activeOverlay.imageHeight,
                    width: (item.box.width * cameraLayout.width) / activeOverlay.imageWidth,
                    height: (item.box.height * 260) / activeOverlay.imageHeight,
                    borderColor: borderColor,
                  },
                ]}>
                <View style={[styles.overlayTag, { backgroundColor: tagBg }]}>
                  <Text style={styles.overlayTagText}>{tagLabel}</Text>
                </View>
              </View>
            );
          })}
        </View>
      )}

      {(cameraSource === 'phone' || connected) && (
        running
          ? <PrimaryButton label="Stop Recognition" onPress={stop} variant="danger" />
          : <PrimaryButton label="Start Recognition" onPress={start} />
      )}

      {/* ── Voice Attendance Button ── */}
      <Pressable
        style={styles.voiceBtn}
        onPress={() => setVoiceModalOpen(true)}>
        <Text style={styles.voiceBtnText}>🎤  Voice Attendance Mode</Text>
      </Pressable>

      <PrimaryButton label="Save Attendance to Device" onPress={saveAttendanceLocally} />
      <View style={styles.bulkRow}>
        <PrimaryButton label="Mark All Present" onPress={() => requestBulkMark('present')} variant="secondary" />
        <PrimaryButton label="Mark All Absent" onPress={() => requestBulkMark('absent')} variant="secondary" />
      </View>

      {/* Attendance Stats Summary Card */}
      <View style={styles.statsCard}>
        <View style={styles.statCol}>
          <Text style={styles.statNum}>{totalCount}</Text>
          <Text style={styles.statLabel}>Total</Text>
        </View>
        <View style={styles.statDivider} />
        <View style={styles.statCol}>
          <Text style={[styles.statNum, { color: colors.success }]}>{presentCount}</Text>
          <Text style={styles.statLabel}>Present</Text>
        </View>
        <View style={styles.statDivider} />
        <View style={styles.statCol}>
          <Text style={[styles.statNum, { color: colors.danger }]}>{absentCount}</Text>
          <Text style={styles.statLabel}>Absent</Text>
        </View>
        <View style={styles.statDivider} />
        <View style={styles.statCol}>
          <Text style={[styles.statNum, { color: colors.accent }]}>{presentPercent}%</Text>
          <Text style={styles.statLabel}>Attendance</Text>
        </View>
      </View>

      <Text style={[typography.subtitle, { marginTop: spacing.xs, marginBottom: spacing.xs }]}>Roster</Text>

      {loadingRoster ? (
        <Text style={typography.body}>Loading roster…</Text>
      ) : (
        <View style={styles.rosterContainer}>
          {roster.map((item) => (
            <Pressable key={`roster-${item.student_id}`} style={styles.row} onPress={() => requestManualToggle(item.student_id)}>
              <View>
                <Text style={typography.body}>{item.name} ({item.usn})</Text>
                {item.method ? (
                  <Text style={styles.methodBadgeText}>
                    {item.method === 'fingerprint' ? '👆 Fingerprint' : item.method === 'dual' ? '🛡️ Dual Verified' : item.method === 'face' ? '👤 Face' : item.method === 'voice_command' ? '🎤 Voice' : item.method}
                  </Text>
                ) : null}
              </View>
              <Text style={{ color: item.status === 'present' ? colors.success : item.status === 'absent'? colors.danger : colors.textSecondary, fontWeight: '700' }}>
                {item.status.toUpperCase()}
              </Text>
            </Pressable>
          ))}
        </View>
      )}

      {/* ── Voice Attendance Modal ── */}
      <VoiceAttendanceModal
        visible={voiceModalOpen}
        sessionId={sessionId}
        backendBaseUrl={settings.backendBaseUrl}
        onClose={() => setVoiceModalOpen(false)}
        onMarked={(studentId, _usn, _name, status) => {
          setRoster((prev) =>
            updateRosterWithMarkedStudent(prev, studentId, { status, method: 'voice_command' })
          );
        }}
      />
    </ScrollView>
  );
};

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.background },
  contentContainer: { padding: spacing.lg, paddingBottom: spacing.xl * 2 },
  rosterContainer: { marginTop: spacing.xs },
  groupPhotoBtn: { backgroundColor: colors.accent, paddingVertical: 10, paddingHorizontal: 16, borderRadius: 8, alignItems: 'center', marginVertical: spacing.xs },
  groupPhotoBtnText: { color: '#ffffff', fontWeight: '700', fontSize: 13 },
  statsCard: {
    flexDirection: 'row',
    backgroundColor: colors.surface,
    padding: spacing.md,
    borderRadius: 10,
    justifyContent: 'space-around',
    alignItems: 'center',
    marginVertical: spacing.sm,
    borderWidth: 1,
    borderColor: colors.border,
  },
  statCol: { alignItems: 'center' },
  statNum: { fontSize: 18, fontWeight: '700', color: colors.textPrimary },
  statLabel: { color: colors.textSecondary, fontSize: 10, marginTop: 2 },
  statDivider: { width: 1, height: '70%', backgroundColor: colors.border },
  tabRow: { flexDirection: 'row', backgroundColor: colors.surface, borderRadius: 10, padding: 4, marginVertical: spacing.sm },
  tab: { flex: 1, paddingVertical: 10, alignItems: 'center', borderRadius: 8 },
  activeTab: { backgroundColor: colors.accent },
  tabText: { color: colors.textSecondary, fontWeight: '600', fontSize: 13 },
  activeTabText: { color: '#ffffff', fontWeight: '700' },
  modeSubTabRow: { flexDirection: 'row', backgroundColor: colors.surface, borderRadius: 8, padding: 3, marginBottom: spacing.xs, borderWidth: 1, borderColor: colors.border },
  modeSubTab: { flex: 1, paddingVertical: 7, alignItems: 'center', borderRadius: 6 },
  activeModeSubTab: { backgroundColor: colors.accent },
  modeSubTabText: { color: colors.textSecondary, fontSize: 11, fontWeight: '600' },
  activeModeSubTabText: { color: '#ffffff', fontWeight: '700' },
  cameraBox: { marginVertical: spacing.xs, position: 'relative' },
  overlayBox: {
    position: 'absolute',
    borderWidth: 2.5,
    borderRadius: 8,
    zIndex: 99,
  },
  overlayTag: {
    alignSelf: 'flex-start',
    paddingHorizontal: 8,
    paddingVertical: 3,
    borderRadius: 4,
    marginTop: -24,
  },
  overlayTagText: {
    color: '#ffffff',
    fontSize: 11,
    fontWeight: '700',
  },
  cameraActionRow: { flexDirection: 'row', justifyContent: 'flex-end', marginVertical: 6 },
  switchCamBtn: { backgroundColor: colors.surface, paddingHorizontal: 12, paddingVertical: 6, borderRadius: 6, borderWidth: 1, borderColor: colors.border },
  switchCamText: { color: colors.textPrimary, fontSize: 12, fontWeight: '600' },
  input: {
    backgroundColor: colors.surface, color: colors.textPrimary, borderRadius: 10,
    padding: spacing.md, marginVertical: spacing.xs, borderWidth: 1, borderColor: colors.border,
  },
  biometricTerminalCard: {
    backgroundColor: colors.surface,
    padding: spacing.md,
    borderRadius: 10,
    alignItems: 'center',
    borderWidth: 1.5,
    borderColor: colors.success,
    marginVertical: spacing.xs,
  },
  biometricIconCircle: {
    width: 60,
    height: 60,
    borderRadius: 30,
    backgroundColor: 'rgba(34, 197, 94, 0.15)',
    justifyContent: 'center',
    alignItems: 'center',
    marginBottom: spacing.xs,
  },
  biometricIcon: { fontSize: 28 },
  biometricTitle: { fontSize: 14, fontWeight: '700', color: colors.success, marginBottom: 2 },
  biometricSubtitle: { fontSize: 11, color: colors.textSecondary, textAlign: 'center', marginBottom: spacing.xs },
  logTickerBox: {
    width: '100%',
    backgroundColor: colors.background,
    borderRadius: 6,
    padding: 8,
    maxHeight: 90,
    borderWidth: 1,
    borderColor: colors.border,
  },
  logTickerText: { fontSize: 10, color: colors.textSecondary, fontFamily: 'monospace', marginBottom: 2 },
  dualModeBanner: {
    backgroundColor: '#0284c7',
    paddingVertical: 6,
    paddingHorizontal: 10,
    borderRadius: 6,
    marginBottom: 6,
    alignItems: 'center',
  },
  dualModeBannerActive: { backgroundColor: '#ea580c' },
  dualModeBannerText: { color: '#ffffff', fontSize: 12, fontWeight: '700' },
  bulkRow: { flexDirection: 'row', justifyContent: 'space-between', marginTop: spacing.sm },
  row: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', paddingVertical: spacing.xs, borderBottomWidth: 1, borderBottomColor: colors.border },
  methodBadgeText: { fontSize: 10, color: colors.textSecondary, marginTop: 2 },
  topActionRow: {
    flexDirection: 'row',
    gap: spacing.xs,
    marginVertical: spacing.xs,
  },
  voiceBtnTop: {
    backgroundColor: '#7C3AED',
    paddingVertical: 10,
    paddingHorizontal: 12,
    borderRadius: 8,
    alignItems: 'center',
    justifyContent: 'center',
  },
  voiceBtn: {
    backgroundColor: '#7C3AED',
    borderRadius: 10,
    paddingVertical: spacing.md,
    alignItems: 'center',
    justifyContent: 'center',
    marginVertical: spacing.xs,
  },
  voiceBtnDisabled: { opacity: 0.4 },
  voiceBtnText: { color: '#ffffff', fontSize: 14, fontWeight: '700' },
  voiceBtnSub: { color: 'rgba(255,255,255,0.7)', fontSize: 11, marginTop: 2 },
});