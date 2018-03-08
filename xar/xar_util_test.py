from __future__ import absolute_import
from __future__ import division
from __future__ import print_function
from __future__ import unicode_literals

import os
import subprocess
import tempfile
import unittest

from xar import xar_util

class XarUtilTest(unittest.TestCase):
    def test_xar_factory(self):
        "Test XarFactory and XarReader"

        # Make a boring xar file.
        srcdir = self.make_test_skeleton()

        tf = tempfile.NamedTemporaryFile(delete=False)
        xar = xar_util.XarFactory(srcdir, tf.name, "#!boring shebang")
        xar.compression_algorithm = 'lzo'
        xar.block_size = 4096
        xar.go()

        # Make sure the header is what we expect; also grab the offset.
        with open(tf.name, "rb") as fh:
            first_line = fh.readline()
            self.assertEquals(first_line, b"#!boring shebang\n")
            saw_stop = False
            offset = None
            for line in fh:
                if line == b"#xar_stop\n":
                    saw_stop = True
                    break
                if line.startswith(b"OFFSET="):
                    offset = int(line[8:-2])
            self.assertTrue(saw_stop)
            self.assertEquals(offset, 4096)

            fh.seek(offset)
            squashfs_contents = fh.read()

        # Write the squashfs file out, expand it, and make sure it
        # contains the same files as the source.
        outdir = os.path.join(tempfile.mkdtemp(), 'squashfs-root')
        with tempfile.NamedTemporaryFile() as out, \
             open("/dev/null", "wb") as devnull:
            out.write(squashfs_contents)
            out.flush()
            subprocess.check_call(
                ["/usr/sbin/unsquashfs",
                 '-d', outdir,
                 '-no-xattrs',
                 out.name], stdout=devnull)

        self.assertDirectoryEquals(srcdir, outdir)

    def test_partition_files(self):
        "Test the file partitioning functionality used for split XARs."
        srcdir = self.make_test_skeleton()
        dstdir = tempfile.mkdtemp()
        debuginfo_dir = tempfile.mkdtemp()
        mp3_dir = tempfile.mkdtemp()

        # Set up and execute the partitioning.
        print("Partitioning %s to %s (normal) and %s (debuginfo)" %
              (srcdir, dstdir, debuginfo_dir))

        uuid = xar_util.make_uuid()
        extension_map = {
            ".debuginfo": xar_util.PartitionDestination(debuginfo_dir, uuid),
            ".mp3": xar_util.PartitionDestination(mp3_dir, uuid),
        }
        xar_util.partition_files(srcdir, dstdir, extension_map)

        # Every debuginfo file in dstdir should be a symlink; every
        # .txt file should be a real file.  We should find the same
        # number of txt files as debuginfo symlinks.
        num_normal_files = 0
        num_symlinks = 0
        for dirname, _, filenames in os.walk(dstdir):
            for filename in filenames:
                fn = os.path.join(dirname, filename)
                if fn.endswith((".debuginfo", ".mp3")):
                    self.assertTrue(os.path.islink(fn))
                    link = os.readlink(fn)
                    self.assertTrue(
                        link.find('/%s/' % uuid) != -1,
                        "%s symlink to %s contains /%s/" % (link, fn, uuid))
                    num_symlinks += 1
                else:
                    self.assertTrue(os.path.isfile(fn),
                                    "%s is a file" % fn)
                    num_normal_files += 1

        # Two symlinks per normal file
        self.assertEquals(num_normal_files, 7)
        self.assertEquals(2 * num_normal_files, num_symlinks)

        # Make sure only normal files are in the debuginfo dir.
        for dirname, _, filenames in os.walk(debuginfo_dir):
            for filename in filenames:
                fn = os.path.join(dirname, filename)
                if fn.endswith(".debuginfo"):
                    self.assertTrue(os.path.isfile(fn))
                else:
                    self.fail("found non-debuginfo file in debug partition")

        # Same, but for mp3.
        for dirname, _, filenames in os.walk(mp3_dir):
            for filename in filenames:
                fn = os.path.join(dirname, filename)
                if fn.endswith(".mp3"):
                    self.assertTrue(os.path.isfile(fn))
                else:
                    self.fail("found non-mp3 file in mp3 partition")

        self.assertDirectoryEquals(srcdir, dstdir)

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
        xar = xar_util.XarFactory(srcdir, tf.name, "#!boring shebang")
        xar.compression_algorithm = 'lzo'
        xar.block_size = 4096
        xar.xar_header["IGNORED"] = "0" * 5000
        xar.go()

        # Make sure the header is what we expect; also grab the offset.
        with open(tf.name, "rb") as fh:
            first_line = fh.readline()
            self.assertEquals(first_line, b"#!boring shebang\n")
            saw_stop = False
            offset = None
            for line in fh:
                if line == b"#xar_stop\n":
                    saw_stop = True
                    break
                if line.startswith(b"OFFSET="):
                    offset = int(line[8:-2])
            self.assertTrue(saw_stop)
            self.assertEquals(offset, 8192)

            fh.seek(offset)
            squashfs_contents = fh.read()

        # Write the squashfs file out, expand it, and make sure it
        # contains the same files as the source.
        outdir = os.path.join(tempfile.mkdtemp(), 'squashfs-root')
        with tempfile.NamedTemporaryFile() as out, \
             open("/dev/null", "wb") as devnull:
            out.write(squashfs_contents)
            out.flush()
            subprocess.check_call(
                ["/usr/sbin/unsquashfs",
                 '-d', outdir,
                 '-no-xattrs',
                 out.name], stdout=devnull)

        self.assertDirectoryEquals(srcdir, outdir)

    def assertDirectoryEquals(self, src, dst):
        """Verify two directories contain the same entries, recursively.  Does
        not verify file contents, merely filenames."""
        def directory_contents(d):
            ret = []
            for dirname, dirs, files in os.walk(d):
                for entry in dirs + files:
                    full_path = os.path.join(dirname, entry)
                    ret.append(full_path[len(d) + 1:])
            return sorted(ret)

        src_contents = directory_contents(src)
        dst_contents = directory_contents(dst)
        self.assertEquals(src_contents, dst_contents)

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


if __name__ == '__main__':
    unittest.main()
