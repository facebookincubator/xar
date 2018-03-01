from __future__ import absolute_import
from __future__ import division
from __future__ import print_function
from __future__ import unicode_literals

import os


def _make_lua_path(*dirs):
    """Return a lua module search path that searches in the given dirs."""
    paths = []
    for d in dirs:
        paths += [os.path.join(d, '?', 'init.lua'), os.path.join(d, '?.lua')]
    return ';'.join(paths)


def _make_lua_cpath(*dirs):
    """Return a lua extension search path that searches in the given dirs."""
    paths = [os.path.join(d, '?.so') for d in dirs]
    return ';'.join(paths)


def lar_boot_commands(
        preload=None,
        has_python=False,
        interpreter=None,
        interpreter_args='',
        has_run_file=False,
        run_file_name='',):
    """Generate shell commands to set up paths and start the interpreter."""
    cmds = []
    cmds += ["""
if [[ "$LAR_GDB" ]]; then
    gdb_commands=$(mktemp /tmp/lar_gdb.XXXXXX)
    echo "! rm -f $gdb_commands" >> $gdb_commands
    LAR_PREFIX="gdb.raw -x $gdb_commands --args"
fi

_save() {
    var=$1
    saved_var=FB_SAVED_$var
    if [[ -n "${!var+SET}" ]]; then
        export $saved_var="${!var}"
    fi
}

_set() {
    var=$1
    value=$2
    if [[ "$LAR_GDB" ]]; then
        echo "set environment $var $value" >> $gdb_commands
    else
        export $var="$value"
    fi
}

_append() {
    var="${1}"
    value="${!var}"
    sep="$2"
    shift 2
    for v in "$@"; do
        if [[ "${v}" ]]; then
            if [[ "${value}" ]]; then
                value=${value}${sep}
            fi
            value=${value}${v}
        fi
    done
    _set "$var" "$value"
}

_save LD_LIBRARY_PATH
_append LD_LIBRARY_PATH : ${BASE_DIR}
"""]
    if preload:
        cmds += ["""
_save LD_PRELOAD
_append LD_PRELOAD " " {preload}
""".format(preload=' '.join(preload))]

    cmds += [
        'export LUA_PATH="{}"'.format(_make_lua_path('${BASE_DIR}/_lua')),
        'export LUA_CPATH="{}"'.format(_make_lua_cpath('${BASE_DIR}/_lua')),
    ]

    if has_python:
        cmds += ["""
_save PYTHONPATH
_set PYTHONPATH "${BASE_DIR}"
_set FB_LAR_INIT_PYTHON 1
"""]

    exe_cmd = (
        'exec ${{LAR_PREFIX}} ${{BASE_DIR}}/{interpreter} {interpreter_args} '
        '${{LAR_ARGS}}'
    ).format(interpreter=interpreter, interpreter_args=interpreter_args)

    exe_args = '"$@"'
    if has_run_file:
        exe_args = '-- ${{BASE_DIR}}/{run_file_name} "$@"'.format(
            run_file_name=run_file_name)

    cmds += ["""
{exe_cmd} {exe_args}
""".format(exe_cmd=exe_cmd, exe_args=exe_args)]

    return cmds
