import React, { useState } from 'react';
import { View, Text, TextInput, StyleSheet, Alert, Pressable } from 'react-native';
import { colors, spacing, typography } from '../../theme/theme';
import { PrimaryButton } from '../../components/PrimaryButton';
import { useAuth } from '../../app/auth/AuthContext';
import { useRecognitionEngine } from '../../hooks/useRecognitionEngine';

export const LoginScreen: React.FC = () => {
  const { login } = useAuth();
  const { settings, updateSettings } = useRecognitionEngine();
  const [serverUrl, setServerUrl] = useState(settings.backendBaseUrl);
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [loading, setLoading] = useState(false);

  const submit = async () => {
    setLoading(true);
    try {
      let normalizedUrl = serverUrl.trim().replace(/\/+$/, '');
      if (!normalizedUrl.startsWith('http://') && !normalizedUrl.startsWith('https://')) {
        normalizedUrl = `http://${normalizedUrl}`;
      }
      normalizedUrl = normalizedUrl
        .replace(/\/api\/mobile\/?$/i, '')
        .replace(/\/api\/?$/i, '')
        .replace(/\/login\/?$/i, '')
        .replace(/\/+$/, '');

      if (normalizedUrl !== settings.backendBaseUrl) {
        await updateSettings({ backendBaseUrl: normalizedUrl });
      }
      const res = await login(normalizedUrl, email.trim(), password);
      if (res.isOffline) {
        Alert.alert(
          'Offline Mode Login',
          res.message,
        );
      } else {
        Alert.alert(
          'Login Successful',
          res.message,
        );
      }
    } catch (e: any) {
      const errStr = e?.message ?? String(e);
      Alert.alert('Login Failed', errStr);
    } finally {
      setLoading(false);
    }
  };

  return (
    <View style={styles.container}>
      <Text style={typography.title}>Attendance App</Text>
      <Text style={[typography.subtitle, { marginTop: spacing.sm }]}>Server URL</Text>
      <TextInput
        style={styles.input}
        placeholder="e.g. http://127.0.0.1:5000"
        placeholderTextColor={colors.textSecondary}
        autoCapitalize="none"
        value={serverUrl}
        onChangeText={setServerUrl}
      />
      <View style={styles.urlPresetRow}>
        <Pressable
          style={styles.presetChip}
          onPress={() => setServerUrl('http://127.0.0.1:5000')}>
          <Text style={styles.presetText}>🔌 USB (127.0.0.1:5000)</Text>
        </Pressable>
        <Pressable
          style={styles.presetChip}
          onPress={() => setServerUrl('http://10.42.16.72:5000')}>
          <Text style={styles.presetText}>📶 Wi-Fi (10.42.16.72:5000)</Text>
        </Pressable>
      </View>

      <Text style={[typography.subtitle, { marginTop: spacing.xs }]}>Credentials</Text>
      <TextInput
        style={styles.input}
        placeholder="Email"
        placeholderTextColor={colors.textSecondary}
        autoCapitalize="none"
        keyboardType="email-address"
        value={email}
        onChangeText={setEmail}
      />
      <TextInput
        style={styles.input}
        placeholder="Password"
        placeholderTextColor={colors.textSecondary}
        secureTextEntry
        value={password}
        onChangeText={setPassword}
      />
      <PrimaryButton label="Log In" onPress={submit} loading={loading} />
    </View>
  );
};

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.background, justifyContent: 'center', padding: spacing.lg },
  input: {
    backgroundColor: colors.surface, color: colors.textPrimary, borderRadius: 10,
    padding: spacing.md, marginBottom: spacing.xs, borderWidth: 1, borderColor: colors.border,
  },
  urlPresetRow: { flexDirection: 'row', justifyContent: 'space-between', marginBottom: spacing.md },
  presetChip: { backgroundColor: colors.surface, paddingHorizontal: 10, paddingVertical: 6, borderRadius: 6, borderWidth: 1, borderColor: colors.border },
  presetText: { color: colors.textSecondary, fontSize: 11, fontWeight: '600' },
});