# Copyright (c) Facebook, Inc. and its affiliates. All Rights Reserved
#
# This source code is licensed under the BSD-style license found in the
# LICENSE file in the root directory of this source tree.

from __future__ import absolute_import, division, print_function, unicode_literals

import os
import subprocess
import tempfile
import unittest

from xar import xar_builder


def mode(filename):
    return os.stat(filename).st_mode & 0o777


class XarTestCase(unittest.TestCase):
    def _unxar(self, xarfile, outdir):
        """unsquashfs the xarfile into the outdir."""
        # Make sure the header is what we expect; also grab the offset.
        with open(xarfile, "rb") as fh:
            first_line = fh.readline()
            shebang = first_line.decode("utf-8").strip()
            self.assertEquals(shebang, xar_builder.BORING_SHEBANG)
            saw_stop = False
            offset = None
            for line in fh:
                if line == b"#xar_stop\n":
                    saw_stop = True
                    break
                if line.startswith(b"OFFSET="):
                    offset = int(line[8:-2])
            self.assertTrue(saw_stop)
            self.assertTrue(offset % 4096 == 0)

            fh.seek(offset)
            squashfs_contents = fh.read()

        # Write the squashfs file out, expand it, and make sure it
        # contains the same files as the source.
        with tempfile.NamedTemporaryFile() as out, open("/dev/null", "wb") as devnull:
            out.write(squashfs_contents)
            out.flush()
            subprocess.check_call(
                ["unsquashfs", "-d", outdir, "-no-xattrs", out.name], stdout=devnull
            )

    def assertDirectoryEqual(self, src, dst, check_contents=True):
        """Verify two directories contain the same entries, recursively."""

        def directory_contents(d):
            ret = []
            for dirname, dirs, files in os.walk(d):
                for entry in dirs + files:
                    full_path = os.path.join(dirname, entry)
                    ret.append(full_path[len(d) + 1 :])
            return sorted(ret)

        src_contents = directory_contents(src)
        dst_contents = directory_contents(dst)
        self.assertEqual(src_contents, dst_contents)
        for src_file, dst_file in zip(src_contents, dst_contents):
            src_file = os.path.join(src, src_file)
            dst_file = os.path.join(dst, dst_file)
            if check_contents and os.path.isfile(src_file):
                self.assertFilesEqual(src_file, dst_file)

    def assertFilesEqual(self, src, dst):
        """Verify that the contents of two files are the same."""
        self.assertTrue(os.path.exists(src))
        self.assertTrue(os.path.exists(dst))
        with open(src, "rb") as fh:
            src_contents = fh.read()
        with open(dst, "rb") as fh:
            dst_contents = fh.read()
        self.assertEqual(src_contents, dst_contents)
        self.assertEqual(mode(src), mode(dst))
