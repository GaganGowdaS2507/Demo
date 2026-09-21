/**
 * =============================================================================
 * EmbeddingUtils
 * =============================================================================
 * Pure, stateless math on embedding vectors. Deliberately has zero
 * dependencies on React Native or any native module so it can be unit tested
 * in plain Node, and so the exact same logic can be ported to a Python/Node
 * "laptop-side" validation script for cross-platform parity checks (see
 * scripts/reference_pipeline.py in the README).
 * =============================================================================
 */

/** L2-normalizes a vector in place-safe (returns a new array) fashion. */
export function l2Normalize(vector: Float32Array): Float32Array {
  let sumSquares = 0;
  for (let i = 0; i < vector.length; i++) {
    sumSquares += vector[i] * vector[i];
  }
  const norm = Math.sqrt(sumSquares);

  if (norm === 0) {
    // Degenerate embedding (all zeros) — return as-is rather than dividing by zero.
    return new Float32Array(vector);
  }

  const normalized = new Float32Array(vector.length);
  for (let i = 0; i < vector.length; i++) {
    normalized[i] = vector[i] / norm;
  }
  return normalized;
}

/** Returns the L2 norm (magnitude) of a vector — useful for debugging whether a model's raw output is already unit-normalized. */
export function l2Norm(vector: Float32Array): number {
  let sumSquares = 0;
  for (let i = 0; i < vector.length; i++) {
    sumSquares += vector[i] * vector[i];
  }
  return Math.sqrt(sumSquares);
}

/** Converts a Float32Array to a plain number[] for JSON/SQLite storage. */
export function embeddingToArray(embedding: Float32Array): number[] {
  return Array.from(embedding);
}

/** Converts a stored plain number[] back into a Float32Array for computation. */
export function arrayToEmbedding(arr: number[]): Float32Array {
  return new Float32Array(arr);
}

/** Basic sanity check used before persisting/comparing an embedding. */
export function isValidEmbedding(vector: Float32Array, expectedDimension: number): boolean {
  if (vector.length !== expectedDimension) return false;
  for (let i = 0; i < vector.length; i++) {
    if (!Number.isFinite(vector[i])) return false;
  }
  return true;
}
