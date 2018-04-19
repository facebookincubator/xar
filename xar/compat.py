from __future__ import absolute_import
from __future__ import division
from __future__ import print_function
from __future__ import unicode_literals

import sys


PY2 = sys.version_info[0] == 2

try:
    # >= 3.4
    from importlib.util import cache_from_source, source_from_cache
except ImportError:
    if not PY2:
        # >= 3.0, < 3.4
        from imp import cache_from_source, source_from_cache
    else:
        # Not present in Python 2
        def cache_from_source(path, debug_override=None):
            assert path.endswith(".py")
            if debug_override is None:
                debug_override = __debug__
            if debug_override:
                suffix = "c"
            else:
                suffix = "o"
            return path + suffix

        def source_from_cache(path):
            assert path.endswith("c") or path.endswith("o")
            return path[:-1]
