import React, { useEffect, useState } from 'react';
import { View, Text, StyleSheet, ActivityIndicator, Alert } from 'react-native';
import { colors, spacing, typography } from '../theme/theme';
import { PrimaryButton } from '../components/PrimaryButton';
import { runInitialFacultySetup, SetupProgress } from '../app/services/InitialSetupService';

interface Props {
  baseUrl: string;
  onComplete: () => void;
  onCancelLogin: () => void; // fall back to login screen if setup fails
}

export const SetupScreen: React.FC<Props> = ({ baseUrl, onComplete, onCancelLogin }) => {
  const [progress, setProgress] = useState<SetupProgress>({ step: 'profile', message: 'Starting setup…', percent: 0 });
  const [failed, setFailed] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        await runInitialFacultySetup(baseUrl, (p) => { if (!cancelled) setProgress(p); });
        if (!cancelled) onComplete();
      } catch (e: any) {
        if (!cancelled) setFailed(e?.message ?? 'Setup failed. Check your connection and try again.');
      }
    })();
    return () => { cancelled = true; };
  }, [baseUrl]);

  return (
    <View style={styles.container}>
      <Text style={typography.title}>Setting Up Your Account</Text>
      <Text style={[typography.body, { marginBottom: spacing.lg }]}>
        This only happens once. We're downloading your profile, classes, and
        student data so attendance works even without internet.
      </Text>

      {!failed && (
        <>
          <ActivityIndicator size="large" color={colors.accent} />
          <Text style={[typography.body, styles.status]}>{progress.message}</Text>
          <View style={styles.barTrack}>
            <View style={[styles.barFill, { width: `${progress.percent}%` }]} />
          </View>
        </>
      )}

      {failed && (
        <>
          <Text style={[typography.body, { color: colors.danger, marginBottom: spacing.md }]}>{failed}</Text>
          <PrimaryButton label="Back to Login" onPress={onCancelLogin} variant="secondary" />
        </>
      )}
    </View>
  );
};

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.background, justifyContent: 'center', padding: spacing.lg },
  status: { marginTop: spacing.md, textAlign: 'center' },
  barTrack: { height: 8, borderRadius: 4, backgroundColor: colors.surface, marginTop: spacing.lg, overflow: 'hidden' },
  barFill: { height: 8, backgroundColor: colors.accent },
});