
import axios from 'axios';
import AsyncStorage from '@react-native-async-storage/async-storage';

const TOKEN_KEY = '@attendance_app/token';
const ROLE_KEY = '@attendance_app/role';
const NAME_KEY = '@attendance_app/name';
const FACULTY_ID_KEY = '@attendance_app/faculty_id';
const USER_ID_KEY = '@attendance_app/user_id';

function client(baseURL: string) {
  const instance = axios.create({ baseURL, timeout: 20000 });
  instance.interceptors.request.use(async (cfg) => {
    const token = await AsyncStorage.getItem(TOKEN_KEY);
    if (token && token.length > 0) {
      cfg.headers.Authorization = `Bearer ${token}`;
    }
    return cfg;
  });
  instance.interceptors.response.use(
    (res) => res,
    (err) => {
      const serverMsg = err.response?.data?.message;
      if (serverMsg) {
        return Promise.reject(new Error(serverMsg));
      }
      return Promise.reject(err);
    },
  );
  return instance;
}

export async function saveSession(data: {
  token?: string | null;
  role: string;
  name: string;
  faculty_id?: number | null;
  user_id?: number | null;
}) {
  if (data.token) await AsyncStorage.setItem(TOKEN_KEY, data.token);
  await AsyncStorage.setItem(ROLE_KEY, data.role);
  await AsyncStorage.setItem(NAME_KEY, data.name);
  if (data.faculty_id != null) {
    await AsyncStorage.setItem(FACULTY_ID_KEY, String(data.faculty_id));
  } else {
    await AsyncStorage.removeItem(FACULTY_ID_KEY);
  }
  if (data.user_id != null) {
    await AsyncStorage.setItem(USER_ID_KEY, String(data.user_id));
  }
}

export async function login(baseUrl: string, email: string, password: string) {
  const res = await client(baseUrl).post('/api/mobile/login', { email, password });

  if (res.data.success) {
    await saveSession({
      token: res.data.token,
      role: res.data.role,
      name: res.data.name,
      faculty_id: res.data.faculty_id,
      user_id: res.data.user_id,
    });
  }
  return res.data;
}

export async function logout() {
  await AsyncStorage.multiRemove([TOKEN_KEY, ROLE_KEY, NAME_KEY, FACULTY_ID_KEY, USER_ID_KEY]);
}

export async function getSession() {
  const [token, role, name, facultyId, userId] = await Promise.all([
    AsyncStorage.getItem(TOKEN_KEY),
    AsyncStorage.getItem(ROLE_KEY),
    AsyncStorage.getItem(NAME_KEY),
    AsyncStorage.getItem(FACULTY_ID_KEY),
    AsyncStorage.getItem(USER_ID_KEY),
  ]);
  return {
    token, role, name,
    faculty_id: facultyId != null ? Number(facultyId) : null,
    user_id: userId != null ? Number(userId) : null,
  };
}
export interface FacultyProfileResponse {
  success: boolean;
  name: string;
  email: string;
  department: string | null;
  designation: string | null;
  sections: { section_id: number; section_label: string; sem_number: number }[];
  subjects: { subject_id: number; name: string; code: string }[];
}

export async function fetchFacultyProfile(baseUrl: string) {
  const res = await client(baseUrl).get('/api/mobile/profile');
  return res.data as FacultyProfileResponse;
}

export interface MobileEmbeddingRow {
  student_id: number; usn: string; name: string; section_id: number;
  embedding: number[]; model_version: string;
}

export async function fetchMobileEmbeddings(baseUrl: string, sectionId?: number) {
  const params = sectionId != null ? { section_id: sectionId } : undefined;
  const res = await client(baseUrl).get('/api/mobile/embeddings', { params });
  return res.data as { success: boolean; count: number; students: MobileEmbeddingRow[] };
}

export interface MobileFingerprintRow {
  template_id: number;
  student_id: number;
  usn: string;
  name: string;
  section_id?: number;
  camera_id?: number;
}

export async function fetchFingerprintTemplates(baseUrl: string, sectionId?: number) {
  const params = sectionId != null ? { section_id: sectionId } : undefined;
  const res = await client(baseUrl).get('/api/mobile/fingerprints', { params });
  return res.data as { success: boolean; count: number; fingerprints: MobileFingerprintRow[] };
}

export interface AttendanceSyncRecord {
  session_id: number;
  student_id: number;
  usn: string;
  match_score: number;
  captured_at: number;
  status?: 'present' | 'absent';
  method?: string;
  fingerprint_score?: number;
}

export async function syncAttendance(baseUrl: string, records: AttendanceSyncRecord[]) {
  const res = await client(baseUrl).post('/api/mobile/attendance/sync', { records });
  return res.data as { success: boolean; inserted: number; skipped: number; errors: string[] };
}

export interface MobileSessionEntry {
  session_id: number; session_date: string; start_time: string; end_time: string;
  section_id: number; section_label: string; subject_name: string; status: string;
}

export async function fetchFacultyContext(baseUrl: string) {
  const res = await client(baseUrl).get('/api/mobile/sync');
  return res.data as { role: 'faculty'; faculty_id: number; sessions: MobileSessionEntry[] };
}

export interface RosterStudent {
  student_id: number; usn: string; name: string; status: 'present' | 'absent';
}

export async function fetchSessionRoster(baseUrl: string, sessionId: number) {
  const res = await client(baseUrl).get(`/api/mobile/session/${sessionId}/roster`);
  return res.data as { roster: RosterStudent[] };
}

export interface ClassroomPhotoMatch {
  student_id: number;
  usn: string;
  full_name: string;
  score: number;
}

export interface ClassroomPhotoResult {
  success: boolean;
  matched: ClassroomPhotoMatch[];
  unrecognized_count: number;
  total_faces_detected: number;
  photos_processed: number;
}

export async function uploadClassroomPhotos(
  baseUrl: string,
  sessionId: number,
  photoUris: string[],
): Promise<ClassroomPhotoResult> {
  const formData = new FormData();
  photoUris.forEach((uri, idx) => {
    formData.append('photos', {
      uri,
      name: `classroom_photo_${idx + 1}.jpg`,
      type: 'image/jpeg',
    } as any);
  });

  const res = await client(baseUrl).post(
    `/api/mobile/sessions/${sessionId}/classroom_photos`,
    formData,
    { headers: { 'Content-Type': 'multipart/form-data' } },
  );
  return res.data as ClassroomPhotoResult;
}