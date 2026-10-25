"""Reviewed polylines in normalized image coordinates, with unknown labels ignored."""
import hashlib
import io
import json
import math
from collections import Counter
from pathlib import Path

from PIL import Image, ImageDraw, ImageOps

LINES = ('life', 'head', 'heart', 'fate')
SPLITS = ('train', 'val', 'test')
STATES = ('visible', 'not_visible', 'unclear')
MAX_IMAGE_BYTES = 20 * 1024 * 1024
MAX_PIXELS = 16_000_000


def digest_file(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def fingerprint(manifest):
    return hashlib.sha256(json.dumps(manifest, sort_keys=True, separators=(',', ':'),
                                    ensure_ascii=False).encode()).hexdigest()


def image_path(root, relative):
    root = Path(root).resolve()
    if not isinstance(relative, str) or not relative or Path(relative).is_absolute():
        raise ValueError('Image paths must be relative to the private dataset directory')
    path = (root / relative).resolve()
    if not path.is_relative_to(root):
        raise ValueError('Image path escapes the dataset directory')
    return path


def read_image(root, sample):
    path = image_path(root, sample['image'])
    if path.stat().st_size > MAX_IMAGE_BYTES:
        raise ValueError('Training image exceeds byte limit')
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != sample['sha256']:
        raise ValueError('Training image checksum changed')
    with Image.open(io.BytesIO(raw)) as image:
        if image.format not in ('JPEG', 'PNG', 'WEBP') or getattr(image, 'n_frames', 1) != 1:
            raise ValueError('Expected one JPEG, PNG or WebP frame')
        if min(image.size) < 32 or image.width * image.height > MAX_PIXELS:
            raise ValueError('Training image dimensions outside limits')
        # Coordinates refer to the displayed pixels. Rotate BEFORE annotation, never here.
        if image.getexif().get(274, 1) != 1:
            raise ValueError('Normalize EXIF orientation before annotating')
        image.load()
        return image.convert('RGB')


def _text(value):
    return isinstance(value, str) and bool(value.strip()) and len(value) <= 2048


def validate_manifest(path):
    path = Path(path)
    if path.stat().st_size > 32 * 1024 * 1024:
        raise ValueError('Manifest exceeds size limit')
    manifest = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(manifest, dict) or manifest.get('version') != 1 or manifest.get('purpose') not in ('training', 'smoke'):
        raise ValueError('Unsupported manifest version or purpose')
    if manifest.get('coordinate_space') != 'normalized_image':
        raise ValueError('Coordinates must use the complete, EXIF-normalized input image')
    if not isinstance(manifest.get('sources'), list) or not manifest['sources']:
        raise ValueError('Source provenance is required')
    sources = {}
    for source in manifest['sources']:
        if not isinstance(source, dict):
            raise ValueError('Invalid source record')
        if not all(_text(source.get(k)) for k in
                   ('id', 'url', 'license', 'reviewed_by', 'reviewed_at', 'permission_reference')):
            raise ValueError('Each source needs a recorded rights review, not just a license guess')
        if source['id'] in sources or source.get('training_allowed') is not True:
            raise ValueError('Duplicate source or training not authorized')
        if type(source.get('deployment_allowed')) is not bool:
            raise ValueError('Record deployment permission explicitly')
        sources[source['id']] = source
    samples = manifest.get('samples')
    if not isinstance(samples, list) or not samples:
        raise ValueError('Reviewed samples are required')
    identifiers, groups, test_originals, test_pixels = set(), {}, set(), set()
    counts, labels = Counter(), Counter()
    for sample in samples:
        if not isinstance(sample, dict):
            raise ValueError('Invalid sample record')
        if not all(_text(sample.get(k)) for k in
                   ('id', 'person_id', 'original_id', 'image', 'sha256', 'reviewed_by')):
            raise ValueError('Each sample needs provenance, identity grouping and human review')
        if sample['id'] in identifiers:
            raise ValueError('Duplicate sample ID')
        identifiers.add(sample['id'])
        split = sample.get('split')
        if split not in SPLITS or sample.get('source') not in sources:
            raise ValueError('Unknown split or source')
        if sample.get('domain') not in ('booth', 'public'):
            raise ValueError('Record booth or public capture domain')
        if sample['domain'] == 'booth' and not _text(sample.get('consent_reference')):
            raise ValueError('Booth photos need a separate training-consent reference')
        line_labels = sample.get('lines', {})
        if not isinstance(line_labels, dict) or set(line_labels) != set(LINES):
            raise ValueError('All four line states must be reviewed, including missing lines')
        for name in LINES:
            label = line_labels[name]
            if not isinstance(label, dict) or label.get('state') not in STATES:
                raise ValueError('Invalid line state')
            points = label.get('points')
            if not isinstance(points, list):
                raise ValueError('Line points must be an ordered list')
            if label['state'] == 'visible':
                if not 2 <= len(points) <= 256:
                    raise ValueError('Visible lines need 2 to 256 reviewed curve points')
                for point in points:
                    if (not isinstance(point, list) or len(point) != 2
                            or any(type(v) not in (int, float) or not math.isfinite(v)
                                   or not 0 <= v <= 1 for v in point)):
                        raise ValueError('Polyline coordinates must be finite and normalized')
                if len({tuple(point) for point in points}) < 2:
                    raise ValueError('A visible curve must have nonzero length')
            elif points:
                raise ValueError('Unknown or unobserved lines must not have invented points')
            labels[f'{split}:{name}:{label["state"]}'] += 1
        image = read_image(path.parent, sample)
        pixels = hashlib.sha256(str(image.size).encode() + image.tobytes()).hexdigest()
        if split == 'test':
            if sample['original_id'] in test_originals or pixels in test_pixels:
                raise ValueError('Test set must not contain repeated or augmented originals')
            test_originals.add(sample['original_id'])
            test_pixels.add(pixels)
        # person_id is global across sources; both hands and sessions stay in one split.
        for kind, key in (('person', sample['person_id']), ('original', sample['original_id']),
                          ('file', sample['sha256']), ('pixels', pixels)):
            previous = groups.setdefault((kind, key), split)
            if previous != split:
                raise ValueError('Person, original or duplicate image leaks across splits')
        counts[split] += 1
        counts[f'{split}:{sample["domain"]}'] += 1
    return manifest, {'manifest_sha256': fingerprint(manifest), 'samples': dict(counts),
                      'labels': dict(labels),
                      'deployment_allowed': all(s['deployment_allowed'] for s in sources.values())}


def rasterize(sample, size=256, line_width=3):
    masks, known = [], []
    for name in LINES:
        label = sample['lines'][name]
        mask = Image.new('L', (size, size), 0)
        if label['state'] == 'visible':
            points = [(round(x * (size - 1)), round(y * (size - 1))) for x, y in label['points']]
            ImageDraw.Draw(mask).line(points, fill=255, width=line_width, joint='curve')
        masks.append(mask)
        known.append(label['state'] != 'unclear')
    return masks, known


class PalmDataset:
    def __init__(self, manifest, root, split, size=256, line_width=3, augment=False,
                 domain=None):
        self.samples = [s for s in manifest['samples'] if s['split'] == split
                        and (domain is None or s['domain'] == domain)]
        self.root, self.size, self.line_width, self.augment = root, size, line_width, augment

    def __len__(self):
        return len(self.samples)

    def __getitem__(self, index):
        import numpy as np
        import torch
        from PIL import ImageEnhance

        sample = self.samples[index]
        image = read_image(self.root, sample).resize((self.size, self.size), Image.Resampling.BILINEAR)
        masks, known = rasterize(sample, self.size, self.line_width)
        if self.augment:
            if torch.rand(()).item() < .5:
                image, masks = ImageOps.mirror(image), [ImageOps.mirror(m) for m in masks]
            angle = torch.rand(()).item() * 24 - 12
            image = image.rotate(angle, resample=Image.Resampling.BILINEAR)
            masks = [m.rotate(angle, resample=Image.Resampling.NEAREST) for m in masks]
            image = ImageEnhance.Brightness(image).enhance(.8 + .4 * torch.rand(()).item())
            image = ImageEnhance.Contrast(image).enhance(.8 + .4 * torch.rand(()).item())
        inputs = torch.from_numpy(np.asarray(image).copy()).permute(2, 0, 1).float() / 255
        targets = torch.from_numpy(np.stack([np.asarray(m) for m in masks]).copy()).float() / 255
        return inputs, targets, torch.tensor(known, dtype=torch.bool)
