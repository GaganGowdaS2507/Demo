"""
=============================================================================
reference_pipeline.py
=============================================================================
Laptop-side reference implementation of the SAME crop -> align -> resize ->
normalize -> infer -> L2-normalize -> cosine-similarity pipeline used by the
mobile app (see src/core/processing/ImageProcessor.ts, EmbeddingUtils.ts,
SimilarityCalculator.ts).

Purpose: run this script on a laptop against the exact same model file and
test images used on-device, and diff the resulting embeddings/similarity
scores against what the app reports (visible in the Enrollment / Recognition
Test debug panels). If the numbers match closely (allowing for small
floating-point differences between runtimes), you have verified that the
mobile pipeline is mathematically faithful to the reference — which is the
whole point of this benchmarking project: whichever model you eventually
ship, its behavior on-device must match what you validated offline.

Usage:
    pip install opencv-python numpy onnxruntime tflite-runtime mediapipe

    python reference_pipeline.py \
        --image path/to/face.jpg \
        --model path/to/mobilefacenet.tflite \
        --runtime tflite \
        --input-size 112 \
        --normalization neg_one_to_one \
        --layout NHWC

    python reference_pipeline.py \
        --image path/to/face.jpg \
        --model path/to/arcface_r100.onnx \
        --runtime onnx \
        --input-size 112 \
        --normalization neg_one_to_one \
        --layout NCHW

This script intentionally mirrors ImageProcessor.ts step-for-step, including
comments cross-referencing the corresponding TypeScript function, so anyone
auditing parity can read the two side by side.
=============================================================================
"""
import argparse
import time

import cv2
import numpy as np


def detect_face_bbox(image_bgr: np.ndarray):
    """
    Minimal Haar-cascade based face detection, used ONLY as a fallback when
    MediaPipe/ML Kit-equivalent detection isn't available on the laptop.
    For rigorous parity testing, prefer supplying the SAME bounding box the
    app detected (read it off the Enrollment screen's debug panel) via
    --bbox x,y,w,h instead of relying on this fallback detector, since ML
    Kit and Haar cascades will not produce identical boxes.
    """
    cascade = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
    gray = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2GRAY)
    faces = cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5)
    if len(faces) == 0:
        raise ValueError("No face detected by fallback Haar cascade. Supply --bbox explicitly.")
    # Largest face, matching ImageProcessor.ts / EnrollmentScreen.tsx "largest face" convention.
    x, y, w, h = max(faces, key=lambda f: f[2] * f[3])
    return x, y, w, h


def crop_with_margin(image_bgr: np.ndarray, bbox, margin_fraction: float):
    """Mirrors computeCropBox() in ImageProcessor.ts."""
    x, y, w, h = bbox
    img_h, img_w = image_bgr.shape[:2]
    margin_x = w * margin_fraction
    margin_y = h * margin_fraction

    crop_x = max(0, int(x - margin_x))
    crop_y = max(0, int(y - margin_y))
    crop_w = min(img_w - crop_x, int(w + margin_x * 2))
    crop_h = min(img_h - crop_y, int(h + margin_y * 2))

    return image_bgr[crop_y:crop_y + crop_h, crop_x:crop_x + crop_w]


def resize_square(image_bgr: np.ndarray, size: int):
    """Mirrors the ImageResizer.createResizedImage(..., mode: 'stretch') step."""
    return cv2.resize(image_bgr, (size, size), interpolation=cv2.INTER_LINEAR)


def normalize(image_bgr: np.ndarray, scheme: str, channel_order: str, layout: str):
    """Mirrors normalizeValue() + buildTensor() in ImageProcessor.ts."""
    image_rgb = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2RGB).astype(np.float32)

    if channel_order == "BGR":
        image_rgb = image_rgb[:, :, ::-1]

    if scheme == "zero_to_one":
        tensor = image_rgb / 255.0
    elif scheme == "neg_one_to_one":
        tensor = image_rgb / 127.5 - 1.0
    elif scheme == "imagenet_mean_std":
        mean = np.array([0.485, 0.456, 0.406], dtype=np.float32)
        std = np.array([0.229, 0.224, 0.225], dtype=np.float32)
        tensor = (image_rgb / 255.0 - mean) / std
    elif scheme == "raw_uint8":
        tensor = image_rgb
    else:
        raise ValueError(f"Unknown normalization scheme: {scheme}")

    if layout == "NCHW":
        tensor = np.transpose(tensor, (2, 0, 1))  # HWC -> CHW

    return np.expand_dims(tensor, axis=0).astype(np.float32)  # add batch dim


def l2_normalize(vector: np.ndarray) -> np.ndarray:
    """Mirrors l2Normalize() in EmbeddingUtils.ts."""
    norm = np.linalg.norm(vector)
    if norm == 0:
        return vector
    return vector / norm


def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """Mirrors cosineSimilarity() in SimilarityCalculator.ts."""
    denom = (np.linalg.norm(a) * np.linalg.norm(b))
    if denom == 0:
        return 0.0
    return float(np.dot(a, b) / denom)


def run_tflite(model_path: str, tensor: np.ndarray) -> np.ndarray:
    import tflite_runtime.interpreter as tflite

    interpreter = tflite.Interpreter(model_path=model_path)
    interpreter.allocate_tensors()
    input_details = interpreter.get_input_details()
    output_details = interpreter.get_output_details()

    interpreter.set_tensor(input_details[0]["index"], tensor)
    interpreter.invoke()
    return interpreter.get_tensor(output_details[0]["index"])[0]


def run_onnx(model_path: str, tensor: np.ndarray) -> np.ndarray:
    import onnxruntime as ort

    session = ort.InferenceSession(model_path, providers=["CPUExecutionProvider"])
    input_name = session.get_inputs()[0].name
    output_name = session.get_outputs()[0].name
    result = session.run([output_name], {input_name: tensor})
    return result[0][0]


def main():
    parser = argparse.ArgumentParser(description="Reference face embedding pipeline.")
    parser.add_argument("--image", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--runtime", choices=["tflite", "onnx"], required=True)
    parser.add_argument("--input-size", type=int, required=True)
    parser.add_argument(
        "--normalization",
        choices=["zero_to_one", "neg_one_to_one", "imagenet_mean_std", "raw_uint8"],
        required=True,
    )
    parser.add_argument("--layout", choices=["NHWC", "NCHW"], default="NHWC")
    parser.add_argument("--channel-order", choices=["RGB", "BGR"], default="RGB")
    parser.add_argument("--margin", type=float, default=0.15)
    parser.add_argument("--bbox", help="Optional explicit x,y,w,h to bypass fallback detection.")
    parser.add_argument("--l2-normalize", action="store_true", default=True)
    args = parser.parse_args()

    image_bgr = cv2.imread(args.image)
    if image_bgr is None:
        raise FileNotFoundError(f"Could not read image: {args.image}")

    if args.bbox:
        bbox = tuple(int(v) for v in args.bbox.split(","))
    else:
        bbox = detect_face_bbox(image_bgr)

    t0 = time.time()
    cropped = crop_with_margin(image_bgr, bbox, args.margin)
    resized = resize_square(cropped, args.input_size)
    tensor = normalize(resized, args.normalization, args.channel_order, args.layout)
    preprocess_ms = (time.time() - t0) * 1000

    t1 = time.time()
    if args.runtime == "tflite":
        raw_embedding = run_tflite(args.model, tensor)
    else:
        raw_embedding = run_onnx(args.model, tensor)
    inference_ms = (time.time() - t1) * 1000

    embedding = l2_normalize(raw_embedding) if args.l2_normalize else raw_embedding

    print(f"Preprocessing time: {preprocess_ms:.2f} ms")
    print(f"Inference time:     {inference_ms:.2f} ms")
    print(f"Embedding dim:      {embedding.shape[0]}")
    print(f"Embedding norm:     {np.linalg.norm(embedding):.6f}")
    print(f"First 8 values:     {np.round(embedding[:8], 6).tolist()}")
    print()
    print("Compare these values against the on-device debug panel for the same")
    print("image/model to validate cross-platform pipeline parity.")


if __name__ == "__main__":
    main()
