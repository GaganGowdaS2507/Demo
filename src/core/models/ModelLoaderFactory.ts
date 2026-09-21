/**
 * =============================================================================
 * ModelLoaderFactory
 * =============================================================================
 * Single place that maps a ModelRuntime ('tflite' | 'onnx') to its concrete
 * IModelLoader implementation. Adding a new runtime in the future (e.g.
 * PyTorch Mobile / ExecuTorch) means: (1) implement IModelLoader, (2) add one
 * case here. Nothing else in the app changes.
 * =============================================================================
 */
import type { IModelLoader, ModelRuntime } from '../types';
import { ONNXModelLoader } from './ONNXModelLoader';

export function createModelLoader(runtime: ModelRuntime): IModelLoader {
  switch (runtime) {
    case 'onnx':
      return new ONNXModelLoader();
    default: {
      const exhaustiveCheck: never = runtime;
      throw new Error(`ModelLoaderFactory: unsupported runtime "${exhaustiveCheck}"`);
    }
  }
}
