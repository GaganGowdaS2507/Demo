/**
 * =============================================================================
 * ModelCatalog
 * =============================================================================
 * Declarative registry of every model available for benchmarking. To add a
 * new model to test:
 *   1. Drop the .tflite or .onnx file into android/app/src/main/assets/models/
 *   2. Add one ModelMetadata entry below describing its input size,
 *      normalization scheme, embedding dimension, etc.
 *   3. It immediately appears in Settings > Active Model and Model Info.
 *
 * No other code changes are required — this is the whole point of the
 * pluggable architecture. Preprocessing parameters live PER MODEL (not
 * globally) because different models genuinely expect different input sizes
 * and normalization — but the *pipeline steps themselves* (crop -> align ->
 * resize -> normalize -> infer -> L2) are identical for all of them, run by
 * the same ImageProcessor and RecognitionEngine code.
 * =============================================================================
 */
import type { ModelMetadata } from '../types';

export const MODEL_CATALOG: ModelMetadata[] = [
  {
    modelId: 'mobilefacenet-onnx-v1',
    displayName: 'MobileFaceNet (ONNX)',
    runtime: 'onnx',
    modelPath: 'models/w600k_mbf.onnx',
    version: '1.0',

    inputTensors: [
      {
        name: 'input.1',
        shape: [1, 3, 112, 112],
        dtype: 'float32',
      },
    ],

    outputTensors: [
      {
        name: '516',
        shape: [1, 512],
        dtype: 'float32',
      },
    ],

    embeddingDimension: 512,
    requiresL2Normalization: true,

    preprocessing: {
      inputSize: 112,
      useAlignment: true,
      marginFraction: 0.15,
      normalization: {
        scheme: 'neg_one_to_one',
      },
      channelOrder: 'RGB',
      tensorLayout: 'NCHW',
    },

    notes: 'Official InsightFace MobileFaceNet (MBF@WebFace600K)',
  },
];

export function getModelById(modelId: string): ModelMetadata | undefined {
  return MODEL_CATALOG.find((m) => m.modelId === modelId);
}

export const DEFAULT_MODEL_ID = 'mobilefacenet-onnx-v1';