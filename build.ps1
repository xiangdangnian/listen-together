$ErrorActionPreference = "Stop"
$projectRoot = $PSScriptRoot
$python = Join-Path $projectRoot ".venv\Scripts\python.exe"
$pyinstaller = Join-Path $projectRoot ".venv\Scripts\pyinstaller.exe"
$distDir = Join-Path $projectRoot "dist"
$appDir = Join-Path $distDir "ListenTogether"
$vlcSource = "C:\Program Files\VideoLAN\VLC"
$vlcTarget = Join-Path $appDir "vlc"
$projectResolved = [System.IO.Path]::GetFullPath($projectRoot)

function Assert-ProjectPath([string]$target) {
    $resolved = [System.IO.Path]::GetFullPath($target)
    $prefix = $projectResolved.TrimEnd('\') + '\'
    if (-not $resolved.StartsWith($prefix, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to modify a path outside the project: $resolved"
    }
}

if (-not (Test-Path -LiteralPath $python)) {
    throw "Project virtual environment is missing."
}

if (Test-Path -LiteralPath (Join-Path $projectRoot "build")) {
    $buildDir = Join-Path $projectRoot "build"
    Assert-ProjectPath $buildDir
    Remove-Item -LiteralPath $buildDir -Recurse -Force
}
if (Test-Path -LiteralPath $appDir) {
    Assert-ProjectPath $appDir
    Remove-Item -LiteralPath $appDir -Recurse -Force
}

& $pyinstaller `
    --noconfirm `
    --clean `
    --windowed `
    --name ListenTogether `
    --paths (Join-Path $projectRoot "src") `
    --hidden-import vlc `
    (Join-Path $projectRoot "run_app.py")

if (-not (Test-Path -LiteralPath $appDir)) {
    throw "PyInstaller output was not created."
}

if (Test-Path -LiteralPath $vlcSource) {
    Copy-Item -LiteralPath $vlcSource -Destination $vlcTarget -Recurse -Force
}

$archive = Join-Path $distDir "ListenTogether-Windows.zip"
if (Test-Path -LiteralPath $archive) {
    Assert-ProjectPath $archive
    Remove-Item -LiteralPath $archive -Force
}
Compress-Archive -LiteralPath $appDir -DestinationPath $archive -CompressionLevel Optimal
Write-Host "Built: $appDir"
Write-Host "Archive: $archive"
