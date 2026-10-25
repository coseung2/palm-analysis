"""Train the canonical-palm line segmenter on pseudo-labels from `pseudolabel.build_plsu`.

This is an experiment on machine-assigned line classes, not the reviewed-manifest pipeline in
`cli.py`; its checkpoints are inspection evidence for the tracer and are never activated by the
server. Augmentation deliberately degrades the clean PLSU studio photos (white background,
1600x1200) towards small, noisy phone photos with textured backgrounds.

    python -m palm_training.train_lines --data data/training/plsu_lines --output data/training/runs/lines-01
"""
import argparse
import hashlib
import json
import math
import time
from pathlib import Path

import numpy as np

from .line_model import IMAGENET_MEAN, IMAGENET_STD


def _split(sample_id, val_fraction=.1):
    return 'val' if int(hashlib.sha256(sample_id.encode()).hexdigest(), 16) % 1000 < val_fraction * 1000 else 'train'


def _background(shape, rng):
    import cv2

    h, w = shape
    noise = rng.random((h // 8 + 1, w // 8 + 1, 3)).astype(np.float32)
    texture = cv2.resize(noise, (w, h), interpolation=cv2.INTER_CUBIC)
    if rng.random() < .5:  # streaky wood/fabric-like texture
        texture = cv2.GaussianBlur(texture, (0, 0), sigmaX=1 + 6 * rng.random(), sigmaY=.5)
    base = rng.uniform(.2, .9, 3).astype(np.float32)
    return np.clip(base + (texture - .5) * rng.uniform(.05, .35), 0, 1)


def degrade(image, labels, rng, size):
    """image float32 HxWx3 in [0,1]; labels uint8 CxHxW. Returns augmented copies at `size`."""
    import cv2

    h, w = image.shape[:2]
    # Studio white background -> random texture, so the model never relies on a clean border.
    if rng.random() < .8:
        hsv = cv2.cvtColor((image * 255).astype(np.uint8), cv2.COLOR_RGB2HSV)
        backdrop = (hsv[..., 2] > 215) & (hsv[..., 1] < 30)
        backdrop = cv2.GaussianBlur(backdrop.astype(np.float32), (0, 0), 2)[..., None]
        image = image * (1 - backdrop) + _background((h, w), rng) * backdrop
    angle, scale = rng.uniform(-10, 10), rng.uniform(.88, 1.12)
    m = cv2.getRotationMatrix2D((w / 2, h / 2), angle, scale)
    m[:, 2] += rng.uniform(-.04, .04, 2) * (w, h)
    image = cv2.warpAffine(image, m, (w, h), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)
    labels = np.stack([cv2.warpAffine(c, m, (w, h), flags=cv2.INTER_NEAREST) for c in labels])
    # Photometric: exposure, white balance, saturation, gamma.
    image = image * rng.uniform(.6, 1.3) * rng.uniform(.85, 1.15, 3)
    gray = image.mean(2, keepdims=True)
    image = np.clip(gray + (image - gray) * rng.uniform(.5, 1.5), 0, 1) ** rng.uniform(.7, 1.4)
    if rng.random() < .5:  # soft shading gradient across the palm
        yy, xx = np.mgrid[0:h, 0:w] / max(h, w)
        direction = rng.normal(size=2)
        ramp = (xx * direction[0] + yy * direction[1])
        ramp = (ramp - ramp.min()) / max(np.ptp(ramp), 1e-6)
        image = image * (1 - rng.uniform(0, .45) * ramp[..., None])
    # Resolution loss: phone photos often give a palm only 100-200 px wide.
    factor = rng.uniform(.18, 1.0) if rng.random() < .85 else 1.0
    if factor < 1:
        small = cv2.resize(image, (max(32, int(w * factor)), max(32, int(h * factor))),
                           interpolation=cv2.INTER_AREA)
        image = cv2.resize(small, (w, h), interpolation=cv2.INTER_CUBIC if rng.random() < .5 else cv2.INTER_LINEAR)
    if rng.random() < .4:
        image = cv2.GaussianBlur(image, (0, 0), rng.uniform(.3, 1.6))
    image = np.clip(image + rng.normal(0, rng.uniform(0, .04), image.shape), 0, 1).astype(np.float32)
    if rng.random() < .6:
        ok, buffer = cv2.imencode('.jpg', cv2.cvtColor((image * 255).astype(np.uint8), cv2.COLOR_RGB2BGR),
                                  [cv2.IMWRITE_JPEG_QUALITY, int(rng.uniform(25, 95))])
        image = cv2.cvtColor(cv2.imdecode(buffer, cv2.IMREAD_COLOR), cv2.COLOR_BGR2RGB).astype(np.float32) / 255
    if size != w:
        image = cv2.resize(image, (size, size), interpolation=cv2.INTER_AREA)
        labels = np.stack([cv2.resize(c, (size, size), interpolation=cv2.INTER_NEAREST) for c in labels])
    return image, labels


class LineDataset:
    def __init__(self, root, ids, size, augment, seed=0):
        self.root, self.ids, self.size, self.augment = Path(root), ids, size, augment
        self.rng = np.random.default_rng(seed)

    def __len__(self):
        return len(self.ids)

    def __getitem__(self, index):
        import cv2
        import torch

        sample = self.ids[index]
        image = cv2.cvtColor(cv2.imread(str(self.root / 'samples' / f'{sample}.jpg')), cv2.COLOR_BGR2RGB)
        image = image.astype(np.float32) / 255
        packed = np.load(self.root / 'samples' / f'{sample}.npz')
        labels = np.unpackbits(packed['labels'], axis=-1)[..., :image.shape[1]]
        known = packed['known']
        if self.augment:
            image, labels = degrade(image, labels, self.rng, self.size)
        elif self.size != image.shape[0]:
            image = cv2.resize(image, (self.size, self.size), interpolation=cv2.INTER_AREA)
            labels = np.stack([cv2.resize(c, (self.size, self.size), interpolation=cv2.INTER_NEAREST)
                               for c in labels])
        x = ((image - IMAGENET_MEAN) / IMAGENET_STD).transpose(2, 0, 1)
        return (torch.from_numpy(np.ascontiguousarray(x)).float(),
                torch.from_numpy(labels.astype(np.float32)), torch.from_numpy(known.astype(bool)))


def _worker_init(worker_id):
    import torch

    info = torch.utils.data.get_worker_info()
    info.dataset.rng = np.random.default_rng(torch.initial_seed() % 2**32 + worker_id)


def train(args):
    import torch
    from torch.utils.data import DataLoader

    from .line_net import build_line_net
    from .network import masked_loss

    torch.manual_seed(args.seed)
    root = Path(args.data)
    index_path = Path(args.index) if args.index else root / 'index.json'
    index = json.loads(index_path.read_text())
    names = tuple(index['channels'])
    ids = [s['id'] for s in index['samples']]
    split = {'train': [i for i in ids if _split(i) == 'train'], 'val': [i for i in ids if _split(i) == 'val']}
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=False)
    data_digest = hashlib.sha256(index_path.read_bytes()).hexdigest()
    run = {'names': names, 'size': args.size, 'epochs': args.epochs, 'batch_size': args.batch_size,
           'learning_rate': args.learning_rate, 'seed': args.seed, 'index_sha256': data_digest,
           'train': len(split['train']), 'val': len(split['val']), 'encoder': 'mit_b0 (imagenet)',
           'labels': 'pseudo-labels: reviewed binary creases, machine-assigned line classes'}
    (output / 'run.json').write_text(json.dumps(run, indent=2))
    model = build_line_net(len(names)).to(args.device)
    optimizer = torch.optim.AdamW(model.parameters(), lr=args.learning_rate, weight_decay=1e-4)
    steps = args.epochs * math.ceil(len(split['train']) / args.batch_size)
    schedule = torch.optim.lr_scheduler.OneCycleLR(optimizer, args.learning_rate, total_steps=steps,
                                                   pct_start=.08)
    scaler = torch.amp.GradScaler(enabled=args.device == 'cuda')
    loaders = {
        'train': DataLoader(LineDataset(root, split['train'], args.size, True, args.seed), args.batch_size,
                            shuffle=True, num_workers=args.workers, drop_last=True,
                            worker_init_fn=_worker_init, persistent_workers=args.workers > 0),
        'val': DataLoader(LineDataset(root, split['val'], args.size, False), args.batch_size,
                          num_workers=args.workers),
    }
    history, best = [], math.inf
    for epoch in range(args.epochs):
        started = time.time()
        model.train()
        total = 0.0
        for x, y, known in loaders['train']:
            x, y, known = x.to(args.device), y.to(args.device), known.to(args.device)
            with torch.autocast(args.device, enabled=args.device == 'cuda'):
                logits = model(x)
            loss = masked_loss(logits.float(), y, known)
            optimizer.zero_grad(set_to_none=True)
            scaler.scale(loss).backward()
            scaler.step(optimizer)
            scaler.update()
            schedule.step()
            total += float(loss) * len(x)
        model.eval()
        val, count = 0.0, 0
        with torch.inference_mode():
            for x, y, known in loaders['val']:
                logits = model(x.to(args.device)).float()
                val += float(masked_loss(logits, y.to(args.device), known.to(args.device))) * len(x)
                count += len(x)
        row = {'epoch': epoch + 1, 'train_loss': total / len(loaders['train'].dataset),
               'val_loss': val / max(count, 1), 'seconds': round(time.time() - started, 1)}
        history.append(row)
        print(json.dumps(row), flush=True)
        if row['val_loss'] < best:
            best = row['val_loss']
            torch.save({'model': model.state_dict(), 'names': list(names), 'size': args.size,
                        'epoch': epoch + 1}, output / 'lines.pt')
        (output / 'history.json').write_text(json.dumps(history, indent=1))


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('--data', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--index', help='alternative index.json (default: DATA/index.json)')
    parser.add_argument('--device', default='cuda')
    parser.add_argument('--epochs', type=int, default=60)
    parser.add_argument('--batch-size', type=int, default=8)
    parser.add_argument('--learning-rate', type=float, default=6e-4)
    parser.add_argument('--size', type=int, default=512)
    parser.add_argument('--workers', type=int, default=6)
    parser.add_argument('--seed', type=int, default=42)
    args = parser.parse_args(argv)
    if args.device == 'cuda':
        import torch
        if not torch.cuda.is_available():
            raise SystemExit('CUDA requested but unavailable')
    train(args)


if __name__ == '__main__':
    main()
