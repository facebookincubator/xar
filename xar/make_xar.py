"""
A simple script to create a mountable archive file (XAR file),
generally from an existing PAR file.

Usage (basic XAR):
  make_xar --directory=dir_to_xarify \
    --output=/path/to/output.xar
    [ --partition_extensions x --partition_extensions y .. ]

Usage (executable XAR):
  make_xar --xar_exec /path/to/xarexec \
    --inner_executable=executable_inside_squash_file \
    --parfile=parfile_to_xar \
    --output=/path/to/output_executable

This script is designed to turn any directory or existing par file
into a xar file.  It creates the squashfs file and the shebang that
invokes xarexec (if requested); this shebang contains most of the
above parameters and is baked into the resulting executable.
"""

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function
from __future__ import unicode_literals

import argparse
import logging
import os
import sys
import zipfile

from xar import py_util, xar_builder, xar_util


class XarArgumentError(Exception):
    pass


def main():
    logging.basicConfig(level=logging.DEBUG,
                        format='%(asctime)s %(levelname)s %(message)s')
    p = argparse.ArgumentParser()
    p.add_argument("--output", required=True, help="Output XAR file.")
    # XAR options
    p.add_argument("--xar-exec",
                   help="Path to xarexec, which must be present to run the "
                   "XAR file.",
                   default="/usr/bin/env xarexec")
    p.add_argument("--xar-mount-root", default=None,
                   help="Where the XAR file will mount by default.")

    p.add_argument("--xar-compression-algorithm", default="zstd",
                   help="Default compression algorithm for XAR file.")
    p.add_argument("--xar-block-size", default=256 * 1024,
                   help="Block size used when compressing XAR file.")
    p.add_argument("--xar-zstd-level", default=16,
                   help="Default zstd level when zstd compression is used.")

    group = p.add_mutually_exclusive_group(required=True)
    # Python options
    group.add_argument("--python",
                       help="Make an executable python XAR from the given"
                            "directory or zip archive.")
    p.add_argument("--python-interpreter", default=None,
                   help="Python interpreter for building and running the XAR. "
                        "If not set and constructing from a zip archive we try "
                        "to extract the shebang to get the Python interpreter."
                        "Otherwise we default to 'python'.")
    p.add_argument("--python-entry-point", default=None,
                   help="MODULE[:FUNCTION]"
                        "The entry point for the python XAR. If unset, we look "
                        "for a __main__ module in the XAR and use that.")
    # Raw options
    group.add_argument("--raw", help="Make a raw xar from a directory")
    p.add_argument("--raw-executable", default=None,
                   help="Executable invoked once the XAR is mounted. It must "
                        "be a path relative to the XAR root.If unset the XAR "
                        "is not executable.")
    opts = p.parse_args()

    squashfs_options = xar_util.SquashfsOptions()
    squashfs_options.compression_algorithm = opts.xar_compression_algorithm
    squashfs_options.block_size = opts.xar_block_size
    squashfs_options.zstd_level = opts.xar_zstd_level

    if opts.python:
        xar = xar_builder.PythonXarBuilder(opts.xar_exec, opts.xar_mount_root)
        interpreter = opts.python_interpreter
        entry_point = opts.python_entry_point
        # Either copy the directory or extract the archive.
        # Infer interpreter and entry_point if unset.
        if os.path.isdir(opts.python):
            xar.add_directory(opts.python)
            entry_point = entry_point or xar_util.get_python_main(opts.python)
        else:
            z_interpreter, z_entry_point = \
                py_util.extract_python_archive_info(opts.python)
            with zipfile.ZipFile(opts.python) as zf:
                interpreter = interpreter or z_interpreter
                entry_point = entry_point or z_entry_point
                xar.add_zipfile(zf)
        if interpreter is None:
            interpreter = '/usr/bin/env python'
        if entry_point is None:
            raise XarArgumentError("Python entry point not set and no __main__")

        xar.set_interpreter(interpreter)
        xar.set_entry_point(entry_point)
    elif opts.raw:
        xar = xar_builder.XarBuilder(opts.xar_exec, opts.xar_mount_root)
        xar.add_directory(opts.raw)
        if opts.raw_executable is not None:
            xar.set_executable(opts.raw_executable)
    else:
        raise ValueError("Unexpected value")

    xar.build(opts.output, squashfs_options)

    return 0

if __name__ == "__main__":
    sys.exit(main())
