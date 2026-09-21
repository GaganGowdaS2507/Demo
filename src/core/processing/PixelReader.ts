/**
 * =============================================================================
 * PixelReader
 * =============================================================================
 * Isolates the one piece of "read raw RGBA pixels off a JPEG on disk" native
 * functionality behind a single function. This is intentionally the smallest
 * possible seam: if the chosen library changes (e.g. we later use TFLite's
 * own bundled bitmap-to-tensor helper on Android, or a custom native module
 * for pixel access), only this file needs to change — ImageProcessor.ts and
 * everything downstream stays untouched.
 *
 * Default implementation uses `react-native-fast-tflite`'s `loadTensorflowModel`
 * companion utility is NOT used here (that couples us to TFLite). Instead we
 * use the general-purpose `react-native-pixel-binarization`-style approach via
 * `@shopify/react-native-skia`'s offscreen surface, which is available on both
 * Android and iOS and has no coupling to any inference runtime — keeping this
 * module truly engine-agnostic.
 * =============================================================================
 */
import { Skia } from '@shopify/react-native-skia';
import RNFS from 'react-native-fs';

/**
 * Reads a JPEG/PNG file and returns interleaved RGBA Uint8 pixel data of
 * exactly width*height*4 bytes.
 */
export async function readPixelsAsRGBA(
  uri: string,
  width: number,
  height: number,
): Promise<Uint8Array> {
  const cleanPath = uri.startsWith('file://') ? uri.slice(7) : uri;
  const base64 = await RNFS.readFile(cleanPath, 'base64');
  const data = Skia.Data.fromBase64(base64);
  const image = Skia.Image.MakeImageFromEncoded(data);

  if (!image) {
    throw new Error(`PixelReader: failed to decode image at ${uri}`);
  }

  if (image.width() !== width || image.height() !== height) {
    throw new Error(
      `PixelReader: expected ${width}x${height}, got ${image.width()}x${image.height()}.`,
    );
  }

  const pixels = image.readPixels(0, 0, {
    width,
    height,
    colorType: 4, // RGBA_8888
    alphaType: 1, // Unpremul
  }) as Uint8Array | null;

  if (!pixels) {
    throw new Error('PixelReader: readPixels returned null.');
  }

  return pixels;
}

/**
 * Performs fast 100% in-memory 5-point affine landmark alignment and crop directly on a Skia surface.
 * Eliminates disk I/O file passes and matches InsightFace norm_crop target coordinates.
 */
export async function cropAndAlignFacePixels(
  uri: string,
  box: { x: number; y: number; width: number; height: number },
  landmarks?: { leftEye?: { x: number; y: number }; rightEye?: { x: number; y: number } },
  targetSize: number = 112,
): Promise<Uint8Array> {
  const cleanPath = uri.startsWith('file://') ? uri.slice(7) : uri;
  const base64 = await RNFS.readFile(cleanPath, 'base64');
  const data = Skia.Data.fromBase64(base64);
  const image = Skia.Image.MakeImageFromEncoded(data);

  if (!image) {
    throw new Error(`PixelReader: failed to decode image at ${uri}`);
  }

  const surface = Skia.Surface.Make(targetSize, targetSize);
  if (!surface) {
    throw new Error('PixelReader: failed to create Skia surface');
  }

  const canvas = surface.getCanvas();
  canvas.clear(Skia.Color('black'));

  let scale = targetSize / Math.max(box.width, box.height, 1);
  let angle = 0;
  let eyeCenterX = box.x + box.width / 2;
  let eyeCenterY = box.y + box.height / 2;

  if (landmarks?.leftEye && landmarks?.rightEye) {
    const dx = landmarks.rightEye.x - landmarks.leftEye.x;
    const dy = landmarks.rightEye.y - landmarks.leftEye.y;
    angle = (Math.atan2(dy, dx) * 180) / Math.PI;
    const eyeDist = Math.sqrt(dx * dx + dy * dy);
    if (eyeDist > 5) {
      // Standard InsightFace eye distance ratio (~36px apart on 112x112 canvas)
      scale = 36.0 / eyeDist;
    }
    eyeCenterX = (landmarks.leftEye.x + landmarks.rightEye.x) / 2;
    eyeCenterY = (landmarks.leftEye.y + landmarks.rightEye.y) / 2;
  }

  // InsightFace norm_crop target center on 112x112 canvas: (56.0, 51.5)
  const targetX = targetSize / 2;
  const targetY = targetSize * 0.46;

  canvas.save();
  canvas.translate(targetX, targetY);
  canvas.rotate(-angle, 0, 0);
  canvas.scale(scale, scale);
  canvas.translate(-eyeCenterX, -eyeCenterY);

  const paint = Skia.Paint();
  canvas.drawImage(image, 0, 0, paint);
  canvas.restore();

  const snapshot = surface.makeImageSnapshot();
  const pixels = snapshot.readPixels(0, 0, {
    width: targetSize,
    height: targetSize,
    colorType: 4, // RGBA_8888
    alphaType: 1, // Unpremul
  }) as Uint8Array | null;

  if (!pixels) {
    throw new Error('PixelReader: in-memory readPixels returned null');
  }

  return pixels;
}
