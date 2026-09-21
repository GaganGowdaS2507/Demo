import AsyncStorage from '@react-native-async-storage/async-storage';
import { sha256 } from 'react-native-sha256';

const OFFLINE_USERS_KEY = '@attendance_app/offline_users';

export interface OfflineUserEntry {
  email: string;
  passwordHash: string;
  role: 'faculty';
  name: string;
  facultyId: number | null;
  userId: number | null;
  departmentId?: number | null;
  token?: string | null;
  lastLoginAt: number;
}

/**
 * Normalizes email for case-insensitive offline authentication lookup.
 */
function normalizeEmail(email: string): string {
  return email.trim().toLowerCase();
}

/**
 * Caches a user's credentials and session details locally upon successful online login.
 */
export async function cacheCredentials(
  email: string,
  password: string,
  role: 'faculty',
  name: string,
  facultyId: number | null,
  userId: number | null,
  token?: string | null,
  departmentId?: number | null,
): Promise<void> {
  try {
    const raw = await AsyncStorage.getItem(OFFLINE_USERS_KEY);
    const users: OfflineUserEntry[] = raw ? JSON.parse(raw) : [];
    const normEmail = normalizeEmail(email);
    const passwordHash = await sha256(password);

    const entry: OfflineUserEntry = {
      email: normEmail,
      passwordHash,
      role,
      name,
      facultyId,
      userId,
      token: token ?? null,
      departmentId: departmentId ?? null,
      lastLoginAt: Date.now(),
    };

    const idx = users.findIndex((u) => normalizeEmail(u.email) === normEmail);
    if (idx >= 0) {
      users[idx] = entry;
    } else {
      users.push(entry);
    }

    await AsyncStorage.setItem(OFFLINE_USERS_KEY, JSON.stringify(users));
  } catch (err) {
    console.warn('[OfflineUserCache] Failed to cache user credentials:', err);
  }
}

/**
 * Verifies email and password against stored offline user credentials.
 */
export async function verifyOffline(
  email: string,
  password: string,
): Promise<OfflineUserEntry | null> {
  try {
    const raw = await AsyncStorage.getItem(OFFLINE_USERS_KEY);
    if (!raw) return null;

    const users: OfflineUserEntry[] = JSON.parse(raw);
    const normEmail = normalizeEmail(email);
    const passwordHash = await sha256(password);

    const matched = users.find(
      (u) => normalizeEmail(u.email) === normEmail && u.passwordHash === passwordHash,
    );

    return matched || null;
  } catch (err) {
    console.warn('[OfflineUserCache] Failed to verify offline credentials:', err);
    return null;
  }
}

/**
 * Retrieves cached user entry by email without verifying password.
 */
export async function getCachedUserByEmail(email: string): Promise<OfflineUserEntry | null> {
  try {
    const raw = await AsyncStorage.getItem(OFFLINE_USERS_KEY);
    if (!raw) return null;
    const users: OfflineUserEntry[] = JSON.parse(raw);
    const normEmail = normalizeEmail(email);
    return users.find((u) => normalizeEmail(u.email) === normEmail) || null;
  } catch {
    return null;
  }
}