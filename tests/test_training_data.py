import copy
import hashlib
import json

import pytest
from PIL import Image

from palm_training.data import LINES, fingerprint, image_path, rasterize, validate_manifest


def make_manifest(root, purpose='smoke'):
    root.mkdir(parents=True, exist_ok=True)
    samples = []
    for index, split in enumerate(('train', 'val', 'test')):
        path = root / f'{split}.png'
        Image.new('RGB', (64, 64), (index * 40, 120, 180)).save(path)
        samples.append({
            'id': f'smoke-{index}', 'person_id': f'synthetic-{index}',
            'original_id': f'generated-{index}', 'source': 'synthetic', 'split': split,
            'domain': 'booth', 'consent_reference': 'synthetic; no real subject',
            'image': path.name, 'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
            'reviewed_by': 'automated smoke fixture; not human-reviewed training data',
            'lines': {name: {'state': 'visible', 'points': [[.1, .2 + i * .15], [.9, .3 + i * .15]]}
                      for i, name in enumerate(LINES)},
        })
    manifest = {
        'version': 1, 'purpose': purpose, 'coordinate_space': 'normalized_image',
        'sources': [{
            'id': 'synthetic', 'url': 'local synthetic test fixture', 'license': 'test fixture',
            'reviewed_by': 'automated smoke test', 'reviewed_at': '2026-10-19',
            'permission_reference': 'synthetic geometry only',
            'training_allowed': True, 'deployment_allowed': False,
        }], 'samples': samples,
    }
    path = root / 'manifest.json'
    path.write_text(json.dumps(manifest), encoding='utf-8')
    return path, manifest


def save(path, manifest):
    path.write_text(json.dumps(manifest), encoding='utf-8')


def test_valid_manifest_has_private_aggregate_summary(tmp_path):
    path, manifest = make_manifest(tmp_path)
    actual, summary = validate_manifest(path)
    assert actual == manifest
    assert summary['samples']['train'] == summary['samples']['test:booth'] == 1
    assert summary['deployment_allowed'] is False
    assert summary['manifest_sha256'] == fingerprint(manifest)
    assert 'synthetic-0' not in json.dumps(summary)


@pytest.mark.parametrize('key', ['training_allowed', 'permission_reference', 'reviewed_by'])
def test_source_requires_explicit_review(tmp_path, key):
    path, manifest = make_manifest(tmp_path)
    del manifest['sources'][0][key]
    save(path, manifest)
    with pytest.raises(ValueError):
        validate_manifest(path)


@pytest.mark.parametrize('key', ['person_id', 'original_id'])
def test_identity_and_original_cannot_cross_splits(tmp_path, key):
    path, manifest = make_manifest(tmp_path)
    manifest['samples'][1][key] = manifest['samples'][0][key]
    save(path, manifest)
    with pytest.raises(ValueError, match='leaks'):
        validate_manifest(path)


def test_duplicate_pixels_cannot_cross_splits_even_with_different_file_hashes(tmp_path):
    path, manifest = make_manifest(tmp_path)
    duplicate = tmp_path / 'different-encoding.png'
    with Image.open(tmp_path / 'train.png') as image:
        image.save(duplicate, compress_level=0)
    manifest['samples'][1].update(image=duplicate.name,
                                  sha256=hashlib.sha256(duplicate.read_bytes()).hexdigest())
    save(path, manifest)
    with pytest.raises(ValueError, match='leaks'):
        validate_manifest(path)


def test_unknown_is_ignored_and_absent_is_supervised_negative(tmp_path):
    _, manifest = make_manifest(tmp_path)
    sample = copy.deepcopy(manifest['samples'][0])
    sample['lines']['fate'] = {'state': 'unclear', 'points': []}
    sample['lines']['heart'] = {'state': 'not_visible', 'points': []}
    masks, known = rasterize(sample, size=64)
    assert known == [True, True, True, False]
    assert masks[0].getbbox() is not None
    assert masks[2].getbbox() is masks[3].getbbox() is None


@pytest.mark.parametrize('points', [[[0, 0], [float('nan'), 1]],
                                    [[0, 0], [1.01, .5]], [[.5, .5], [.5, .5]], []])
def test_invalid_curve_rejected(tmp_path, points):
    path, manifest = make_manifest(tmp_path)
    manifest['samples'][0]['lines']['fate']['points'] = points
    save(path, manifest)
    with pytest.raises(ValueError):
        validate_manifest(path)


def test_absent_curve_cannot_contain_fabricated_points(tmp_path):
    path, manifest = make_manifest(tmp_path)
    manifest['samples'][0]['lines']['fate']['state'] = 'not_visible'
    save(path, manifest)
    with pytest.raises(ValueError, match='invented'):
        validate_manifest(path)


def test_training_consent_and_all_four_reviews_required(tmp_path):
    path, manifest = make_manifest(tmp_path)
    del manifest['samples'][0]['consent_reference']
    save(path, manifest)
    with pytest.raises(ValueError, match='consent'):
        validate_manifest(path)
    manifest['samples'][0]['consent_reference'] = 'synthetic'
    del manifest['samples'][0]['lines']['fate']
    save(path, manifest)
    with pytest.raises(ValueError, match='four'):
        validate_manifest(path)


def test_checksum_change_rejected(tmp_path):
    path, _ = make_manifest(tmp_path)
    Image.new('RGB', (64, 64), 'white').save(tmp_path / 'train.png')
    with pytest.raises(ValueError, match='checksum'):
        validate_manifest(path)


def test_paths_cannot_escape_private_dataset(tmp_path):
    with pytest.raises(ValueError, match='escapes'):
        image_path(tmp_path, '../outside.png')
    with pytest.raises(ValueError, match='relative'):
        image_path(tmp_path, str(tmp_path / 'outside.png'))


def test_test_split_cannot_repeat_augmented_originals(tmp_path):
    path, manifest = make_manifest(tmp_path)
    duplicate = copy.deepcopy(manifest['samples'][2])
    duplicate['id'] = 'another-synthetic-view'
    manifest['samples'].append(duplicate)
    save(path, manifest)
    with pytest.raises(ValueError, match='repeated'):
        validate_manifest(path)


def test_orientation_must_be_normalized_before_annotation(tmp_path):
    path, manifest = make_manifest(tmp_path)
    image = Image.new('RGB', (64, 64), 'red')
    exif = Image.Exif()
    exif[274] = 6
    destination = tmp_path / 'rotated.jpg'
    image.save(destination, exif=exif)
    manifest['samples'][0].update(image=destination.name,
                                  sha256=hashlib.sha256(destination.read_bytes()).hexdigest())
    save(path, manifest)
    with pytest.raises(ValueError, match='EXIF'):
        validate_manifest(path)
