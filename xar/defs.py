from __future__ import absolute_import
from __future__ import division
from __future__ import print_function
from __future__ import unicode_literals

include_defs("//common/defs/platform")

def build_is_inplace(lang):
    return ('read_config' in globals() and
            read_config(lang, 'package_style') == 'inplace')


def xar_python_binary(
        name=None,
        src_rule_name=None,
        output_name=None,
        deps=None,
        extra_make_xar_args=None,):
    """Create a XAR file from a given PAR file.

    Typically, you need only pass in a base_name; this is used to convert
    FOO.par into FOO.xar, which will be based off of the target ':FOO'.  It will
    create a custom_rule named FOO_xar that creates the actual xar file.

      name - this target name
      src_rule_name - name of the par rule to create a xar from
                      (default: name_par)
      output_name - the output xar name (default: name.xar)
      deps - the dependency to produce the par file
             (default: [':src_rule_name'])
      extra_make_xar_args - array of extra make_xar args, (default: [])
    """

    # Set some sensible defaults based on name
    if src_rule_name is None:
        src_rule_name = ":" + name + "_par"
    if deps is None:
        deps = [src_rule_name]
    if extra_make_xar_args is None:
        extra_make_xar_args = []
    if output_name is None:
        output_name = name + ".xar"

    if build_is_inplace('python'):
        buck_genrule(
            name=name,
            cmd='$(location //tools/xar/facebook:make_dummy_xar_in_dev_mode.sh) $OUT',
            out=output_name,
        )
    else:
        custom_rule(
            name=name,
            strict=False,  # Remove (https://fburl.com/strict-custom-rules)
            output_gen_files=[output_name],
            build_args=" ".join([
                "--xar_exec '/usr/bin/env xarexec_fuse' ",
                "--parfile=$(location %s) " % (src_rule_name,),
                "--output=%s" % (output_name,),
            ] + extra_make_xar_args),
            build_script_dep="//tools/xar/facebook:make_xar",
            deployable=True,
            deps=deps + ["//tools/xar/facebook:xar_bootstrap.sh.tmpl",
                         "//tools/xar/facebook:__run_xar_main__.py"],
        )


def xar_lua_binary(
        name=None,
        src_rule_name=None,
        executable=None,
        output_name=None,
        deps=None,
        extra_make_xar_args=None,):
    """Create a XAR file from a given LAR file.

    Typically, you need only pass in `name`; this is used to convert
    FOO_lar.lar into FOO.xar, which will be based off of the target ':FOO_lar'.
    It will create a custom_rule named FOO that creates the actual xar file.

      name - this target name
      src_rule_name - name of the lar rule to create a xar from
                      (default: name_lar)
      executable - the lua executable executed by the bootstrap script
      output_name - the output xar name (default: name.xar)
      deps - the dependency to produce the par file
             (default: [':src_rule_name'])
      extra_make_xar_args - array of extra make_xar args, (default: [])
    """

    # Set some sensible defaults based on name
    if src_rule_name is None:
        src_rule_name = ":" + name + "_lar"
    if executable is None:
        base_name = src_rule_name.split(":")[-1]
        executable = base_name + ".lex-starter"
    if deps is None:
        deps = [src_rule_name]
    if extra_make_xar_args is None:
        extra_make_xar_args = []
    if output_name is None:
        output_name = name + ".xar"

    if build_is_inplace('lua'):
        buck_genrule(
            name=name,
            cmd='$(location //tools/xar/facebook:make_dummy_xar_in_dev_mode.sh) $OUT',
            out=output_name,
        )
    else:
        custom_rule(
            name=name,
            strict=False,  # Remove (https://fburl.com/strict-custom-rules)
            output_gen_files=[output_name],
            build_args=" ".join([
                "--xar_exec '/usr/bin/env xarexec_fuse' ",
                "--xar_exec /bin/xarexec_fuse ",
                "--larfile=$(location %s) " % (src_rule_name,),
                "--lua_executable=%s " % (executable,),
                "--output=%s" % (output_name,),
            ] + extra_make_xar_args),
            build_script_dep="//tools/xar/facebook:make_xar",
            deployable=True,
            deps=deps,
        )


def xar_js_binary(
        srcs,
        index,
        name=None,
        output_name=None,):
    buck_genrule(
        name='generate_bootstrap',
        cmd='$(location //tools/xar/facebook:make_jsxar_bootstrap.sh) ' +
            index + ' $OUT',
        out='jsxar_bootstrap.sh',
    )
    if output_name is None:
        output_name = name + ".xar"
    buck_genrule(
        name=name,
        out=output_name,
        srcs=srcs + [':generate_bootstrap'],
        cmd="$(exe //tools/xar/facebook:make_xar) " + " ".join([
            "--xar_exec '/usr/bin/env xarexec_fuse'",
            "--inner_executable=jsxar_bootstrap.sh",
            "--directory=$SRCDIR",
            "--output=$OUT",
        ]),
    )


def xar_nodejs_binary(
        name,
        asar,
        main,
        output_name=None,):
    node_bin = {
        'Darwin': 'xplat//third-party/node:macos',
        'Linux': 'xplat//third-party/node:linux',
        'Windows': 'xplat//third-party/node:windows',
    }.get(get_platform(), 'Linux')
    buck_genrule(
        name='%s__run' % (name,),
        cmd=" ".join([
            'NODE="$(location %s)";' % (node_bin,),
            '$(location //tools/xar/facebook:make_nodejsxar_bootstrap.sh)',
            '"${NODE##*/}"',
            main,
            '$OUT',
        ]),
        out='jsxar_bootstrap.sh',
    )
    if output_name is None:
        output_name = name + ".xar"
    buck_genrule(
        name=name,
        out=output_name,
        srcs=[
            ':%s__run' % (name,),
            node_bin,
        ],
        cmd=" && ".join([
            " ".join([
                "$(exe xplat//third-party/node/asar:extract)",
                "$(location %s)" % asar,
                ".",
                "$SRCDIR/asar",
            ]),
            " ".join([
                "$(exe //tools/xar/facebook:make_xar)",
                "--xar_exec '/usr/bin/env xarexec_fuse'",
                "--inner_executable=jsxar_bootstrap.sh",
                "--directory=$SRCDIR",
                "--output=$OUT",
            ]),
        ]),
        executable=True,
    )
