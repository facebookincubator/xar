# Copyright (c) Facebook, Inc. and its affiliates. All Rights Reserved
#
# This source code is licensed under the BSD-style license found in the
# LICENSE file in the root directory of this source tree.

from __future__ import absolute_import, division, print_function, unicode_literals


BOOTSTRAP_XAR = "bootstrap_xar.sh"
RUN_XAR_MAIN = "__run_xar_main__.py"

BOOTSTRAP_XAR_TEMPLATE = """#!/bin/sh -eu

readlink_e() {{
    local path="$1"
    readlink -e "$path" 2>/dev/null && return

    # macosx / bsd readlink doesn't support -e
    # so use pwd -P with some recursive readlinking

    # strip trailing /
    path="${{path%/}}"

    # make path an absolute path
    if [[ "${{path:0:1}}" != "/" ]]
    then
        path="$(pwd -P)/$path"
    fi

    local slash_basename=""
    local counter=0
    while [[ -h "$path" ]]
    do
        if [[ counter -gt 200 ]]
        then
            echo "ERROR: Cyclical symbolic link detected: $path" 1>&2
            return
        fi
        counter=$(( counter + 1 ))

        target="$(readlink "$path")"
        if [[ "${{target:0:1}}" == "/" ]]
        then
            path="$target"
        else
            slash_basename="/$(basename "$path")"
            path="${{path%$slash_basename}}/$target"
        fi
    done

    # determine the target
    slash_basename="/$(basename "$path")"
    if [[ "$slash_basename" == "/.." || "$slash_basename" == "/." ]]
    then
        slash_basename=""
    fi
    local parent_dir="${{path%$slash_basename}}"

    # subshell to preserve the cwd (instead of pushd/popd)
    (cd "$parent_dir"; echo "$(pwd -P)$slash_basename")
}}

BOOTSTRAP_PATH="$0"
ORIGINAL_EXECUTABLE="$1"; shift
DIR=$(dirname "$BOOTSTRAP_PATH")

# Save any existing LD_LIBRARY_PATH
if [ -n "${{LD_LIBRARY_PATH+SET}}" ]; then
  export XAR_SAVED_LD_LIBRARY_PATH=$LD_LIBRARY_PATH
fi

# Don't inherit PYTHONPATH.  We set it to be the XAR mountpoint.
if [ -n "${{PYTHONPATH+SET}}" ]; then
  export XAR_SAVED_PYTHONPATH=$PYTHONPATH
fi

export XAR_INVOKED_NAME="$ORIGINAL_EXECUTABLE"
export LD_LIBRARY_PATH="$DIR"
export PYTHONPATH="$DIR"
export XAR_RUNTIME_FILES
XAR_RUNTIME_FILES="$(dirname "$(readlink_e "$BOOTSTRAP_PATH")")"
export XAR_PYTHON_COMMAND="{python}"

exec {python} "$DIR/{run_xar_main}" "$@"
"""


def run_xar_main(**kwargs):
    """
    Constructs the run_xar_main given the template arguments.
    If the {function} template argument is present, then the entry point
    {module}.{function}() is executed as main. Otherwise, {module} is run as the
    main module.
    """
    run_xar_main = """
from __future__ import absolute_import
from __future__ import division
from __future__ import print_function


# Put everything inside an __invoke_main() function.
# This way anything we define won't pollute globals(), since runpy
# will propagate our globals() as to the user's main module.
def __invoke_main():
    import fcntl
    import os
    import shlex
    import sys

    sys.argv[0] = os.getenv("XAR_INVOKED_NAME")

    # Hold a file descriptor open to a file inside our XAR to keep it
    # mounted while the xar is running.  We simply open the actual
    # directory rather than any file (which would also work).
    xar_mountpoint = os.getenv('XAR_RUNTIME_FILES')
    if xar_mountpoint:
        fd = os.open(xar_mountpoint, os.O_RDONLY)
        flags = fcntl.fcntl(fd, fcntl.F_GETFD)
        fcntl.fcntl(fd, fcntl.F_SETFD, flags | fcntl.FD_CLOEXEC)
"""
    if "function" in kwargs:
        run_xar_main += """
    import {module}
    {module}.{function}()
"""
    else:
        run_xar_main += """
    import runpy
    module = "{module}"
    runpy._run_module_as_main(module, False)
"""
    run_xar_main += """

__invoke_main()
"""

    return run_xar_main.format(**kwargs)
