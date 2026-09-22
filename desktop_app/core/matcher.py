"""
desktop_app/core/matcher.py
Classroom Photo Batch Matcher for Faculty Desktop App.
Matches face embeddings from 1 to 3 classroom photos against local section roster.
De-duplicates multiple detections of the same student and records face bounding boxes.
"""

import logging
import cv2
import numpy as np
from PIL import Image

logger = logging.getLogger(__name__)

CLASSROOM_MIN_FACE_SIZE = 30
CLASSROOM_DETECTION_THRESHOLD = 0.45
DEFAULT_RECOGNITION_THRESHOLD = 0.38


def load_image_bgr(image_path):
    """Loads an image as BGR numpy array with correct EXIF orientation."""
    try:
        pil_img = Image.open(image_path)
        # Handle EXIF transpose if rotated by camera
        try:
            from PIL import ImageOps
            pil_img = ImageOps.exif_transpose(pil_img)
        except Exception:
            pass

        pil_img = pil_img.convert("RGB")
        rgb = np.array(pil_img)
        bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
        return bgr
    except Exception as e:
        logger.error(f"Failed to load image '{image_path}': {e}")
        return None


def run_classroom_recognition(
    image_paths,
    engine,
    student_roster,
    threshold=DEFAULT_RECOGNITION_THRESHOLD,
    min_face_size=CLASSROOM_MIN_FACE_SIZE,
    detection_threshold=CLASSROOM_DETECTION_THRESHOLD,
    progress_callback=None
):
    """
    Executes edge recognition on classroom photos.

    Args:
        image_paths: list of image file paths (1 to 3 images)
        engine: DesktopRecognitionEngine instance (already initialized)
        student_roster: list of dicts:
            [{"student_id": int, "usn": str, "name": str, "embedding": list/np.ndarray, "model_version": str}]
        threshold: minimum cosine similarity score to consider recognized
        min_face_size: minimum width/height of face in pixels
        detection_threshold: minimum face detector score
        progress_callback: optional callable(percent, message)

    Returns:
        dict: {
            "matched": list of {
                "student_id": int,
                "usn": str,
                "name": str,
                "score": float,
                "source_photo_index": int,
                "bbox": (x1, y1, x2, y2),
                "is_present": True
            },
            "unrecognized_faces": list of {
                "source_photo_index": int,
                "bbox": (x1, y1, x2, y2),
                "det_score": float,
                "best_score": float
            },
            "total_faces_detected": int,
            "photos_processed": int,
            "annotated_images": list of cv2 BGR images with drawn bounding boxes
        }
    """
    if not engine or not engine.is_initialized:
        raise RuntimeError("Recognition engine is not initialized.")

    if not student_roster:
        logger.warning("Student roster is empty for this section.")

    # Build embedding candidate matrix and lookup maps
    candidate_ids = []
    candidate_embeddings = []
    student_info_map = {}

    for s in student_roster:
        sid = s["student_id"]
        student_info_map[sid] = s
        emb = s.get("embedding")
        if emb is not None:
            emb_arr = np.asarray(emb, dtype=np.float32)
            # Normalize
            norm = np.linalg.norm(emb_arr)
            if norm > 0:
                emb_arr = emb_arr / norm
            candidate_ids.append(sid)
            candidate_embeddings.append(emb_arr)

    candidate_matrix = None
    if candidate_embeddings:
        candidate_matrix = np.stack(candidate_embeddings).astype(np.float32)

    total_photos = len(image_paths)
    best_by_student = {}
    unrecognized_faces = []
    total_faces_detected = 0
    annotated_images = []

    for photo_idx, path in enumerate(image_paths):
        if progress_callback:
            pct = int((photo_idx / max(1, total_photos)) * 80)
            progress_callback(pct, f"Processing photo {photo_idx + 1} of {total_photos}...")

        bgr = load_image_bgr(path)
        if bgr is None:
            continue

        annotated_bgr = bgr.copy()
        faces = engine.detect_faces(bgr)
        total_faces_detected += len(faces)
        logger.info(f"Photo {photo_idx + 1}: detected {len(faces)} raw faces.")

        for face in faces:
            x1, y1, x2, y2 = engine.get_face_bbox(face)
            w, h = x2 - x1, y2 - y1
            det_score = engine.get_det_score(face)

            if min(w, h) < min_face_size or det_score < detection_threshold:
                continue

            # Extract embedding (ArcFace or fallback MBF)
            emb = engine.get_embedding(face)
            if emb is None:
                continue

            matched_sid, score = (None, 0.0)
            if candidate_matrix is not None and len(candidate_ids) > 0:
                matched_sid, score = engine.match_top1(emb, candidate_matrix, candidate_ids)

            # If score below threshold and MBF model is available, try MBF embedding
            if (matched_sid is None or score < threshold) and engine.mbf_session is not None:
                mbf_emb = engine.get_mbf_embedding(bgr, face)
                if mbf_emb is not None and candidate_matrix is not None:
                    m_sid, m_score = engine.match_top1(mbf_emb, candidate_matrix, candidate_ids)
                    if m_score > score:
                        matched_sid, score = m_sid, m_score

            is_match = matched_sid is not None and score >= threshold

            if is_match:
                info = student_info_map.get(matched_sid, {})
                prev = best_by_student.get(matched_sid)
                if prev is None or score > prev["score"]:
                    best_by_student[matched_sid] = {
                        "student_id": matched_sid,
                        "usn": info.get("usn", ""),
                        "name": info.get("name", f"Student #{matched_sid}"),
                        "score": float(score),
                        "source_photo_index": photo_idx,
                        "bbox": (x1, y1, x2, y2),
                        "is_present": True
                    }

                # Draw green bounding box on preview
                cv2.rectangle(annotated_bgr, (x1, y1), (x2, y2), (0, 200, 0), 2)
                label = f"{info.get('usn', '')} ({int(score * 100)}%)"
                cv2.putText(
                    annotated_bgr, label, (x1, max(20, y1 - 8)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 220, 0), 2, cv2.LINE_AA
                )
            else:
                unrecognized_faces.append({
                    "source_photo_index": photo_idx,
                    "bbox": (x1, y1, x2, y2),
                    "det_score": float(det_score),
                    "best_score": float(score),
                })
                # Draw orange/red box for unknown
                cv2.rectangle(annotated_bgr, (x1, y1), (x2, y2), (0, 0, 220), 2)
                cv2.putText(
                    annotated_bgr, f"? ({int(score * 100)}%)", (x1, max(20, y1 - 8)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 220), 1, cv2.LINE_AA
                )

        annotated_images.append(annotated_bgr)

    if progress_callback:
        progress_callback(100, "Matching complete!")

    matched_list = sorted(best_by_student.values(), key=lambda m: m["usn"] or "")

    return {
        "matched": matched_list,
        "unrecognized_faces": unrecognized_faces,
        "total_faces_detected": total_faces_detected,
        "photos_processed": len(annotated_images),
        "annotated_images": annotated_images,
    }
