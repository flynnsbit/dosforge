# cli-smoke.ps1 — manual CLI smoke harness for dosforge on Windows.
#
# Runs every supported IMG and VHD CLI combination against a built
# dosforge.exe (the bundle), captures stdout/stderr/exit per case, and
# prints a single PASS/FAIL table at the end. Use this to confirm the
# CLI is working end-to-end before testing in any emulator.
#
# Usage:
#   .\cli-smoke.ps1                           # uses .\dist\dosforge\dosforge.exe (default)
#   .\cli-smoke.ps1 -ExePath C:\dosforge\dosforge.exe
#   .\cli-smoke.ps1 -Filter floppy            # only run cases whose name matches "floppy"
#   .\cli-smoke.ps1 -KeepArtifacts            # don't delete the generated IMG/VHD files

[CmdletBinding()]
param(
    [string] $ExePath = "$PSScriptRoot\..\dist\dosforge\dosforge.exe",
    [string] $WorkDir = "$PSScriptRoot\..\.smoke\cli-smoke",
    [string] $Filter = "",
    [switch] $KeepArtifacts
)

$ErrorActionPreference = 'Stop'
$repoRoot = (Resolve-Path "$PSScriptRoot\..").Path
$freedosAssets = Join-Path $repoRoot "dosassets\freedos"

if (-not (Test-Path $ExePath)) {
    Write-Host "ERROR: dosforge.exe not found at $ExePath" -ForegroundColor Red
    Write-Host "Build it first: .\.venv\Scripts\python.exe -m PyInstaller windows\dosforge.spec --noconfirm"
    exit 2
}
$ExePath = (Resolve-Path $ExePath).Path

if (-not (Test-Path $WorkDir)) { New-Item -ItemType Directory -Force $WorkDir | Out-Null }
$WorkDir = (Resolve-Path $WorkDir).Path

# ----- helpers -----------------------------------------------------------

$script:Results = @()

function Record($name, $passed, $expect, $detail) {
    $script:Results += [pscustomobject]@{
        Name    = $name
        Result  = if ($passed) { 'PASS' } else { 'FAIL' }
        Expect  = $expect
        Detail  = $detail
    }
    $color = if ($passed) { 'Green' } else { 'Red' }
    $tag   = if ($passed) { '[PASS]' } else { '[FAIL]' }
    Write-Host ("{0,-7} {1,-50} {2}" -f $tag, $name, $detail) -ForegroundColor $color
}

function Run-Cli([string[]] $argList, [string] $expectResult = 'success') {
    # Returns @{ ExitCode; StdOut; StdErr }. Never throws.
    $stdoutFile = [IO.Path]::GetTempFileName()
    $stderrFile = [IO.Path]::GetTempFileName()
    try {
        $proc = Start-Process -FilePath $ExePath -ArgumentList $argList `
            -NoNewWindow -PassThru -Wait `
            -RedirectStandardOutput $stdoutFile -RedirectStandardError $stderrFile
        $out = Get-Content $stdoutFile -Raw -ErrorAction SilentlyContinue
        $err = Get-Content $stderrFile -Raw -ErrorAction SilentlyContinue
        return @{ ExitCode = $proc.ExitCode; StdOut = $out; StdErr = $err }
    } finally {
        Remove-Item $stdoutFile,$stderrFile -ErrorAction SilentlyContinue
    }
}

function Should-Skip([string] $name) {
    if (-not $Filter) { return $false }
    return -not ($name -like "*$Filter*")
}

# ----- 1. Plumbing -------------------------------------------------------

Write-Host "`n=== 1. Plumbing ===" -ForegroundColor Cyan
$plumbing = @(
    @{ name='check-deps';                args=@('check-deps');                expect_in_out='All required dependencies'; },
    @{ name='check-deps img';            args=@('check-deps','--media-type','img'); expect_in_out='All required dependencies'; },
    @{ name='sudo-check';                args=@('sudo-check');                expect_in_out='Privilege diagnostics'; },
    @{ name='list-mounts';               args=@('list-mounts');               expect_in_out=''; },
    @{ name='list-martypc-formats';      args=@('list-martypc-formats');      expect_in_out='at-1024-16-63'; },
    @{ name='list-bios-drive-types';     args=@('list-bios-drive-types');     expect_in_out='phoenix'; }
)
foreach ($c in $plumbing) {
    if (Should-Skip $c.name) { continue }
    $r = Run-Cli $c.args
    $ok = ($r.ExitCode -eq 0)
    if ($ok -and $c.expect_in_out) {
        $ok = $r.StdOut -and ($r.StdOut.ToLower().Contains($c.expect_in_out.ToLower()))
    }
    $detail = "exit=$($r.ExitCode)"
    if (-not $ok -and $r.StdErr) { $detail += "  stderr=$($r.StdErr.Trim().Substring(0,[Math]::Min(80,$r.StdErr.Trim().Length)))" }
    Record $c.name $ok 'success' $detail
}

# ----- 2. Non-bootable IMG floppies (all 8 sizes) ------------------------

Write-Host "`n=== 2. Non-bootable IMG floppies ===" -ForegroundColor Cyan
$floppies = @(
    @{ size='160k';  bytes=163840 },
    @{ size='180k';  bytes=184320 },
    @{ size='360k';  bytes=368640 },
    @{ size='720k';  bytes=737280 },
    @{ size='1200k'; bytes=1228800 },
    @{ size='1440k'; bytes=1474560 },
    @{ size='1840k'; bytes=1884160 },
    @{ size='2880k'; bytes=2949120 }
)
foreach ($f in $floppies) {
    $name = "img-$($f.size)"
    if (Should-Skip $name) { continue }
    $path = Join-Path $WorkDir "$name.img"
    Remove-Item $path -ErrorAction SilentlyContinue
    $r = Run-Cli @('create','--media-type','img','--floppy-type',$f.size,'--path',$path)
    $ok = $false; $detail = "exit=$($r.ExitCode)"
    if ($r.ExitCode -eq 0 -and (Test-Path $path)) {
        $actual = (Get-Item $path).Length
        if ($actual -eq $f.bytes) {
            # Quick BPB sanity: byte 510..511 must be 55 AA.
            $b = [byte[]](Get-Content $path -Encoding Byte -TotalCount 512)
            if ($b[510] -eq 0x55 -and $b[511] -eq 0xAA) {
                $ok = $true
                $detail = "size=$actual bytes ($($f.size)), boot sig OK"
            } else {
                $detail = "boot signature missing (got $('{0:x2}{1:x2}' -f $b[510],$b[511]))"
            }
        } else {
            $detail = "size mismatch: expected $($f.bytes), got $actual"
        }
    } elseif ($r.StdErr) {
        $detail += "  stderr=" + $r.StdErr.Trim()
    }
    Record $name $ok 'success' $detail
    if (-not $KeepArtifacts) { Remove-Item $path -ErrorAction SilentlyContinue }
}

# ----- 3. Non-bootable VHDs ----------------------------------------------

Write-Host "`n=== 3. Non-bootable VHDs ===" -ForegroundColor Cyan
$vhds = @(
    @{ size='16M';  fmt='fat16'; type=0x06 },
    @{ size='32M';  fmt='fat16'; type=0x06 },
    @{ size='64M';  fmt='fat16'; type=0x06 },
    @{ size='128M'; fmt='fat32'; type=0x0C },
    @{ size='256M'; fmt='fat32'; type=0x0C },
    @{ size='512M'; fmt='fat32'; type=0x0C }
)
foreach ($v in $vhds) {
    $name = "vhd-$($v.fmt)-$($v.size)"
    if (Should-Skip $name) { continue }
    $path = Join-Path $WorkDir "$name.vhd"
    Remove-Item $path -ErrorAction SilentlyContinue
    $r = Run-Cli @('create','--media-type','vhd','--format',$v.fmt,'--size',$v.size,'--path',$path)
    $ok = $false; $detail = "exit=$($r.ExitCode)"
    if ($r.ExitCode -eq 0 -and (Test-Path $path)) {
        $b = [byte[]](Get-Content $path -Encoding Byte -TotalCount 512)
        $sigOk = ($b[510] -eq 0x55 -and $b[511] -eq 0xAA)
        $partType = $b[450]
        $firstLba = [BitConverter]::ToUInt32([byte[]]$b[454..457], 0)
        if ($sigOk -and $partType -eq $v.type -and $firstLba -eq 2048) {
            $ok = $true
            $detail = "type=0x{0:x2} first_lba={1} size={2:N0}" -f $partType, $firstLba, (Get-Item $path).Length
        } else {
            $detail = "sig=$sigOk type=0x{0:x2} (expected 0x{1:x2}) first_lba={2}" -f $partType, $v.type, $firstLba
        }
    } elseif ($r.StdErr) {
        $detail += "  stderr=" + $r.StdErr.Trim()
    }
    Record $name $ok 'success' $detail
    if (-not $KeepArtifacts) { Remove-Item $path -ErrorAction SilentlyContinue }
}

# ----- 4. VHD with custom payload ----------------------------------------

Write-Host "`n=== 4. VHD with custom payload ===" -ForegroundColor Cyan
$payloadName = 'vhd-custom-payload'
if (-not (Should-Skip $payloadName)) {
    $payload = Join-Path $WorkDir "payload-src"
    Remove-Item -Recurse -Force $payload -ErrorAction SilentlyContinue
    New-Item -ItemType Directory -Force (Join-Path $payload "TOOLS") | Out-Null
    "hello dosforge" | Out-File (Join-Path $payload "README.TXT") -Encoding ascii
    "@ECHO OFF" | Out-File (Join-Path $payload "TOOLS\HELLO.BAT") -Encoding ascii
    $path = Join-Path $WorkDir "$payloadName.vhd"
    Remove-Item $path -ErrorAction SilentlyContinue
    $r = Run-Cli @('create','--media-type','vhd','--format','fat16','--size','32M','--path',$path,'--custom-payload-path',$payload)
    $ok = $false; $detail = "exit=$($r.ExitCode)"
    if ($r.ExitCode -eq 0 -and (Test-Path $path)) {
        # mdir the partition at @@1048576 and look for the payload names.
        $mdir = Join-Path (Split-Path $ExePath -Parent) "_internal\vendor\windows\bin\mdir.exe"
        if (-not (Test-Path $mdir)) {
            $mdir = Join-Path (Split-Path $ExePath -Parent) "vendor\windows\bin\mdir.exe"
        }
        if (Test-Path $mdir) {
            $mdirOut = & $mdir -i "$path@@1048576" :: 2>&1 | Out-String
            $normalized = ($mdirOut -replace ' ','').ToUpper()
            if ($normalized.Contains('READMETXT') -and $normalized.Contains('TOOLS')) {
                $ok = $true
                $detail = "mdir found README.TXT + TOOLS"
            } else {
                $detail = "mdir missing payload files"
            }
        } else {
            $detail = "mdir.exe not found near $ExePath"
        }
    } elseif ($r.StdErr) {
        $detail += "  stderr=" + $r.StdErr.Trim()
    }
    Record $payloadName $ok 'success' $detail
    if (-not $KeepArtifacts) {
        Remove-Item $path -ErrorAction SilentlyContinue
        Remove-Item -Recurse -Force $payload -ErrorAction SilentlyContinue
    }
}

# ----- 5. Machine targets ------------------------------------------------

Write-Host "`n=== 5. Machine-target VHDs ===" -ForegroundColor Cyan
$xebec = @(
    @{ type='type2';  cyl=615; heads=4; spt=17 },
    @{ type='type13'; cyl=306; heads=8; spt=17 },
    @{ type='type16'; cyl=612; heads=4; spt=17 }
)
foreach ($x in $xebec) {
    $name = "vhd-xebec-$($x.type)"
    if (Should-Skip $name) { continue }
    $path = Join-Path $WorkDir "$name.vhd"
    Remove-Item $path -ErrorAction SilentlyContinue
    $r = Run-Cli @('create','--media-type','vhd','--format','fat16','--machine-target','martypc-xebec','--martypc-xebec-drive-type',$x.type,'--path',$path)
    $ok = $false; $detail = "exit=$($r.ExitCode)"
    if ($r.ExitCode -eq 0 -and (Test-Path $path)) {
        $sz = (Get-Item $path).Length
        $footer = New-Object byte[] 512
        $stream = [IO.File]::OpenRead($path)
        $null = $stream.Seek(-512, 'End')
        $null = $stream.Read($footer, 0, 512)
        $stream.Close()
        $cyl = [BitConverter]::ToUInt16(([byte[]]@($footer[57], $footer[56])), 0)
        $heads = $footer[58]; $spt = $footer[59]
        if ($cyl -eq $x.cyl -and $heads -eq $x.heads -and $spt -eq $x.spt) {
            $ok = $true
            $detail = "CHS={0}/{1}/{2} size={3:N0}" -f $cyl, $heads, $spt, $sz
        } else {
            $detail = "CHS mismatch: got {0}/{1}/{2}, expected {3}/{4}/{5}" -f $cyl, $heads, $spt, $x.cyl, $x.heads, $x.spt
        }
    } elseif ($r.StdErr) {
        $detail += "  stderr=" + $r.StdErr.Trim()
    }
    Record $name $ok 'success' $detail
    if (-not $KeepArtifacts) { Remove-Item $path -ErrorAction SilentlyContinue }
}

$xtideName = 'vhd-xtide-504m'
if (-not (Should-Skip $xtideName)) {
    $path = Join-Path $WorkDir "$xtideName.vhd"
    Remove-Item $path -ErrorAction SilentlyContinue
    $r = Run-Cli @('create','--media-type','vhd','--format','fat16','--machine-target','martypc-xtide','--martypc-at-drive-type','at-1024-16-63','--path',$path)
    $ok = $false; $detail = "exit=$($r.ExitCode)"
    if ($r.ExitCode -eq 0 -and (Test-Path $path)) {
        $expectedTotal = 1024 * 16 * 63 * 512
        $actual = (Get-Item $path).Length - 512
        if ($actual -eq $expectedTotal) {
            $ok = $true
            $detail = "504 MiB exact data area"
        } else {
            $detail = "size mismatch: expected $expectedTotal, got $actual"
        }
    } elseif ($r.StdErr) {
        $detail += "  stderr=" + $r.StdErr.Trim()
    }
    Record $xtideName $ok 'success' $detail
    if (-not $KeepArtifacts) { Remove-Item $path -ErrorAction SilentlyContinue }
}

# ----- 6. Bootable FreeDOS FAT16 VHD ------------------------------------

Write-Host "`n=== 6. Bootable FreeDOS FAT16 VHD ===" -ForegroundColor Cyan
$freedosVhdName = 'vhd-freedos-fat16'
if (-not (Should-Skip $freedosVhdName)) {
    # Use the bundled freedos assets (works for both editable installs
    # and the bundled exe — dosassets/freedos/ at the bundle root).
    $assets = $freedosAssets
    if (-not (Test-Path $assets)) {
        $bundled = Join-Path (Split-Path $ExePath -Parent) "dosassets\freedos"
        if (Test-Path $bundled) { $assets = $bundled }
    }
    if (Test-Path $assets) {
        $path = Join-Path $WorkDir "$freedosVhdName.vhd"
        Remove-Item $path -ErrorAction SilentlyContinue
        $r = Run-Cli @('create','--media-type','vhd','--format','fat16','--size','64M','--path',$path,'--boot-mode','freedos','--freedos-source','local','--boot-assets-path',$assets)
        $ok = $false; $detail = "exit=$($r.ExitCode)"
        if ($r.ExitCode -eq 0 -and (Test-Path $path)) {
            $b = [byte[]](Get-Content $path -Encoding Byte -TotalCount 512)
            $mbrCode = ($b[0..439] | Where-Object { $_ -ne 0 }).Count
            $vbr = New-Object byte[] 512
            $stream = [IO.File]::OpenRead($path)
            $null = $stream.Seek(1048576, 'Begin')
            $null = $stream.Read($vbr, 0, 512)
            $stream.Close()
            $vbrSig = ($vbr[510] -eq 0x55) -and ($vbr[511] -eq 0xAA)
            if ($mbrCode -ge 200 -and $vbrSig) {
                $ok = $true
                $detail = "MBR code: $mbrCode non-zero bytes; VBR signature OK"
            } else {
                $detail = "MBR code: $mbrCode bytes (expected >=200); VBR sig=$vbrSig"
            }
        } elseif ($r.StdErr) {
            $detail += "  stderr=" + $r.StdErr.Trim()
        }
        Record $freedosVhdName $ok 'success' $detail
        if (-not $KeepArtifacts) { Remove-Item $path -ErrorAction SilentlyContinue }
    } else {
        Record $freedosVhdName $false 'success' "dosassets/freedos not found near $ExePath or repo"
    }
}

# ----- 7. Negative cases (must reject cleanly) --------------------------

Write-Host "`n=== 7. Negative cases (clean rejections) ===" -ForegroundColor Cyan
$negative = @(
    @{ name='reject-msdos33';  args=@('create','--media-type','vhd','--format','fat16','--size','32M','--boot-mode','msdos33',  '--path','{path}'); expect='not yet supported' },
    @{ name='reject-msdos331'; args=@('create','--media-type','vhd','--format','fat16','--size','32M','--boot-mode','msdos331', '--path','{path}'); expect='not yet supported' },
    @{ name='reject-msdos622'; args=@('create','--media-type','vhd','--format','fat16','--size','32M','--boot-mode','msdos622', '--path','{path}'); expect='not yet supported' },
    @{ name='reject-compaq331';args=@('create','--media-type','vhd','--format','fat16','--size','32M','--boot-mode','compaq331','--path','{path}'); expect='not yet supported' },
    @{ name='reject-pcdos';    args=@('create','--media-type','vhd','--format','fat16','--size','32M','--boot-mode','pcdos',    '--path','{path}'); expect='not yet supported' },
    @{ name='reject-pcdos7';   args=@('create','--media-type','vhd','--format','fat16','--size','32M','--boot-mode','pcdos7',   '--path','{path}'); expect='not yet supported' },
    @{ name='reject-ibm8088';  args=@('create','--media-type','vhd','--format','fat16','--size','32M','--boot-mode','ibm8088','--ibm-dos-version','dos33','--path','{path}'); expect='not yet supported' },
    @{ name='reject-freedos-fat32'; args=@('create','--media-type','vhd','--format','fat32','--size','128M','--boot-mode','freedos','--freedos-source','local','--boot-assets-path',$freedosAssets,'--path','{path}'); expect='fat16' }
)
foreach ($n in $negative) {
    if (Should-Skip $n.name) { continue }
    $path = Join-Path $WorkDir "$($n.name).vhd"
    Remove-Item $path -ErrorAction SilentlyContinue
    $resolvedArgs = $n.args | ForEach-Object { if ($_ -eq '{path}') { $path } else { $_ } }
    $r = Run-Cli $resolvedArgs
    # Pass = non-zero exit, message contains the expected snippet, no Python traceback in stderr.
    $combined = "$($r.StdOut)`n$($r.StdErr)".ToLower()
    $hasTraceback = $r.StdErr -and $r.StdErr.Contains('Traceback (most recent call last)')
    $hasExpect = $combined.Contains($n.expect.ToLower())
    $ok = ($r.ExitCode -ne 0) -and $hasExpect -and -not $hasTraceback
    $detail = "exit=$($r.ExitCode) found_msg=$hasExpect traceback=$hasTraceback"
    Record $n.name $ok 'rejection' $detail
    Remove-Item $path -ErrorAction SilentlyContinue
}

# ----- summary -----------------------------------------------------------

Write-Host ""
Write-Host "=== Summary ===" -ForegroundColor Cyan
$pass = ($script:Results | Where-Object { $_.Result -eq 'PASS' }).Count
$fail = ($script:Results | Where-Object { $_.Result -eq 'FAIL' }).Count
$total = $pass + $fail
Write-Host ("Total: {0}    PASS: {1}    FAIL: {2}" -f $total, $pass, $fail) -ForegroundColor $(if ($fail -eq 0) { 'Green' } else { 'Red' })
Write-Host ""
$script:Results | Format-Table -AutoSize | Out-String | Write-Host

if ($fail -gt 0) {
    Write-Host "FAIL details:" -ForegroundColor Red
    $script:Results | Where-Object { $_.Result -eq 'FAIL' } | ForEach-Object {
        Write-Host ("  - {0}: {1}" -f $_.Name, $_.Detail) -ForegroundColor Red
    }
    exit 1
}
exit 0
