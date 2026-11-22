$ErrorActionPreference = 'Stop'
$runtime = Join-Path $env:LOCALAPPDATA 'MilewayRuntime'
$python = Join-Path $runtime 'Scripts/python.exe'
if (!(Test-Path -LiteralPath $python)) {
    & python -m venv $runtime
    if ($LASTEXITCODE) { throw 'Install Python 3.12 with PATH enabled.' }
}
$requirements = Join-Path $PSScriptRoot 'requirements.txt'
$stamp = Join-Path $runtime 'mileway-requirements.sha256'
$sha = [Security.Cryptography.SHA256]::Create()
try { $hash = [BitConverter]::ToString($sha.ComputeHash([IO.File]::ReadAllBytes($requirements))) } finally { $sha.Dispose() }
if (!(Test-Path -LiteralPath $stamp) -or (Get-Content -LiteralPath $stamp -Raw).Trim() -ne $hash) {
    & $python -m pip install -r $requirements
    if ($LASTEXITCODE) { throw 'Python dependency installation failed.' }
    Set-Content -LiteralPath $stamp -Value $hash
}
& $python (Join-Path $PSScriptRoot 'run.py')
exit $LASTEXITCODE
