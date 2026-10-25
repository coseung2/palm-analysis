import copy

import pytest

from palm_training.cli import qualification
from palm_training.data import LINES
from palm_training.metrics import LineMetrics

np = pytest.importorskip('numpy', reason='Install the optional training extra for scoring tests')
pytest.importorskip('skimage', reason='Install the optional training extra for scoring tests')


def test_perfect_masks_score_one_and_unknown_is_excluded():
    masks = np.zeros((4, 64, 64), dtype=bool)
    masks[:, 20, 10:50] = True
    metrics = LineMetrics()
    metrics.add(masks, masks, [True, True, True, False])
    rows = metrics.result()
    assert rows['life']['dice'] == rows['life']['centerline_f1'] == 1
    assert rows['fate']['positives'] == 0
    assert rows['fate']['dice'] is None


def test_unobserved_fate_false_positive_is_counted():
    targets = np.zeros((4, 64, 64), dtype=bool)
    predicted = targets.copy()
    predicted[3, 20, 10:50] = True
    metrics = LineMetrics()
    metrics.add(predicted, targets, [True] * 4)
    rows = metrics.result()
    assert rows['fate']['absent_false_positive_rate'] == 1
    assert rows['life']['absent_false_positive_rate'] == 0


def test_centerline_tolerance_and_empty_prediction():
    targets = np.zeros((4, 64, 64), dtype=bool)
    targets[:, 20, 10:50] = True
    predicted = np.zeros_like(targets)
    predicted[:, 21, 10:50] = True
    metrics = LineMetrics(tolerance=2)
    metrics.add(predicted, targets, [True] * 4)
    row = metrics.result()['life']
    assert row['centerline_f1'] == 1
    assert row['dice'] == 0
    metrics = LineMetrics()
    metrics.add(np.zeros_like(targets), targets, [True] * 4)
    assert metrics.result()['life']['centerline_f1'] == 0


def report():
    return {
        'version': 1, 'purpose': 'training', 'split': 'test', 'domain': 'booth',
        'deployment_allowed': True, 'manifest_sha256': 'a' * 64, 'person_count': 20,
        'checkpoint_sha256': 'b' * 64, 'protocol': {'size': 512},
        'architecture': 'palm-four-line-unet-v1',
        'lines': {name: {'positives': 20, 'negatives': 20,
                         'positive_people': 10, 'negative_people': 10, 'dice': .85,
                         'centerline_f1': .85, 'absent_false_positive_rate': .05}
                  for name in LINES},
    }


def improved():
    baseline = report()
    candidate = copy.deepcopy(baseline)
    candidate['checkpoint_sha256'] = 'c' * 64
    for line in candidate['lines'].values():
        line.update(dice=.88, centerline_f1=.88)
    return candidate, baseline


def test_comparable_improvement_only_qualifies_for_manual_review():
    candidate, baseline = improved()
    result = qualification(candidate, baseline)
    assert result['eligible_for_review']
    assert result['requires_manual_review']
    assert result['requires_target_vm_latency_check']
    assert not result['live_model_activated']


def test_synthetic_and_no_baseline_never_qualify():
    baseline = report()
    candidate = copy.deepcopy(baseline)
    candidate['purpose'] = 'smoke'
    result = qualification(candidate, baseline)
    assert not result['eligible_for_review']
    assert any('baseline checkpoint' in reason for reason in result['blocking_reasons'])


def test_rights_insufficient_examples_and_fate_regression_block():
    candidate, baseline = improved()
    candidate['deployment_allowed'] = False
    candidate['lines']['fate'].update(negatives=0, centerline_f1=.6,
                                     absent_false_positive_rate=.2)
    result = qualification(candidate, baseline)
    assert not result['eligible_for_review']
    assert any('rights' in reason for reason in result['blocking_reasons'])
    assert any('fate: regression' in reason for reason in result['blocking_reasons'])


def test_different_test_set_or_nonfinite_metrics_block():
    candidate, baseline = improved()
    candidate['manifest_sha256'] = 'd' * 64
    candidate['lines']['life']['dice'] = float('nan')
    assert not qualification(candidate, baseline)['eligible_for_review']
