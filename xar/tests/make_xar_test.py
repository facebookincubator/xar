# Copyright (c) Facebook, Inc. and its affiliates. All Rights Reserved
#
# This source code is licensed under the BSD-style license found in the
# LICENSE file in the root directory of this source tree.

from __future__ import absolute_import, division, print_function, unicode_literals

import contextlib
import os
import subprocess
import tempfile
import unittest

from xar import make_xar, xar_util


try:
    import zipapp
except ImportError:
    zipapp = None


class MakeXarTest(unittest.TestCase):
    @contextlib.contextmanager
    def make_test_directory(self):
        try:
            dir = tempfile.mkdtemp()
            with open(os.path.join(dir, "__main__.py"), "w") as f:
                f.write("print('python')")
            with open(os.path.join(dir, "other.py"), "w") as f:
                f.write("print('other')")
            with open(os.path.join(dir, "__main__.sh"), "w") as f:
                f.write("#!/bin/sh\necho shell")
            with tempfile.NamedTemporaryFile("w") as xarfile:
                yield xarfile.name, dir
        finally:
            xar_util.safe_rmtree(dir)

    def xarexec_exists(self):
        try:
            subprocess.check_call(["which", "xarexec_fuse"])
            return True
        except subprocess.CalledProcessError:
            return False

    def check_xar(self, xarfile):
        return subprocess.check_output([xarfile]).strip()

    def test_make_python_xar_from_directory(self):
        with self.make_test_directory() as (xar, dir):
            args = ["--output", xar, "--python", dir]
            make_xar.main(args)
            if self.xarexec_exists():
                self.assertEqual(self.check_xar(xar), b"python")
            args += ["--python-entry-point", "other"]
            make_xar.main(args)
            if self.xarexec_exists():
                self.assertEqual(self.check_xar(xar), b"other")

    def test_make_python_xar_from_archive(self):
        if zipapp is None:
            return
        with self.make_test_directory() as (xar, dir):
            with tempfile.NamedTemporaryFile("w") as zip:
                zipapp.create_archive(dir, zip.name)
                args = ["--output", xar, "--python", zip.name]
                make_xar.main(args)
                if self.xarexec_exists():
                    self.assertEqual(self.check_xar(xar), b"python")
                args += ["--python-entry-point", "other"]
                make_xar.main(args)
                if self.xarexec_exists():
                    self.assertEqual(self.check_xar(xar), b"other")

    def test_make_raw_xar(self):
        with self.make_test_directory() as (xar, dir):
            args = ["--output", xar, "--raw", dir]
            make_xar.main(args)
            if self.xarexec_exists():
                with self.assertRaises(OSError):
                    self.check_xar(xar)
            args += ["--raw-executable", "__main__.sh"]
            make_xar.main(args)
            if self.xarexec_exists():
                self.assertEqual(self.check_xar(xar), b"shell")
