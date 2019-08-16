# Copyright (c) Facebook, Inc. and its affiliates. All Rights Reserved
#
# This source code is licensed under the BSD-style license found in the
# LICENSE file in the root directory of this source tree.

from __future__ import absolute_import, division, print_function, unicode_literals

import copy
import io
import os
import tempfile
import unittest

from xar import py_util, xar_builder, xar_util
from xar.tests import xar_test_helpers


class XarUtilTest(xar_test_helpers.XarTestCase):
    def test_xar_factory(self):
        "Test XarFactory and XarReader"

        # Make a boring xar file.
        srcdir = self.make_test_skeleton()

        tf = tempfile.NamedTemporaryFile(delete=False)
        xar = xar_util.XarFactory(srcdir, tf.name, xar_builder.BORING_SHEBANG)
        xar.squashfs_options.compression_algorithm = "gzip"
        xar.squashfs_options.block_size = 4096
        xar.go()

        outdir = os.path.join(tempfile.mkdtemp(), "squashfs-root")
        self._unxar(tf.name, outdir)
        self.assertDirectoryEqual(srcdir, outdir)

    def test_partition_files(self):
        "Test the file partitioning functionality used for split XARs."
        srcdir = xar_util.StagingDirectory(self.make_test_skeleton())
        dstdir = copy.deepcopy(srcdir)
        debuginfo_dir = xar_util.StagingDirectory()
        mp3_dir = xar_util.StagingDirectory()

        # Set up and execute the partitioning.
        print(
            "Partitioning %s (normal) to %s (debuginfo) and %s (mp3)"
            % (dstdir.path(), debuginfo_dir.path(), mp3_dir.path())
        )

        uuid = xar_util.make_uuid()
        extension_map = {
            ".debuginfo": xar_util.PartitionDestination(debuginfo_dir, uuid),
            ".mp3": xar_util.PartitionDestination(mp3_dir, uuid),
        }
        xar_util.partition_files(dstdir, extension_map)

        # Every debuginfo file in dstdir should be a symlink; every
        # .txt file should be a real file.  We should find the same
        # number of txt files as debuginfo symlinks.
        num_normal_files = 0
        num_symlinks = 0
        for dirname, _, filenames in os.walk(dstdir.path()):
            for filename in filenames:
                fn = os.path.join(dirname, filename)
                if fn.endswith((".debuginfo", ".mp3")):
                    self.assertTrue(os.path.islink(fn))
                    link = os.readlink(fn)
                    self.assertTrue(
                        link.find("/%s/" % uuid) != -1,
                        "%s symlink to %s contains /%s/" % (link, fn, uuid),
                    )
                    num_symlinks += 1
                else:
                    self.assertTrue(os.path.isfile(fn), "%s is a file" % fn)
                    num_normal_files += 1

        # Two symlinks per normal file
        self.assertEquals(num_normal_files, 7)
        self.assertEquals(2 * num_normal_files, num_symlinks)

        # Make sure only normal files are in the debuginfo dir.
        for dirname, _, filenames in os.walk(debuginfo_dir.path()):
            for filename in filenames:
                fn = os.path.join(dirname, filename)
                if fn.endswith(".debuginfo"):
                    self.assertTrue(os.path.isfile(fn))
                else:
                    self.fail("found non-debuginfo file in debug partition")

        # Same, but for mp3.
        for dirname, _, filenames in os.walk(mp3_dir.path()):
            for filename in filenames:
                fn = os.path.join(dirname, filename)
                if fn.endswith(".mp3"):
                    self.assertTrue(os.path.isfile(fn))
                else:
                    self.fail("found non-mp3 file in mp3 partition")

        self.assertDirectoryEqual(srcdir.path(), dstdir.path(), check_contents=False)

        srcdir.delete()
        dstdir.delete()
        debuginfo_dir.delete()
        mp3_dir.delete()

    def test_align_offset(self):
        self.assertEquals(0, xar_util._align_offset(0))
        self.assertEquals(4096, xar_util._align_offset(1))
        self.assertEquals(4096, xar_util._align_offset(4095))
        self.assertEquals(4096, xar_util._align_offset(4096))
        self.assertEquals(8192, xar_util._align_offset(4097))

    def test_long_header(self):
        """Test headers longer than 4096 bytes"""
        # Make a boring xar file.
        srcdir = self.make_test_skeleton()

        tf = tempfile.NamedTemporaryFile(delete=False)
        xar = xar_util.XarFactory(srcdir, tf.name, xar_builder.BORING_SHEBANG)
        xar.squashfs_options.compression_algorithm = "gzip"
        xar.squashfs_options.block_size = 4096
        xar.xar_header["IGNORED"] = "0" * 5000
        xar.go()

        outdir = os.path.join(tempfile.mkdtemp(), "squashfs-root")
        self._unxar(tf.name, outdir)
        self.assertDirectoryEqual(srcdir, outdir)

    def test_write_sort_file(self):
        """Tests write_sort_file()"""
        source_dir = self.make_test_skeleton()
        # Add in a file with spaces
        with open(os.path.join(source_dir, "space file.txt"), "w") as fh:
            fh.write("space file")

        sort_file = io.StringIO()
        priorities = [".txt", ".debuginfo", ".mp3"]
        xar_util.write_sort_file(source_dir, priorities, sort_file)
        sort_data = [
            line.split(" ") for line in sort_file.getvalue().strip().split("\n")
        ]
        for filename, priority in sort_data:
            self.assertFalse(" " in filename)
            if filename.endswith(".txt"):
                self.assertEqual(priority, "-4")
            if filename.endswith(".debuginfo"):
                self.assertEqual(priority, "-3")
            if filename.endswith(".mp3"):
                self.assertEqual(priority, "-2")

    def test_staging_deepcopy(self):
        original = xar_util.StagingDirectory(self.make_test_skeleton())
        clone = copy.deepcopy(original)
        self.assertNotEqual(original.absolute(), clone.absolute())
        self.assertDirectoryEqual(original.absolute(), clone.absolute())

    def test_temporary_file_deepcopy(self):
        original = xar_util.TemporaryFile()
        data = "the data"
        with original.open("w+t") as f:
            f.write(data)
        clone = copy.deepcopy(original)
        self.assertNotEqual(original.name(), clone.name())
        with clone.open("r+t") as f:
            self.assertEqual(data, f.read())

    def test_mksquashfs_options(self):
        "Test XarFactory uses mksquashfs option in SquashfsOptions"
        # Make a boring xar file.
        srcdir = self.make_test_skeleton()

        tf = tempfile.NamedTemporaryFile(delete=False)
        xar = xar_util.XarFactory(srcdir, tf.name, xar_builder.BORING_SHEBANG)
        xar.squashfs_options.mksquashfs = "bogus_mksquashfs_path"
        with self.assertRaises(Exception):
            xar.go()

    def make_test_skeleton(self):
        "Make a simple tree of test files"
        srcdir = tempfile.mkdtemp()

        # First create a bunch of directories, and then files inside
        # each one -- one .txt and one .debuginfo file per directory.
        for d in "d1 d1/sub1 d1/sub2 d2 d3 d3/sub4".split():
            os.mkdir(os.path.join(srcdir, d))

        n = 0
        for dirpath, _, _ in os.walk(srcdir):
            with open(os.path.join(dirpath, "%s.txt" % n), "w") as fh:
                fh.write("orignal file %s\n" % n)
            n += 1

        for dirpath, _, _ in os.walk(srcdir):
            with open(os.path.join(dirpath, "%s.debuginfo" % n), "w") as fh:
                fh.write("debuginfo %s\n" % n)
            n += 1

        for dirpath, _, _ in os.walk(srcdir):
            with open(os.path.join(dirpath, "%s.mp3" % n), "w") as fh:
                fh.write("mp3 %s\n" % n)
            n += 1

        return srcdir


if __name__ == "__main__":
    unittest.main()
