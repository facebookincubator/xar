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

import logging
import os
import shutil
import sys
import tempfile
import time
import zipfile
import argparse

from xar import xar_util

MAX_SHEBANG = 128  # from linux/include/linux/binfmts.h's BINPRM_BUF_SIZE

def main(args):
    logging.basicConfig(level=logging.DEBUG,
                        format='%(asctime)s %(levelname)s %(message)s')
    p = argparse.ArgumentParser()
    p.add_argument("--xar_exec",
                   help="path to xarexec, which must be present to run the "
                   "XAR file",
                   default="/usr/bin/env xarexec_fuse")
    p.add_argument("--inner_executable",
                   help="executable invoked once the XAR is mounted")
    group = p.add_mutually_exclusive_group(required=True)
    group.add_argument("--parfile", help="python parfile to convert")
    group.add_argument("--larfile", help="lua larfile to convert")
    group.add_argument("--directory", help="directory to convert")
    p.add_argument("--lua_executable", default=None,
                   help="lua executable invoked by the bootstrap script")
    p.add_argument("--output", required=True, help="output XAR file")
    p.add_argument("--mount_root", default=None,
                   help="where the XAR file will mount by default")
    p.add_argument("--compression_algorithm", default="zstd",
                   help="default compression algorithm for XAR file")
    p.add_argument("--block_size", default=256 * 1024,
                   help="block size used when compressing XAR file")
    p.add_argument("--zstd_level", default=16,
                   help="default zstd level when zstd compression is used")
    p.add_argument("--partition_extensions", action='append', default=[])
    p.add_argument("--install_dir",
                   help="directory to write output XAR to")
    p.add_argument("--fbcode_dir", default="",
                   help="here for build system compatibility; becomes "
                        "the prefix input files are searched for")
    opts = p.parse_args(args)

    # We default to zstd, which is both fast and small.  Compression
    # parameters can be set by hand, but this provides a few decent
    # default options for simplicity.
    compression_algorithm = opts.compression_algorithm
    block_size = opts.block_size
    zstd_level = opts.zstd_level

    # Create a map of filename_extension -> tempdir where we split files.
    partition_dirs = {}
    for ext in opts.partition_extensions:
        dirname = tempfile.mkdtemp()
        partition_dirs["." + ext.lstrip('.')] = \
            xar_util.PartitionDestination(dirname, xar_util.make_uuid())
        os.chmod(dirname, 0o755)

    # Staging directory for the main squashfs file.
    staging_dir = tempfile.mkdtemp()

    # Some basic metadata for the header
    version = int(time.time())
    boring_shebang = "#!/bin/echo This is not an executable XAR file."

    sort_file = None
    if opts.fbcode_dir:
        if opts.parfile:
            opts.parfile = os.path.join(opts.fbcode_dir, opts.parfile)
        if opts.larfile:
            opts.larfile = os.path.join(opts.fbcode_dir, opts.larfile)

    # PAR files are special.  We extract it, make sure timestamps in
    # pyc files match the filesystem, and sort the files to keep the
    # unlikely-to-be-accessed files at the end of the squash file.
    if opts.parfile or opts.larfile:
        zf = zipfile.ZipFile(opts.parfile or opts.larfile)
        xar_util.extract_par_file(zf, staging_dir)

        if opts.parfile:
            # Copy our bootstrap files in, making substitutions inside of
            # xar_boostrap.sh as necessary.
            shutil.copy2(os.path.join(opts.fbcode_dir,
                                      "tools/xar/__run_xar_main__.py"),
                         staging_dir)
            with open(os.path.join(opts.fbcode_dir,
                                   "tools/xar/xar_bootstrap.sh.tmpl")) as file:
                xar_bootstrap = file.read()
            fbmake_info = xar_util.extract_manifest_info(opts.parfile, zf)
            xar_bootstrap = xar_bootstrap.format(**fbmake_info)
        elif opts.larfile:
            xar_bootstrap = xar_util.lua_bootstrap(opts.lua_executable)
        else:
            raise ValueError("Expected parfile or larfile")

        bootstrap_output = os.path.join(staging_dir, "xar_bootstrap.sh")
        with open(bootstrap_output, "w") as of:
            of.write(xar_bootstrap)
            os.chmod(bootstrap_output, 0o755)

        with tempfile.NamedTemporaryFile(mode="w+t", delete=False) as sort_tf:
            # Colocate some files in the beginning of the squash file;
            # this reduces random defragmentation.  Prioritize files
            # roughly in the order they will likely be read to.
            priorities = [
                ".sh",
                "__run_xar_main__.py",
                "__init__.pyc",
                ".pyc",
                ".lua",
                ".so",
                "",
            ]
            xar_util.write_sort_file(staging_dir, priorities, sort_tf)
            sort_file = sort_tf.name
    else:
        # copytree demands the directory not exist... so let's use a
        # subdir of our tempdir.
        staging_dir = os.path.join(staging_dir, "copytree_workaround")
        shutil.copytree(opts.directory, staging_dir)
        # Move files per --partition_extensions, creating relative
        # symlinks for files that are moved.
        xar_util.partition_files(
            opts.directory, staging_dir, partition_dirs)

    # This becomes the permission of the mounted squashfs file.
    os.chmod(staging_dir, 0o755)

    output_filename = opts.output
    if opts.install_dir:
        output_filename = os.path.join(opts.install_dir,
                                       os.path.basename(opts.output))
    base_output_name, xar_ext = os.path.splitext(output_filename)
    # Create a tempfile for each xar dependency
    xarfiles = {}
    for extension, destination in partition_dirs.items():
        output_name = base_output_name + extension + xar_ext
        xarfiles[extension] = \
            (output_name, tempfile.NamedTemporaryFile(delete=False))
        xar = xar_util.XarFactory(destination.path,
                                  xarfiles[extension][1].name,
                                  boring_shebang)
        xar.compression_algorithm = compression_algorithm
        xar.block_size = block_size
        xar.zstd_level = zstd_level
        xar.version = version
        xar.uuid = destination.uuid
        xar.sort_file = sort_file
        xar.go()

    # Write the xar file for the main file.
    tf = tempfile.NamedTemporaryFile(delete=False)
    if opts.inner_executable:
        shebang = "#!%s" % opts.xar_exec
        if len(shebang) > MAX_SHEBANG:
            logging.fatal("Shebang too long; %d bytes total: \n%s" %
                          (len(shebang), shebang))
            return 1
        xar = xar_util.XarFactory(staging_dir, tf.name, shebang)
        xar.xar_header["XAREXEC_TARGET"] = opts.inner_executable
    else:
        xar = xar_util.XarFactory(staging_dir, tf.name, boring_shebang)

    xar.xar_header['DEPENDENCIES'] = " ".join([os.path.basename(v[0])
                                               for v in xarfiles.values()])
    if opts.mount_root:
        xar.xar_header['MOUNT_ROOT'] = opts.mount_root

    xar.version = version
    xar.compression_algorithm = compression_algorithm
    xar.block_size = block_size
    xar.zstd_level = zstd_level
    xar.sort_file = sort_file
    xar.go()
    shutil.move(tf.name, output_filename)

    # Finally rename the tempfile to the actual intended destination.
    for output_name, tf in xarfiles.values():
        shutil.move(tf.name, output_name)

    # Finally, make the output executable.  We are done.
    if opts.inner_executable:
        os.chmod(output_filename, 0o755)

    return 0

if __name__ != '__main__':
    raise ImportError("don't import me")

sys.exit(main(sys.argv[1:]))
