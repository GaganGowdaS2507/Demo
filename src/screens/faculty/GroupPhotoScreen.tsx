import React, { useState, useEffect } from 'react';
import {
  View, Text, Image, ScrollView, StyleSheet, Alert, Pressable, ActivityIndicator, FlatList,
} from 'react-native';
import { useRoute, useNavigation } from '@react-navigation/native';
import { launchCamera, launchImageLibrary } from 'react-native-image-picker';
import { colors, spacing, typography } from '../../theme/theme';
import { PrimaryButton } from '../../components/PrimaryButton';
import { useRecognitionEngine } from '../../hooks/useRecognitionEngine';
import { faceDetector } from '../../core/detection/MLKitFaceDetector';
import { similarityCalculator } from '../../core/similarity/SimilarityCalculator';
import {
  getGallery, GalleryEntry, queueAttendance, saveRoster, getRoster,
} from '../../app/db/AttendanceDatabase';
import { uploadClassroomPhotos } from '../../app/api/BackendClient';
import { useAuth } from '../../app/auth/AuthContext';

interface MatchedStudentItem {
  student_id: number;
  usn: string;
  name: string;
  score: number;
  selected: boolean;
}

export const GroupPhotoScreen: React.FC = () => {
  const { engine, settings } = useRecognitionEngine();
  const { userId } = useAuth();
  const route = useRoute<any>();
  const navigation = useNavigation();
  const { sessionId, sectionId, sectionLabel } = route.params ?? {};

  const [photos, setPhotos] = useState<string[]>([]);
  const [processingMode, setProcessingMode] = useState<'local' | 'server'>('local');
  const [loading, setLoading] = useState(false);
  const [statusMessage, setStatusMessage] = useState<string>('');

  const [matchedStudents, setMatchedStudents] = useState<MatchedStudentItem[]>([]);
  const [unrecognizedCount, setUnrecognizedCount] = useState<number>(0);
  const [totalFaces, setTotalFaces] = useState<number>(0);
  const [hasRecognized, setHasRecognized] = useState(false);

  const addPhoto = (type: 'camera' | 'library') => {
    if (photos.length >= 3) {
      Alert.alert('Limit Reached', 'You can upload maximum 3 classroom photos per session.');
      return;
    }

    const options = { mediaType: 'photo' as const, quality: 0.9 as const };
    const launcher = type === 'camera' ? launchCamera : launchImageLibrary;

    launcher(options, (response) => {
      if (response.assets && response.assets.length > 0) {
        const uri = response.assets[0].uri;
        if (uri) {
          setPhotos((prev) => [...prev, uri]);
        }
      }
    });
  };

  const removePhoto = (index: number) => {
    setPhotos((prev) => prev.filter((_, i) => i !== index));
    setHasRecognized(false);
  };

  const runRecognition = async () => {
    if (photos.length === 0) {
      Alert.alert('No Photos', 'Please capture or select at least 1 classroom photo.');
      return;
    }
    if (!userId) {
      Alert.alert('Error', 'User session invalid.');
      return;
    }

    setLoading(true);
    setStatusMessage('Initializing recognition...');

    try {
      if (processingMode === 'server') {
        setStatusMessage('Uploading photos to backend server...');
        const res = await uploadClassroomPhotos(settings.backendBaseUrl, sessionId, photos);
        if (res.success) {
          const items: MatchedStudentItem[] = res.matched.map((m) => ({
            student_id: m.student_id,
            usn: m.usn,
            name: m.full_name,
            score: Math.round(m.score * 100),
            selected: true,
          }));
          setMatchedStudents(items);
          setUnrecognizedCount(res.unrecognized_count);
          setTotalFaces(res.total_faces_detected);
          setHasRecognized(true);
        } else {
          Alert.alert('Backend Error', 'Failed to recognize photos on backend server.');
        }
      } else {
        // Local On-Device Mode
        if (!engine) {
          Alert.alert('Engine Error', 'On-device recognition engine is not loaded.');
          return;
        }

const CLASSROOM_DETECTION_OPTIONS = {
  performanceMode: 'accurate' as const,
  landmarkMode: 'all' as const,
  contourMode: 'none' as const,
  classificationMode: 'none' as const,
  minFaceSize: 0.02,
  trackingEnabled: false,
};

        setStatusMessage('Loading section enrollment gallery...');
        const fullGallery: GalleryEntry[] = await getGallery();
        const sessionRoster = await getRoster(sessionId);
        const rosterStudentIds = new Set(sessionRoster.map((r: any) => r.student_id));

        const gallery = fullGallery.filter(
          (g) => rosterStudentIds.has(g.student_id) || g.section_id === sectionId || rosterStudentIds.size === 0,
        );

        const studentBestMap = new Map<number, { student_id: number; usn: string; name: string; score: number }>();
        let detectedFaceCount = 0;
        let unknownCount = 0;
        const threshold = settings.similarityThreshold ?? 0.38;

        for (let pIdx = 0; pIdx < photos.length; pIdx++) {
          const uri = photos[pIdx];
          setStatusMessage(`Scanning classroom photo ${pIdx + 1} of ${photos.length}...`);

          const detection = await faceDetector.detectFaces(uri, CLASSROOM_DETECTION_OPTIONS);
          detectedFaceCount += detection.faces.length;

          for (const face of detection.faces) {
            try {
              const probe = await engine.generateEmbedding(uri, face);
              const best = similarityCalculator.findBestMatch(
                probe.embedding,
                gallery.map((g) => ({ id: String(g.student_id), embedding: g.embedding })),
                threshold,
              );

              const matched = best ? gallery.find((g) => String(g.student_id) === best.id) : undefined;
              if (best && matched) {
                const existing = studentBestMap.get(matched.student_id);
                if (!existing || best.result.score > existing.score) {
                  studentBestMap.set(matched.student_id, {
                    student_id: matched.student_id,
                    usn: matched.usn,
                    name: matched.name,
                    score: best.result.score,
                  });
                }
              } else {
                unknownCount++;
              }
            } catch (err) {
              console.log('[GroupPhoto] Face recognition item error:', err);
              unknownCount++;
            }
          }
        }

        const items: MatchedStudentItem[] = Array.from(studentBestMap.values()).map((m) => ({
          student_id: m.student_id,
          usn: m.usn,
          name: m.name,
          score: Math.round(m.score * 100),
          selected: true,
        }));

        setMatchedStudents(items);
        setUnrecognizedCount(unknownCount);
        setTotalFaces(detectedFaceCount);
        setHasRecognized(true);
      }
    } catch (e: any) {
      Alert.alert('Recognition Failed', e?.message ?? String(e));
    } finally {
      setLoading(false);
      setStatusMessage('');
    }
  };

  const toggleSelectStudent = (studentId: number) => {
    setMatchedStudents((prev) =>
      prev.map((item) => (item.student_id === studentId ? { ...item, selected: !item.selected } : item)),
    );
  };

  const confirmAttendance = async () => {
    const selectedList = matchedStudents.filter((s) => s.selected);
    if (selectedList.length === 0) {
      Alert.alert('No Selection', 'Please select at least one student to mark present.');
      return;
    }

    try {
      const currentRoster = await getRoster(sessionId);
      const updatedRoster = [...currentRoster];

      for (const item of selectedList) {
        await queueAttendance({
          session_id: sessionId,
          student_id: item.student_id,
          usn: item.usn,
          student_name: item.name,
          match_score: item.score / 100.0,
          captured_at: Date.now(),
          faculty_user_id: userId!,
          status: 'present',
        });

        const rIdx = updatedRoster.findIndex((r) => r.student_id === item.student_id);
        if (rIdx >= 0) {
          updatedRoster[rIdx] = { ...updatedRoster[rIdx], status: 'present', method: 'classroom_photo' };
        }
      }

      await saveRoster(sessionId, updatedRoster);
      Alert.alert(
        'Attendance Queued',
        `Successfully marked ${selectedList.length} students as present from classroom photo(s).`,
        [{ text: 'OK', onPress: () => navigation.goBack() }],
      );
    } catch (e: any) {
      Alert.alert('Save Failed', e?.message ?? String(e));
    }
  };

  return (
    <ScrollView style={styles.container} contentContainerStyle={{ paddingBottom: spacing.lg }}>
      <Text style={typography.title}>Classroom Group Photo Mode</Text>
      <Text style={typography.subtitle}>
        Section: {sectionLabel ?? `#${sectionId}`} | Session #{sessionId}
      </Text>

      {/* Mode Selector */}
      <View style={styles.modeRow}>
        <Pressable
          style={[styles.modeTab, processingMode === 'local' && styles.activeModeTab]}
          onPress={() => setProcessingMode('local')}>
          <Text style={[styles.modeText, processingMode === 'local' && styles.activeModeText]}>
            📱 Offline On-Device
          </Text>
        </Pressable>
        <Pressable
          style={[styles.modeTab, processingMode === 'server' && styles.activeModeTab]}
          onPress={() => setProcessingMode('server')}>
          <Text style={[styles.modeText, processingMode === 'server' && styles.activeModeText]}>
            🌐 Server API Mode
          </Text>
        </Pressable>
      </View>

      {/* Photo Picker Slots */}
      <Text style={[typography.subtitle, { marginTop: spacing.md }]}>
        Classroom Photos ({photos.length}/3)
      </Text>

      <View style={styles.photoRow}>
        {photos.map((uri, idx) => (
          <View key={`photo-slot-${idx}`} style={styles.photoCard}>
            <Image source={{ uri }} style={styles.thumbnail} />
            <Text style={styles.photoLabel}>Photo #{idx + 1}</Text>
            <Pressable style={styles.removeBtn} onPress={() => removePhoto(idx)}>
              <Text style={styles.removeText}>✕</Text>
            </Pressable>
          </View>
        ))}

        {photos.length < 3 && (
          <View style={styles.addPhotoCard}>
            <Text style={styles.addIcon}>📸</Text>
            <View style={styles.addBtnRow}>
              <Pressable style={styles.chipBtn} onPress={() => addPhoto('camera')}>
                <Text style={styles.chipText}>Camera</Text>
              </Pressable>
              <Pressable style={styles.chipBtn} onPress={() => addPhoto('library')}>
                <Text style={styles.chipText}>Gallery</Text>
              </Pressable>
            </View>
          </View>
        )}
      </View>

      {/* Recognize Button */}
      {photos.length > 0 && !loading && (
        <View style={{ marginTop: spacing.md }}>
          <PrimaryButton label={`Recognize ${photos.length} Classroom Photo(s)`} onPress={runRecognition} />
        </View>
      )}

      {loading && (
        <View style={styles.loadingBox}>
          <ActivityIndicator size="large" color={colors.accent} />
          <Text style={[typography.body, { marginTop: spacing.sm }]}>{statusMessage}</Text>
        </View>
      )}

      {/* Results View */}
      {hasRecognized && !loading && (
        <View style={styles.resultsContainer}>
          <Text style={[typography.subtitle, { marginTop: spacing.md }]}>Recognition Summary</Text>
          <View style={styles.summaryCard}>
            <View style={styles.summaryCol}>
              <Text style={styles.summaryNum}>{totalFaces}</Text>
              <Text style={styles.summaryLabel}>Total Faces</Text>
            </View>
            <View style={styles.summaryCol}>
              <Text style={[styles.summaryNum, { color: colors.success }]}>{matchedStudents.length}</Text>
              <Text style={styles.summaryLabel}>Identified</Text>
            </View>
            <View style={styles.summaryCol}>
              <Text style={[styles.summaryNum, { color: colors.danger }]}>{unrecognizedCount}</Text>
              <Text style={styles.summaryLabel}>Unrecognized</Text>
            </View>
          </View>

          <Text style={[typography.subtitle, { marginTop: spacing.md }]}>
            Identified Students ({matchedStudents.filter((s) => s.selected).length}/{matchedStudents.length})
          </Text>

          {matchedStudents.length === 0 ? (
            <Text style={[typography.body, { marginVertical: spacing.sm }]}>
              No enrolled section students were recognized in these photos.
            </Text>
          ) : (
            matchedStudents.map((item) => (
              <Pressable
                key={`matched-${item.student_id}`}
                style={styles.studentRow}
                onPress={() => toggleSelectStudent(item.student_id)}>
                <Text style={styles.checkbox}>{item.selected ? '☑' : '☐'}</Text>
                <View style={{ flex: 1, marginLeft: spacing.sm }}>
                  <Text style={typography.body}>{item.name}</Text>
                  <Text style={styles.usnSub}>{item.usn}</Text>
                </View>
                <Text style={styles.scoreTag}>{item.score}% match</Text>
              </Pressable>
            ))
          )}

          {matchedStudents.length > 0 && (
            <View style={{ marginTop: spacing.md }}>
              <PrimaryButton
                label={`Confirm & Mark ${matchedStudents.filter((s) => s.selected).length} Present`}
                onPress={confirmAttendance}
              />
            </View>
          )}
        </View>
      )}
    </ScrollView>
  );
};

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.background, padding: spacing.lg },
  modeRow: { flexDirection: 'row', backgroundColor: colors.surface, borderRadius: 10, padding: 4, marginVertical: spacing.sm },
  modeTab: { flex: 1, paddingVertical: 8, alignItems: 'center', borderRadius: 8 },
  activeModeTab: { backgroundColor: colors.accent },
  modeText: { color: colors.textSecondary, fontWeight: '600', fontSize: 12 },
  activeModeText: { color: '#ffffff', fontWeight: '700' },
  photoRow: { flexDirection: 'row', justifyContent: 'space-between', marginVertical: spacing.sm },
  photoCard: { width: '31%', backgroundColor: colors.surface, borderRadius: 10, padding: 4, alignItems: 'center', position: 'relative' },
  thumbnail: { width: '100%', height: 90, borderRadius: 8 },
  photoLabel: { color: colors.textSecondary, fontSize: 10, marginTop: 4 },
  removeBtn: { position: 'absolute', top: 2, right: 2, backgroundColor: 'rgba(0,0,0,0.6)', width: 20, height: 20, borderRadius: 10, alignItems: 'center', justifyContent: 'center' },
  removeText: { color: '#ffffff', fontSize: 10, fontWeight: '700' },
  addPhotoCard: { width: '31%', height: 115, backgroundColor: colors.surface, borderRadius: 10, borderWidth: 1.5, borderColor: colors.border, borderStyle: 'dashed', justifyContent: 'center', alignItems: 'center' },
  addIcon: { fontSize: 24, marginBottom: 4 },
  addBtnRow: { flexDirection: 'column', gap: 4 },
  chipBtn: { backgroundColor: colors.accent, paddingHorizontal: 8, paddingVertical: 4, borderRadius: 4 },
  chipText: { color: '#ffffff', fontSize: 10, fontWeight: '700' },
  loadingBox: { padding: spacing.lg, alignItems: 'center', justifyContent: 'center' },
  resultsContainer: { marginTop: spacing.sm },
  summaryCard: { flexDirection: 'row', backgroundColor: colors.surface, padding: spacing.md, borderRadius: 10, justifyContent: 'space-around', marginVertical: spacing.xs },
  summaryCol: { alignItems: 'center' },
  summaryNum: { fontSize: 20, fontWeight: '700', color: colors.textPrimary },
  summaryLabel: { color: colors.textSecondary, fontSize: 11 },
  studentRow: { flexDirection: 'row', alignItems: 'center', backgroundColor: colors.surface, padding: spacing.sm, borderRadius: 8, marginVertical: 4 },
  checkbox: { fontSize: 20, color: colors.accent },
  usnSub: { color: colors.textSecondary, fontSize: 11 },
  scoreTag: { color: colors.success, fontSize: 12, fontWeight: '700' },
});
