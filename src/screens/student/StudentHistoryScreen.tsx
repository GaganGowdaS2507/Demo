// src/screens/student/StudentHistoryScreen.tsx
import React, { useEffect, useState } from 'react';
import { View, Text, FlatList, StyleSheet, ActivityIndicator } from 'react-native';
import axios from 'axios';
import { colors, spacing, typography } from '../../theme/theme';
import { useRecognitionEngine } from '../../hooks/useRecognitionEngine';
import { getSession } from '../../app/api/BackendClient';

export const StudentHistoryScreen: React.FC = () => {
  const { settings } = useRecognitionEngine();
  const [rows, setRows] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    (async () => {
      try {
        const { token } = await getSession();
        const res = await axios.get(`${settings.backendBaseUrl}/api/student/attendance/history`, {
          headers: { Authorization: `Bearer ${token}` },
        });
        setRows(res.data.records || []);
      } catch (e) {
        console.warn('[StudentHistory] fetch failed', e);
      } finally {
        setLoading(false);
      }
    })();
  }, [settings.backendBaseUrl]);

  if (loading) return <ActivityIndicator style={{ flex: 1 }} color={colors.accent} />;

  return (
    <View style={styles.container}>
      <Text style={typography.title}>Attendance History</Text>
      <FlatList
        data={rows}
        keyExtractor={(r, i) => String(r.id ?? i)}
        renderItem={({ item }) => (
          <View style={styles.row}>
            <Text style={typography.body}>{item.subject_name} — {item.status} — {item.marked_at}</Text>
          </View>
        )}
      />
    </View>
  );
};

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.background, padding: spacing.lg },
  row: { paddingVertical: spacing.xs, borderBottomWidth: 1, borderBottomColor: colors.border },
});