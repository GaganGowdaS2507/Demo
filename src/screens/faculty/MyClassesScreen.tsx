import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { View, Text, FlatList, StyleSheet, Pressable } from 'react-native';
import { useNavigation, useFocusEffect } from '@react-navigation/native';
import { colors, spacing, typography } from '../../theme/theme';
import { PrimaryButton } from '../../components/PrimaryButton';
import { useRecognitionEngine } from '../../hooks/useRecognitionEngine';
import { getFacultySections, getFacultySubjects, getTimetableSessions, saveTimetableSessions } from '../../app/db/AttendanceDatabase';
import { fetchFacultyContext } from '../../app/api/BackendClient';

function todayStr() {
  const d = new Date();
  const year = d.getFullYear();
  const month = String(d.getMonth() + 1).padStart(2, '0');
  const day = String(d.getDate()).padStart(2, '0');
  return `${year}-${month}-${day}`;
}

export const MyClassesScreen: React.FC = () => {
  const navigation = useNavigation<any>();
  const { settings } = useRecognitionEngine();
  const [sections, setSections] = useState<any[]>([]);
  const [subjects, setSubjects] = useState<any[]>([]);
  const [sessions, setSessions] = useState<any[]>([]);
  const [refreshing, setRefreshing] = useState(false);

  const loadLocal = useCallback(async () => {
    setSections(await getFacultySections());
    setSubjects(await getFacultySubjects());
    setSessions(await getTimetableSessions());
  }, []);

  const refreshFromServer = useCallback(async () => {
    setRefreshing(true);
    try {
      const ctx = await fetchFacultyContext(settings.backendBaseUrl);
      await saveTimetableSessions(ctx.sessions);
      await loadLocal();
    } catch {
      // offline — keep showing cached data
    } finally {
      setRefreshing(false);
    }
  }, [settings.backendBaseUrl, loadLocal]);

  useFocusEffect(
    useCallback(() => {
      refreshFromServer();
    }, [refreshFromServer])
  );

  useEffect(() => { loadLocal(); }, [loadLocal]);

  const rows = useMemo(() => {
    const today = todayStr();
    const sectionMap = new Map<number, any>();

    for (const sec of sections) {
      sectionMap.set(sec.section_id, sec);
    }

    const todaySessions = sessions.filter((s) => s.session_date === today);
    for (const s of todaySessions) {
      if (!sectionMap.has(s.section_id)) {
        sectionMap.set(s.section_id, {
          section_id: s.section_id,
          section_label: s.section_label ?? `Section ${s.section_id}`,
          sem_number: '—',
          is_proxy: true,
        });
      }
    }

    return Array.from(sectionMap.values()).map((sec) => {
      const secTodaySessions = todaySessions.filter((s) => s.section_id === sec.section_id);
      const subjectName = secTodaySessions[0]?.subject_name
        ?? subjects.find((sub) => true)?.name
        ?? '—';
      return {
        section: sec,
        todaySessions: secTodaySessions,
        subjectName,
      };
    });
  }, [sections, sessions, subjects]);

  const openAttendance = (session: any, sectionLabel: string) => {
    navigation.navigate('Attendance', { sessionId: session.session_id, sectionId: session.section_id, sectionLabel });
  };

  return (
    <View style={styles.container}>
      <Text style={typography.title}>My Classes</Text>
      <FlatList
        data={rows}
        keyExtractor={(item) => String(item.section.section_id)}
        refreshing={refreshing}
        onRefresh={refreshFromServer}
        renderItem={({ item }) => {
          const hasSessionToday = item.todaySessions.length > 0;
          return (
            <View style={styles.card}>
              <Text style={typography.subtitle}>
                {item.section.section_label} {item.section.sem_number !== '—' ? `· Sem ${item.section.sem_number}` : ''}
                {item.section.is_proxy ? ' (Shared Class)' : ''}
              </Text>
              <Text style={typography.body}>{item.subjectName}</Text>
              <Text style={typography.body}>
                {hasSessionToday ? `${item.todaySessions.length} session(s) today` : 'No Session Today'}
              </Text>
              {hasSessionToday ? (
                item.todaySessions.map((s: any) => (
                  <PrimaryButton
                    key={s.session_id}
                    label={`Take Attendance · ${s.subject_name || item.subjectName} (${s.start_time}–${s.end_time})`}
                    onPress={() => openAttendance(s, item.section.section_label)}
                  />
                ))
              ) : (
                <PrimaryButton label="No Session Today" onPress={() => {}} disabled />
              )}
            </View>
          );
        }}
        ListEmptyComponent={<Text style={typography.body}>No sections assigned yet. Pull down to refresh.</Text>}
      />
    </View>
  );
};

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.background, padding: spacing.lg },
  card: { backgroundColor: colors.surface, borderRadius: 12, padding: spacing.md, marginBottom: spacing.sm },
});