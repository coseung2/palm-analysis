import json
from pathlib import Path

import pytest
from test_training_data import make_manifest

from palm_training.cli import main
from palm_training.data import PalmDataset, validate_manifest

pytest.importorskip('torch', reason='Install the optional training extra for model tests')
pytest.importorskip('skimage', reason='Install the optional training extra for scoring tests')


def test_masked_loss_has_no_unknown_channel_gradient():
    import torch

    from palm_training.network import masked_loss

    logits = torch.zeros((1, 4, 16, 16), requires_grad=True)
    loss = masked_loss(logits, torch.zeros_like(logits),
                       torch.tensor([[True, True, True, False]]))
    loss.backward()
    assert logits.grad[0, 3].abs().sum().item() == 0
    assert logits.grad[0, 0].abs().sum().item() > 0
    all_unknown = masked_loss(logits, torch.zeros_like(logits), torch.zeros((1, 4), dtype=torch.bool))
    assert all_unknown.item() == 0


def test_dataset_preserves_four_channels_and_validity(tmp_path):
    path, _ = make_manifest(tmp_path)
    manifest, _ = validate_manifest(path)
    dataset = PalmDataset(manifest, path.parent, 'train', size=128, augment=True)
    inputs, targets, known = dataset[0]
    assert tuple(inputs.shape) == (3, 128, 128)
    assert tuple(targets.shape) == (4, 128, 128)
    assert known.all().item()
    assert float(inputs.min()) >= 0 and float(inputs.max()) <= 1


def test_one_epoch_train_evaluate_and_gate_smoke(tmp_path, capsys):
    path, _ = make_manifest(tmp_path / 'dataset')
    output = tmp_path / 'experiment'
    assert main(['validate', '--manifest', str(path)]) == 0
    assert main(['train', '--manifest', str(path), '--output', str(output),
                 '--epochs', '1', '--size', '128', '--batch-size', '1']) == 0
    metadata = json.loads((output / 'candidate.json').read_text())
    assert metadata['test_used_for_selection'] is False
    assert metadata['live_model_activated'] is False
    report = tmp_path / 'test-report.json'
    assert main(['evaluate', '--manifest', str(path), '--checkpoint', str(output / 'candidate.pt'),
                 '--output', str(report)]) == 0
    evaluated = json.loads(report.read_text())
    assert evaluated['sample_count'] == 1
    assert evaluated['purpose'] == 'smoke'
    assert set(evaluated['lines']) == {'life', 'head', 'heart', 'fate'}
    assert evaluated['checkpoint_sha256'] == metadata['checkpoint_sha256']
    gate = tmp_path / 'qualification.json'
    assert main(['qualify', '--candidate-report', str(report), '--baseline-report', str(report),
                 '--output', str(gate)]) == 2
    assert json.loads(gate.read_text())['eligible_for_review'] is False
    with pytest.raises(FileExistsError):
        main(['evaluate', '--manifest', str(path), '--checkpoint', str(output / 'candidate.pt'),
              '--output', str(report)])
    assert 'synthetic-0' not in capsys.readouterr().out


def test_missing_rights_blocks_before_output_directory_created(tmp_path):
    path, manifest = make_manifest(tmp_path / 'dataset')
    manifest['sources'][0]['training_allowed'] = False
    path.write_text(json.dumps(manifest), encoding='utf-8')
    output = tmp_path / 'no-experiment'
    with pytest.raises(ValueError):
        main(['train', '--manifest', str(path), '--output', str(output), '--epochs', '1'])
    assert not Path(output).exists()
