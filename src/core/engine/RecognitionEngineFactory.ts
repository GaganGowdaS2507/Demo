/**
 * =============================================================================
 * RecognitionEngineFactory
 * =============================================================================
 * Builds a ready-to-use IRecognitionEngine for a given ModelMetadata entry
 * from the model catalog (see core/config/ModelCatalog.ts). This is the
 * single switchboard for "which model is currently under test" — Settings
 * and Model Info screens call this when the user picks a different model.
 * =============================================================================
 */
import type { IRecognitionEngine, ModelMetadata } from '../types';
import { createModelLoader } from '../models/ModelLoaderFactory';
import { RecognitionEngine } from './RecognitionEngine';

export async function createRecognitionEngine(
  metadata: ModelMetadata,
): Promise<{ engine: IRecognitionEngine; status: Awaited<ReturnType<IRecognitionEngine['initialize']>> }> {
  const loader = createModelLoader(metadata.runtime);
  const engine = new RecognitionEngine(loader);
  const status = await engine.initialize(metadata);
  return { engine, status };
}
