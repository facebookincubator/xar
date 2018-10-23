#!/usr/bin/env python
# Copyright (c) Facebook, Inc. and its affiliates. All Rights Reserved
"""Handy helper utils to work with XARs at runtime"""

from __future__ import absolute_import, division, print_function, unicode_literals

import os


def get_runtime_path():
    # type: (...) -> str
    """Return the location of the runtime files directory"""

    runtime_path = os.getenv("XAR_RUNTIME_FILES")
    if runtime_path:
        if not os.access(runtime_path, os.R_OK):
            raise ValueError("XAR_RUNTIME_FILES is invalid: %s" % runtime_path)
        return runtime_path

    raise ValueError("Cannot determine runtime files path.")
