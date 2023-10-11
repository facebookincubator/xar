#!/usr/bin/env python
# Copyright (c) Facebook, Inc. and its affiliates. All Rights Reserved
#
# This source code is licensed under the BSD-style license found in the
# LICENSE file in the root directory of this source tree.
"""
A trivial XAR used to confirm XARs execute correctly on a host.
"""

from __future__ import absolute_import, division, print_function, unicode_literals

import os
import sys
from pathlib import Path


# We don't really use pyinit but this ensures we can import native
# code properly, which indicates the XAR is properly mounted, etc.
# For now, this is only for Linux; macs don't support native code.
if sys.platform == "linux":
    from libfb.py import pyinit

    parser = pyinit.FbcodeArgumentParser()
    opts = parser.parse_args(sys.argv[1:])

# Print any env variables that are XAR or PAR related.
for k, v in sorted(os.environ.items()):
    if k.startswith(("FB_XAR", "FB_PAR")):
        print("%s=%s" % (k, v))

assert "FB_XAR_INVOKED_NAME" in os.environ
binary_name = os.path.splitext(os.path.basename(os.getenv("FB_XAR_INVOKED_NAME")))[0]

for env in (
    "FB_PAR_RUNTIME_FILES",
    # 'LD_LIBRARY_PATH',
    # 'LD_PRELOAD',
):
    assert env in os.environ, "%s not in environment" % env

xar_mountpoint = Path(os.environ["FB_PAR_RUNTIME_FILES"])
for file in ("xar_bootstrap.sh",):
    assert os.access(xar_mountpoint / file, os.R_OK), "%s isn't accessible" % file

# When running in Linux, we expect either the Python interpreter (NativePython mode) or
# at least one shared library to be mmap'd from inside the XAR's contents.  Verify this
# by inspecting `/proc/self/maps` for something mmap'd from inside the XAR.
if sys.platform == "linux":
    with open("/proc/self/maps") as maps_file:
        maps = maps_file.read().splitlines()
    has_mapped_files_from_xar = any(str(xar_mountpoint) in line for line in maps)
    assert (
        has_mapped_files_from_xar
    ), "found at least one mmap'd file from the contents of the XAR"

print(f"ARGV_0={sys.argv[0]}")
print("ok")
