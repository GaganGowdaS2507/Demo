/**
 * =============================================================================
 * MLKitFaceDetector
 * =============================================================================
 * Concrete IFaceDetector implementation backed by Google ML Kit's on-device
 * Face Detection API (@react-native-ml-kit/face-detection). ML Kit's face
 * detection model ships with the library and runs fully offline — no network
 * calls, no Firebase project required (this is the on-device API, not the
 * cloud Vision API).
 *
 * This is the ONLY file in the app that imports the ML Kit package. If we
 * ever swap detectors, this is the only file that changes.
 * =============================================================================
 */
import FaceDetection, {
  FaceDetectionOptions,
} from '@react-native-ml-kit/face-detection';
import type {
  DetectedFace,
  FaceDetectionResult,
  IFaceDetector,
  FaceLandmarks,
} from '../types';
import { Image } from 'react-native';

const DETECTION_OPTIONS: FaceDetectionOptions = {
  performanceMode: 'accurate',
  landmarkMode: 'all',
  contourMode: 'none',
  classificationMode: 'all', // eye-open probabilities etc.
  minFaceSize: 0.1,
  trackingEnabled: false,
};

function getImageSize(uri: string): Promise<{ width: number; height: number }> {
  return new Promise((resolve, reject) => {
    Image.getSize(
      uri,
      (width, height) => resolve({ width, height }),
      (error) => reject(error),
    );
  });
}

// /** Maps ML Kit's raw landmark array into our typed FaceLandmarks shape. */
// function mapLandmarks(rawLandmarks: any[] | undefined): FaceLandmarks {
//   const landmarks: FaceLandmarks = {};
//   if (!rawLandmarks) return landmarks;

//   for (const lm of rawLandmarks) {
//     const point = { x: lm.position?.x ?? lm.x, y: lm.position?.y ?? lm.y };
//     switch (lm.type) {
//       case 'leftEye':
//         landmarks.leftEye = point;
//         break;
//       case 'rightEye':
//         landmarks.rightEye = point;
//         break;
//       case 'noseBase':
//         landmarks.noseBase = point;
//         break;
//       case 'mouthLeft':
//         landmarks.leftMouth = point;
//         break;
//       case 'mouthRight':
//         landmarks.rightMouth = point;
//         break;
//       default:
//         break;
//     }
//   }
//   return landmarks;
// }

function mapLandmarks(rawLandmarks: any): FaceLandmarks {
  if (!rawLandmarks) {
    return {};
  }

  return {
    leftEye: rawLandmarks.leftEye?.position,
    rightEye: rawLandmarks.rightEye?.position,
    noseBase: rawLandmarks.noseBase?.position,
    leftMouth: rawLandmarks.mouthLeft?.position,
    rightMouth: rawLandmarks.mouthRight?.position,
  };
}
export class MLKitFaceDetector implements IFaceDetector {
  private initialized = false;

  async initialize(): Promise<void> {
    // ML Kit's on-device model is bundled at build time; there is no explicit
    // async init step required, but we keep this method for interface
    // symmetry and to allow future warm-up logic (e.g. first-run model check).
    this.initialized = true;
  }

  async detectFaces(imageUri: string, options?: FaceDetectionOptions): Promise<FaceDetectionResult> {
    if (!this.initialized) {
      throw new Error('MLKitFaceDetector.initialize() must be called before use.');
    }

    const start = Date.now();
    const opts = options ?? DETECTION_OPTIONS;
    const [rawFaces, imageSize] = await Promise.all([
      FaceDetection.detect(imageUri, opts),
      getImageSize(imageUri),
    ]);
    console.log("RAW FACES =", rawFaces);
    console.log("IS ARRAY =", Array.isArray(rawFaces));
    console.log("TYPE =", typeof rawFaces);
    const detectionTimeMs = Date.now() - start;

    const faces: DetectedFace[] = rawFaces.map((f: any) => ({
      boundingBox: {
          x: f.frame.left,
          y: f.frame.top,
          width: f.frame.width,
          height: f.frame.height,
      },
      landmarks: mapLandmarks(f.landmarks),
      rollAngle: f.rotationZ,
      yawAngle: f.rotationY,
      detectionConfidence: f.trackingID !== undefined ? 1.0 : undefined,
      leftEyeOpenProbability: f.leftEyeOpenProbability,
      rightEyeOpenProbability: f.rightEyeOpenProbability,
    }));

    return {
      faces,
      imageWidth: imageSize.width,
      imageHeight: imageSize.height,
      detectionTimeMs,
    };
  }

  async release(): Promise<void> {
    this.initialized = false;
  }
}

/** Convenience singleton — the app only ever needs one detector instance. */
export const faceDetector = new MLKitFaceDetector();
