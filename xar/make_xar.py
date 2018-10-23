# Copyright (c) Facebook, Inc. and its affiliates. All Rights Reserved
#
# This source code is licensed under the BSD-style license found in the
# LICENSE file in the root directory of this source tree.
"""
A simple script to create a mountable archive file (XAR file), from an existing
Python executable archive, or a directory.

Usage (basic XAR):
  make_xar --raw=dir_to_xarify \
    --output=/path/to/output.xar

Usage (executable XAR):
  make_xar --xar_exec=/path/to/xarexec \
    --raw-executable=executable_inside_squash_file \
    --output=/path/to/output_executable

Usage (Python XAR):
  make_xar --python=dir_or_archive_to_xarify \
    --python-entry-point=module.in.squash_file:main_function

The script is designed to turn any directory or existing Python executable
archive into a xar file. It creates the squashfs file and the shebang that
invokes xarexec (if requested). The xar_builder API is available for more
involved use cases.
"""

from __future__ import absolute_import, division, print_function, unicode_literals

import argparse
import logging
import os
import sys
import zipfile

from xar import py_util, xar_builder, xar_util


class XarArgumentError(Exception):
    pass


def main(args=None):
    logging.basicConfig(
        level=logging.DEBUG, format="%(asctime)s %(levelname)s %(message)s"
    )
    p = argparse.ArgumentParser()
    p.add_argument("--output", required=True, help="Output XAR file.")
    # XAR options
    p.add_argument(
        "--xar-exec",
        help="Path to xarexec, which must be present to run the XAR file.",
        default="/usr/bin/env xarexec_fuse",
    )
    p.add_argument(
        "--xar-mount-root",
        default=None,
        help="Where the XAR file will mount by default.",
    )

    p.add_argument(
        "--xar-compression-algorithm",
        default="gzip",
        help="Compression algorithm for the XAR file.",
    )
    p.add_argument(
        "--xar-block-size",
        default=256 * 1024,
        help="Block size used when compressing the XAR file.",
    )
    p.add_argument(
        "--xar-zstd-level",
        default=16,
        help="Default zstd level when zstd compression is used.",
    )

    group = p.add_mutually_exclusive_group(required=True)
    # Python options
    group.add_argument(
        "--python",
        help="Make an executable python XAR from the given" "directory or zip archive.",
    )
    p.add_argument(
        "--python-interpreter",
        default=None,
        help="Python interpreter for building and running the XAR. "
        "If not set and constructing from a zip archive we try "
        "to extract the shebang to get the Python interpreter. "
        "Otherwise we default to an interpreter compatible with the running Python.",
    )
    p.add_argument(
        "--python-entry-point",
        default=None,
        help="MODULE[:FUNCTION]"
        "The entry point for the python XAR. If unset, we look "
        "for a __main__ module in the XAR and use that.",
    )
    # Raw options
    group.add_argument("--raw", help="Make a raw xar from a directory")
    p.add_argument(
        "--raw-executable",
        default=None,
        help="Executable invoked once the XAR is mounted. It must "
        "be a path relative to the XAR root. If unset the XAR "
        "is not executable. The arguments passed to the executable when "
        "invoked are the XAR path, followed by all the arguments passed to "
        "the XAR.",
    )
    opts = p.parse_args(args)

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
            entry_point = entry_point or py_util.get_python_main(opts.python)
        else:
            z_interpreter, z_entry_point = py_util.extract_python_archive_info(
                opts.python
            )
            with zipfile.ZipFile(opts.python) as zf:
                interpreter = interpreter or z_interpreter
                entry_point = entry_point or z_entry_point
                xar.add_zipfile(zf)
        if entry_point is None:
            raise XarArgumentError("Python entry point not set and no __main__")

        if interpreter is not None:
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
