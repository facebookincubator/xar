#!/usr/bin/env python
#
# Copyright (c) 2018-present, Facebook, Inc.
# All rights reserved.
#
# This source code is licensed under the BSD-style license found in the
# LICENSE file in the root directory of this source tree.
"""%prog - a tool for mounting and unmounting XAR files.

This program is **DEPRECATED**; to mount a xar, simply use "xarexec -m $PATH"
and to garbage collect XAR mounts, use clean_xar_mounts.

The primary use of this program is to unmount XAR files that aren't in
use (to reduce the number of mounted FUSE filesystems).  It also can
mount xar files if requested, primarily useful for non-executable XAR
files.

By default, it unmounts any XAR file mounted more than 15 minutes old;
the unmount will fail if anything is still using the XAR, such as a running
process.
"""

# This is a utility script.  We cannot rely on PAR files for
# distributing this (since it may be used to mount fbcode runtimes!)
# so we must be able to execute with the system Python.
#
# This script is very conservative; it must run on Python 2.4 (which
# is what some of our oldest machines run).  Yuck.

from __future__ import absolute_import, division, print_function, unicode_literals

import errno
import fcntl
import glob
import logging
import optparse
import os
import re
import signal
import subprocess
import sys
import time


attr_re = re.compile(r'^([a-zA-Z_]+)="(.*)"')
required_attributes = ("VERSION", "UUID", "OFFSET")

logger = logging.getLogger("tools.xar")


def is_mounted(path):
    path = os.path.realpath(path)
    mp_stat = os.stat(path)
    parent_stat = os.stat(os.path.dirname(path))
    return parent_stat.st_dev != mp_stat.st_dev


class XarFile(object):
    def __init__(self, filename):
        self.filename = filename
        root, self.extension = os.path.splitext(self.filename)
        self.alias = os.path.basename(root)
        self._read_header()

        version_suffix = "-%d" % self.version
        if self.alias.endswith(version_suffix):
            self.alias = self.alias[: -len(version_suffix)]

    def _read_header(self):
        self.attributes = {}
        fh = open(self.filename, "rb")
        try:
            header = fh.read(4096).split("\n")
            for line in header:
                if line == "#xar_stop":
                    break

                if line[0] == "#":
                    continue
                m = attr_re.match(line)
                if m:
                    self.attributes[m.group(1)] = m.group(2)
        finally:
            fh.close()

        for attr in required_attributes:
            if attr not in self.attributes:
                raise ValueError("Attribute %s missing from %s" % (attr, self.filename))

        self.version = int(self.attributes["VERSION"])
        # todo: handle dependencies, mount them, etc
        self.dependencies = []
        self.optional_dependencies = []

    def mount(self, xarexec):
        logger.info("Mounting %s with %s" % (self.filename, xarexec))
        proc = subprocess.Popen(
            [xarexec.split(), "-m", self.filename], stdout=subprocess.PIPE
        )
        stdout, _ = proc.communicate()
        if proc.returncode != 0:
            logger.fatal("Mount of %s failed, see stderr for details" % self.filename)
            return False
        self.mountpoint = stdout.split("\n")[0].strip()
        return True

    def symlink(self, destdir):
        dest = os.path.join(destdir, self.alias)
        logger.info("Symlinking %s -> %s" % (self.mountpoint, dest))
        if os.path.islink(dest):
            os.unlink(dest)

        os.symlink(self.mountpoint, dest)


# flock a file descriptor of the given type within timeout_sec.
# Return True if successful.  Uses alarm rather than hammering the
# lock with a polling nonblocking check.
def flock_with_timeout(lock_fd, lock_type, timeout_sec):
    signal.signal(signal.SIGALRM, lambda sig, fr: None)
    signal.alarm(timeout_sec)
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        return True
    except IOError as ie:
        if ie.errno != errno.EINTR:
            logging.error("Unexpected signal during flock: %s" % ie.strerror)
        return False
    finally:
        signal.alarm(0)


# Check whether a mount point should be unmounted.  We only consider
# squashfuse mounts in the correct locations.  Returns a tuple of
# (should_unmount, lock_fd) of whether to unmount and a descriptor
# holding a flock (which should be closed after the unmount).
def should_unmount(devname, mountpath, fstype, timeout):
    if fstype not in ("fuse.squashfuse", "fuse.squashfuse_ll", "osxfusefs", "osxfuse", "macfuse"):
        return (False, None)

    logging.debug("Considering %s (%s)..." % (mountpath, fstype))
    # Only consider certain prefixes, and strip them off into
    # mount_suffix
    allowed_prefixes = ("/mnt/xarfuse/", "/dev/shm/")
    mount_suffix = None
    for prefix in allowed_prefixes:
        if mountpath.startswith(prefix):
            mount_suffix = mountpath[len(prefix) :]
            logging.debug("Mount suffix: %s" % mount_suffix)
            break

    if mount_suffix is None:
        logger.info("Skipping unmount of %s, incorrect prefix" % mountpath)
        return (False, None)

    # Mounts are of the form /prefix/uid-N/UUID-ns-NSID/... -- we need to
    # extract the UUID portion.
    uuid_regex = re.compile(r"uid-\d+/([^/]+)-ns-([^-/]+)$")
    match = uuid_regex.match(mount_suffix)
    if not match:
        logger.info("Skipping unmount of %s, unexpected path strucure" % mountpath)
        return (False, None)

    # Sometimes mtab gets out of sync with reality; all XARs should
    # contain files, so let's confirm they actually do, and if not,
    # consider them worth unmounting.
    try:
        if len(os.listdir(mountpath)) == 0:
            logger.info("Unmounting empty directory %s", mountpath)
            return (True, None)
    except OSError as oe:
        logger.info("Unable to listdir %s, skipping emptiness check", mountpath)

    # Look for the lockfile for this uuid.
    stat_target = None
    if match:
        stat_target = os.path.join(
            os.path.dirname(mountpath), "lockfile." + match.group(1)
        )

    # Legacy case from when lockfiles lacked the uuid portion.
    if not os.path.exists(stat_target):
        stat_target = os.path.join(os.path.dirname(mountpath), "lockfile")

    logging.debug("Using stat target %s" % stat_target)
    # We have a lockfile; use its mtime to determine if the mount
    # point is old enough to try to reap.
    lock_fd = None
    try:
        O_CLOEXEC = 524288  # not in os prior to 3.3
        lock_fd = os.open(stat_target, os.O_RDWR | O_CLOEXEC)
        # lock the file before checking timestamp to protect against a
        # race with XarexecFuse.
        if not flock_with_timeout(lock_fd, fcntl.LOCK_EX, 60):
            logging.info("Unable to lock %s, skipping..." % stat_target)
            os.close(lock_fd)
            return (False, None)
        st = os.fstat(lock_fd)
    except OSError as oe:
        # Chances are the open itself failed.  In this case, we fail
        # open and unmount.
        if lock_fd is not None:
            os.close(lock_fd)
        if oe.errno == errno.ENOENT:
            logger.info("Unable to open %s, assuming unmount...", stat_target)
            return (True, None)
        raise

    if time.time() - st.st_mtime <= timeout * 60:
        logger.info(
            "Skipping unmount of %s, too recent (%.2fs)"
            % (mountpath, time.time() - st.st_mtime)
        )
        os.close(lock_fd)
        return (False, None)

    # TODO(chip): one day we will need to support permanent mounts
    # somehow (for fbcode runtime, etc).  Hueristic TBD.
    return (True, lock_fd)


# Linux-specific cleanup actions - look at /proc/mounts and /etc/mtab
def linux_mounts():
    # On some systems, /etc/mtab is a symlink to /proc/mounts (which
    # is symlink ot /proc/self/mounts).  Avoid duplicates via
    # realpath.
    mounts = []
    mounts_files = set(os.path.realpath(s) for s in ["/proc/mounts", "/etc/mtab"])

    for filename in mounts_files:
        fh = open(filename)
        try:
            for line in fh:
                parts = line.rstrip().split()
                devname, mountpath, fstype = parts[:3]
                # mtab can be escaped; fix it up before calling
                # umount.  Details:
                # https://gnu.org/software/libc/manual/html_node/mtab.html
                # Note backslashes are just '\134' and not '\0134'
                # - special case.
                mountpath = mountpath.replace("\\134", "\\")
                for ch in " \t\r\n":
                    mountpath = mountpath.replace("\\" + oct(ord(ch)), ch)
                mounts.append((devname, mountpath, fstype))
        finally:
            fh.close()

    return mounts


# macOS-specific cleanup actions - /proc/mounts not available, easiest way from
# python is to shellout to `mount` and parse the output.
def macos_mounts():
    output = subprocess.check_output(["mount"]).split("\n")
    mounts = []
    for mount in output:
        # Skip empty lines
        if not mount:
            continue

        # Device name
        dev, rest = mount.split(" on ")
        space = rest.find(" ")
        if space < 0:
            continue

        # Mount point
        mount_point, stats = rest[0:space], rest[space + 1 :]

        # FS type
        fstype = stats.strip("()").split(", ")[0]
        mounts.append((dev, mount_point, fstype))

    return mounts


# Try unmount everything in `mounts`.
def unmount(mounts, opts):
    for mount in mounts:
        devname, mountpoint, fstype = mount
        do_it, lock_fd = should_unmount(devname, mountpoint, fstype, opts.timeout)
        if do_it:
            logger.info("Attempting to unmount %s..." % mountpoint)
            subprocess.call(["umount", mountpoint])
            try:
                os.rmdir(mountpoint)
            except Exception:
                pass
            if lock_fd is not None:
                os.close(lock_fd)


def main(args):
    # Ensure we don't wait forever to, say, acquire a lock.
    logging.basicConfig(
        level=logging.DEBUG, format="%(asctime)s %(levelname)s %(message)s"
    )

    p = optparse.OptionParser(__doc__)
    p.add_option(
        "--xarexec",
        default="/usr/bin/env xarexec_fuse",
        help="xarexec executable to use to mount XAR files",
    )
    p.add_option("--symlink-dir", help="directory to maintain symlinks in")
    p.add_option(
        "--cleanup", action="store_true", help="unmount unused XAR mountpoints"
    )
    p.add_option("--verbose", action="store_true", help="print debugging info")
    p.add_option(
        "--timeout",
        type=int,
        default=15,
        help="time, in minutes, after a xar was mounted to attempt " "to unmount it",
    )
    opts, files = p.parse_args(args)

    # Don't print much unless --verbose is specified.
    if not opts.verbose:
        logger.setLevel(logging.ERROR)

    if opts.cleanup:
        if "darwin" in sys.platform:
            mounts = macos_mounts()
        else:
            mounts = linux_mounts()

        unmount(mounts, opts)

    xar_files = {}
    filenames = []
    for file_or_dir in files:
        if os.path.isdir(file_or_dir):
            filenames.extend(glob.glob(os.path.join(file_or_dir, "*.xar")))
        else:
            filenames.append(file_or_dir)

    for filename in filenames:
        xar_file = XarFile(filename)
        if (
            xar_file.alias not in xar_files
            or xar_file.version > xar_files[xar_file.alias].version
        ):
            xar_files[xar_file.alias] = xar_file

    # Mount each xarfile and, optionally, create our symlink.
    for xar_file in xar_files.values():
        if xar_file.mount(opts.xarexec) and opts.symlink_dir:
            xar_file.symlink(opts.symlink_dir)

    # Remove dangling symlinks; unfortunately this is racey, as it
    # cannot be done atomically (ie we can't remove the symlink only
    # if the contents are something we expect).
    if opts.symlink_dir:
        for entry in os.listdir(opts.symlink_dir):
            path = os.path.join(opts.symlink_dir, entry)
            if not os.access(path, os.R_OK) or not is_mounted(path):
                logger.info("Removing symlink to unmounted image: %s" % path)
                os.unlink(path)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
