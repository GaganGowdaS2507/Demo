/**
 * =============================================================================
 * ONNXModelLoader
 * =============================================================================
 * Concrete IModelLoader for ONNX Runtime Mobile, backed by
 * `onnxruntime-react-native`. Runs fully offline using the bundled ORT
 * Mobile native binaries — no network calls at inference time. Model files
 * (.ort or .onnx) ship in the app bundle under android/app/src/main/assets/models/.
 *
 * This is the ONLY file that imports `onnxruntime-react-native`. Anything
 * above this layer (RecognitionEngine, screens) only ever sees IModelLoader —
 * so switching the "active" recognition backend from TFLite to ONNX is a
 * one-line change in RecognitionEngineFactory, nothing else.
 * =============================================================================
 */
import RNFS from 'react-native-fs';
import { InferenceSession, Tensor } from 'onnxruntime-react-native';
import type { IModelLoader, ModelLoadStatus, ModelMetadata } from '../types';

export class ONNXModelLoader implements IModelLoader {
  readonly runtime = 'onnx' as const;

  private session: InferenceSession | null = null;
  private metadata: ModelMetadata | null = null;

  async load(metadata: ModelMetadata): Promise<ModelLoadStatus> {
    const start = Date.now();

    try {
      const modelFile = `${RNFS.DocumentDirectoryPath}/${metadata.modelId}.onnx`;

      const exists = await RNFS.exists(modelFile);

      if (!exists) {
        console.log('[ONNX] Copying model from assets...');

        console.log('[ONNX] metadata.modelPath =', metadata.modelPath);
        
        await RNFS.copyFileAssets(
          metadata.modelPath,
          modelFile,
        );

        console.log('[ONNX] Model copied to:', modelFile);
      } else {
        console.log('[ONNX] Model already exists:', modelFile);
      }

      console.log('[ONNX] Loading model:', modelFile);

      this.session = await InferenceSession.create(modelFile, {
        executionProviders: ['cpu'],
        graphOptimizationLevel: 'all',
      });

      this.metadata = metadata;

      return {
        isLoaded: true,
        loadTimeMs: Date.now() - start,
      };
    } catch (err: any) {
      console.log('[ONNX] ERROR:', err);

      this.session = null;
      this.metadata = null;

      return {
        isLoaded: false,
        error: err?.message ?? String(err),
      };
    }
  }

  isReady(): boolean {
    return this.session !== null;
  }

  async runInference(inputTensor: Float32Array): Promise<Float32Array> {
    if (!this.session || !this.metadata) {
      throw new Error('ONNXModelLoader: model not loaded. Call load() first.');
    }

    const inputSpec = this.metadata.inputTensors[0];
    const inputName = inputSpec.name;
    const outputSpec = this.metadata.outputTensors[0];

    const feeds: Record<string, Tensor> = {
      [inputName]: new Tensor('float32', inputTensor, inputSpec.shape),
    };

    const results = await this.session.run(feeds, [outputSpec.name]);
    const outputTensor = results[outputSpec.name];
    return outputTensor.data as Float32Array;
  }

  getMetadata(): ModelMetadata | null {
    return this.metadata;
  }

  async unload(): Promise<void> {
    if (this.session) {
      await this.session.release();
    }
    this.session = null;
    this.metadata = null;
  }
}
