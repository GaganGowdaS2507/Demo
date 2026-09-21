import { fetchMobileEmbeddings, fetchFingerprintTemplates } from '../api/BackendClient';
import { upsertGallery, upsertFingerprintTemplates, getGallerySyncedAt } from '../db/AttendanceDatabase';
import { DEFAULT_MODEL_ID } from '../../core/config/ModelCatalog';

export async function syncStudentGallery(backendBaseUrl: string, sectionId?: number) {
  const data = await fetchMobileEmbeddings(backendBaseUrl, sectionId);
  if (!data.success) throw new Error('Failed to fetch embeddings from backend');

  await upsertGallery(
    data.students.map((s) => ({
      student_id: s.student_id, usn: s.usn, name: s.name,
      section_id: s.section_id, embedding: s.embedding,
    })),
    DEFAULT_MODEL_ID,
  );

  // Also sync fingerprint template mappings
  try {
    const fpData = await fetchFingerprintTemplates(backendBaseUrl, sectionId);
    if (fpData.success && fpData.fingerprints) {
      await upsertFingerprintTemplates(fpData.fingerprints);
    }
  } catch (e) {
    console.warn('[StudentGallerySync] fingerprint templates sync fallback:', e);
  }

  return { count: data.count };
}

export async function getLastSyncTime() {
  return getGallerySyncedAt();
}