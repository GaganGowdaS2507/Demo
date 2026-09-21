/**
 * =============================================================================
 * RecognitionEngine
 * =============================================================================
 * The pluggable core of the whole app. Orchestrates:
 *   ImageProcessor.process()  -->  IModelLoader.runInference()  -->  L2 normalize
 *
 * Screens talk ONLY to IRecognitionEngine. Swapping "which model is under
 * test" never touches UI code — it's a matter of calling
 * RecognitionEngineFactory.create(modelMetadata) with a different
 * ModelMetadata (different runtime + different .tflite/.onnx file + its own
 * PreprocessingConfig).
 *
 * Note: face DETECTION (finding the face in the frame) happens upstream via
 * IFaceDetector and is passed in as a `DetectedFace`, since detection is
 * shared across all engines and should only run once per image, not once per
 * model-under-test.
 * =============================================================================
 */
import type {
  DetectedFace,
  EmbeddingResult,
  IModelLoader,
  IRecognitionEngine,
  ModelLoadStatus,
  ModelMetadata,
} from '../types';
import { imageProcessor } from '../processing/ImageProcessor';
import { l2Normalize, isValidEmbedding } from '../embedding/EmbeddingUtils';

export class RecognitionEngine implements IRecognitionEngine {
  readonly engineId: string;

  constructor(private readonly modelLoader: IModelLoader) {
    this.engineId = `engine-${modelLoader.runtime}`;
  }

  async initialize(metadata: ModelMetadata): Promise<ModelLoadStatus> {
    return this.modelLoader.load(metadata);
  }

  isReady(): boolean {
    return this.modelLoader.isReady();
  }

  async generateEmbedding(imageUri: string, face: DetectedFace): Promise<EmbeddingResult> {
    if (!this.isReady()) {
      throw new Error(
        `RecognitionEngine (${this.engineId}): not initialized. Call initialize() first.`,
      );
    }

    const metadata = this.modelLoader.getMetadata();
    if (!metadata) {
      throw new Error(`RecognitionEngine (${this.engineId}): metadata unavailable.`);
    }

    const overallStart = Date.now();

    // Step 1: deterministic preprocessing (identical logic regardless of runtime)
    const preprocessed = await imageProcessor.process(imageUri, face, metadata.preprocessing);

    // Step 2: run inference through whichever runtime this engine wraps
    const inferenceStart = Date.now();
    const rawEmbedding = await this.modelLoader.runInference(preprocessed.tensorData);
    const inferenceTimeMs = Date.now() - inferenceStart;

    if (!isValidEmbedding(rawEmbedding, metadata.embeddingDimension)) {
      throw new Error(
        `RecognitionEngine (${this.engineId}): model produced an invalid embedding ` +
          `(expected dim ${metadata.embeddingDimension}, got ${rawEmbedding.length}, ` +
          `or contained NaN/Infinity values).`,
      );
    }

    // Step 3: L2 normalize if the model card says the raw output isn't already unit-norm
    const finalEmbedding = metadata.requiresL2Normalization
      ? l2Normalize(rawEmbedding)
      : rawEmbedding;

    const totalTimeMs = Date.now() - overallStart;

    return {
      embedding: finalEmbedding,
      embeddingDimension: finalEmbedding.length,
      inferenceTimeMs,
      preprocessingTimeMs: preprocessed.preprocessingTimeMs,
      totalTimeMs,
      wasL2Normalized: metadata.requiresL2Normalization,
      modelId: metadata.modelId,
      modelDisplayName: metadata.displayName,
      runtime: metadata.runtime,
      preprocessingConfig: metadata.preprocessing,
    };
  }

  getMetadata(): ModelMetadata | null {
    return this.modelLoader.getMetadata();
  }

  async dispose(): Promise<void> {
    await this.modelLoader.unload();
  }
}
