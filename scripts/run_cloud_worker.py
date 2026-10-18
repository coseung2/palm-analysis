"""Drop bootstrap/admin secrets before executing the long-lived VM consumer."""
import os
import sys

REQUIRED = (
    'PALM_RUNTIME_READY', 'PALM_OCX_BASE_URL', 'PALM_OCX_API_KEY', 'PALM_OCX_MODEL',
    'PALM_DEV_SUPABASE_URL', 'PALM_DEV_SERVICE_KEY',
)


def main():
    if any(name not in os.environ for name in REQUIRED):
        raise SystemExit('Worker secret mapping incomplete; values suppressed.')
    keep = (
        'PATH', 'HOME', 'LANG', 'USER', 'LOGNAME', 'TMPDIR', 'SSL_CERT_FILE', 'SSL_CERT_DIR',
        'PALM_LINE_MODEL_PATH', 'OMP_NUM_THREADS', 'MKL_NUM_THREADS',
    )
    environment = {name: os.environ[name] for name in (*REQUIRED, *keep) if name in os.environ}
    os.execve(sys.executable, [sys.executable, '-m', 'palm_backend.cloud_worker'], environment)


if __name__ == '__main__':
    main()
