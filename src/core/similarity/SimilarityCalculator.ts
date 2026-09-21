/**
 * =============================================================================
 * SimilarityCalculator
 * =============================================================================
 * Cosine similarity between two embeddings, plus threshold evaluation for
 * display in the Recognition Test screen. Pure math, no native dependencies —
 * mirrors EmbeddingUtils in being independently unit-testable and portable to
 * the laptop-side reference pipeline for parity validation.
 * =============================================================================
 */
import type { ISimilarityCalculator, SimilarityResult } from '../types';

export class SimilarityCalculator implements ISimilarityCalculator {
  cosineSimilarity(a: Float32Array, b: Float32Array): number {
    if (a.length !== b.length) {
      throw new Error(
        `SimilarityCalculator: dimension mismatch (${a.length} vs ${b.length}). ` +
          `Embeddings from different models must never be compared directly.`,
      );
    }

    let dot = 0;
    let normA = 0;
    let normB = 0;
    for (let i = 0; i < a.length; i++) {
      dot += a[i] * b[i];
      normA += a[i] * a[i];
      normB += b[i] * b[i];
    }

    if (normA === 0 || normB === 0) return 0;
    return dot / (Math.sqrt(normA) * Math.sqrt(normB));
  }

  evaluate(a: Float32Array, b: Float32Array, threshold: number): SimilarityResult {
    const score = this.cosineSimilarity(a, b);
    // Cosine similarity is naturally in [-1, 1]; map to a 0-100 display scale.
    const confidencePercent = Math.max(0, Math.min(100, ((score + 1) / 2) * 100));

    return {
      score,
      confidencePercent,
      passesThreshold: score >= threshold,
      thresholdUsed: threshold,
    };
  }

  /**
   * Finds the best match for a probe embedding against a gallery of enrolled
   * embeddings. Used by the Recognition Test screen. Returns null if the
   * gallery is empty.
   */
  findBestMatch(
    probe: Float32Array,
    gallery: Array<{ id: string; embedding: Float32Array }>,
    threshold: number,
  ): { id: string; result: SimilarityResult } | null {
    let best: { id: string; result: SimilarityResult } | null = null;

    for (const entry of gallery) {
      const result = this.evaluate(probe, entry.embedding, threshold);
      if (result.passesThreshold) {
        if (!best || result.score > best.result.score) {
          best = { id: entry.id, result };
        }
      }
    }

    return best;
  }
}

export const similarityCalculator = new SimilarityCalculator();
