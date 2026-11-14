$ErrorActionPreference = 'Stop'
Push-Location -LiteralPath $PSScriptRoot
try {
    $nativePython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
    if (Test-Path -LiteralPath $nativePython) {
        & $nativePython -m native_vnc
    }
    else {
        python -m native_vnc
    }
    if ($LASTEXITCODE -ne 0) { throw "Native VNC exited with code $LASTEXITCODE" }
}
finally {
    Pop-Location
}
