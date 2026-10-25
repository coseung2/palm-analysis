"""Draw locally traced palm lines on photos for offline inspection (no upload, no storage).

Usage: python scripts/trace_lines.py OUT_DIR PHOTO [PHOTO ...] [--model CHECKPOINT]
"""
import argparse
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from palm_backend.line_tracer import ORDER, trace_palm  # noqa: E402

COLORS = {'life': (230, 40, 40), 'head': (30, 160, 30), 'heart': (40, 70, 235),
          'fate': (200, 40, 220), 'sun': (255, 140, 0), 'obstacle': (0, 170, 200), 'marriage': (230, 60, 140)}
LABELS = {'life': '생명선', 'head': '두뇌선', 'heart': '감정선', 'fate': '운명선', 'sun': '태양선',
          'obstacle': '장해선', 'marriage': '결혼선'}


def font(size):
    for name in ('malgun.ttf', 'NanumGothic.ttf', 'AppleSDGothicNeo.ttc'):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def draw(photo, trace):
    scale = 900 / max(photo.size)
    view = photo.resize((round(photo.width * scale), round(photo.height * scale)), Image.LANCZOS)
    canvas = Image.new('RGB', (view.width + 220, view.height), 'white')
    canvas.paste(view, (0, 0))
    d = ImageDraw.Draw(canvas)
    big = font(22)
    y = 30
    for name in ORDER:
        line = trace.lines.get(name) if trace else None
        visible = bool(line and line.visible)
        if visible:
            d.line([(x * view.width, yy * view.height) for x, yy in line.points],
                   fill=COLORS[name], width=6, joint='curve')
        mark = '' if visible else ' (미검출)'
        d.text((view.width + 16, y), f'{LABELS[name]}{mark}', fill=COLORS[name] if visible else (150, 150, 150), font=big)
        y += 36
    for name, group in (trace.minor.items() if trace else ()):
        for line in group:
            d.line([(x * view.width, yy * view.height) for x, yy in line.points],
                   fill=COLORS[name], width=4, joint='curve')
        label = f'{LABELS[name]} {len(group)}개' if group else f'{LABELS[name]} (미검출)'
        d.text((view.width + 16, y), label, fill=COLORS[name] if group else (150, 150, 150), font=big)
        y += 36
    if trace is None:
        d.text((view.width + 16, y), '손 인식 실패', fill=(0, 0, 0), font=big)
    return canvas


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('out')
    parser.add_argument('photos', nargs='+')
    parser.add_argument('--model')
    args = parser.parse_args()
    evidence = None
    if args.model:
        from palm_training.line_model import load_evidence_model
        evidence = load_evidence_model(args.model)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    for path in args.photos:
        with Image.open(path) as source:
            photo = ImageOps.exif_transpose(source).convert('RGB')
        trace = trace_palm(photo, evidence_model=evidence)
        draw(photo, trace).save(out / f'{Path(path).stem}_lines.jpg', quality=92)
        summary = ({n: (line.visible, line.length, line.support) for n, line in trace.lines.items()}
                   if trace else None)
        print(Path(path).name, summary)


if __name__ == '__main__':
    main()
