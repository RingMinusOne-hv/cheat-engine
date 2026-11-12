<#
    build_turing_explorer.ps1 -- build "Turing Explorer": this Cheat Engine (with its Turing-HV backend) with no Cheat
    Engine name or vocabulary in anything it ships, as a ready-to-run folder.

      1. rebrand\rebrand.py stage: copy the source to -Stage and rebrand the copy (the repository is not changed)
      2. lazbuild -B (Release 64-Bit) in the copy -> turing-explorer.exe (-dTURING_EXPLORER: the backend starts with it)
      3. rebrand\rebrand.py dist: assemble -Dist (the exe, the trusted thvbridge.exe and turinghv.dll from bin\, the Lua
         runtime, the scripts and data it reads) -- no driver, no injectable DLLs, no update check
      4. rebrand\rebrand.py scan: every file of -Dist searched for the old names; prints what is left (should be nothing)
      5. te-broker.exe --selftest (elevated): the hypervisor still serves the copied bridge (thvbridge.exe, renamed)

    The bridge is the one in bin\ (trusted by its code pages, so copying it keeps the trust; only its help text is
    patched, same length).  Rebuild and re-trust it with build_thvbridge.ps1 as before; then run this again.

        powershell -ExecutionPolicy Bypass -File "Cheat Engine\turinghv\build_turing_explorer.ps1" [-Dist <dir>] [-Stage <dir>] [-Art purple|ce|mark]

    -Art: the program icon and the logos -- purple (default): Cheat Engine's with its blue turned purple; ce: Cheat
    Engine's as they are; mark: the generated Turing Explorer mark.
    Needs Lazarus at C:\lazarus and Python 3 with Pillow (the pictures).  About 5 minutes (the clean build).
#>
param([string]$Dist = 'C:\projs\turing-explorer', [string]$Stage = 'C:\projs\turing-explorer-build', [switch]$NoBuild,
      [ValidateSet('purple', 'ce', 'mark')][string]$Art = 'purple')
$ErrorActionPreference = 'Stop'
$here = $PSScriptRoot
$src = (Resolve-Path (Join-Path $here '..')).Path
$py = Join-Path $here 'rebrand\rebrand.py'

foreach ($d in $Dist, $Stage) {
    if ($d -match '(?i)cheat') { throw "$d holds 'cheat': choose a folder without it (the path is visible to other programs)" }
}
if (Get-Process turing-explorer -ErrorAction SilentlyContinue | Where-Object { $_.Path -like "$Dist\*" }) {
    throw 'Turing Explorer is running from the output folder: close it first'
}

if (-not $NoBuild) {
    & python $py stage --src $src --stage $Stage --art $Art
    if ($LASTEXITCODE -ne 0) { throw 'rebrand stage failed' }
    $log = Join-Path $Stage 'build.log'
    Write-Host 'building (clean build, a few minutes)...'
    & 'C:\lazarus\lazbuild.exe' -B --build-mode="Release 64-Bit" (Join-Path $Stage 'turingexplorer.lpi') *> $log
    if ($LASTEXITCODE -ne 0) {
        Get-Content $log | Select-String -Pattern ' Error: | Fatal: ' | Select-Object -First 20 | ForEach-Object { Write-Host $_ -ForegroundColor Red }
        throw "the build failed (see $log)"
    }
}
& python $py dist --src $src --stage $Stage --dist $Dist
if ($LASTEXITCODE -ne 0) { throw 'rebrand dist failed' }
& python $py scan --dist $Dist --show 3
$clean = $LASTEXITCODE -eq 0

$admin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
    [Security.Principal.WindowsBuiltInRole]::Administrator)
if ($admin) { & (Join-Path $Dist 'te-broker.exe') --selftest } else { Write-Host 'not elevated: skipped te-broker.exe --selftest' }

if ($clean) { Write-Host "Done: $Dist\turing-explorer.exe" -ForegroundColor Green }
else { Write-Host "Built, but the scan above found old names in $Dist" -ForegroundColor Yellow }
