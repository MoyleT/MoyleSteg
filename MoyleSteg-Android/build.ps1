$ErrorActionPreference = "Stop"
Push-Location $PSScriptRoot
try {
    py -3 tools/build_android.py @args
    if ($LASTEXITCODE -ne 0) { throw "Build failed with exit code $LASTEXITCODE" }
} finally { Pop-Location }
