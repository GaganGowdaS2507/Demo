"""
desktop_app/core/engine.py
Edge Recognition Engine for AttendAI Faculty Desktop App.
Runs locally using bundled InsightFace models (SCRFD detector + ArcFace ResNet50 + MobileFaceNet).
100% offline edge inference - zero compute load on central Flask server.
"""

import os
import sys
import logging
import threading
import cv2
import numpy as np

logger = logging.getLogger(__name__)


def get_base_dir():
    """Returns base directory of desktop application (handles frozen PyInstaller binary)."""
    if getattr(sys, 'frozen', False):
        return sys._MEIPASS
    return os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def normalize_embedding(emb):
    """L2 normalize a 1D or 2D embedding vector."""
    if emb is None:
        return None
    emb = np.asarray(emb, dtype=np.float32)
    norm = np.linalg.norm(emb, axis=-1, keepdims=True)
    if np.any(norm == 0):
        return emb
    return emb / norm


class DesktopRecognitionEngine:
    """
    Client-side Recognition Engine.
    Runs locally on faculty workstation/laptop with CPU or GPU/DirectML acceleration.
    """

    def __init__(self, models_root=None):
        self.base_dir = get_base_dir()
        self.models_root = models_root or self.base_dir
        self.models_dir = os.path.join(self.models_root, "models")
        self.buffalo_dir = os.path.join(self.models_dir, "buffalo_l")
        self.mbf_model_path = os.path.join(self.models_dir, "w600k_mbf.onnx")

        self.app = None
        self.mbf_session = None
        self.mbf_input_name = None
        self.is_initialized = False
        self.device = "CPU"
        self.lock = threading.Lock()

    def initialize(self):
        """Initializes InsightFace FaceAnalysis and MobileFaceNet sessions."""
        if self.is_initialized:
            return True

        with self.lock:
            try:
                import insightface
                from insightface.app import FaceAnalysis
                import onnxruntime as ort

                providers = ort.get_available_providers()
                logger.info(f"Available ONNX Runtime execution providers: {providers}")

                # Choose best execution provider (DirectML / CUDA / CPU)
                use_gpu = False
                selected_providers = ["CPUExecutionProvider"]
                if "CUDAExecutionProvider" in providers:
                    selected_providers = ["CUDAExecutionProvider", "CPUExecutionProvider"]
                    use_gpu = True
                    self.device = "GPU (CUDA)"
                elif "DmlExecutionProvider" in providers:
                    selected_providers = ["DmlExecutionProvider", "CPUExecutionProvider"]
                    use_gpu = True
                    self.device = "GPU (DirectML)"
                else:
                    self.device = "CPU"

                ctx_id = 0 if use_gpu else -1

                logger.info(f"Loading FaceAnalysis from {self.models_root} on {self.device}...")
                self.app = FaceAnalysis(
                    name="buffalo_l",
                    root=self.models_root,
                    allowed_modules=["detection", "recognition"],
                    providers=selected_providers
                )
                self.app.prepare(ctx_id=ctx_id, det_size=(640, 640))

                # Load MobileFaceNet model if present
                if os.path.exists(self.mbf_model_path):
                    try:
                        self.mbf_session = ort.InferenceSession(
                            self.mbf_model_path,
                            providers=selected_providers
                        )
                        self.mbf_input_name = self.mbf_session.get_inputs()[0].name
                        logger.info("MobileFaceNet model loaded successfully.")
                    except Exception as mbf_err:
                        logger.warning(f"Could not load MBF session: {mbf_err}")
                        self.mbf_session = None
                else:
                    logger.info(f"MBF model not found at {self.mbf_model_path}")

                self.is_initialized = True
                logger.info(f"DesktopRecognitionEngine initialized successfully on {self.device}.")
                return True

            except Exception as e:
                logger.error(f"Failed to initialize DesktopRecognitionEngine: {e}", exc_info=True)
                self.is_initialized = False
                return False

    def detect_faces(self, bgr_frame):
        """
        Detects faces in BGR frame.
        Returns list of InsightFace face objects. Thread-safe.
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
        """Extracts normalized 512-d ArcFace embedding from detected face."""
        emb = getattr(face, "normed_embedding", None)
        if emb is None:
            raw = getattr(face, "embedding", None)
            if raw is not None:
                emb = normalize_embedding(raw)
        if emb is not None:
            return emb.astype(np.float32)
        return None

    def get_mbf_embedding(self, bgr_frame, face):
        """Extracts 512-d MobileFaceNet embedding from detected face using landmark alignment."""
        if self.mbf_session is None or not hasattr(face, "kps") or face.kps is None:
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

    @staticmethod
    def get_face_bbox(face):
        """Returns integer bbox (x1, y1, x2, y2)."""
        bbox = face.bbox.astype(int)
        return int(bbox[0]), int(bbox[1]), int(bbox[2]), int(bbox[3])

    @staticmethod
    def get_det_score(face):
        """Returns detection confidence score [0.0 - 1.0]."""
        return float(getattr(face, "det_score", 0.0))

    @staticmethod
    def match_top1(query_emb, candidate_matrix, candidate_ids):
        """
        Computes cosine similarity of query_emb against candidate_matrix (shape N x 512).
        Returns: (best_id, score) or (None, 0.0)
        """
        if candidate_matrix is None or len(candidate_ids) == 0:
            return None, 0.0

        q = normalize_embedding(query_emb).astype(np.float32)
        sims = candidate_matrix @ q  # shape: (N,)
        idx = int(np.argmax(sims))
        score = float(sims[idx])
        return candidate_ids[idx], score
