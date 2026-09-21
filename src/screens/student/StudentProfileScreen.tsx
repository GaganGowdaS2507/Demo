// src/screens/student/StudentProfileScreen.tsx
import React from 'react';
import { View, Text, StyleSheet } from 'react-native';
import { colors, spacing, typography } from '../../theme/theme';
import { PrimaryButton } from '../../components/PrimaryButton';
import { useAuth } from '../../app/auth/AuthContext';

export const StudentProfileScreen: React.FC = () => {
  const { name, logout } = useAuth();
  return (
    <View style={styles.container}>
      <Text style={typography.title}>Profile</Text>
      <Text style={typography.body}>{name}</Text>
      <PrimaryButton label="Log Out" onPress={logout} variant="danger" />
    </View>
  );
};

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.background, padding: spacing.lg },
});