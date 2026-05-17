"""Platform-independent pure-Python building blocks.

These modules implement the low-level disk-image primitives that the
Linux backend currently delegates to external commands (``parted``,
``mkfs.fat``, etc.). They allow the Windows backend (and, optionally,
the Linux backend) to produce the same byte-level artifacts without
any external dependency beyond ``qemu-img`` for VHD allocation.

Modules:

- :mod:`dosforge._core.vhd_footer` — read / patch the VPC-fixed VHD
  footer CHS + checksum.
- :mod:`dosforge._core.mbr` — write a single-partition MS-DOS MBR
  partition table.
- :mod:`dosforge._core.fat12_floppy` — write a FAT12 floppy IMG with
  a DOS-compatible BPB.
"""

from __future__ import annotations
