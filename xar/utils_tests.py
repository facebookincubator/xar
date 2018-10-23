#!/usr/bin/env python
# Copyright (c) Facebook, Inc. and its affiliates. All Rights Reserved

from __future__ import absolute_import, division, print_function, unicode_literals

import tempfile
import unittest
from shutil import rmtree

import xar.utils


try:
    import unittest.mock as mock
except ImportError:
    import mock


class XarUtilsTestCase(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.mkdtemp()

    def tearDown(self):
        try:
            rmtree(self.tempdir)
        except OSError:
            pass

    def test_get_runtime_path(self):
        with mock.patch("xar.utils.os.getenv") as fake_env:
            fake_env.return_value = self.tempdir
            self.assertEqual(xar.utils.get_runtime_path(), self.tempdir)

            fake_env.return_value = None
            with self.assertRaises(ValueError):
                xar.utils.get_runtime_path()


if __name__ == "__main__":
    unittest.main()
