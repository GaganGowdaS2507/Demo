import { fetchFacultyProfile, fetchFacultyContext, fetchMobileEmbeddings } from '../api/BackendClient';
import {
  reconcileGallery,
  saveFacultyProfile, saveFacultySections, saveFacultySubjects,
  saveTimetableSessions, upsertGallery, wipeAllLocalData,
} from '../db/AttendanceDatabase';
import { DEFAULT_MODEL_ID } from '../../core/config/ModelCatalog';

export type SetupStep =
  | 'profile' | 'sections' | 'subjects' | 'timetable' | 'roster_students' | 'embeddings' | 'done';

export interface SetupProgress {
  step: SetupStep;
  message: string;
  percent: number;
}

/**
 * Runs once, right after a successful faculty login. Downloads everything
 * needed to work fully offline afterward, and reports progress via onProgress.
 */
export async function runInitialFacultySetup(
  baseUrl: string,
  onProgress: (p: SetupProgress) => void,
): Promise<void> {
  // Clear any existing local cache from previous user logins before importing fresh data
  await wipeAllLocalData();

  onProgress({ step: 'profile', message: 'Downloading faculty profile…', percent: 10 });
  const profile = await fetchFacultyProfile(baseUrl);
  if (!profile.success) throw new Error('Could not download faculty profile');
  await saveFacultyProfile({
    name: profile.name, email: profile.email,
    department: profile.department, designation: profile.designation,
  });

  onProgress({ step: 'sections', message: 'Downloading assigned sections…', percent: 25 });
  await saveFacultySections(profile.sections);

  onProgress({ step: 'subjects', message: 'Downloading assigned subjects…', percent: 35 });
  await saveFacultySubjects(profile.subjects);

  onProgress({ step: 'timetable', message: "Downloading today's and upcoming sessions…", percent: 50 });
  const ctx = await fetchFacultyContext(baseUrl);
  await saveTimetableSessions(ctx.sessions);

  onProgress({ step: 'embeddings', message: 'Downloading student face data for offline recognition…', percent: 70 });
  let total = 0;
  for (const sec of profile.sections) {
    try {
      const emb = await fetchMobileEmbeddings(baseUrl, sec.section_id);
      if (emb.success && emb.students.length) {
        await upsertGallery(
          emb.students.map((s) => ({
            student_id: s.student_id, usn: s.usn, name: s.name,
            section_id: sec.section_id, embedding: s.embedding,
          })),
          DEFAULT_MODEL_ID,
        );
        total += emb.students.length;
      }
    } catch (err) {
      console.log(`[InitialSetup] Section ${sec.section_id} embeddings unavailable:`, err);
    }
  }

  onProgress({ step: 'done', message: `Setup complete — ${total} students ready offline.`, percent: 100 });
}