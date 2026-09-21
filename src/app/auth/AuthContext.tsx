import React, { createContext, useContext, useEffect, useState, useCallback } from 'react';
import AsyncStorage from '@react-native-async-storage/async-storage';
import * as Backend from '../api/BackendClient';
import { getFacultyProfile } from '../db/AttendanceDatabase';
import { cacheCredentials, verifyOffline } from './OfflineUserCache';

const SETUP_DONE_KEY = '@attendance_app/setup_done_for_user';

export interface LoginResult {
  isOffline: boolean;
  message: string;
}

interface AuthState {
  isLoading: boolean;
  isLoggedIn: boolean;
  isOfflineMode: boolean;
  role: 'faculty' | null;
  name: string | null;
  facultyId: number | null;
  userId: number | null;
  needsSetup: boolean;
  login: (baseUrl: string, email: string, password: string) => Promise<LoginResult>;
  completeSetup: () => Promise<void>;
  logout: () => Promise<void>;
}

const AuthContext = createContext<AuthState | null>(null);

export const AuthProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [isLoading, setIsLoading] = useState(true);
  const [isOfflineMode, setIsOfflineMode] = useState(false);
  const [role, setRole] = useState<'faculty' | null>(null);
  const [name, setName] = useState<string | null>(null);
  const [facultyId, setFacultyId] = useState<number | null>(null);
  const [userId, setUserId] = useState<number | null>(null);
  const [needsSetup, setNeedsSetup] = useState(false);

  useEffect(() => {
    (async () => {
      const s = await Backend.getSession();
      if (s.token && s.role === 'faculty') {
        setRole('faculty');
        setName(s.name);
        setFacultyId(s.faculty_id ?? null);
        setUserId(s.user_id ?? null);

        // A local faculty_profile row means setup already ran for this login.
        const cachedProfile = await getFacultyProfile();
        const setupMarker = await AsyncStorage.getItem(SETUP_DONE_KEY);
        setNeedsSetup(!(cachedProfile && setupMarker === s.faculty_id?.toString()));
      }
      setIsLoading(false);
    })();
  }, []);

  const login = useCallback(async (baseUrl: string, email: string, password: string): Promise<LoginResult> => {
    try {
      // 1. Try Online Login via Backend server
      const res = await Backend.login(baseUrl, email, password);
      if (!res.success) throw new Error(res.message || 'Login failed');
      if (res.role !== 'faculty') throw new Error('This app is for faculty accounts only.');

      // Cache credentials locally for future offline login
      await cacheCredentials(
        email,
        password,
        'faculty',
        res.name,
        res.faculty_id ?? null,
        res.user_id ?? null,
        res.token ?? null,
        res.department_id ?? null,
      );

      setRole('faculty');
      setName(res.name);
      setFacultyId(res.faculty_id ?? null);
      setUserId(res.user_id ?? null);
      setIsOfflineMode(false);

      // Check if setup/import has already been performed for this user
      const cachedProfile = await getFacultyProfile();
      const setupMarker = await AsyncStorage.getItem(SETUP_DONE_KEY);
      const isAlreadySetup = !!(cachedProfile && setupMarker === res.faculty_id?.toString());
      setNeedsSetup(!isAlreadySetup);

      return {
        isOffline: false,
        message: 'Connected to server. Updated latest data.',
      };
    } catch (e: any) {
      const errStr = e?.message ?? String(e);
      const isNetworkError =
        errStr.toLowerCase().includes('network error') ||
        errStr.toLowerCase().includes('failed to connect') ||
        errStr.toLowerCase().includes('econnrefused') ||
        errStr.toLowerCase().includes('timeout') ||
        errStr.includes('404');

      if (!isNetworkError) {
        // Credential rejection or bad status error from live server
        throw e;
      }

      // 2. Network / Server Unreachable -> Fallback to Offline Authentication
      const cachedUser = await verifyOffline(email, password);
      if (!cachedUser) {
        throw new Error(
          'Server is not reachable and no matching offline credentials were found on this device.',
        );
      }

      // Check if local database setup/data exists for this faculty user
      const cachedProfile = await getFacultyProfile();
      if (!cachedProfile) {
        throw new Error(
          'First-time login on this device requires an active server connection to import your profile and face data.',
        );
      }

      // Restore session from offline cache
      await Backend.saveSession({
        token: cachedUser.token || 'offline_cached_token',
        role: cachedUser.role,
        name: cachedUser.name,
        faculty_id: cachedUser.facultyId,
        user_id: cachedUser.userId,
      });

      setRole('faculty');
      setName(cachedUser.name);
      setFacultyId(cachedUser.facultyId);
      setUserId(cachedUser.userId);
      setIsOfflineMode(true);
      setNeedsSetup(false);

      return {
        isOffline: true,
        message:
          'Server is not reachable. Logged in using offline cached credentials with previously imported data.',
      };
    }
  }, []);

  const completeSetup = useCallback(async () => {
    if (facultyId != null) {
      await AsyncStorage.setItem(SETUP_DONE_KEY, String(facultyId));
    }
    setNeedsSetup(false);
  }, [facultyId]);

  const logout = useCallback(async () => {
    await Backend.logout();
    setRole(null);
    setName(null);
    setFacultyId(null);
    setUserId(null);
    setNeedsSetup(false);
    setIsOfflineMode(false);
  }, []);

  return (
    <AuthContext.Provider value={{
      isLoading, isLoggedIn: !!role, isOfflineMode, role, name, facultyId, userId, needsSetup,
      login, completeSetup, logout,
    }}>
      {children}
    </AuthContext.Provider>
  );
};

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth must be used within AuthProvider');
  return ctx;
}