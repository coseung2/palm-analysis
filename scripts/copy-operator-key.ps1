$ErrorActionPreference = 'Stop'
Push-Location (Split-Path $PSScriptRoot -Parent)
try {
    $key = & '.\.venv\Scripts\python.exe' -c 'from palm_backend.config import Settings; print(Settings().operator_key.get_secret_value())'
    if ($LASTEXITCODE -ne 0 -or -not $key -or $key.Length -lt 32) { throw 'Operator key could not be loaded' }
    Set-Clipboard -Value $key
    $key = $null
    '운영자 키를 클립보드에 복사했습니다. 사이트의 운영 화면에 붙여넣고 사용 후 클립보드를 비워 주세요.'
} finally { Pop-Location; $key = $null }
