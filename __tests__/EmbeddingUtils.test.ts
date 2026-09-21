import {
  l2Normalize,
  l2Norm,
  isValidEmbedding,
  embeddingToArray,
  arrayToEmbedding,
} from '../src/core/embedding/EmbeddingUtils';

describe('EmbeddingUtils', () => {
  test('l2Normalize produces a unit-norm vector', () => {
    const v = new Float32Array([3, 4]); // norm = 5
    const normalized = l2Normalize(v);
    expect(normalized[0]).toBeCloseTo(0.6, 5);
    expect(normalized[1]).toBeCloseTo(0.8, 5);
    expect(l2Norm(normalized)).toBeCloseTo(1.0, 5);
  });

  test('l2Normalize handles zero vector without throwing', () => {
    const v = new Float32Array([0, 0, 0]);
    const normalized = l2Normalize(v);
    expect(Array.from(normalized)).toEqual([0, 0, 0]);
  });

  test('isValidEmbedding rejects wrong dimension', () => {
    const v = new Float32Array([1, 2, 3]);
    expect(isValidEmbedding(v, 3)).toBe(true);
    expect(isValidEmbedding(v, 4)).toBe(false);
  });

  test('isValidEmbedding rejects NaN/Infinity', () => {
    const v = new Float32Array([1, NaN, 3]);
    expect(isValidEmbedding(v, 3)).toBe(false);
    const v2 = new Float32Array([1, Infinity, 3]);
    expect(isValidEmbedding(v2, 3)).toBe(false);
  });

  test('array <-> Float32Array round-trip preserves values', () => {
    const original = new Float32Array([0.1, 0.2, 0.3]);
    const arr = embeddingToArray(original);
    const back = arrayToEmbedding(arr);
    expect(Array.from(back).map((n) => Number(n.toFixed(5)))).toEqual(
      Array.from(original).map((n) => Number(n.toFixed(5))),
    );
  });
});
