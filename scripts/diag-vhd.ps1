# diag-vhd.ps1 -- dump dosforge VHD layout to diagnose 86Box boot issues
#
# Usage: .\scripts\diag-vhd.ps1 -Path freedos.vhd

param(
    [Parameter(Mandatory)] [string] $Path
)
$ErrorActionPreference = 'Stop'
$Path = (Resolve-Path $Path).Path
$f = Get-Item $Path
$sz = $f.Length

Write-Host "=== File: $Path ==="
Write-Host ("Size on disk: {0:N0} bytes" -f $sz)

$footer = New-Object byte[] 512
$s = [IO.File]::OpenRead($Path)
$null = $s.Seek(-512, 'End')
$null = $s.Read($footer, 0, 512)
$s.Close()
$cookie = [Text.Encoding]::ASCII.GetString($footer[0..7])
$cyl = [BitConverter]::ToUInt16(([byte[]]@($footer[57], $footer[56])), 0)
$heads = $footer[58]
$spt = $footer[59]

Write-Host ""
Write-Host "=== VHD footer ==="
Write-Host ("cookie:        '$cookie'")
Write-Host ("CHS:           cyl=$cyl heads=$heads spt=$spt")

$mbr = [byte[]](Get-Content $Path -Encoding Byte -TotalCount 512)
$bootSig = '{0:x2}{1:x2}' -f $mbr[510], $mbr[511]
$mbrBootCodeNonZero = ($mbr[0..439] | Where-Object { $_ -ne 0 }).Count
Write-Host ""
Write-Host "=== MBR ==="
Write-Host ("boot sig (510..511): $bootSig (expected 55aa)")
Write-Host ("boot-code non-zero bytes (0..439): $mbrBootCodeNonZero")

$pe = $mbr[446..461]
$bootable = $pe[0]
$firstHead = $pe[1]
$firstSecCyl = $pe[2]
$firstCylLow = $pe[3]
$ptype = $pe[4]
$firstLba = [BitConverter]::ToUInt32([byte[]]$pe[8..11], 0)
$sectorCount = [BitConverter]::ToUInt32([byte[]]$pe[12..15], 0)
$firstSector = $firstSecCyl -band 0x3F
$firstCyl = ((($firstSecCyl -band 0xC0) -shl 2) -bor $firstCylLow)

Write-Host ""
Write-Host "=== Partition entry 0 ==="
Write-Host ("bootable:    0x{0:x2}" -f $bootable)
Write-Host ("type:        0x{0:x2}" -f $ptype)
Write-Host ("first_chs:   cyl=$firstCyl head=$firstHead sec=$firstSector")
Write-Host ("first_lba:   $firstLba")
Write-Host ("sectors:     $sectorCount")

if ($heads -gt 0 -and $spt -gt 0) {
    $chsLba = ($firstCyl * $heads + $firstHead) * $spt + ($firstSector - 1)
    Write-Host ("first_chs resolves to LBA: $chsLba (should equal first_lba=$firstLba)")
    if ($chsLba -ne $firstLba) {
        Write-Host "  >> MISMATCH first_chs vs first_lba <<" -ForegroundColor Red
    }
}

function Read-Sector([int64] $lba) {
    $buf = New-Object byte[] 512
    $sx = [IO.File]::OpenRead($Path)
    $null = $sx.Seek($lba * 512, 'Begin')
    $null = $sx.Read($buf, 0, 512)
    $sx.Close()
    return $buf
}

function Hex-Sig([byte[]] $buf) {
    return '{0:x2}{1:x2}' -f $buf[510], $buf[511]
}

Write-Host ""
Write-Host "=== Sector signatures (looking for 55aa) ==="
$lbas = @(0, 1, 63, $firstLba)
foreach ($lba in $lbas) {
    $b = Read-Sector $lba
    Write-Host ("LBA {0,8} (byte {1,10:N0}): {2}" -f $lba, ($lba * 512), (Hex-Sig $b))
}

$vbr = Read-Sector $firstLba
$fsTag = [Text.Encoding]::ASCII.GetString($vbr[54..61])
$oem = [Text.Encoding]::ASCII.GetString($vbr[3..10])
$vbrCodeNonZero = ($vbr[62..509] | Where-Object { $_ -ne 0 }).Count

Write-Host ""
Write-Host "=== VBR at first_lba=$firstLba ==="
Write-Host ("OEM (3..10):     '$oem'")
Write-Host ("FS type (54..61): '$fsTag'")
Write-Host ("boot-code non-zero bytes (62..509): $vbrCodeNonZero")
Write-Host ("first 16 bytes:   " + (($vbr[0..15] | ForEach-Object { '{0:x2}' -f $_ }) -join ' '))
Write-Host ("bytes 510..511:   {0:x2} {1:x2}" -f $vbr[510], $vbr[511])
