// src/app/services/FacultyContextSync.ts
import { fetchFacultyContext, fetchSessionRoster } from '../api/BackendClient';
import { saveRoster, getRoster } from '../db/AttendanceDatabase';
import { syncStudentGallery } from './StudentGallerySync';

export async function loadFacultyTimetable(baseUrl: string) {
  const data = await fetchFacultyContext(baseUrl);
  if (data.role !== 'faculty') throw new Error('This account is not a faculty account');
  return { facultyId: data.faculty_id, sessions: data.sessions };
}

export async function loadSessionRoster(baseUrl: string, sessionId: number, sectionId: number) {
  let roster: any[] = [];
  try {
    const rosterData = await fetchSessionRoster(baseUrl, sessionId);
    roster = rosterData.roster;
    await saveRoster(sessionId, roster);
  } catch {
    roster = await getRoster(sessionId);
  }

  await syncStudentGallery(baseUrl, sectionId).catch(() => {});
  return { sessionId, roster };
}
