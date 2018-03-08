from __future__ import absolute_import
from __future__ import division
from __future__ import print_function
from __future__ import unicode_literals

import collections
import logging
import os
import re
import shutil
import struct
import subprocess
import tempfile
import time
import stat
import sys
import uuid

from xar.lar_util import lar_boot_commands

logger = logging.getLogger('xar')


def make_uuid():
    # ugh line length limit; we need a small uuid
    return str(uuid.uuid1()).split("-")[0]


def _align_offset(offset, align=4096):
    """Aligns the offset to the given alignment"""
    mask = align - 1
    assert (mask & align) == 0
    return (offset + mask) & (~mask)


class XarFactory(object):
    """A class for creating XAR files.

    Pretty straight forward; take an input directory, output file, and some
    metadata and produce a XAR file of the contents.
    """
    def __init__(self, dirname, output, header_prefix):
        self.dirname = dirname
        self.output = output
        self.header_prefix = header_prefix
        self.xar_header = {}
        self.compression_algorithm = 'zstd'
        self.block_size = 256 * 1024
        self.zstd_level = 16
        self.uuid = None
        self.version = None
        self.sort_file = None

    def go(self):
        "Make the XAR file."
        logger.info("Squashing %s to %s" % (self.dirname, self.output))
        if self.uuid is None:
            self.uuid = make_uuid()

        if self.version is None:
            self.version = time.time()

        tf = tempfile.NamedTemporaryFile(delete=False)
        # Create!
        cmd = ["/usr/sbin/mksquashfs", self.dirname, tf.name, "-noappend",
               '-noI', '-noX',  # is this worth it?  probably
               '-force-uid', 'nobody',
               '-force-gid', 'nobody',
               '-b', str(self.block_size),
               "-comp", self.compression_algorithm]
        if self.compression_algorithm == 'zstd':
            cmd.extend(('-Xcompression-level', str(self.zstd_level)))

        if self.sort_file:
            cmd.extend(['-sort', self.sort_file])

        if sys.stdout.isatty():
            subprocess.check_call(cmd)
        else:
            with open("/dev/null", "wb") as f:
                subprocess.check_call(cmd, stdout=f)

        headers = [self.header_prefix]
        # Take the squash file, create a header, and write it
        with open(self.output, "wb") as of:
            # Make a "safe" header that is easily parsed and also not
            # going to explode if accidentally executed.
            headers.append('OFFSET="$OFFSET"')
            headers.append('UUID="$UUID"')
            headers.append('VERSION="%d"' % self.version)
            for key, val in self.xar_header.items():
                headers.append('%s="%s"' % (key, str(val).replace('"', ' ')))
            headers.append("#xar_stop")
            headers.append("echo This XAR file should not be executed by sh")
            headers.append("exit 1")
            headers.append("# Actual squashfs file begins at $OFFSET")
            text_headers = "\n".join(headers) + '\n'
            # 128 is to account for expansion of $OFFSET and $UUID;
            # it's well over what they might reasonably be.
            header_size = _align_offset(128 + len(text_headers))
            text_headers = text_headers.replace("$OFFSET", "%d" % header_size)
            text_headers = text_headers.replace("$UUID", self.uuid)
            text_headers += '\n' * (header_size - len(text_headers))
            of.write(text_headers.encode('UTF-8'))

            # Now append the squashfs file to the header.
            with open(tf.name, "rb") as rf:
                while True:
                    data = rf.read(1024 * 1024)
                    if not data:
                        break
                    of.write(data)


# Simple class to represent a partition destination.  Each destination
# is a path and a uuid from which the contents come (ie, the uuid of
# the spar file that contains the file that is moved into the
# partition; used for symlink construction).
PartitionDestination = collections.namedtuple(
    'PartitionDestination', 'path uuid')


def partition_files(source_dir,
                    dest_dir,
                    extension_destinations):
    """Partition source_dir into multiple output directories.

    A partition is defined by extension_destinations which maps suffixes (such
    as ".debuginfo") to a PartitionDestination instance.

    dest_dir contains all files that aren't in a partition, and symlinks for
    ones that are.  symlinks are relative and of the form
    "../../../uuid/path/to/file" so that the final symlinks are correct
    relative to /mnt/xar/....
    """
    source_dir = source_dir.rstrip('/')

    for dirpath, _dirnames, filenames in os.walk(source_dir):
        # path relative to source_dir; used for creating the right
        # file inside the staging dir
        relative_dirname = dirpath[len(source_dir) + 1:]

        # Special case; if a file is in the root of source_dir, then
        # relative_dirname is empty, but that has the same number of
        # '/' as just 'bin', so we need to special case it the empty
        # value.
        if not relative_dirname:
            relative_depth = 1
        else:
            relative_depth = 2 + relative_dirname.count("/")

        for filename in filenames:
            # Does this extension map to a separate output?
            _, extension = os.path.splitext(filename)
            dest_base = extension_destinations.get(extension, None)
            if dest_base is not None:
                output_dir = os.path.join(dest_base.path, relative_dirname)
            else:
                output_dir = os.path.join(dest_dir, relative_dirname)
            dest_dir_dest = os.path.join(dest_dir, relative_dirname, filename)
            output_path = os.path.join(output_dir, filename)
            if not os.path.isdir(output_dir):
                os.makedirs(output_dir, 0o755)

            src = os.path.join(source_dir, dirpath, filename)
            # If this file is destined for another tree, make a
            # relative symlink in dest_dir_dest pointing to the
            # sub-xar destination.
            if extension in extension_destinations:
                dependency_mountpoint = dest_base.uuid
                staging_symlink = os.path.join(
                    '../' * relative_depth,
                    dependency_mountpoint,
                    relative_dirname,
                    filename)
                logger.info("%s %s" % (staging_symlink, dest_dir_dest))
                if not os.path.isdir(os.path.dirname(dest_dir_dest)):
                    os.makedirs(os.path.dirname(dest_dir_dest), 0o755)
                if os.path.exists(dest_dir_dest):
                    os.unlink(dest_dir_dest)
                os.symlink(staging_symlink, dest_dir_dest)

            # Now copy the file to whichever destination it is heading to.
            if os.access(src, os.R_OK):
                shutil.copy2(src, output_path)
            else:
                sys.stderr.write("Unable to read %s, skipping\n" % src)


def extract_pyc_timestamp(path):
    "Extract the embedded timestamp from a pyc file"

    # A PYC file has a four byte header then four byte timestamp.  The
    # timestamp must match the timestamp on the py file, otherwise the
    # interpreter will attempt to re-compile the py file.  We extract
    # the timestamp to adulterate the py/pyc files before squashing
    # them.
    with open(path, "rb") as fh:
        prefix = fh.read(8)
        return struct.unpack(b'<I', prefix[4:])[0]


def extract_par_file(zf, output_dir):
    "Extract a par file (aka a zip file), fixing pyc timestamps as needed."

    timestamps = {}
    for zi in zf.infolist():
        destination = os.path.join(output_dir, zi.filename)

        mode = zi.external_attr >> 16
        if stat.S_ISLNK(mode):
            target = zf.read(zi).decode("utf-8")
            os.symlink(target, destination)
        else:
            zf.extract(zi, path=output_dir)
            os.chmod(destination, stat.S_IMODE(mode))

        # Use the embedded timestamp for from the pyc file for the
        # pyc and py file; otherwise, use the timezone-less
        # timestamp from the zipfile (sigh).
        if zi.filename.endswith(".pyc"):
            new_time = extract_pyc_timestamp(destination)
            timestamps[destination] = new_time       # pyc file
            timestamps[destination[:-1]] = new_time  # py file too
        else:
            new_time = tuple((list(zi.date_time) + [0, 0, -1]))
            timestamps[destination] = time.mktime(new_time)

    # Set our timestamps.
    for path, timestamp in timestamps.items():
        try:
            os.utime(path, (timestamp, timestamp))
        except OSError as e:
            # Sometimes we had a pyc file but no py file; the utime
            # would fail.
            if not path.endswith(".py"):
                raise e


def extract_manifest_info(zf_path, zf):
    """
    Extract information we need from the par file's manifest; in particular,
    we need python_home, main_module, and python_command
    """

    # Simple version: the manifest contains an fbmake entry with the
    # fields we need.  Use them.
    manifest = zf.read("__manifest__.py")
    contents = {}
    exec(manifest, contents)

    try:
        # fbmake manifests
        info = contents['fbmake']
    except KeyError:
        # buck manifests
        info = contents['Manifest'].fbmake
        if 'ld_preload' not in info:
            # FIXME: Hack until Buck's manifest includes ld_preload info.
            with open(zf_path, "rb") as fh:
                header = fh.read(16384)
            r = re.compile(br'^# LD_PRELOAD=(.+)$')
            m = r.match(header)
            info['ld_preload'] = m.group(1) if m else ''

    return info


def lua_bootstrap(interpreter):
    """
    Bootstrap shell script to launch Lua interpreter
    """

    bootstrap = ["""#!/bin/bash
set -e

BOOTSTRAP_PATH="$0"
BASE_DIR=$(dirname "$BOOTSTRAP_PATH")
shift
"""]

    bootstrap += lar_boot_commands(
        has_python=True,
        interpreter=interpreter,
    )

    return "\n".join(bootstrap)
