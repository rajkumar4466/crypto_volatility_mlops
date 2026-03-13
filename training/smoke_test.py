"""
ONNX post-export validator.

Provides smoke_test_onnx() to verify a freshly exported ONNX model before it
propagates downstream (S3 upload, promotion gate, Lambda serving).

Failures raise AssertionError — never return False silently so callers always
see failures as exceptions.
"""

import sys

import numpy as np
import onnxruntime as rt


def smoke_test_onnx(model_path: str, n_features: int = 12) -> bool:
    """Load the ONNX model at model_path and run a single inference to verify output shape.

    Args:
        model_path: Filesystem path to the .onnx file.
        n_features: Expected number of input features (default 12 for btc_features view).

    Returns:
        True if all assertions pass.

    Raises:
        AssertionError: If any output shape or class key assertion fails — never returns False.
    """
    sess = rt.InferenceSession(model_path)

    sample = np.zeros((1, n_features), dtype=np.float32)
    input_name = sess.get_inputs()[0].name

    outputs = sess.run(None, {input_name: sample})

    # outputs[0]: predicted class labels, shape must be (1,)
    assert outputs[0].shape == (1,), (
        f"Unexpected label output shape: expected (1,), got {outputs[0].shape}"
    )

    # outputs[1]: list of probability dicts, one dict per sample
    assert isinstance(outputs[1], list) and len(outputs[1]) == 1, (
        f"Expected outputs[1] to be a list of length 1, got: {type(outputs[1])} len={len(outputs[1]) if isinstance(outputs[1], list) else 'N/A'}"
    )

    # Both class keys (0=CALM, 1=VOLATILE) must be present
    assert 0 in outputs[1][0] and 1 in outputs[1][0], (
        f"Missing class keys in probability dict; got keys: {list(outputs[1][0].keys())}"
    )

    return True


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python smoke_test.py <model_path>")
        sys.exit(1)

    model_path = sys.argv[1]
    try:
        result = smoke_test_onnx(model_path)
        print(f"Smoke test PASSED: {model_path}")
        sys.exit(0)
    except AssertionError as exc:
        print(f"Smoke test FAILED: {exc}")
        sys.exit(1)
