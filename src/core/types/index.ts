/**
 * =============================================================================
 * CORE TYPES
 * =============================================================================
 * Single source of truth for all cross-layer contracts. Every module
 * (detection, processing, model loading, engine, database, UI) depends only
 * on these interfaces — never on each other's concrete implementations.
 *
 * This is what makes the recognition engine "pluggable": as long as a new
 * engine implements IRecognitionEngine and returns an EmbeddingResult that
 * matches this shape, nothing else in the app needs to change.
 * =============================================================================
 */

// -----------------------------------------------------------------------------
// Geometry
// -----------------------------------------------------------------------------

export interface BoundingBox {
  x: number;
  y: number;
  width: number;
  height: number;
}

export interface Point2D {
  x: number;
  y: number;
}

/** Standard 5-point facial landmarks used for alignment (eyes, nose, mouth corners). */
export interface FaceLandmarks {
  leftEye?: Point2D;
  rightEye?: Point2D;
  noseBase?: Point2D;
  leftMouth?: Point2D;
  rightMouth?: Point2D;
}

// -----------------------------------------------------------------------------
// Face Detection Layer
// -----------------------------------------------------------------------------

export interface DetectedFace {
  boundingBox: BoundingBox;
  landmarks: FaceLandmarks;
  /** Rotation of the face around the Z axis (roll), in degrees. Used for alignment. */
  rollAngle?: number;
  /** Y axis rotation (yaw), in degrees. Useful for filtering profile faces. */
  yawAngle?: number;
  /** Detector's confidence that this is a face (0-1), if provided. */
  detectionConfidence?: number;
  /** Eye-open probabilities, useful for liveness / quality heuristics. */
  leftEyeOpenProbability?: number;
  rightEyeOpenProbability?: number;
}

export interface FaceDetectionResult {
  faces: DetectedFace[];
  imageWidth: number;
  imageHeight: number;
  detectionTimeMs: number;
}

/**
 * Contract for any face detector implementation. ML Kit is the default and
 * only implementation today, but this interface allows swapping in a
 * different detector (e.g. MediaPipe) without touching the rest of the app.
 */
export interface IFaceDetector {
  initialize(): Promise<void>;
  detectFaces(imageUri: string, options?: any): Promise<FaceDetectionResult>;
  release(): Promise<void>;
}

// -----------------------------------------------------------------------------
// Image Processing Layer
// -----------------------------------------------------------------------------

export type NormalizationScheme =
  | 'zero_to_one' // pixel / 255.0
  | 'neg_one_to_one' // (pixel / 127.5) - 1.0
  | 'imagenet_mean_std' // (pixel/255 - mean) / std, per-channel
  | 'raw_uint8'; // no normalization, model expects 0-255

export interface NormalizationConfig {
  scheme: NormalizationScheme;
  /** Only used when scheme === 'imagenet_mean_std' */
  mean?: [number, number, number];
  std?: [number, number, number];
}

export interface PreprocessingConfig {
  /** Target square size the model expects, e.g. 112 for ArcFace/MobileFaceNet, 160 for FaceNet. */
  inputSize: number;
  /** Whether to align the face using eye landmarks before cropping. */
  useAlignment: boolean;
  /** Fractional margin added around the tight face box before crop (0.0 - 1.0). */
  marginFraction: number;
  normalization: NormalizationConfig;
  /** Channel order expected by the model. */
  channelOrder: 'RGB' | 'BGR';
  /** Whether the model expects NHWC (TFLite default) or NCHW (many ONNX exports). */
  tensorLayout: 'NHWC' | 'NCHW';
}

export interface PreprocessedFace {
  /** Flat Float32Array ready to feed into the model, already laid out per tensorLayout. */
  tensorData: Float32Array;
  /** Shape actually produced, e.g. [1, 112, 112, 3]. Kept for debugging/display. */
  shape: number[];
  /** Debugging: URI of the cropped/aligned face image, if persisted for inspection. */
  debugCroppedImageUri?: string;
  preprocessingTimeMs: number;
  configUsed: PreprocessingConfig;
}

/**
 * Contract for the deterministic crop -> align -> resize -> normalize pipeline.
 * This must behave IDENTICALLY regardless of which recognition engine is
 * active, since preprocessing consistency is what makes model comparisons fair.
 */
export interface IImageProcessor {
  process(
    imageUri: string,
    face: DetectedFace,
    config: PreprocessingConfig,
  ): Promise<PreprocessedFace>;
}

// -----------------------------------------------------------------------------
// Model Loader Layer
// -----------------------------------------------------------------------------

export type ModelRuntime = 'onnx';

export interface TensorSpec {
  name: string;
  shape: number[];
  dtype: string;
}

export interface ModelMetadata {
  modelId: string;
  displayName: string;
  runtime: ModelRuntime;
  /** Path relative to app bundle / documents dir where the model file lives. */
  modelPath: string;
  version: string;
  inputTensors: TensorSpec[];
  outputTensors: TensorSpec[];
  embeddingDimension: number;
  preprocessing: PreprocessingConfig;
  /** Whether output embedding requires L2 normalization post-inference. */
  requiresL2Normalization: boolean;
  fileSizeBytes?: number;
  /** Free-form notes: training dataset, license, source, etc. */
  notes?: string;
}

export interface ModelLoadStatus {
  isLoaded: boolean;
  loadTimeMs?: number;
  error?: string;
}

/**
 * Contract for loading a model file into a given runtime (TFLite / ONNX / future).
 * Concrete loaders (TFLiteModelLoader, ONNXModelLoader) implement this so the
 * RecognitionEngine never needs runtime-specific logic.
 */
export interface IModelLoader {
  readonly runtime: ModelRuntime;
  load(metadata: ModelMetadata): Promise<ModelLoadStatus>;
  isReady(): boolean;
  /** Runs a raw forward pass. Input/output shapes are described by ModelMetadata. */
  runInference(inputTensor: Float32Array): Promise<Float32Array>;
  getMetadata(): ModelMetadata | null;
  unload(): Promise<void>;
}

// -----------------------------------------------------------------------------
// Recognition Engine Layer (the pluggable core)
// -----------------------------------------------------------------------------

export interface EmbeddingResult {
  embedding: Float32Array;
  embeddingDimension: number;
  inferenceTimeMs: number;
  preprocessingTimeMs: number;
  totalTimeMs: number;
  wasL2Normalized: boolean;
  modelId: string;
  modelDisplayName: string;
  runtime: ModelRuntime;
  preprocessingConfig: PreprocessingConfig;
}

/**
 * The central abstraction of this app. Every recognition backend (TFLite
 * MobileFaceNet, ONNX ArcFace, a future runtime, etc.) implements this same
 * interface. Screens and the database layer talk ONLY to IRecognitionEngine,
 * never to a concrete model loader — this is what lets us A/B test models
 * with zero UI changes.
 */
export interface IRecognitionEngine {
  readonly engineId: string;
  initialize(metadata: ModelMetadata): Promise<ModelLoadStatus>;
  isReady(): boolean;
  /** Full pipeline: detect (optional, if face not pre-supplied) -> crop/align -> resize -> normalize -> infer -> L2 normalize. */
  generateEmbedding(imageUri: string, face: DetectedFace): Promise<EmbeddingResult>;
  getMetadata(): ModelMetadata | null;
  dispose(): Promise<void>;
}

// -----------------------------------------------------------------------------
// Similarity Layer
// -----------------------------------------------------------------------------

export interface SimilarityResult {
  score: number; // cosine similarity, range [-1, 1]
  confidencePercent: number; // normalized 0-100 for display
  passesThreshold: boolean;
  thresholdUsed: number;
}

export interface ISimilarityCalculator {
  cosineSimilarity(a: Float32Array, b: Float32Array): number;
  evaluate(a: Float32Array, b: Float32Array, threshold: number): SimilarityResult;
}

// -----------------------------------------------------------------------------
// Database Layer
// -----------------------------------------------------------------------------

export interface EnrolledFace {
  id: string; // uuid
  personName: string;
  modelId: string; // embeddings from different models are NEVER compared cross-model
  embeddingDimension: number;
  embedding: number[]; // stored as plain array (Float32Array is not directly JSON/SQLite friendly)
  wasL2Normalized: boolean;
  sourceImageUri?: string;
  debugCroppedImageUri?: string;
  inferenceTimeMs: number;
  preprocessingTimeMs: number;
  createdAt: number; // epoch ms
  notes?: string;
}

export interface RecognitionLogEntry {
  id: string;
  modelId: string;
  matchedFaceId: string | null;
  matchedPersonName: string | null;
  similarityScore: number;
  confidencePercent: number;
  passedThreshold: boolean;
  thresholdUsed: number;
  inferenceTimeMs: number;
  preprocessingTimeMs: number;
  totalTimeMs: number;
  createdAt: number;
}

export interface IDatabase {
  initialize(): Promise<void>;
  insertFace(face: EnrolledFace): Promise<void>;
  getAllFaces(modelId?: string): Promise<EnrolledFace[]>;
  getFaceById(id: string): Promise<EnrolledFace | null>;
  deleteFace(id: string): Promise<void>;
  clearAllFaces(): Promise<void>;
  insertRecognitionLog(entry: RecognitionLogEntry): Promise<void>;
  getRecentLogs(limit: number): Promise<RecognitionLogEntry[]>;
  getPerformanceStats(modelId: string): Promise<PerformanceStats>;
}

export interface PerformanceStats {
  modelId: string;
  sampleCount: number;
  avgInferenceTimeMs: number;
  minInferenceTimeMs: number;
  maxInferenceTimeMs: number;
  avgTotalTimeMs: number;
  avgSimilarityScore: number;
  passRate: number; // fraction of recognitions that passed threshold
}

// -----------------------------------------------------------------------------
// App-level settings
// -----------------------------------------------------------------------------


export interface AppSettings {
  activeModelId: string;
  similarityThreshold: number;
  saveDebugCrops: boolean;
  cameraFacing: 'front' | 'back';
  detectorPerformanceMode: 'fast' | 'accurate';
  // --- Attendance app additions (non-breaking, optional-in-spirit but given defaults below) ---
  backendBaseUrl: string;
  esp32StreamUrl: string;
  attendanceCooldownMinutes: number;
  autoSyncOnReconnect: boolean;
}