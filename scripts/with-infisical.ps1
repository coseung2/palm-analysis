param(
    [string]$ProjectId = 'bde1d1c7-150c-4490-a43f-61ff9b6c6aae',
    [string]$Environment = 'dev',
    [string]$SecretPath = '/',
    [Parameter(Mandatory=$true)][string]$Executable,
    [Parameter(Position=1, ValueFromRemainingArguments=$true)][string[]]$CommandArguments
)
$ErrorActionPreference = 'Stop'
$root = Join-Path $env:LOCALAPPDATA 'Eoseowa\infisical-machine'
$secure = ConvertTo-SecureString ([IO.File]::ReadAllText((Join-Path $root 'client-secret.dpapi')).Trim())
$secret = [Net.NetworkCredential]::new('', $secure).Password
$id = [IO.File]::ReadAllText((Join-Path $root 'client-id.txt')).Trim()
$previous = $env:INFISICAL_TOKEN
try {
    $auth = Invoke-RestMethod -Method Post -Uri 'https://app.infisical.com/api/v1/auth/universal-auth/login' -ContentType 'application/json' -Body (@{clientId=$id;clientSecret=$secret} | ConvertTo-Json -Compress)
    $env:INFISICAL_TOKEN = $auth.accessToken
    $secret = $null; $auth = $null
    & infisical run --projectId=$ProjectId --env=$Environment --path=$SecretPath --silent -- $Executable @CommandArguments
    $result = $LASTEXITCODE
} finally {
    if ($null -eq $previous) { Remove-Item Env:INFISICAL_TOKEN -ErrorAction SilentlyContinue } else { $env:INFISICAL_TOKEN = $previous }
    $secure.Dispose(); $secret = $null; $auth = $null
}
exit $result
