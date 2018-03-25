#!/usr/bin/env python3
"""
A trivial XAR used to confirm XARs execute correctly on a host.
"""

import sys
import os
from pathlib import Path


# We don't really use pyinit but this ensures we can import native
# code properly, which indicates the XAR is properly mounted, etc.
# For now, this is only for Linux; macs don't support native code.
if sys.platform == 'linux':
    from libfb.py import pyinit

    parser = pyinit.FbcodeArgumentParser()
    opts = parser.parse_args(sys.argv[1:])

# Print any env variables that are XAR or PAR related.
for k, v in sorted(os.environ.items()):
    if k.startswith(('FB_XAR', 'FB_PAR')):
        print('%s=%s' % (k, v))

assert 'FB_XAR_INVOKED_NAME' in os.environ
binary_name = os.path.splitext(
    os.path.basename(os.getenv('FB_XAR_INVOKED_NAME'))
)[0]

for env in (
    'FB_PAR_RUNTIME_FILES',
    # 'LD_LIBRARY_PATH',
    # 'LD_PRELOAD',
):
    assert env in os.environ, f'{env} not in environment'

xar_mountpoint = Path(os.environ['FB_PAR_RUNTIME_FILES'])
for file in (
    'xar_bootstrap.sh',
    f'libtools_xar_{binary_name}-cxx-build-info-lib.so',
):
    assert os.access(xar_mountpoint / file, os.R_OK), f"{file} isn't accessible"

if sys.platform == 'linux':
    with open('/proc/self/maps') as maps_file:
        maps = maps_file.read()
    for file in (
        f'libtools_xar_{binary_name}-cxx-build-info-lib.so',
    ):
        assert str(xar_mountpoint / file) in maps, f"{file} not preloaded"

print('ok')
