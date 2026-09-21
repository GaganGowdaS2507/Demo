/**
 * Minimal shared theme so every screen looks consistent without pulling in a
 * heavyweight UI library — keeps the app focused on benchmarking, not styling.
 */
export const colors = {
  background: '#0B0F14',
  surface: '#141A22',
  surfaceAlt: '#1C2430',
  border: '#2A3542',
  textPrimary: '#EAF0F6',
  textSecondary: '#8FA1B3',
  accent: '#4C9AFF',
  success: '#4CD97B',
  warning: '#F5B94C',
  danger: '#F55C5C',
};

export const spacing = {
  xs: 4,
  sm: 8,
  md: 16,
  lg: 24,
  xl: 32,
};

export const typography = {
  title: { fontSize: 22, fontWeight: '700' as const, color: colors.textPrimary },
  subtitle: { fontSize: 16, fontWeight: '600' as const, color: colors.textPrimary },
  body: { fontSize: 14, fontWeight: '400' as const, color: colors.textSecondary },
  mono: { fontFamily: 'monospace', fontSize: 12, color: colors.textSecondary },
};
