import importlib.util
from pathlib import Path


def test_worker_bootstrap_preserves_model_options_but_drops_admin_secrets(monkeypatch):
    path = Path(__file__).resolve().parents[1] / 'scripts/run_cloud_worker.py'
    spec = importlib.util.spec_from_file_location('test_bootstrap', path)
    bootstrap = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(bootstrap)
    for key in bootstrap.REQUIRED:
        monkeypatch.setenv(key, 'test-only')
    monkeypatch.setenv('PALM_LINE_MODEL_PATH', '/test-only/palm-lines.pth')
    monkeypatch.setenv('PALM_LINE_SEGMENTER_PATH', '/test-only/palm-line-reader.onnx')
    monkeypatch.setenv('OMP_NUM_THREADS', '2')
    monkeypatch.setenv('MKL_NUM_THREADS', '2')
    monkeypatch.setenv('Supabase_access_token', 'test-admin-secret')
    monkeypatch.setenv('INFISICAL_TOKEN', 'test-bootstrap-secret')
    monkeypatch.setenv('Supabase_DB_SECRET', 'test-db-password')
    calls = []
    monkeypatch.setattr(bootstrap.os, 'execve', lambda executable, args, env: calls.append(env))
    bootstrap.main()
    env = calls[0]
    assert env['PALM_LINE_MODEL_PATH'] == '/test-only/palm-lines.pth'
    assert env['PALM_LINE_SEGMENTER_PATH'] == '/test-only/palm-line-reader.onnx'
    assert env['OMP_NUM_THREADS'] == env['MKL_NUM_THREADS'] == '2'
    assert all(name not in env for name in ('Supabase_access_token', 'INFISICAL_TOKEN', 'Supabase_DB_SECRET'))
