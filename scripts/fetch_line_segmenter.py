"""Download the pinned palm-line-reader student model and verify it before use.

Writes data/models/palm-line-reader-<precision>.onnx (gitignored). Point
PALM_LINE_SEGMENTER_PATH at it to enable the auxiliary 3-line overlay.
"""
import argparse
import hashlib
import sys
from pathlib import Path
from urllib.request import urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from palm_backend.line_segmenter import MODEL_SHA256  # noqa: E402

COMMIT = 'bc48939f4deee6d8ff842bfde499396dab9c4830'
SOURCE = 'https://raw.githubusercontent.com/samuelwbarber/palm-line-reader/{commit}/models/student_{precision}.onnx'
EXPECTED = {
    # fp32 runs 2-3x faster than fp16 on CPU onnxruntime (fp16 weights are upcast per run).
    'fp32': '3c02b88b82e54889d0ab2bf2ba108aec554a1b50759f7c7aaa45f2f114ed24ff',
    'fp16': 'e2c9f826676b3aaf0a715f3087fcd4fc0b4dccd8c53de05fd26696a8399f8dd6',
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--precision', choices=sorted(EXPECTED), default='fp32')
    parser.add_argument('--out_dir', default='data/models')
    args = parser.parse_args()
    expected = EXPECTED[args.precision]
    assert expected in MODEL_SHA256
    with urlopen(SOURCE.format(commit=COMMIT, precision=args.precision), timeout=120) as response:
        data = response.read()
    if hashlib.sha256(data).hexdigest() != expected:
        raise SystemExit('Downloaded model does not match the pinned SHA-256; nothing written.')
    target = Path(args.out_dir) / f'palm-line-reader-{args.precision}.onnx'
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix('.part')
    temporary.write_bytes(data)
    temporary.replace(target)
    print(f'verified {len(data)} bytes -> {target}')


if __name__ == '__main__':
    main()
