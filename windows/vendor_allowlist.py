"""Shared vendor allowlist for the Windows PyInstaller specs.

After the v0.4.0 DOSBox-X swap, all three Windows bundle variants
(full, lite, cli) bundle the same minimal vendor closure:

  - ``qemu-img.exe``                            VHD creation
  - 7 mtools EXEs (mformat, mcopy, mattrib, ...) FAT format + file staging
  - ``dosbox-x.exe``                            Legacy DOS SYS install
  - 28 transitively-required DLLs               qemu-img + mtools deps

DOSBox-X is statically linked so it adds no DLLs to the bundle.

Earlier dosforge releases shipped qemu-system-i386.exe + ~110 MB of
GTK/SDL/codec/Spice/virgl/USB DLLs alongside the install-flow.  All of
that is replaced by the 24 MB DOSBox-X EXE; this allowlist captures the
empirically-verified minimum closure.
"""

from __future__ import annotations

VENDOR_ALLOWLIST: frozenset[str] = frozenset(
    name.lower()
    for name in (
        # Mandatory: VHD creation + FAT staging
        "qemu-img.exe",
        "mformat.exe",
        "mcopy.exe",
        "mattrib.exe",
        "mdir.exe",
        "mtype.exe",
        "mdel.exe",
        "mmd.exe",
        # DOSBox-X: legacy DOS SYS install driver (single self-contained EXE)
        "dosbox-x.exe",
        # Direct + transitive DLL dependencies of qemu-img + mtools
        # (28 files, ~19.5 MB)
        "libbrotlicommon.dll",
        "libbrotlidec.dll",
        "libbrotlienc.dll",
        "libbz2-1.dll",
        "libcrypto-3-x64.dll",
        "libcurl-4.dll",
        "libffi-8.dll",
        "libgcc_s_seh-1.dll",
        "libglib-2.0-0.dll",
        "libgmp-10.dll",
        "libgnutls-30.dll",
        "libhogweed-6.dll",
        "libiconv-2.dll",
        "libidn2-0.dll",
        "libintl-8.dll",
        "libnettle-8.dll",
        "libnfs-14.dll",
        "libp11-kit-0.dll",
        "libpcre2-8-0.dll",
        "libpsl-5.dll",
        "libssh.dll",
        "libssh2-1.dll",
        "libssp-0.dll",
        "libtasn1-6.dll",
        "libunistring-5.dll",
        "libwinpthread-1.dll",
        "libzstd.dll",
        "zlib1.dll",
    )
)
