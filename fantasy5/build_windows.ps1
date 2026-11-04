$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
if ([Environment]::OSVersion.Platform -ne 'Win32NT') { throw 'Windows x64 build host required.' }
function Check-Exit { if ($LASTEXITCODE -ne 0) { throw "Command failed: $LASTEXITCODE" } }
py -3.11 -c "import struct; assert struct.calcsize('P') == 8"
Check-Exit
py -3.11 -m venv .venv
Check-Exit
$python = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
& $python -m pip install -r requirements-build.txt
Check-Exit
New-Item -ItemType Directory -Force -Path dist | Out-Null
& $python -m unittest discover -s tests -v 2>&1 | Tee-Object -FilePath 'dist\unit-tests.txt'
Check-Exit
& $python -m PyInstaller --noconfirm --clean --onedir --console --name '加州天天樂拖牌分析' --collect-all tzdata --add-data "seed_history.json;." app.py
Check-Exit
$dest = Join-Path $PSScriptRoot 'dist\加州天天樂拖牌分析'
Copy-Item -LiteralPath 'START.cmd','README_使用說明.txt','WINDOWS_ACCEPTANCE.md' -Destination $dest
foreach ($dir in @('data','exports','logs')) { New-Item -ItemType Directory -Force -Path (Join-Path $dest $dir) | Out-Null }
$testParent = Join-Path $env:RUNNER_TEMP '中文 空白路徑'
if (-not $env:RUNNER_TEMP) { $testParent = Join-Path $env:TEMP ('Fantasy5-Smoke-'+[guid]::NewGuid()) }
New-Item -ItemType Directory -Force -Path $testParent | Out-Null
$testDest = Join-Path $testParent '加州天天樂拖牌分析'
Copy-Item -LiteralPath $dest -Destination $testDest -Recurse
$exe = Join-Path $testDest '加州天天樂拖牌分析.exe'
# Validate PE machine field, not merely the filename extension.
$bytes = [IO.File]::ReadAllBytes($exe)
$pe = [BitConverter]::ToInt32($bytes, 0x3c)
if ($bytes[0] -ne 0x4d -or $bytes[1] -ne 0x5a -or [BitConverter]::ToInt32($bytes,$pe) -ne 0x4550 -or [BitConverter]::ToUInt16($bytes,$pe+4) -ne 0x8664) { throw 'Not an x64 PE executable' }
$report = Join-Path $PSScriptRoot 'dist\windows-smoke.json'
$oldPath = $env:PATH
try {
    # Installed Python is unavailable through PATH during the frozen smoke test.
    $env:PATH = "$env:SystemRoot\System32;$env:SystemRoot"
    $p = Start-Process -FilePath $exe -ArgumentList @('--self-test', ('"'+$report+'"')) -PassThru -RedirectStandardOutput 'dist\exe-stdout.txt' -RedirectStandardError 'dist\exe-stderr.txt'
    if (-not $p.WaitForExit(120000)) { $p.Kill(); throw 'EXE smoke test timed out' }
    if ($p.ExitCode -ne 0) { Get-Content 'dist\exe-stderr.txt'; throw "EXE smoke failed: $($p.ExitCode)" }
    if (-not (Test-Path -LiteralPath $report)) { throw 'Missing smoke test report' }
    $liveReport = Join-Path $PSScriptRoot 'dist\live-source-check.json'
    $live = Start-Process -FilePath $exe -ArgumentList @('--live-test', ('"'+$liveReport+'"')) -PassThru -RedirectStandardOutput 'dist\live-stdout.txt' -RedirectStandardError 'dist\live-stderr.txt'
    if (-not $live.WaitForExit(120000)) { $live.Kill(); throw 'Live verification timed out' }
    if ($live.ExitCode -ne 0 -or -not (Test-Path -LiteralPath $liveReport)) { throw 'Live verification crashed' }

} finally { $env:PATH = $oldPath }
Remove-Item -LiteralPath $testParent -Recurse -Force
Copy-Item -LiteralPath $report,$liveReport,'dist\unit-tests.txt' -Destination $dest
# Confirm packaging excludes test data and only empty user data folders are shipped.
if (Get-ChildItem -LiteralPath (Join-Path $dest 'data') -Force) { throw 'Unexpected production seed data' }
Compress-Archive -LiteralPath $dest -DestinationPath 'dist\Fantasy5_Windows_Portable.zip' -Force
Get-FileHash 'dist\Fantasy5_Windows_Portable.zip' -Algorithm SHA256 | Format-List | Out-File 'dist\SHA256.txt'
Write-Host 'Windows x64 PE build and frozen automated tests passed. Manual Win10/11 checks remain listed in WINDOWS_ACCEPTANCE.md.'
