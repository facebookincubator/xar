# Copyright (c) Facebook, Inc. and its affiliates. All Rights Reserved
#
# This source code is licensed under the BSD-style license found in the
# LICENSE file in the root directory of this source tree.

from __future__ import absolute_import, division, print_function, unicode_literals

import copy
import os

from xar import xar_builder, xar_util
from xar.tests import xar_test_helpers


class XarBuilderTest(xar_test_helpers.XarTestCase):
    def setUp(self):
        self.xar_builder = xar_builder.XarBuilder()
        self.sqopts = xar_util.SquashfsOptions()
        self.sqopts.compression_algorithm = "gzip"
        self.src = xar_util.StagingDirectory()
        # A set of files for testing
        self.files = {
            "executable.sh": ("executable.sh", "#!echo executable", "w", 0o755),
            "lib.so": ("lib.so", b"binary source", "wb", 0o644),
            "source.txt": ("source.txt", "text source", "w", 0o644),
            "subdir/source.txt": ("subdir/source.txt", "subdir", "w", 0o644),
        }
        for filename, data, mode, permissions in self.files.values():
            self.src.write(data, filename, mode, permissions)
            self.assertEqual(
                xar_test_helpers.mode(self.src.absolute(filename)), permissions
            )

    def tearDown(self):
        self.xar_builder.delete()
        self.src.delete()

    def _set_xar_builder(self, xar_builder):
        self.xar_builder.delete()
        self.xar_builder = xar_builder

    def _src_file(self, key):
        return self.src.absolute(self.files[key][0])

    def _staging(self):
        return self.xar_builder._staging

    def test_add_file(self):
        # Add a file
        src_file = self._src_file("source.txt")
        self.xar_builder.add_file(src_file)
        dst_file = self.xar_builder._staging.absolute("source.txt")
        self.assertFilesEqual(src_file, dst_file)
        # Try to add the file again
        with self.assertRaises(xar_util.StagingDirectory.Error):
            self.xar_builder.add_file(src_file)
        # Add an executable in a subdirectory
        src_file = self._src_file("executable.sh")
        self.xar_builder.add_file(src_file, "subdir/file")
        dst_file = self.xar_builder._staging.absolute("subdir/file")
        self.assertFilesEqual(src_file, dst_file)
        # Try to add after frozen
        self.xar_builder.freeze()
        with self.assertRaises(xar_builder.XarBuilder.FrozenError):
            self.xar_builder.add_file(src_file, "file")

    def test_add_directory(self):
        # Set the staging dir to the test directory
        self.xar_builder.add_directory(self.src.path())
        self.assertDirectoryEqual(self.src.path(), self._staging().path())
        # Add a copy to a subdir
        self.xar_builder.add_directory(self.src.path(), "my-subdir")
        subdir = os.path.join(self._staging().path(), "my-subdir")
        self.assertDirectoryEqual(self.src.path(), subdir)
        # Attempt to overwrite the staging directory
        with self.assertRaises(xar_util.StagingDirectory.Error):
            self.xar_builder.add_directory(self.src.path())
        # Attempt to overwrite the subdir
        with self.assertRaises(xar_util.StagingDirectory.Error):
            self.xar_builder.add_directory(self.src.path(), "my-subdir")
        # Try to add after frozen
        self.xar_builder.freeze()
        with self.assertRaises(xar_builder.XarBuilder.FrozenError):
            self.xar_builder.add_directory(self.src.path(), "another-subdir")

    def test_set_shebang(self):
        # Invalid shebangs
        with self.assertRaises(xar_builder.XarBuilder.InvalidShebangError):
            self.xar_builder._set_shebang("bang")
        with self.assertRaises(xar_builder.XarBuilder.InvalidShebangError):
            self.xar_builder._set_shebang("#!too long" + ("0" * 130))
        # Valid shebang
        self.xar_builder._set_shebang("#!bang")
        self.assertEqual("#!bang", self.xar_builder._shebang)
        # Shebang already set
        with self.assertRaises(xar_builder.XarBuilder.InvalidShebangError):
            self.xar_builder._set_shebang("#!bang")
        # Try to set after frozen
        self.xar_builder.freeze()
        with self.assertRaises(xar_builder.XarBuilder.FrozenError):
            self.xar_builder._set_shebang("#!bang")

    def test_set_executable(self):
        # Invalid executable
        with self.assertRaises(xar_builder.XarBuilder.InvalidExecutableError):
            self.xar_builder.set_executable("bad")
        # Valid executable
        src = self._src_file("executable.sh")
        self.xar_builder.add_executable(src)
        self.assertEqual("#!/usr/bin/env xarexec_fuse", self.xar_builder._shebang)
        self.assertFilesEqual(src, self._staging().absolute("executable.sh"))
        # Executable already set
        with self.assertRaises(xar_builder.XarBuilder.InvalidExecutableError):
            self.xar_builder.add_executable(src, "different")
        # Try to add after frozen
        self.xar_builder.freeze()
        with self.assertRaises(xar_builder.XarBuilder.FrozenError):
            self.xar_builder.set_executable("executable")

    def test_sort(self):
        self.xar_builder.add_directory(self.src.path())
        self.xar_builder.sort_by_extension([".txt", ".so", ""])
        # Try to override
        with self.assertRaises(xar_builder.XarBuilder.Error):
            self.xar_builder.sort_by_extension([".txt", ".so", ""])
        # Override
        self.xar_builder.sort_by_extension([".txt", ".so", ""], override=True)

        self.xar_builder.freeze()
        # Try to set while frozen
        with self.assertRaises(xar_builder.XarBuilder.FrozenError):
            self.xar_builder.sort_by_extension(None, override=True)
        # Check the result
        self.assertTrue(self.xar_builder._sort_file is not None)
        with self.xar_builder._sort_file.open("r") as f:
            sort_data = f.read().strip()
        sort_data = [l.split(" ") for l in sort_data.split("\n")]
        for filename, priority in sort_data:
            if filename.endswith(".txt"):
                self.assertEqual(priority, "-4")
            elif filename.endswith(".so"):
                self.assertEqual(priority, "-3")
            else:
                self.assertEqual(priority, "-2")

    def test_partition(self):
        self.xar_builder.add_directory(self.src.path())
        self.xar_builder.partition_by_extension([".txt"])
        # Try to override
        with self.assertRaises(xar_builder.XarBuilder.Error):
            self.xar_builder.partition_by_extension([".txt"])
        # Override
        self.xar_builder.partition_by_extension([".txt"], override=True)

        self.xar_builder.freeze()
        # Try to set while frozen
        with self.assertRaises(xar_builder.XarBuilder.FrozenError):
            self.xar_builder.partition_by_extension(None, override=True)
        # Check the source directory
        for dirpath, _dirnames, filenames in os.walk(self._staging().path()):
            for filename in filenames:
                abs_filename = os.path.join(dirpath, filename)
                if filename.endswith(".txt"):
                    self.assertTrue(os.path.islink(abs_filename))
                else:
                    self.assertFalse(os.path.islink(abs_filename))
        # Check the partion directory
        self.assertEqual(len(self.xar_builder._partition_dest), 1)
        dest = self.xar_builder._partition_dest[".txt"]
        for dirpath, _dirname, filenames in os.walk(dest[0].path()):
            for filename in filenames:
                abs_filename = os.path.join(dirpath, filename)
                self.assertTrue(filename.endswith(".txt"))
                self.assertFalse(os.path.islink(abs_filename))
        # The directories should have the same file names
        self.assertDirectoryEqual(
            self.src.path(), self._staging().path(), check_contents=False
        )

    def test_build(self):
        self.xar_builder.add_directory(self.src.path())
        dst = xar_util.StagingDirectory()
        test_xar = os.path.join(dst.path(), "test.xar")
        test_root = os.path.join(dst.path(), "squashfs-root")
        self.xar_builder.build(test_xar, self.sqopts)
        self._unxar(test_xar, test_root)
        self.assertDirectoryEqual(self.src.path(), test_root)
        dst.delete()

    def test_sort_build(self):
        self.xar_builder.add_directory(self.src.path())
        self.xar_builder.sort_by_extension([".txt", ".so", ""])
        dst = xar_util.StagingDirectory()
        test_xar = os.path.join(dst.path(), "test.xar")
        test_root = os.path.join(dst.path(), "squashfs-root")
        self.xar_builder.build(test_xar, self.sqopts)
        self._unxar(test_xar, test_root)
        self.assertDirectoryEqual(self.src.path(), test_root)
        dst.delete()

    def test_deepcopy(self):
        other = copy.deepcopy(self.xar_builder)
        self.assertEqual(other._sort_file, None)
        self.assertEqual(other._frozen, self.xar_builder._frozen)
        self.assertEqual(other._xar_exec, self.xar_builder._xar_exec)
        other.delete()

        self.xar_builder._sort_file = xar_util.TemporaryFile()
        other = copy.deepcopy(self.xar_builder)
        self.assertNotEqual(
            other._staging.absolute(), self.xar_builder._staging.absolute()
        )
        self.assertNotEqual(other._sort_file.name(), self.xar_builder._sort_file.name())
        other.delete()
