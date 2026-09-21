import { SimilarityCalculator } from '../src/core/similarity/SimilarityCalculator';

describe('SimilarityCalculator', () => {
  const calc = new SimilarityCalculator();

  test('identical vectors have cosine similarity 1', () => {
    const v = new Float32Array([1, 2, 3]);
    expect(calc.cosineSimilarity(v, v)).toBeCloseTo(1.0, 5);
  });

  test('orthogonal vectors have cosine similarity 0', () => {
    const a = new Float32Array([1, 0]);
    const b = new Float32Array([0, 1]);
    expect(calc.cosineSimilarity(a, b)).toBeCloseTo(0, 5);
  });

  test('opposite vectors have cosine similarity -1', () => {
    const a = new Float32Array([1, 0]);
    const b = new Float32Array([-1, 0]);
    expect(calc.cosineSimilarity(a, b)).toBeCloseTo(-1, 5);
  });

  test('throws on dimension mismatch to prevent cross-model comparison bugs', () => {
    const a = new Float32Array([1, 2, 3]);
    const b = new Float32Array([1, 2]);
    expect(() => calc.cosineSimilarity(a, b)).toThrow();
  });

  test('evaluate() correctly applies threshold', () => {
    const a = new Float32Array([1, 0]);
    const b = new Float32Array([1, 0]);
    const result = calc.evaluate(a, b, 0.9);
    expect(result.passesThreshold).toBe(true);
    expect(result.score).toBeCloseTo(1.0, 5);
    expect(result.confidencePercent).toBeCloseTo(100, 1);
  });

  test('findBestMatch returns the highest-scoring gallery entry', () => {
    const probe = new Float32Array([1, 0]);
    const gallery = [
      { id: 'a', embedding: new Float32Array([0, 1]) }, // orthogonal -> 0
      { id: 'b', embedding: new Float32Array([1, 0]) }, // identical -> 1
      { id: 'c', embedding: new Float32Array([0.7, 0.7]) }, // ~0.707
    ];
    const best = calc.findBestMatch(probe, gallery, 0.5);
    expect(best?.id).toBe('b');
    expect(best?.result.score).toBeCloseTo(1.0, 5);
  });
});
