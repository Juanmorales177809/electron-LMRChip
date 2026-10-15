param(
    [string]$Destination = "build/python-runtime"
)

$ErrorActionPreference = "Stop"
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$target = [System.IO.Path]::GetFullPath((Join-Path $projectRoot $Destination))
$buildRoot = [System.IO.Path]::GetFullPath((Join-Path $projectRoot "build"))
if (-not $target.StartsWith($buildRoot + [System.IO.Path]::DirectorySeparatorChar, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "Python runtime destination must stay inside $buildRoot"
}

$expectedVersion = "3.13.16"
$python = Join-Path $target "python.exe"
if (Test-Path -LiteralPath $python) {
    $installedVersion = & $python -c "import platform; print(platform.python_version())"
    if ($installedVersion -eq $expectedVersion) {
        Write-Host "Python $expectedVersion runtime already exists at $target"
        exit 0
    }
    Remove-Item -LiteralPath $target -Recurse -Force
}

New-Item -ItemType Directory -Path $buildRoot -Force | Out-Null
$archive = Join-Path $buildRoot "python-$expectedVersion-embed-amd64.zip"
$expectedHash = "97dae5274cc54867065e8d5a3226e48c35017ed332a0fdb0e27d5b5821961297"
if (-not (Test-Path -LiteralPath $archive)) {
    Invoke-WebRequest -Uri "https://www.python.org/ftp/python/$expectedVersion/python-$expectedVersion-embed-amd64.zip" -OutFile $archive
}
$actualHash = (Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash.ToLowerInvariant()
if ($actualHash -ne $expectedHash) {
    throw "Python archive checksum mismatch."
}
New-Item -ItemType Directory -Path $target -Force | Out-Null
Expand-Archive -LiteralPath $archive -DestinationPath $target -Force

$pathFile = Join-Path $target "python313._pth"
@("python313.zip", ".", "Lib/site-packages", "../python", "import site") | Set-Content -LiteralPath $pathFile -Encoding ASCII
New-Item -ItemType Directory -Path (Join-Path $target "Lib/site-packages") -Force | Out-Null

$builderVersion = & py -3.13 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"
if ($LASTEXITCODE -ne 0 -or $builderVersion -ne "3.13") {
    throw "A local Python 3.13 installation is required to assemble dependencies."
}
& py -3.13 -m pip install --disable-pip-version-check --no-cache-dir `
    --target (Join-Path $target "Lib/site-packages") `
    "numpy==2.2.6" "scipy==1.15.3" "seabreeze==2.11.0" "pyserial==3.5"
if ($LASTEXITCODE -ne 0) { throw "Could not install Python runtime dependencies." }
& $python -c "import numpy, scipy, seabreeze, serial; print('Python runtime verified')"
if ($LASTEXITCODE -ne 0) { throw "Python runtime import verification failed." }
