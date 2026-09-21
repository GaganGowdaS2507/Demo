import React, { useEffect, useState, useCallback } from 'react';
import { View, Text, FlatList, StyleSheet, Alert, RefreshControl } from 'react-native';
import { useFocusEffect } from '@react-navigation/native';
import NetInfo from '@react-native-community/netinfo';
import { colors, spacing, typography } from '../../theme/theme';
import { PrimaryButton } from '../../components/PrimaryButton';
import { useRecognitionEngine } from '../../hooks/useRecognitionEngine';
import { useAuth } from '../../app/auth/AuthContext';
import { getPendingAttendance, getGallerySyncedAt } from '../../app/db/AttendanceDatabase';
import { pushPendingAttendance } from '../../app/services/AttendanceSyncService';

export const PendingAttendanceScreen: React.FC = () => {
  const { settings } = useRecognitionEngine();
  const { userId } = useAuth();
  const [pending, setPending] = useState<any[]>([]);
  const [syncing, setSyncing] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [online, setOnline] = useState<boolean | null>(null);
  const [lastGallerySync, setLastGallerySync] = useState<number | null>(null);

  const refresh = useCallback(async () => {
    if (!userId) { setPending([]); return; }
    setRefreshing(true);
    setPending(await getPendingAttendance(userId));
    setLastGallerySync(await getGallerySyncedAt());
    setRefreshing(false);
  }, [userId]);

  useFocusEffect(
    useCallback(() => {
      refresh();
    }, [refresh])
  );

  useEffect(() => {
    const unsub = NetInfo.addEventListener((s) => setOnline(!!s.isConnected && !!s.isInternetReachable));
    return unsub;
  }, []);

  const syncNow = async () => {
    if (!userId) return;
    setSyncing(true);
    try {
      const res = await pushPendingAttendance(settings.backendBaseUrl, userId);
      await refresh();
      if (res.skipped > 0 && res.errors && res.errors.length > 0) {
        Alert.alert('Sync Result', `${res.inserted} synced, ${res.skipped} skipped.\n\nDetails:\n${res.errors.slice(0, 3).join('\n')}`);
      } else {
        Alert.alert('Sync complete', `${res.inserted} synced, ${res.skipped} skipped.`);
      }
    } catch (e: any) {
      Alert.alert('Sync failed', e?.message ?? String(e));
    } finally {
      setSyncing(false);
    }
  };

  return (
    <View style={styles.container}>
      <Text style={typography.title}>Pending Attendance</Text>
      <Text style={typography.body}>Network: {online === null ? 'checking…' : online ? 'Online' : 'Offline'}</Text>
      <Text style={typography.body}>{pending.length} records waiting to sync</Text>
      <Text style={typography.body}>
        Student data last synced: {lastGallerySync ? new Date(lastGallerySync).toLocaleString() : 'Never'}
      </Text>

      <PrimaryButton label="Sync / Upload Attendance" onPress={syncNow} loading={syncing} disabled={pending.length === 0} />

      <FlatList
        style={{ marginTop: spacing.md }}
        data={pending}
        keyExtractor={(r) => `${r.session_id}-${r.student_id}`}
        refreshControl={
          <RefreshControl refreshing={refreshing} onRefresh={refresh} colors={[colors.accent]} />
        }
        renderItem={({ item }) => (
          <View style={styles.row}>
            <View style={[
              styles.statusBadge,
              { backgroundColor: item.status === 'present' ? colors.success : item.status === 'absent' ? colors.danger : colors.textSecondary },
            ]}>
              <Text style={styles.statusBadgeText}>
                {item.status === 'present' ? 'P' : 'A'}
              </Text>
            </View>
            <Text style={[typography.body, { flex: 1 }]}>
              {item.student_name} ({item.usn}) — session {item.session_id} —{' '}
              {new Date(item.captured_at).toLocaleTimeString()}
            </Text>
          </View>
        )}
        ListEmptyComponent={<Text style={typography.body}>Nothing pending — everything is synced.</Text>}
      />
    </View>
  );
};

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.background, padding: spacing.lg },
  row: {
    flexDirection: 'row', alignItems: 'center', gap: spacing.sm,
    paddingVertical: spacing.xs, borderBottomWidth: 1, borderBottomColor: colors.border,
  },
  statusBadge: {
    width: 22, height: 22, borderRadius: 11,
    alignItems: 'center', justifyContent: 'center',
  },
  statusBadgeText: {
    color: '#fff', fontWeight: '700', fontSize: 12,
  },
});