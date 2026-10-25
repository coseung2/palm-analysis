"""Offline validate/train/evaluate/qualify commands. No network or live-model activation."""
import argparse
import json
import math
import os
import random
import statistics
import time
from pathlib import Path

from .data import LINES, PalmDataset, digest_file, validate_manifest


def write_json(path, value):
    # Never replace another experiment's evidence or checkpoint by accident.
    with Path(path).open('x', encoding='utf-8') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write('\n')


def _torch(device, seed=42, threads=2):
    os.environ.setdefault('CUBLAS_WORKSPACE_CONFIG', ':4096:8')
    import numpy as np
    import torch

    if device == 'cuda' and not torch.cuda.is_available():
        raise ValueError('CUDA requested but unavailable; no silent CPU fallback')
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    torch.set_num_threads(threads)
    torch.use_deterministic_algorithms(True)
    return torch


def _load(checkpoint, device):
    import torch

    from .network import ARCHITECTURE, FourLineUNet

    path = Path(checkpoint)
    if path.stat().st_size > 64 * 1024 * 1024:
        raise ValueError('Unexpected checkpoint size')
    bundle = torch.load(path, map_location='cpu', weights_only=True)
    if (bundle.get('architecture') != ARCHITECTURE or bundle.get('lines') != list(LINES)
            or bundle.get('size') not in (128, 256, 512)
            or type(bundle.get('line_width')) is not int or not 1 <= bundle['line_width'] <= 15):
        raise ValueError('Checkpoint contract mismatch')
    model = FourLineUNet()
    model.load_state_dict(bundle['state_dict'], strict=True)
    if not all(torch.isfinite(tensor).all() for tensor in model.state_dict().values()):
        raise ValueError('Non-finite checkpoint weights')
    model.to(device).eval()
    return model, bundle


def _dataset(manifest, root, split, bundle, augment=False, domain=None):
    return PalmDataset(manifest, root, split, size=bundle['size'],
                       line_width=bundle['line_width'], augment=augment, domain=domain)


def _evaluate(model, dataset, device, thresholds, tolerance):
    import torch
    from torch.utils.data import DataLoader

    from .metrics import LineMetrics

    metrics, timings = LineMetrics(tolerance=tolerance), []
    threshold = torch.tensor(thresholds).view(4, 1, 1)
    with torch.inference_mode():
        for inputs, targets, known in DataLoader(dataset, batch_size=1, shuffle=False):
            if device == 'cuda':
                torch.cuda.synchronize()
            start = time.perf_counter()
            probabilities = model(inputs.to(device)).sigmoid().cpu()
            timings.append((time.perf_counter() - start) * 1000)
            if not torch.isfinite(probabilities).all():
                raise ValueError('Non-finite prediction')
            metrics.add((probabilities[0] >= threshold).numpy(), targets[0].numpy() > .5,
                        known[0].tolist())
    return metrics.result(), timings


def train(args):
    manifest, summary = validate_manifest(args.manifest)
    for split in ('train', 'val'):
        for name in LINES:
            if not summary['labels'].get(f'{split}:{name}:visible', 0):
                raise ValueError('Train and validation need reviewed positive examples of every line')
    torch = _torch(args.device, args.seed, args.threads)
    from torch.utils.data import DataLoader

    from .network import ARCHITECTURE, FourLineUNet, masked_loss

    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=False)
    bundle = {'architecture': ARCHITECTURE, 'lines': list(LINES), 'size': args.size,
              'line_width': args.line_width, 'manifest_sha256': summary['manifest_sha256'],
              'purpose': manifest['purpose'], 'seed': args.seed, 'thresholds': [.5] * 4}
    write_json(output / 'run.json', {**bundle, 'epochs': args.epochs,
                                    'batch_size': args.batch_size, 'learning_rate': args.learning_rate,
                                    'device': args.device, 'torch': str(torch.__version__),
                                    'initialization': 'random; no pretrained weights',
                                    'augmentation': 'train-only mirror/rotation/brightness/contrast',
                                    'live_model_activated': False})
    root = Path(args.manifest).parent
    training = _dataset(manifest, root, 'train', bundle, augment=True)
    validation = _dataset(manifest, root, 'val', bundle)
    model = FourLineUNet().to(args.device)
    optimizer = torch.optim.AdamW(model.parameters(), lr=args.learning_rate, weight_decay=1e-4)
    loader = DataLoader(training, batch_size=args.batch_size, shuffle=True, num_workers=0)
    val_loader = DataLoader(validation, batch_size=args.batch_size, shuffle=False, num_workers=0)
    best_loss, best_state, best_epoch, history = math.inf, None, None, []
    for epoch in range(args.epochs):
        model.train()
        total, count = 0., 0
        for inputs, targets, known in loader:
            if not known.any():
                continue
            optimizer.zero_grad(set_to_none=True)
            loss = masked_loss(model(inputs.to(args.device)), targets.to(args.device),
                               known.to(args.device))
            if not torch.isfinite(loss):
                raise ValueError('Non-finite training loss')
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1., error_if_nonfinite=True)
            optimizer.step()
            total += loss.item() * inputs.shape[0]
            count += inputs.shape[0]
        model.eval()
        validation_total, validation_count = 0., 0
        with torch.inference_mode():
            for inputs, targets, known in val_loader:
                if not known.any():
                    continue
                loss = masked_loss(model(inputs.to(args.device)), targets.to(args.device),
                                   known.to(args.device))
                if not torch.isfinite(loss):
                    raise ValueError('Non-finite validation loss')
                validation_total += loss.item() * inputs.shape[0]
                validation_count += inputs.shape[0]
        val_loss = validation_total / max(validation_count, 1)
        history.append({'epoch': epoch + 1, 'train_loss': total / max(count, 1),
                        'val_loss': val_loss})
        if val_loss < best_loss:
            best_loss, best_epoch = val_loss, epoch + 1
            best_state = {name: tensor.detach().cpu().clone()
                          for name, tensor in model.state_dict().items()}
        # No filenames, IDs, coordinates, photos or provider secrets in console output.
        print(json.dumps(history[-1]), flush=True)
    model.load_state_dict(best_state, strict=True)
    thresholds, best_scores = [.5] * 4, [-math.inf] * 4
    for cutoff in (.3, .4, .5, .6, .7):
        rows, _ = _evaluate(model, validation, args.device, [cutoff] * 4, args.tolerance)
        for index, name in enumerate(LINES):
            row = rows[name]
            score = row['centerline_f1'] - (row['absent_false_positive_rate'] or 0)
            if score > best_scores[index]:
                best_scores[index], thresholds[index] = score, cutoff
    bundle.update(state_dict=best_state, best_epoch=best_epoch, thresholds=thresholds)
    with (output / 'candidate.pt').open('xb') as stream:
        torch.save(bundle, stream)
    write_json(output / 'history.json', history)
    write_json(output / 'candidate.json', {
        'checkpoint_sha256': digest_file(output / 'candidate.pt'),
        'manifest_sha256': summary['manifest_sha256'], 'best_epoch': best_epoch,
        'thresholds': thresholds, 'threshold_selection': 'validation only; F1 minus absent FPR',
        'test_used_for_selection': False, 'live_model_activated': False,
    })
    print('Candidate saved for independent evaluation; live model unchanged.')


def evaluate(args):
    manifest, summary = validate_manifest(args.manifest)
    _torch(args.device, threads=args.threads)
    model, bundle = _load(args.checkpoint, args.device)
    if bundle['manifest_sha256'] != summary['manifest_sha256']:
        raise ValueError('Checkpoint and dataset manifest differ; do not silently change the test set')
    thresholds = bundle.get('thresholds')
    if (not isinstance(thresholds, list) or len(thresholds) != 4
            or any(type(t) not in (int, float) or not math.isfinite(t) or not 0 < t < 1
                   for t in thresholds)):
        raise ValueError('Invalid validation-selected thresholds')
    dataset = _dataset(manifest, Path(args.manifest).parent, 'test', bundle, domain='booth')
    if not len(dataset):
        raise ValueError('Independent booth test photos are required; public data is not a substitute')
    rows, timings = _evaluate(model, dataset, args.device, thresholds, args.tolerance)
    for name in LINES:
        for state, key in (('visible', 'positive_people'), ('not_visible', 'negative_people')):
            rows[name][key] = len({s['person_id'] for s in dataset.samples
                                  if s['lines'][name]['state'] == state})
    report = {
        'version': 1, 'purpose': manifest['purpose'], 'split': 'test', 'domain': 'booth',
        'architecture': bundle['architecture'], 'manifest_sha256': summary['manifest_sha256'],
        'checkpoint_sha256': digest_file(args.checkpoint),
        'deployment_allowed': summary['deployment_allowed'], 'sample_count': len(dataset),
        'person_count': len({s['person_id'] for s in dataset.samples}),
        'protocol': {'size': bundle['size'], 'line_width': bundle['line_width'],
                     'centerline_tolerance_pixels': args.tolerance, 'absent_area_fraction': .001},
        'thresholds': thresholds, 'lines': rows,
        'runtime': {'device': args.device, 'threads': args.threads,
                    'median_model_ms': statistics.median(timings),
                    'max_model_ms': max(timings), 'includes_preprocessing': False,
                    'includes_first_inference': True},
        'live_model_activated': False,
    }
    write_json(args.output, report)
    print(json.dumps(report, ensure_ascii=False, allow_nan=False))


def qualification(candidate, baseline):
    reasons = []
    for report in (candidate, baseline):
        if (report.get('version') != 1 or report.get('purpose') != 'training'
                or report.get('split') != 'test' or report.get('domain') != 'booth'
                or report.get('deployment_allowed') is not True):
            reasons.append('Real booth test data and recorded deployment rights are required')
    if any(type(r.get('person_count')) is not int or r['person_count'] < 20
           for r in (candidate, baseline)):
        reasons.append('At least 20 independent booth test people are required')
    for key in ('manifest_sha256', 'protocol', 'architecture'):
        if not candidate.get(key) or candidate.get(key) != baseline.get(key):
            reasons.append('Candidate and baseline must use identical data and scoring protocol')
    if (not candidate.get('checkpoint_sha256') or not baseline.get('checkpoint_sha256')
            or candidate['checkpoint_sha256'] == baseline['checkpoint_sha256']):
        reasons.append('A distinct, evaluated baseline checkpoint is required')
    differences = []
    for name in LINES:
        row, previous = candidate.get('lines', {}).get(name, {}), baseline.get('lines', {}).get(name, {})
        if any(type(r.get(k)) is not int or r[k] < 20
               for r in (row, previous) for k in ('positives', 'negatives')):
            reasons.append(f'{name}: at least 20 positive and 20 unobserved test examples required')
        if any(type(r.get(k)) is not int or r[k] < 10
               for r in (row, previous) for k in ('positive_people', 'negative_people')):
            reasons.append(f'{name}: each state needs at least 10 independent people')
        keys = ('dice', 'centerline_f1', 'absent_false_positive_rate')
        if any(type(r.get(k)) not in (int, float) or not math.isfinite(r[k]) or not 0 <= r[k] <= 1
               for r in (row, previous) for k in keys):
            reasons.append(f'{name}: complete finite metrics required')
            continue
        if row['centerline_f1'] < .8 or row['absent_false_positive_rate'] > .1:
            reasons.append(f'{name}: provisional quality floor failed')
        if (row['centerline_f1'] < previous['centerline_f1'] - .01
                or row['dice'] < previous['dice'] - .01
                or row['absent_false_positive_rate'] > previous['absent_false_positive_rate']):
            reasons.append(f'{name}: regression against baseline')
        differences.append(row['centerline_f1'] - previous['centerline_f1'])
    if len(differences) != 4 or statistics.mean(differences) < .01:
        reasons.append('Mean centerline F1 gain must be at least 0.01 over the baseline')
    return {'eligible_for_review': not reasons, 'blocking_reasons': sorted(set(reasons)),
            'criteria_status': 'provisional engineering thresholds, not calibrated safety guarantees',
            'requires_manual_review': True, 'requires_target_vm_latency_check': True,
            'live_model_activated': False}


def _bounded_int(low, high):
    def parse(text):
        value = int(text)
        if not low <= value <= high:
            raise argparse.ArgumentTypeError(f'Expected integer {low} through {high}')
        return value
    return parse


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    check = commands.add_parser('validate')
    check.add_argument('--manifest', required=True)
    fitting = commands.add_parser('train')
    fitting.add_argument('--manifest', required=True)
    fitting.add_argument('--output', required=True)
    fitting.add_argument('--epochs', type=_bounded_int(1, 500), default=50)
    fitting.add_argument('--batch-size', type=_bounded_int(1, 32), default=4)
    fitting.add_argument('--size', type=int, choices=(128, 256, 512), default=512)
    fitting.add_argument('--line-width', type=_bounded_int(1, 15), default=3)
    fitting.add_argument('--seed', type=_bounded_int(0, 2**32 - 1), default=42)
    fitting.add_argument('--learning-rate', type=float, default=1e-3)
    scoring = commands.add_parser('evaluate')
    scoring.add_argument('--manifest', required=True)
    scoring.add_argument('--checkpoint', required=True)
    scoring.add_argument('--output', required=True)
    for command in (fitting, scoring):
        command.add_argument('--device', choices=('cpu', 'cuda'), default='cpu')
        command.add_argument('--threads', type=_bounded_int(1, 8), default=2)
        command.add_argument('--tolerance', type=_bounded_int(0, 8), default=2)
    gate = commands.add_parser('qualify')
    gate.add_argument('--candidate-report', required=True)
    gate.add_argument('--baseline-report', required=True)
    gate.add_argument('--output', required=True)
    args = parser.parse_args(argv)
    if args.command == 'validate':
        _, summary = validate_manifest(args.manifest)
        print(json.dumps(summary, ensure_ascii=False))
    elif args.command == 'train':
        if not math.isfinite(args.learning_rate) or not 0 < args.learning_rate <= .1:
            raise ValueError('Learning rate must be finite and in (0, 0.1]')
        train(args)
    elif args.command == 'evaluate':
        evaluate(args)
    else:
        candidate = json.loads(Path(args.candidate_report).read_text(encoding='utf-8'))
        baseline = json.loads(Path(args.baseline_report).read_text(encoding='utf-8'))
        result = qualification(candidate, baseline)
        result['candidate_report_sha256'] = digest_file(args.candidate_report)
        result['baseline_report_sha256'] = digest_file(args.baseline_report)
        write_json(args.output, result)
        print(json.dumps(result, ensure_ascii=False))
        return 0 if result['eligible_for_review'] else 2
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (OSError, ValueError, KeyError, TypeError, RuntimeError, ImportError):
        raise SystemExit('Training command stopped; inspect private inputs locally. No live model changed.') from None
