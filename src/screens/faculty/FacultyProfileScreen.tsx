import React, { useCallback, useEffect, useState } from 'react';
import { View, Text, ScrollView, StyleSheet, RefreshControl, Alert } from 'react-native';
import { colors, spacing, typography } from '../../theme/theme';
import { getFacultyProfile, getFacultySections, getFacultySubjects, saveFacultyProfile, saveFacultySections, saveFacultySubjects } from '../../app/db/AttendanceDatabase';
import { fetchFacultyProfile } from '../../app/api/BackendClient';
import { useRecognitionEngine } from '../../hooks/useRecognitionEngine';
import { PrimaryButton } from '../../components/PrimaryButton';

import { useAuth } from '../../app/auth/AuthContext';

export const FacultyProfileScreen: React.FC = () => {
  const { settings } = useRecognitionEngine();
  const { userId } = useAuth();
  const [profile, setProfile] = useState<any>(null);
  const [sections, setSections] = useState<any[]>([]);
  const [subjects, setSubjects] = useState<any[]>([]);
  const [refreshing, setRefreshing] = useState(false);

  const load = useCallback(async () => {
    setProfile(await getFacultyProfile(userId ?? undefined));
    setSections(await getFacultySections());
    setSubjects(await getFacultySubjects());
  }, [userId]);

  const handleRefresh = async () => {
    setRefreshing(true);
    try {
      const remote = await fetchFacultyProfile(settings.backendBaseUrl);
      if (remote.success) {
        await saveFacultyProfile({
          userId: userId ?? undefined,
          name: remote.name,
          email: remote.email,
          department: remote.department,
          designation: remote.designation,
        });
        await saveFacultySections(remote.sections);
        await saveFacultySubjects(remote.subjects);
        await load();
      } else {
        Alert.alert('Sync Error', 'Could not refresh profile data');
      }
    } catch (e: any) {
      Alert.alert('Sync Error', e?.message ?? String(e));
    } finally {
      setRefreshing(false);
    }
  };

  useEffect(() => { load(); }, [load]);

  if (!profile) {
    return (
      <View style={styles.container}>
        <Text style={typography.body}>No profile data yet. Tap below to fetch profile.</Text>
        <View style={{ marginTop: spacing.md }}>
          <PrimaryButton label="Fetch Profile" onPress={handleRefresh} loading={refreshing} />
        </View>
      </View>
    );
  }

  return (
    <ScrollView
      style={styles.container}
      contentContainerStyle={{ padding: spacing.lg }}
      refreshControl={<RefreshControl refreshing={refreshing} onRefresh={handleRefresh} tintColor={colors.accent} />}
    >
      <Text style={typography.title}>Faculty Profile</Text>

      <View style={styles.section}>
        <Text style={typography.subtitle}>{profile.name}</Text>
        <Text style={typography.body}>{profile.email}</Text>
        <Text style={typography.body}>{profile.department ?? 'Department not set'}</Text>
      </View>

      <Text style={[typography.subtitle, styles.heading]}>Assigned Sections ({sections.length})</Text>
      {sections.length === 0 ? (
        <Text style={typography.body}>No sections assigned.</Text>
      ) : sections.map((s) => (
        <Text key={s.section_id} style={typography.body}>• {s.section_label} — Semester {s.sem_number}</Text>
      ))}

      <Text style={[typography.subtitle, styles.heading]}>Assigned Subjects ({subjects.length})</Text>
      {subjects.length === 0 ? (
        <Text style={typography.body}>No subjects assigned.</Text>
      ) : subjects.map((s) => (
        <Text key={s.subject_id} style={typography.body}>• {s.name} ({s.code})</Text>
      ))}

      <Text style={[typography.subtitle, styles.heading]}>Last Synchronized</Text>
      <Text style={typography.body}>
        {profile.last_sync ? new Date(profile.last_sync).toLocaleString() : 'Just now'}
      </Text>

      <View style={{ marginTop: spacing.xl }}>
        <PrimaryButton label="Refresh Profile Data" onPress={handleRefresh} loading={refreshing} />
      </View>
    </ScrollView>
  );
};

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.background },
  section: { marginBottom: spacing.lg },
  heading: { marginTop: spacing.lg, marginBottom: spacing.xs },
});