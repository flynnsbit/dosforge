# build-testimages.ps1 -- build a bootable image for every dosforge
# IMG and VHD combo currently supported on Windows. Outputs to
# .\testimages\. Prints a PASS/FAIL summary at the end.

param(
    [string] $ExePath = "$PSScriptRoot\..\dist\dosforge\dosforge.exe",
    [string] $OutDir = "$PSScriptRoot\..\testimages"
)

$ErrorActionPreference = 'Continue'
$ExePath = (Resolve-Path $ExePath).Path
if (-not (Test-Path $OutDir)) { New-Item -ItemType Directory -Force $OutDir | Out-Null }
$OutDir = (Resolve-Path $OutDir).Path

$repoRoot = (Resolve-Path "$PSScriptRoot\..").Path
$results = @()

function Build-Image($name, $argList) {
    $start = Get-Date
    Write-Host ""
    Write-Host "=== $name ===" -ForegroundColor Cyan
    $target = $argList[($argList.IndexOf('--path') + 1)]
    Remove-Item $target -ErrorAction SilentlyContinue
    $stdout = [IO.Path]::GetTempFileName()
    $stderr = [IO.Path]::GetTempFileName()
    try {
        $proc = Start-Process -FilePath $ExePath -ArgumentList $argList `
            -NoNewWindow -PassThru -Wait `
            -RedirectStandardOutput $stdout -RedirectStandardError $stderr
        $ok = $proc.ExitCode -eq 0 -and (Test-Path $target)
        $size = if ($ok) { (Get-Item $target).Length } else { 0 }
        $elapsed = ((Get-Date) - $start).TotalSeconds
        $errLine = ''
        if (-not $ok) {
            $errText = (Get-Content $stderr -Raw -ErrorAction SilentlyContinue)
            if ($errText) { $errLine = $errText.Trim().Split("`n")[0] }
        }
        $script:results += [pscustomobject]@{
            Name = $name
            Result = if ($ok) { 'PASS' } else { 'FAIL' }
            Path = if ($ok) { (Resolve-Path $target).Path } else { '' }
            SizeBytes = $size
            Seconds = [Math]::Round($elapsed, 1)
            Error = $errLine
        }
        $color = if ($ok) { 'Green' } else { 'Red' }
        $tag = if ($ok) { '[PASS]' } else { '[FAIL]' }
        $detail = if ($ok) { ("{0:N0} bytes in {1:N1}s" -f $size, $elapsed) } else { $errLine }
        Write-Host ("{0} {1}: {2}" -f $tag, $name, $detail) -ForegroundColor $color
    } finally {
        Remove-Item $stdout, $stderr -ErrorAction SilentlyContinue
    }
}

Write-Host "Output dir: $OutDir" -ForegroundColor Yellow
Write-Host "Using:      $ExePath" -ForegroundColor Yellow

# ============================================================================
# VHDs
# ============================================================================

# FreeDOS FAT16, generic AT-class (86Box default, 504 MiB cap)
Build-Image "vhd-freedos-fat16-64m" @(
    'create', '--media-type','vhd', '--format','fat16', '--size','64M',
    '--path',(Join-Path $OutDir 'vhd-freedos-fat16-64m.vhd'),
    '--boot-mode','freedos', '--freedos-source','local',
    '--boot-assets-path',(Join-Path $repoRoot 'dosassets\freedos')
)

# NOTE: FreeDOS on Xebec is NOT supported (Xebec is XT-class and only
# accepts XT-era DOS modes: none/ibm8088/msdos33/msdos331/pcdos/compaq331).
# For FreeDOS on MartyPC use martypc-xtide (AT-class) below.

# FreeDOS FAT16, MartyPC XT-IDE 504 MiB standard cap
Build-Image "vhd-freedos-marty-xtide-504m" @(
    'create', '--media-type','vhd', '--format','fat16',
    '--machine-target','martypc-xtide', '--martypc-at-drive-type','at-1024-16-63',
    '--path',(Join-Path $OutDir 'vhd-freedos-marty-xtide-504m.vhd'),
    '--boot-mode','freedos', '--freedos-source','local',
    '--boot-assets-path',(Join-Path $repoRoot 'dosassets\freedos')
)

# NOTE: MS-DOS 3.30 and IBM 8088 (dos33) require XT-class geometry
# (max 17 spt). The generic AT-class profile (63 spt) is incompatible
# with the DOS 3.3 SYS step. Use martypc-xebec for these modes.

# MS-DOS 3.30 on MartyPC Xebec (XT) — the exact combo you just verified
Build-Image "vhd-msdos33-marty-xebec-type2" @(
    'create', '--media-type','vhd', '--format','fat16',
    '--machine-target','martypc-xebec', '--martypc-xebec-drive-type','type2',
    '--path',(Join-Path $OutDir 'vhd-msdos33-marty-xebec-type2.vhd'),
    '--boot-mode','msdos33',
    '--boot-assets-path',(Join-Path $repoRoot 'dosassets\msdos33')
)

# MS-DOS 3.31 (Microsoft OEM build, capped at 32 MiB)
Build-Image "vhd-msdos331-32m" @(
    'create', '--media-type','vhd', '--format','fat16', '--size','32M',
    '--path',(Join-Path $OutDir 'vhd-msdos331-32m.vhd'),
    '--boot-mode','msdos331',
    '--boot-assets-path',(Join-Path $repoRoot 'dosassets\msdos331')
)

# Compaq DOS 3.31 (supports FAT16B up to ~504 MiB)
Build-Image "vhd-compaq331-128m" @(
    'create', '--media-type','vhd', '--format','fat16', '--size','128M',
    '--path',(Join-Path $OutDir 'vhd-compaq331-128m.vhd'),
    '--boot-mode','compaq331',
    '--boot-assets-path',(Join-Path $repoRoot 'dosassets\compaq331')
)

# IBM DOS 3.3 (8088/V20 profile) on MartyPC Xebec — same install media as msdos33
Build-Image "vhd-ibm8088-dos33-xebec-type2" @(
    'create', '--media-type','vhd', '--format','fat16',
    '--machine-target','martypc-xebec', '--martypc-xebec-drive-type','type2',
    '--path',(Join-Path $OutDir 'vhd-ibm8088-dos33-xebec-type2.vhd'),
    '--boot-mode','ibm8088', '--ibm-dos-version','dos33',
    '--boot-assets-path',(Join-Path $repoRoot 'dosassets\msdos33')
)

# Non-bootable utility VHDs (handy for data scratch)
Build-Image "vhd-blank-fat16-32m" @(
    'create', '--media-type','vhd', '--format','fat16', '--size','32M',
    '--path',(Join-Path $OutDir 'vhd-blank-fat16-32m.vhd')
)
Build-Image "vhd-blank-fat32-256m" @(
    'create', '--media-type','vhd', '--format','fat32', '--size','256M',
    '--path',(Join-Path $OutDir 'vhd-blank-fat32-256m.vhd')
)

# MS-DOS 5.0 (FAT16, generic AT-class)
Build-Image "vhd-msdos5-64m" @(
    'create', '--media-type','vhd', '--format','fat16', '--size','64M',
    '--path',(Join-Path $OutDir 'vhd-msdos5-64m.vhd'),
    '--boot-mode','msdos5',
    '--boot-assets-path',(Join-Path $repoRoot 'dosassets\msdos5')
)

# MS-DOS 6.22 (FAT16, generic AT-class)
Build-Image "vhd-msdos622-128m" @(
    'create', '--media-type','vhd', '--format','fat16', '--size','128M',
    '--path',(Join-Path $OutDir 'vhd-msdos622-128m.vhd'),
    '--boot-mode','msdos622',
    '--boot-assets-path',(Join-Path $repoRoot 'dosassets\msdos622')
)

# IBM PC-DOS 7.0 (FAT16, generic AT-class)
Build-Image "vhd-pcdos7-128m" @(
    'create', '--media-type','vhd', '--format','fat16', '--size','128M',
    '--path',(Join-Path $OutDir 'vhd-pcdos7-128m.vhd'),
    '--boot-mode','pcdos7',
    '--boot-assets-path',(Join-Path $repoRoot 'dosassets\pcdos7')
)

# MS-DOS 7.1 / Win98 (FAT32, generic AT-class).
# Uses DOS71_1S.PAK extracted from disk01.img inside the install
# diskettes; the .7z under dosassets/msdos71/ is auto-unpacked too.
Build-Image "vhd-msdos71-256m" @(
    'create', '--media-type','vhd', '--format','fat32', '--size','256M',
    '--path',(Join-Path $OutDir 'vhd-msdos71-256m.vhd'),
    '--boot-mode','msdos71',
    '--boot-assets-path',(Join-Path $repoRoot 'dosassets\msdos71')
)

# ============================================================================
# FULL profile (--dos-install-profile full = "startup files + DOS tools").
# Stages CONFIG.SYS, AUTOEXEC.BAT, and a C:\DOS\ (or C:\FDOS\) tree
# containing FDISK, FORMAT, EDIT, etc. Matches the Linux behavior.
# ============================================================================

Build-Image "vhd-freedos-full-fat16-128m" @(
    'create', '--media-type','vhd', '--format','fat16', '--size','128M',
    '--path',(Join-Path $OutDir 'vhd-freedos-full-fat16-128m.vhd'),
    '--boot-mode','freedos', '--freedos-source','local',
    '--dos-install-profile','full',
    '--boot-assets-path',(Join-Path $repoRoot 'dosassets\freedos')
)

Build-Image "vhd-msdos33-full-marty-xebec-type2" @(
    'create', '--media-type','vhd', '--format','fat16',
    '--machine-target','martypc-xebec', '--martypc-xebec-drive-type','type2',
    '--path',(Join-Path $OutDir 'vhd-msdos33-full-marty-xebec-type2.vhd'),
    '--boot-mode','msdos33',
    '--dos-install-profile','full',
    '--boot-assets-path',(Join-Path $repoRoot 'dosassets\msdos33')
)

Build-Image "vhd-msdos331-full-32m" @(
    'create', '--media-type','vhd', '--format','fat16', '--size','32M',
    '--path',(Join-Path $OutDir 'vhd-msdos331-full-32m.vhd'),
    '--boot-mode','msdos331',
    '--dos-install-profile','full',
    '--boot-assets-path',(Join-Path $repoRoot 'dosassets\msdos331')
)

Build-Image "vhd-compaq331-full-128m" @(
    'create', '--media-type','vhd', '--format','fat16', '--size','128M',
    '--path',(Join-Path $OutDir 'vhd-compaq331-full-128m.vhd'),
    '--boot-mode','compaq331',
    '--dos-install-profile','full',
    '--boot-assets-path',(Join-Path $repoRoot 'dosassets\compaq331')
)

Build-Image "vhd-ibm8088-dos33-full-xebec-type2" @(
    'create', '--media-type','vhd', '--format','fat16',
    '--machine-target','martypc-xebec', '--martypc-xebec-drive-type','type2',
    '--path',(Join-Path $OutDir 'vhd-ibm8088-dos33-full-xebec-type2.vhd'),
    '--boot-mode','ibm8088', '--ibm-dos-version','dos33',
    '--dos-install-profile','full',
    '--boot-assets-path',(Join-Path $repoRoot 'dosassets\msdos33')
)

Build-Image "vhd-msdos5-full-128m" @(
    'create', '--media-type','vhd', '--format','fat16', '--size','128M',
    '--path',(Join-Path $OutDir 'vhd-msdos5-full-128m.vhd'),
    '--boot-mode','msdos5',
    '--dos-install-profile','full',
    '--boot-assets-path',(Join-Path $repoRoot 'dosassets\msdos5')
)

Build-Image "vhd-msdos622-full-256m" @(
    'create', '--media-type','vhd', '--format','fat16', '--size','256M',
    '--path',(Join-Path $OutDir 'vhd-msdos622-full-256m.vhd'),
    '--boot-mode','msdos622',
    '--dos-install-profile','full',
    '--boot-assets-path',(Join-Path $repoRoot 'dosassets\msdos622')
)

Build-Image "vhd-pcdos7-full-256m" @(
    'create', '--media-type','vhd', '--format','fat16', '--size','256M',
    '--path',(Join-Path $OutDir 'vhd-pcdos7-full-256m.vhd'),
    '--boot-mode','pcdos7',
    '--dos-install-profile','full',
    '--boot-assets-path',(Join-Path $repoRoot 'dosassets\pcdos7')
)

Build-Image "vhd-msdos71-full-504m" @(
    'create', '--media-type','vhd', '--format','fat32', '--size','504M',
    '--path',(Join-Path $OutDir 'vhd-msdos71-full-504m.vhd'),
    '--boot-mode','msdos71',
    '--dos-install-profile','full',
    '--boot-assets-path',(Join-Path $repoRoot 'dosassets\msdos71')
)

# PC-DOS 7.1 (the only PC-DOS variant with FAT32 + LBA support).
# Built via the QEMU-driven FORMAT32 install — boot sector OEM 'IBM  7.1'
# is written by FORMAT32 itself, IBMBIO.COM/IBMDOS.COM/COMMAND.COM are
# transferred in the order PC-DOS's boot loader requires. Minimum 1 GiB
# (FORMAT32 rejects smaller FAT32 partitions with "drive too small").
Build-Image "vhd-pcdos71-fat32-2g" @(
    'create', '--media-type','vhd', '--format','fat32', '--size','2G',
    '--path',(Join-Path $OutDir 'vhd-pcdos71-fat32-2g.vhd'),
    '--boot-mode','pcdos71',
    '--dos-install-profile','full',
    '--boot-assets-path',(Join-Path $repoRoot 'dosassets\pcdos71')
)

# MS-DOS 3.30 bootable 360K floppy (verified working on Windows after
# the mtools cwd fix that landed earlier in this port).
Build-Image "img-msdos33-360k" @(
    'create', '--media-type','img', '--floppy-type','360k',
    '--img-system-format', '--boot-mode','msdos33',
    '--path',(Join-Path $OutDir 'img-msdos33-360k.img'),
    '--boot-assets-path',(Join-Path $repoRoot 'dosassets\msdos33')
)

# MS-DOS 5.0 bootable 720K floppy
Build-Image "img-msdos5-720k" @(
    'create', '--media-type','img', '--floppy-type','720k',
    '--img-system-format', '--boot-mode','msdos5',
    '--path',(Join-Path $OutDir 'img-msdos5-720k.img'),
    '--boot-assets-path',(Join-Path $repoRoot 'dosassets\msdos5')
)

# MS-DOS 6.22 bootable 1.44 MB floppy
Build-Image "img-msdos622-1440k" @(
    'create', '--media-type','img', '--floppy-type','1440k',
    '--img-system-format', '--boot-mode','msdos622',
    '--path',(Join-Path $OutDir 'img-msdos622-1440k.img'),
    '--boot-assets-path',(Join-Path $repoRoot 'dosassets\msdos622')
)

# IBM PC-DOS 7.0 bootable 1.44 MB floppy (direct system-file assets in
# dosassets\pcdos7\ — works on Windows even though the install media
# itself is XDF and can't be extracted natively).
Build-Image "img-pcdos7-1440k" @(
    'create', '--media-type','img', '--floppy-type','1440k',
    '--img-system-format', '--boot-mode','pcdos7',
    '--path',(Join-Path $OutDir 'img-pcdos7-1440k.img'),
    '--boot-assets-path',(Join-Path $repoRoot 'dosassets\pcdos7')
)

# MS-DOS 3.30 on MartyPC Xebec Type 1 (10 MiB / FAT12) — the smallest
# vintage MFM geometry dosforge supports.
Build-Image "vhd-msdos33-xebec-type1-fat12" @(
    'create', '--media-type','vhd', '--format','fat12',
    '--machine-target','martypc-xebec', '--martypc-xebec-drive-type','type1',
    '--path',(Join-Path $OutDir 'vhd-msdos33-xebec-type1-fat12.vhd'),
    '--boot-mode','msdos33',
    '--boot-assets-path',(Join-Path $repoRoot 'dosassets\msdos33')
)

# ============================================================================
# Floppy IMGs (system-format = bootable)
# ============================================================================
# Each floppy size that's big enough to hold its DOS variant's boot
# files. The "Disk full" cases (FreeDOS 1440k overflowing on FDOS/BIN)
# would show up as FAIL — those are pre-existing CONFIG.SYS C: vs A:
# issues and unrelated to the IMG creation pipeline.

# Known gap on Windows:
#  - FreeDOS img-system-format: the slim FreeDOS bundle's FDOS/BIN
#    payload exceeds 1.44M and 2.88M. Boot sector + KERNEL.SYS land
#    successfully but mcopy fails partway through FDOS/BIN. The
#    resulting .img is bootable but the FDOS/ tree is incomplete.
#  - MS-DOS 3.30 img-system-format: the Windows IMG asset resolver
#    does not yet extract IO.SYS/MSDOS.SYS/COMMAND.COM from DISK01.IMG
#    floppy images. Drop those flopppy combos until the IMG-side
#    legacy DOS installer is wired up.

# Non-bootable utility floppies in every size dosforge supports
foreach ($sz in '160k','180k','360k','720k','1200k','1440k','1840k','2880k') {
    Build-Image "img-blank-$sz" @(
        'create', '--media-type','img', '--floppy-type',$sz,
        '--path',(Join-Path $OutDir "img-blank-$sz.img")
    )
}

# ============================================================================
# Summary
# ============================================================================

Write-Host ""
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "Summary" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan
$pass = ($results | Where-Object Result -eq 'PASS').Count
$fail = ($results | Where-Object Result -eq 'FAIL').Count
$total = $pass + $fail
Write-Host ("Total: {0}   PASS: {1}   FAIL: {2}" -f $total, $pass, $fail) -ForegroundColor $(if ($fail -eq 0) { 'Green' } else { 'Yellow' })
Write-Host ""
$results | Sort-Object Name | Format-Table -AutoSize | Out-String | Write-Host

if ($fail -gt 0) {
    Write-Host "Failures:" -ForegroundColor Red
    $results | Where-Object Result -eq 'FAIL' | ForEach-Object {
        Write-Host ("  $($_.Name): $($_.Error)") -ForegroundColor Red
    }
}

# Manifest
$manifest = Join-Path $OutDir "MANIFEST.txt"
$lines = @(
    "dosforge test images",
    ("Built: " + (Get-Date -Format 'yyyy-MM-dd HH:mm:ss')),
    ("Generator: $ExePath"),
    "",
    "Filename                                 Size (bytes)  Notes",
    "----------------------------------------- ------------  -----"
)
foreach ($r in ($results | Sort-Object Name)) {
    if ($r.Result -eq 'PASS') {
        $base = Split-Path $r.Path -Leaf
        $lines += ("{0,-41} {1,12:N0}" -f $base, $r.SizeBytes)
    }
}
$lines | Out-File $manifest -Encoding utf8
Write-Host "Manifest: $manifest"
