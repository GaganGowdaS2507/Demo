// // src/screens/faculty/FacultyHomeScreen.tsx
// import React, { useCallback, useEffect, useMemo, useState } from 'react';
// import { View, Text, FlatList, StyleSheet, Pressable } from 'react-native';
// import { useNavigation } from '@react-navigation/native';
// import { colors, spacing, typography } from '../../theme/theme';
// import { PrimaryButton } from '../../components/PrimaryButton';
// import { useAuth } from '../../app/auth/AuthContext';
// import { loadFacultyTimetable, loadSessionRoster } from '../../app/services/FacultyContextSync';
// import { useRecognitionEngine } from '../../hooks/useRecognitionEngine';

// export const FacultyHomeScreen: React.FC = () => {
//   const navigation = useNavigation<any>();
//   const { facultyId } = useAuth();
//   const { settings } = useRecognitionEngine();
//   const baseUrl = settings.backendBaseUrl;
//   const [sessions, setSessions] = useState<any[]>([]);
//   const [loading, setLoading] = useState(true);
//   const [starting, setStarting] = useState<number | null>(null);
//   const [period, setPeriod] = useState<'today' | 'upcoming' | 'past'>('today');

//   const load = useCallback(async () => {
//     setLoading(true);
//     try {
//       const ctx = await loadFacultyTimetable(baseUrl);
//       setSessions(ctx.sessions);
//     } catch (e) { /* keep last-known sessions if offline */ }
//     setLoading(false);
//   }, [baseUrl]);

//   useEffect(() => { load(); }, [load]);

//   const filteredSessions = useMemo(() => {
//     const today = new Date().toISOString().slice(0, 10);
//     return sessions.filter((item) => {
//       if (period === 'today') return item.session_date === today;
//       if (period === 'upcoming') return item.session_date > today;
//       return item.session_date < today;
//     });
//   }, [period, sessions]);

//   const handleTakeAttendance = async (item: any) => {
//     setStarting(item.session_id);
//     try {
//       const { sessionId, roster } = await loadSessionRoster(baseUrl, item.session_id, item.section_id);
//       navigation.navigate('LiveAttendance', { sessionId, roster, sectionLabel: item.section_label });
//     } finally {
//       setStarting(null);
//     }
//   };

//   return (
//     <View style={styles.container}>
//       <Text style={typography.title}>Your Classes</Text>
//       <View style={styles.periodRow}>
//         {(['today', 'upcoming', 'past'] as const).map((p) => (
//           <Pressable
//             key={p}
//             style={[styles.periodButton, period === p && styles.periodButtonActive]}
//             onPress={() => setPeriod(p)}
//           >
//             <Text style={[typography.body, period === p && styles.periodTextActive]}>
//               {p === 'today' ? 'Today' : p === 'upcoming' ? 'Upcoming' : 'Past'}
//             </Text>
//           </Pressable>
//         ))}
//       </View>
//       <FlatList
//         data={filteredSessions}
//         keyExtractor={(item, i) => `${item.session_id}-${i}`}
//         refreshing={loading}
//         onRefresh={load}
//         renderItem={({ item }) => (
//           <View style={styles.card}>
//             <Text style={typography.subtitle}>{item.subject_name}</Text>
//             <Text style={typography.body}>{item.section_label} • {item.session_date} {item.start_time}–{item.end_time}</Text>
//             <PrimaryButton
//               label={starting === item.session_id ? 'Opening…' : 'Take Attendance'}
//               onPress={() => handleTakeAttendance(item)}
//               disabled={starting !== null}
//             />
//           </View>
//         )}
//         ListEmptyComponent={<Text style={typography.body}>No classes in this window.</Text>}
//       />
//     </View>
//   );
// };

// const styles = StyleSheet.create({
//   container: { flex: 1, backgroundColor: colors.background, padding: spacing.lg },
//   periodRow: { flexDirection: 'row', marginBottom: spacing.md, justifyContent: 'space-between' },
//   periodButton: {
//     flex: 1,
//     marginHorizontal: spacing.xs,
//     paddingVertical: spacing.sm,
//     paddingHorizontal: spacing.md,
//     borderRadius: 999,
//     backgroundColor: colors.surface,
//     alignItems: 'center',
//   },
//   periodButtonActive: { backgroundColor: colors.accent },
//   periodTextActive: { color: colors.background },
//   card: { backgroundColor: colors.surface, borderRadius: 12, padding: spacing.md, marginBottom: spacing.sm },
// });

import React from 'react';
import { View, Text, StyleSheet, Pressable, Alert } from 'react-native';
import { useNavigation } from '@react-navigation/native';
import { colors, spacing, typography } from '../../theme/theme';
import { useAuth } from '../../app/auth/AuthContext';
import { useRecognitionEngine } from '../../hooks/useRecognitionEngine';

const DashboardRow: React.FC<{ label: string; sub?: string; onPress: () => void; danger?: boolean }> = ({ label, sub, onPress, danger }) => (
  <Pressable style={styles.row} onPress={onPress}>
    <View>
      <Text style={[typography.subtitle, danger && { color: colors.danger }]}>{label}</Text>
      {sub ? <Text style={typography.body}>{sub}</Text> : null}
    </View>
    <Text style={{ color: colors.textSecondary }}>›</Text>
  </Pressable>
);

export const FacultyHomeScreen: React.FC = () => {
  const navigation = useNavigation<any>();
  const { name, isOfflineMode, logout } = useAuth();
  const { engine, isBootstrapping } = useRecognitionEngine();

  const modelLoaded = !isBootstrapping && !!engine && engine.isReady();

  const confirmLogout = () => {
    Alert.alert('Log out?', 'You will need to sign in again to take attendance.', [
      { text: 'Cancel', style: 'cancel' },
      { text: 'Log Out', style: 'destructive', onPress: logout },
    ]);
  };

  return (
    <View style={styles.container}>
      <Text style={typography.title}>Welcome, {name}</Text>

      {isOfflineMode ? (
        <View style={styles.offlineBanner}>
          <Text style={styles.offlineBannerText}>
            🟠 Offline Mode: Loaded previously imported data (Server Unreachable)
          </Text>
        </View>
      ) : null}

      <View style={styles.modelBadge}>
        <View style={[styles.dot, { backgroundColor: modelLoaded ? colors.success : colors.danger }]} />
        <Text style={typography.body}>
          Recognition model: {isBootstrapping ? 'Loading…' : modelLoaded ? 'Loaded' : 'Not Loaded'}
        </Text>
      </View>

      <View style={styles.list}>
        <DashboardRow label="Faculty Profile" sub="Your details, sections, subjects" onPress={() => navigation.navigate('Profile')} />
        <DashboardRow label="My Classes" sub="Today's and upcoming sessions" onPress={() => navigation.navigate('MyClasses')} />
        <DashboardRow label="Pending Attendance Uploads" sub="Sync attendance to the server" onPress={() => navigation.getParent()?.navigate('Pending')} />
        <DashboardRow label="Logout" onPress={confirmLogout} danger />
      </View>
    </View>
  );
};

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.background, padding: spacing.lg },
  offlineBanner: {
    backgroundColor: '#3d2c10',
    borderColor: '#d97706',
    borderWidth: 1,
    borderRadius: 8,
    padding: spacing.sm,
    marginTop: spacing.sm,
  },
  offlineBannerText: {
    color: '#fbbf24',
    fontSize: 12,
    fontWeight: '600',
  },
  modelBadge: { flexDirection: 'row', alignItems: 'center', marginVertical: spacing.md },
  dot: { width: 10, height: 10, borderRadius: 5, marginRight: spacing.sm },
  list: { marginTop: spacing.md },
  row: {
    flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center',
    backgroundColor: colors.surface, borderRadius: 12, padding: spacing.md, marginBottom: spacing.sm,
  },
});