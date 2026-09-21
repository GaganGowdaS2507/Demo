"""
attendance_system/recognition/engine.py
Core face recognition engine using InsightFace + ONNX Runtime.
Handles model initialization, face detection, embedding extraction, matching.
GPU-first with CPU fallback. No PyTorch dependency.
"""

import os
import time
import logging
import pickle
import glob
import threading

import cv2
import numpy as np
from PIL import Image

from config import Config
from recognition.utils import (
    normalize_embedding,
    cosine_similarity,
    serialize_embedding,
    deserialize_embedding,
    save_face_image,
    save_embedding_npz,
    load_embedding_npz,
    pil_to_bgr,
    bgr_to_pil,
    safe_name,
)

logger = logging.getLogger(__name__)


class RecognitionEngine:
    """
    Face recognition engine:
    - InsightFace FaceAnalysis for detection + embedding
    - Embedding index for fast matching
    - GPU-first, CPU-fallback
    - Thread-safe
    """

    def __init__(self):
        self.app = None  # InsightFace FaceAnalysis
        self.is_initialized = False
        self.device = "CPU"
        self.mbf_session = None
        self.mbf_input_name = None
        self.lock = threading.Lock()

        # Embedding index: {student_id: normalized_embedding}
        self._emb_index_sids = []      # list of student_id (int)
        self._emb_index_matrix = None  # np.ndarray shape (N, 512)
        self._emb_index_lock = threading.Lock()

        # Student info caches
        self._student_cache = {}  # student_id -> {usn, name, section_id}
        self._usn_to_id = {}      # usn -> student_id

    # def initialize(self):
    #     """Initialize InsightFace model. GPU-first, CPU-fallback."""
    #     if self.is_initialized:
    #         logger.info("Recognition engine already initialized.")
    #         return True

    #     try:
    #         import insightface
    #         from insightface.app import FaceAnalysis
    #         import onnxruntime as ort

    #         providers = ort.get_available_providers()
    #         logger.info(f"ONNX Runtime providers: {providers}")

    #         # Determine GPU or CPU
    #         use_gpu = "CUDAExecutionProvider" in providers
    #         ctx_id = 0 if use_gpu else -1
    #         self.device = "GPU" if use_gpu else "CPU"

    #         self.app = FaceAnalysis(name=Config.INSIGHTFACE_MODEL)
    #         self.app.prepare(
    #             ctx_id=ctx_id,
    #             det_size=Config.DETECTION_SIZE,
    #         )

    #         # Load secondary MobileFaceNet (mbf) recognition model.
    #         # Uses the SAME aligned 112x112 crop as w600k_r50 — only the
    #         # backbone differs — so both embeddings come from one detection pass.
    #         try:
    #             self.mbf_session = ort.InferenceSession(
    #                 Config.MBF_MODEL_PATH, providers=providers
    #             )
    #             self.mbf_input_name = self.mbf_session.get_inputs()[0].name
    #             logger.info("MBF (mobile) recognition model loaded.")
    #         except Exception as e:
    #             self.mbf_session = None
    #             logger.warning(f"MBF model not loaded, mobile embeddings disabled: {e}")

    #         self.is_initialized = True
    #         logger.info(f"FaceAnalysis ready on {self.device}")
    #         return True

    #     except Exception as e:
    #         logger.warning(f"GPU/auto init failed: {e}. Trying CPU fallback...")
    #         try:
    #             from insightface.app import FaceAnalysis

    #             self.app = FaceAnalysis(name=Config.INSIGHTFACE_MODEL)
    #             self.app.prepare(ctx_id=-1, det_size=Config.DETECTION_SIZE)
    #             self.device = "CPU"
    #             self.is_initialized = True
    #             logger.info("FaceAnalysis ready on CPU (fallback)")
    #             return True

    #         except Exception as e2:
    #             self.app = None
    #             self.is_initialized = False
    #             logger.error(f"Failed to initialize FaceAnalysis: {e2}")
    #             return False

    def initialize(self):
        """Initialize InsightFace model. GPU-first, CPU-fallback."""
        if self.is_initialized:
            logger.info("Recognition engine already initialized.")
            return True

        try:
            import insightface
            from insightface.app import FaceAnalysis
            import onnxruntime as ort

            providers = ort.get_available_providers()
            logger.info(f"ONNX Runtime providers: {providers}")

            # --------------------------------------------------
            # Try GPU if available
            # --------------------------------------------------
            use_gpu = "CUDAExecutionProvider" in providers
            ctx_id = 0 if use_gpu else -1
            self.device = "GPU" if use_gpu else "CPU"

            self.app = FaceAnalysis(name=Config.INSIGHTFACE_MODEL)
            self.app.prepare(
                ctx_id=ctx_id,
                det_size=Config.DETECTION_SIZE,
            )

            # Load MobileFaceNet model
            try:
                self.mbf_session = ort.InferenceSession(
                    Config.MBF_MODEL_PATH,
                    providers=providers,
                )
                self.mbf_input_name = self.mbf_session.get_inputs()[0].name

                logger.info("MBF (mobile) recognition model loaded.")
                logger.info(f"MBF Input Shape : {self.mbf_session.get_inputs()[0].shape}")
                logger.info(f"MBF Output Shape: {self.mbf_session.get_outputs()[0].shape}")

            except Exception as e:
                self.mbf_session = None
                self.mbf_input_name = None
                logger.warning(f"MBF model not loaded: {e}")

            self.is_initialized = True
            logger.info(f"FaceAnalysis ready on {self.device}")
            return True

        except Exception as e:

            logger.warning(f"GPU initialization failed: {e}")
            logger.info("Trying CPU fallback...")

            try:
                from insightface.app import FaceAnalysis
                import onnxruntime as ort

                providers = ["CPUExecutionProvider"]

                self.app = FaceAnalysis(name=Config.INSIGHTFACE_MODEL)
                self.app.prepare(
                    ctx_id=-1,
                    det_size=Config.DETECTION_SIZE,
                )

                self.device = "CPU"

                # ----------------------------------------------
                # Load MBF model AGAIN for CPU fallback
                # ----------------------------------------------
                try:
                    self.mbf_session = ort.InferenceSession(
                        Config.MBF_MODEL_PATH,
                        providers=providers,
                    )
                    self.mbf_input_name = self.mbf_session.get_inputs()[0].name

                    logger.info("MBF (mobile) recognition model loaded (CPU).")
                    logger.info(f"MBF Input Shape : {self.mbf_session.get_inputs()[0].shape}")
                    logger.info(f"MBF Output Shape: {self.mbf_session.get_outputs()[0].shape}")

                except Exception as e:
                    self.mbf_session = None
                    self.mbf_input_name = None
                    logger.warning(f"MBF model not loaded on CPU: {e}")

                self.is_initialized = True
                logger.info("FaceAnalysis ready on CPU (fallback)")
                return True

            except Exception as e2:
                self.app = None
                self.mbf_session = None
                self.mbf_input_name = None
                self.is_initialized = False

                logger.error(f"Failed to initialize FaceAnalysis: {e2}")
                return False

    def detect_faces(self, bgr_frame):
        """
        Detect faces in a BGR frame.
        Returns list of face objects from InsightFace.
        Thread-safe.
        """
        if not self.is_initialized or self.app is None:
            return []

        with self.lock:
            try:
                faces = self.app.get(bgr_frame)
                return faces if faces else []
            except Exception as e:
                logger.error(f"Face detection error: {e}")
                return []

    def get_embedding(self, face):
        """Extract normalized embedding from a detected face object."""
        emb = getattr(face, "normed_embedding", None)
        if emb is None:
            raw = getattr(face, "embedding", None)
            if raw is not None:
                emb = normalize_embedding(raw)
        if emb is not None:
            return emb.astype(np.float32)
        return None

    def get_face_bbox(self, face):
        """Get integer bbox (x1, y1, x2, y2) from face object."""
        return tuple(face.bbox.astype(int))

    def get_det_score(self, face):
        """Get detection confidence score."""
        return float(getattr(face, "det_score", 0.0))

    def compute_embedding_from_bgr(self, bgr_frame):
        """
        Detect the largest face in a BGR frame and return its embedding + crop.
        Returns: (embedding, face_crop_bgr) or (None, None)
        """
        faces = self.detect_faces(bgr_frame)
        if not faces:
            return None, None

        # Pick largest face
        best = max(faces, key=lambda f: (
            (f.bbox[2] - f.bbox[0]) * (f.bbox[3] - f.bbox[1])
        ))

        emb = self.get_embedding(best)
        if emb is None:
            return None, None

        x1, y1, x2, y2 = self.get_face_bbox(best)
        h, w = bgr_frame.shape[:2]
        x1 = max(0, x1)
        y1 = max(0, y1)
        x2 = min(w, x2)
        y2 = min(h, y2)
        face_crop = bgr_frame[y1:y2, x1:x2].copy()

        return emb, face_crop

    def compute_embedding_from_pil(self, pil_image):
        """
        Detect face in a PIL image, return (embedding, face_crop_pil) or (None, None).
        """
        bgr = pil_to_bgr(pil_image)
        emb, crop_bgr = self.compute_embedding_from_bgr(bgr)
        if emb is None:
            return None, None
        crop_pil = bgr_to_pil(crop_bgr)
        return emb, crop_pil

    def get_mbf_embedding(self, bgr_frame, face):
        """
        Compute a MobileFaceNet embedding using the SAME face alignment
        (5-point landmarks) InsightFace already detected — not a second
        detection pass. Returns None if the mbf model isn't loaded.
        """
        if self.mbf_session is None:
            return None
        try:
            from insightface.utils import face_align
            aligned = face_align.norm_crop(bgr_frame, landmark=face.kps, image_size=112)
            blob = cv2.dnn.blobFromImage(
                aligned, 1.0 / 127.5, (112, 112),
                (127.5, 127.5, 127.5), swapRB=True
            )
            out = self.mbf_session.run(None, {self.mbf_input_name: blob})[0]
            return normalize_embedding(out.flatten()).astype(np.float32)
        except Exception as e:
            logger.error(f"MBF embedding error: {e}")
            return None

    def compute_dual_embeddings_from_bgr(self, bgr_frame):
        """
        Detect the largest face once, then return BOTH embeddings from the
        same aligned face image:
          - r50_emb: w600k_r50 embedding (backend/web recognition)
          - mbf_emb: w600k_mbf embedding (mobile offline recognition), or None
        Returns: (r50_emb, mbf_emb, face_crop_bgr) or (None, None, None)
        """
        faces = self.detect_faces(bgr_frame)
        if not faces:
            return None, None, None

        best = max(faces, key=lambda f: (
            (f.bbox[2] - f.bbox[0]) * (f.bbox[3] - f.bbox[1])
        ))

        r50_emb = self.get_embedding(best)
        if r50_emb is None:
            return None, None, None

        mbf_emb = self.get_mbf_embedding(bgr_frame, best)

        x1, y1, x2, y2 = self.get_face_bbox(best)
        h, w = bgr_frame.shape[:2]
        x1, y1 = max(0, x1), max(0, y1)
        x2, y2 = min(w, x2), min(h, y2)
        face_crop = bgr_frame[y1:y2, x1:x2].copy()

        return r50_emb, mbf_emb, face_crop

    def compute_dual_embeddings_from_pil(self, pil_image):
        """PIL version of compute_dual_embeddings_from_bgr, for enrollment."""
        bgr = pil_to_bgr(pil_image)
        r50_emb, mbf_emb, crop_bgr = self.compute_dual_embeddings_from_bgr(bgr)
        if r50_emb is None:
            return None, None, None
        crop_pil = bgr_to_pil(crop_bgr)
        return r50_emb, mbf_emb, crop_pil

    
    # ============================================
    # Embedding Index Management
    # ============================================

    def load_embeddings_from_db(self, db_pool=None):
        """Load all face embeddings from the database."""
        rows = []
        try:
            from core.db import get_db
            if db_pool is not None and hasattr(db_pool, 'get_connection'):
                conn = db_pool.get_connection()
            else:
                conn = get_db()
            cursor = conn.cursor(dictionary=True, buffered=True)
            cursor.execute(
                "SELECT student_id, usn, embedding FROM faces WHERE region = 'full'"
            )
            for row in cursor.fetchall():
                emb = deserialize_embedding(row["embedding"])
                if emb is not None:
                    rows.append((row["student_id"], emb))
            cursor.close()
            conn.close()
        except Exception as e:
            logger.error(f"load_embeddings_from_db error: {e}")
        return rows

    def load_embeddings_from_dataset(self):
        """Load embeddings from dataset/embeddings/*.npz files."""
        rows = []
        pattern = os.path.join(Config.DATASET_EMB_DIR, "*.npz")
        for p in glob.glob(pattern):
            sid_str = os.path.splitext(os.path.basename(p))[0]
            try:
                sid = int(sid_str)
            except ValueError:
                continue
            emb = load_embedding_npz(sid)
            if emb is not None:
                rows.append((sid, emb))
        return rows

    def reload_embedding_index(self, db_pool=None):
        """
        Rebuild the embedding index from DB + dataset.
        DB embeddings take priority over dataset files.
        """
        buckets = {}

        # 1. From DB (primary source)
        for sid, emb in self.load_embeddings_from_db(db_pool):
            buckets[sid] = emb

        # 2. From dataset files (fill gaps)
        for sid, emb in self.load_embeddings_from_dataset():
            if sid not in buckets:
                buckets[sid] = emb

        with self._emb_index_lock:
            if not buckets:
                self._emb_index_sids = []
                self._emb_index_matrix = None
                logger.warning("Embedding index is empty. Enroll students first.")
                return 0

            self._emb_index_sids = list(buckets.keys())
            self._emb_index_matrix = np.stack(
                [buckets[s] for s in self._emb_index_sids]
            ).astype(np.float32)

        count = len(self._emb_index_sids)
        logger.info(f"Embedding index rebuilt: {count} identities.")
        return count

    def refresh_student_cache(self, db_pool=None):
        """Refresh student info cache from DB."""
        try:
            from core.db import get_db
            if db_pool is not None and hasattr(db_pool, 'get_connection'):
                conn = db_pool.get_connection()
            else:
                conn = get_db()

            cursor = conn.cursor(dictionary=True, buffered=True)
            cursor.execute(
                """
                SELECT s.id, s.usn, u.full_name, s.section_id
                FROM students s
                JOIN users u ON u.id = s.user_id
                """
            )
            self._student_cache = {}
            self._usn_to_id = {}
            for row in cursor.fetchall():
                self._student_cache[row["id"]] = {
                    "usn": row["usn"],
                    "name": row["full_name"],
                    "section_id": row["section_id"],
                }
                self._usn_to_id[row["usn"]] = row["id"]
            cursor.close()
            conn.close()
            logger.info(f"Student cache refreshed: {len(self._student_cache)} students.")
        except Exception as e:
            logger.error(f"refresh_student_cache error: {e}")

    def get_student_name(self, student_id):
        """Get student name from cache."""
        info = self._student_cache.get(student_id)
        return info["name"] if info else str(student_id)

    def get_student_usn(self, student_id):
        """Get student USN from cache."""
        info = self._student_cache.get(student_id)
        return info["usn"] if info else str(student_id)

    # ============================================
    # Matching
    # ============================================

    def match_top1(self, query_emb):
        """
        Find the best matching student for a query embedding.
        Returns: (student_id, similarity_score) or (None, 0.0)
        """
        with self._emb_index_lock:
            if self._emb_index_matrix is None or len(self._emb_index_sids) == 0:
                return None, 0.0

            q = normalize_embedding(query_emb).astype(np.float32)
            sims = self._emb_index_matrix @ q  # (N,)
            idx = int(np.argmax(sims))
            score = float(sims[idx])
            return self._emb_index_sids[idx], score

    def identify_face(self, face, threshold=None):
        """
        Given a face object, extract embedding and match.
        Returns: (student_id, score, embedding) or (None, 0.0, None)
        """
        if threshold is None:
            threshold = Config.RECOGNITION_THRESHOLD

        emb = self.get_embedding(face)
        if emb is None:
            return None, 0.0, None

        sid, score = self.match_top1(emb)
        if sid is not None and score >= threshold:
            return sid, score, emb
        return None, score, emb

    def match_face_to_student(self, query_emb, target_student_id, threshold=None):
        """
        Targeted face verification for DUAL_MODE.
        Compares query_emb ONLY against target_student_id's stored embedding.
        Does NOT perform full-database face search.
        Returns: (is_match: bool, similarity_score: float)
        """
        if threshold is None:
            threshold = Config.RECOGNITION_THRESHOLD

        if query_emb is None or target_student_id is None:
            return False, 0.0

        with self._emb_index_lock:
            if self._emb_index_matrix is None or len(self._emb_index_sids) == 0:
                return False, 0.0

            try:
                idx = self._emb_index_sids.index(target_student_id)
            except ValueError:
                # Target student has no enrolled face embedding
                return False, 0.0

            target_emb = self._emb_index_matrix[idx]
            q = normalize_embedding(query_emb).astype(np.float32)
            score = float(np.dot(target_emb, q))
            return (score >= threshold), score

    def verify_face_for_student(self, face, target_student_id, threshold=None):
        """
        Extract embedding for a single detected face and compare ONLY against target_student_id.
        Returns: (is_match: bool, score: float, embedding)
        """
        if threshold is None:
            threshold = Config.RECOGNITION_THRESHOLD

        emb = self.get_embedding(face)
        if emb is None:
            return False, 0.0, None

        is_match, score = self.match_face_to_student(emb, target_student_id, threshold=threshold)
        return is_match, score, emb

    # ============================================
    # Process a single frame (full pipeline)
    # ============================================

    def process_frame(self, bgr_frame, liveness_checker=None):
        """
        Process a single frame:
        1. Detect all faces
        2. For each face: check size, liveness, match embedding
        3. Return list of detection results

        Each result dict:
        {
            'bbox': (x1,y1,x2,y2),
            'det_score': float,
            'student_id': int or None,
            'match_score': float,
            'state': 'recognized' | 'unknown' | 'spoof',
            'embedding': np.array or None,
            'liveness_score': float or None,
            'name': str,
            'usn': str,
        }
        """
        results = []
        faces = self.detect_faces(bgr_frame)

        for face in faces:
            x1, y1, x2, y2 = self.get_face_bbox(face)
            w, h = x2 - x1, y2 - y1
            det_score = self.get_det_score(face)

            # Skip too-small or low-confidence detections
            if min(w, h) < Config.MIN_FACE_SIZE or det_score < Config.DETECTION_THRESHOLD:
                continue

            result = {
                "bbox": (x1, y1, x2, y2),
                "det_score": det_score,
                "student_id": None,
                "match_score": 0.0,
                "state": "unknown",
                "embedding": None,
                "liveness_score": None,
                "name": "Unknown",
                "usn": "",
            }

            # Liveness check
            if liveness_checker is not None:
                try:
                    frame_h, frame_w = bgr_frame.shape[:2]
                    face_bbox = [
                        max(0, x1), max(0, y1),
                        min(frame_w, x2), min(frame_h, y2)
                    ]
                    liveness_score, is_real = liveness_checker.check(
                        bgr_frame,
                        face_bbox
                    )

                    # print(
                    #     "ENGINE RECEIVED:",
                    #     liveness_score,
                    #     is_real
                    # )

                    result["liveness_score"] = liveness_score

                    if not is_real:
                        result["state"] = "spoof"
                        results.append(result)
                        continue
                except Exception as e:
                    logger.debug(f"Liveness check error: {e}")
                    # If liveness check fails, proceed without it

            # Get embedding and match
            student_id, score, emb = self.identify_face(face)
            result["embedding"] = emb
            result["match_score"] = score

            if student_id is not None:
                result["student_id"] = student_id
                result["state"] = "recognized"
                result["name"] = self.get_student_name(student_id)
                result["usn"] = self.get_student_usn(student_id)
            else:
                result["state"] = "unknown"

            results.append(result)

        return results