/**
 * =============================================================================
 * ImageProcessor
 * =============================================================================
 * The deterministic crop -> align -> resize -> normalize pipeline shared by
 * EVERY recognition engine. This is the most important file for making model
 * comparisons fair: TFLite MobileFaceNet and ONNX ArcFace must receive
 * pixel-for-pixel equivalent input (modulo each model's declared input size
 * and normalization scheme) so that any accuracy difference we measure comes
 * from the model itself, not from inconsistent preprocessing.
 *
 * Steps:
 *   1. Crop a margin-padded box around the detected face.
 *   2. Optionally align by rotating so the eye-line is horizontal (uses
 *      ML Kit eye landmarks).
 *   3. Resize to the model's required square input size.
 *   4. Convert to a flat Float32Array, applying the model's normalization
 *      scheme and channel order/tensor layout.
 *
 * Uses `react-native-image-editor` (crop) + `@bam.tech/react-native-image-resizer`
 * (resize) for native, hardware-accelerated operations, and reads raw RGBA
 * pixels via `react-native-fast-tflite`'s bundled helper OR a small native
 * pixel-reading bridge exposed by `react-native-image-to-tensor` style utils.
 * To keep this module runtime-agnostic we isolate all native pixel access
 * behind readPixelsAsRGBA() so it can be swapped for a different bridge
 * without touching normalization/layout logic below.
 * =============================================================================
 */
import type {
  DetectedFace,
  IImageProcessor,
  PreprocessedFace,
  PreprocessingConfig,
} from '../types';
import { readPixelsAsRGBA, cropAndAlignFacePixels } from './PixelReader';

/** Applies adaptive contrast stretching when low-light environment is detected. */
function applyLowLightEnhancement(rgba: Uint8Array, size: number): Uint8Array {
  let totalLuminance = 0;
  let minL = 255;
  let maxL = 0;

  const totalPixels = size * size;
  for (let i = 0; i < totalPixels; i++) {
    const r = rgba[i * 4];
    const g = rgba[i * 4 + 1];
    const b = rgba[i * 4 + 2];
    const lum = 0.299 * r + 0.587 * g + 0.114 * b;
    totalLuminance += lum;
    if (lum < minL) minL = lum;
    if (lum > maxL) maxL = lum;
  }

  const avgLuminance = totalLuminance / totalPixels;

  if (avgLuminance < 85 && maxL > minL + 10) {
    const enhanced = new Uint8Array(rgba.length);
    const range = maxL - minL;
    const scale = 255.0 / range;

    for (let i = 0; i < totalPixels; i++) {
      const idx = i * 4;
      enhanced[idx] = Math.min(255, Math.max(0, (rgba[idx] - minL) * scale));
      enhanced[idx + 1] = Math.min(255, Math.max(0, (rgba[idx + 1] - minL) * scale));
      enhanced[idx + 2] = Math.min(255, Math.max(0, (rgba[idx + 2] - minL) * scale));
      enhanced[idx + 3] = rgba[idx + 3];
    }
    return enhanced;
  }

  return rgba;
}

/** Applies the configured normalization scheme to a single 0-255 channel value. */
function normalizeValue(
  value: number,
  channelIndex: 0 | 1 | 2,
  config: PreprocessingConfig,
): number {
  const { normalization } = config;
  switch (normalization.scheme) {
    case 'zero_to_one':
      return value / 255.0;
    case 'neg_one_to_one':
      return value / 127.5 - 1.0;
    case 'imagenet_mean_std': {
      const mean = normalization.mean ?? [0.485, 0.456, 0.406];
      const std = normalization.std ?? [0.229, 0.224, 0.225];
      return (value / 255.0 - mean[channelIndex]) / std[channelIndex];
    }
    case 'raw_uint8':
      return value;
    default:
      return value / 255.0;
  }
}

export class ImageProcessor implements IImageProcessor {
  async process(
    imageUri: string,
    face: DetectedFace,
    config: PreprocessingConfig,
  ): Promise<PreprocessedFace> {
    const start = Date.now();

    // Step 1: Fast 100% in-memory 5-point affine crop & alignment matching InsightFace norm_crop
    let rgba: Uint8Array;
    try {
      rgba = await cropAndAlignFacePixels(
        imageUri,
        face.boundingBox,
        face.landmarks,
        config.inputSize,
      );
    } catch (e) {
      console.error('[PROCESS] In-memory cropAndAlign FAILED:', e);
      throw e;
    }

    // Step 2: Adaptive low-light enhancement if dark environment detected
    rgba = applyLowLightEnhancement(rgba, config.inputSize);

    // Step 3: Build normalized model input tensor
    const tensorData = buildTensor(rgba, config);
    const preprocessingTimeMs = Date.now() - start;

    return {
      tensorData,
      shape:
        config.tensorLayout === 'NHWC'
          ? [1, config.inputSize, config.inputSize, 3]
          : [1, 3, config.inputSize, config.inputSize],
      debugCroppedImageUri: imageUri,
      preprocessingTimeMs,
      configUsed: config,
    };
  }
}
/** Converts interleaved RGBA Uint8 pixel data into a normalized, layout-correct Float32Array. */
function buildTensor(rgba: Uint8Array, config: PreprocessingConfig): Float32Array {
  const size = config.inputSize;
  const tensor = new Float32Array(size * size * 3);
  const isNHWC = config.tensorLayout === 'NHWC';

  for (let py = 0; py < size; py++) {
    for (let px = 0; px < size; px++) {
      const srcIdx = (py * size + px) * 4; // RGBA stride
      let r = rgba[srcIdx];
      let g = rgba[srcIdx + 1];
      let b = rgba[srcIdx + 2];

      if (config.channelOrder === 'BGR') {
        [r, b] = [b, r];
      }

      const rN = normalizeValue(r, 0, config);
      const gN = normalizeValue(g, 1, config);
      const bN = normalizeValue(b, 2, config);

      if (isNHWC) {
        const dstIdx = (py * size + px) * 3;
        tensor[dstIdx] = rN;
        tensor[dstIdx + 1] = gN;
        tensor[dstIdx + 2] = bN;
      } else {
        // NCHW: channel-major layout
        const plane = size * size;
        const pixelIdx = py * size + px;
        tensor[pixelIdx] = rN;
        tensor[plane + pixelIdx] = gN;
        tensor[plane * 2 + pixelIdx] = bN;
      }
    }
  }

  return tensor;
}

export const imageProcessor = new ImageProcessor();
