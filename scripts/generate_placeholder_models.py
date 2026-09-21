"""
=============================================================================
generate_placeholder_models.py
=============================================================================
Generates the three PLACEHOLDER model files referenced by
src/core/config/ModelCatalog.ts:

    mobilefacenet.tflite   (tflite, input [1,112,112,3], output [1,192])
    facenet_int8.tflite    (tflite, input [1,160,160,3], output [1,128])
    arcface_r100.onnx      (onnx,   input 'data' [1,3,112,112], output 'fc1' [1,512])

IMPORTANT: these are NOT trained face-recognition models. Every weight is
randomly initialized. They exist purely so the app boots, the TFLite/ONNX
runtimes load successfully, and the full pipeline (detect -> crop -> align
-> resize -> normalize -> infer -> L2-normalize -> cosine-similarity) can be
exercised end-to-end without a native crash. Embeddings produced by these
placeholders are meaningless for actual face matching.

To get real recognition accuracy, replace these three files with real
pretrained weights -- see scripts/MODEL_SOURCES.md for exact download and
conversion instructions for each of the three catalog entries.

Usage:
    pip install tensorflow-cpu onnx
    python scripts/generate_placeholder_models.py
=============================================================================
"""
import os

import numpy as np

OUT_DIR = os.path.join(os.path.dirname(__file__), "..", "android", "app", "src", "main", "assets", "models")


def build_tflite_placeholder(out_name: str, input_hw: int, embedding_dim: int, seed: int) -> None:
    import tensorflow as tf

    tf.keras.utils.set_random_seed(seed)
    inputs = tf.keras.Input(shape=(input_hw, input_hw, 3), name="input", dtype=tf.float32)
    x = tf.keras.layers.Conv2D(8, 3, strides=2, padding="same", activation="relu")(inputs)
    x = tf.keras.layers.Conv2D(16, 3, strides=2, padding="same", activation="relu")(x)
    x = tf.keras.layers.GlobalAveragePooling2D()(x)
    outputs = tf.keras.layers.Dense(embedding_dim, name="output")(x)
    model = tf.keras.Model(inputs, outputs)

    converter = tf.lite.TFLiteConverter.from_keras_model(model)
    converter.target_spec.supported_ops = [tf.lite.OpsSet.TFLITE_BUILTINS]
    tflite_model = converter.convert()

    out_path = os.path.join(OUT_DIR, out_name)
    with open(out_path, "wb") as f:
        f.write(tflite_model)

    # sanity-check shapes
    interpreter = tf.lite.Interpreter(model_content=tflite_model)
    interpreter.allocate_tensors()
    inp = interpreter.get_input_details()[0]
    outp = interpreter.get_output_details()[0]
    print(f"[tflite] {out_name}: input {inp['shape']} -> output {outp['shape']}")


def build_onnx_placeholder(out_name: str, seed: int) -> None:
    import onnx
    from onnx import helper, TensorProto, numpy_helper

    rng = np.random.default_rng(seed)

    input_tensor = helper.make_tensor_value_info("data", TensorProto.FLOAT, [1, 3, 112, 112])
    output_tensor = helper.make_tensor_value_info("fc1", TensorProto.FLOAT, [1, 512])

    conv_w = numpy_helper.from_array((rng.standard_normal((8, 3, 3, 3)) * 0.05).astype(np.float32), name="conv_w")
    conv_b = numpy_helper.from_array(np.zeros(8, dtype=np.float32), name="conv_b")
    gemm_w_t = numpy_helper.from_array((rng.standard_normal((8, 512)) * 0.05).astype(np.float32), name="gemm_w_t")
    gemm_b = numpy_helper.from_array(np.zeros(512, dtype=np.float32), name="gemm_b")

    nodes = [
        helper.make_node("Conv", ["data", "conv_w", "conv_b"], ["conv_out"], kernel_shape=[3, 3], strides=[2, 2], pads=[1, 1, 1, 1]),
        helper.make_node("Relu", ["conv_out"], ["relu_out"]),
        helper.make_node("GlobalAveragePool", ["relu_out"], ["gap_out"]),
        helper.make_node("Flatten", ["gap_out"], ["flat_out"], axis=1),
        helper.make_node("Gemm", ["flat_out", "gemm_w_t", "gemm_b"], ["fc1"], alpha=1.0, beta=1.0, transB=0),
    ]

    graph = helper.make_graph(
        nodes, "arcface_r100_placeholder", [input_tensor], [output_tensor],
        initializer=[conv_w, conv_b, gemm_w_t, gemm_b],
    )
    model = helper.make_model(graph, producer_name="placeholder-generator", opset_imports=[helper.make_opsetid("", 13)])
    model.ir_version = 8
    onnx.checker.check_model(model)

    out_path = os.path.join(OUT_DIR, out_name)
    onnx.save(model, out_path)
    print(f"[onnx] {out_name}: input data [1,3,112,112] -> output fc1 [1,512]")


if __name__ == "__main__":
    os.makedirs(OUT_DIR, exist_ok=True)
    build_tflite_placeholder("mobilefacenet.tflite", input_hw=112, embedding_dim=192, seed=1)
    build_tflite_placeholder("facenet_int8.tflite", input_hw=160, embedding_dim=128, seed=2)
    build_onnx_placeholder("arcface_r100.onnx", seed=3)
    print("\nDone. These are PLACEHOLDER weights -- see scripts/MODEL_SOURCES.md for real models.")
