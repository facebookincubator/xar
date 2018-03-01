# Copyright 2004-present Facebook. All Rights Reserved.
from __future__ import absolute_import
from __future__ import division
from __future__ import print_function


# Put everything inside an __invoke_main() function.
# This way anything we define won't pollute globals(), since runpy
# will propagate our globals() as to the user's main module.
def __invoke_main():
    import runpy
    import fcntl
    import os
    import shlex
    import sys
    import time

    module = os.getenv("FB_XAR_MAIN_MODULE")
    sys.argv[0] = os.getenv("FB_XAR_INVOKED_NAME")

    # When invoked with exec -a, sys.executable isn't the Python
    # interpreter, so we must fix it ourselves here.
    command_parts = shlex.split(os.getenv("FB_PYTHON_COMMAND", ""))
    if not command_parts or not os.access(command_parts[0], os.X_OK):
        sys.stderr.write("FB_PYTHON_COMMAND is not executable, aborting: %s",
                         os.getenv("FB_PYTHON_COMMAND"))
        os.abort()
    sys.executable = command_parts[0]

    def LogUsageToScribe():
        yes_variants = ["true", "yes", "enabled", "1"]
        if os.getenv("SCRIBE_LOG_USAGE", 'nope').lower() not in yes_variants:
            # We want to fail closed (that is, not log). So if the environment
            # variable doesn't contain one of our ways to say "yes, please
            # log", we don't. Simply return early.
            return

        scribe_cat = "/usr/local/bin/scribe_cat"   # Required to talk to scribe
        whoami = "/etc/fbwhoami"                   # For cluster info
        opt_in_file = "/etc/please-log-par-usage"  # Existence means we can log
        required_paths = [scribe_cat, whoami, opt_in_file]

        if not all([os.path.exists(p) for p in required_paths]):
            # Missing required files, bail before doing anything else
            return

        pid = -1
        try:
            pid = os.fork()
        except OSError:
            # Machine is hosed, give up
            sys.exit(os.EX_OSERR)

        if pid > 0:
            # We're the parent (the original par); wait for our child to spawn
            # a grandchild and exit, then we can return. We do this so that we
            # don't end up with a zombie in the process table (which will
            # confuse people and/or cause them to think something is wrong).
            os.waitpid(pid, 0)
            return

        # We're the child.  Kick off scribe logging, and never return.
        try:
            # Grab a new session before spawning grandchild
            os.setsid()

            # Fork a grandchild, so this process can exit.
            pid = os.fork()
            if pid == 0:
                # We're the grandchild, time to do work.
                LogUsageToScribeChildProcess(scribe_cat, whoami)
        finally:
            # The child and grandchildren processes should always _exit(), and
            # should never return or throw an exception from this function.
            os._exit(os.EX_OSERR)

    def LogUsageToScribeChildProcess(scribe_cat, whoami):
        os.umask(0o027)
        os.chdir("/")

        import json

        with open(whoami) as whoami:
            whoami_info = dict([l.strip().split('=', 1) for l in whoami])

        tty = os.environ.get('SSH_TTY', '')

        # It's slightly more likely stderr is going to the terminal than
        # stdout, right?
        for pipe in [sys.stderr, sys.stdout, sys.stdin]:
            try:
                tty = os.ttyname(pipe.fileno())
                break
            except OSError:
                pass

        sample = {
            "time": int(time.time()),
            "host": whoami_info['DEVICE_NAME'],
            "user": (os.getenv('SUDO_USER') or
                     os.getenv('LOGNAME', 'anonymous')),
            "cluster": "{DEVICE_DATACENTER}.{DEVICE_CLUSTER}".format(
                **whoami_info
            ),
            "invoked_as": sys.argv[0],
            "parstyle": "xar",
            "args": [] if len(sys.argv) == 1 else sys.argv[1:],
            'launch_time_millis': -1,
            'dieted': False,
            'tty': tty,
        }

        # Beware that this can fail if some of the command line arguments or
        # environment variables cannot be converted to UTF-8.
        # At the moment we let it throw and just don't log a sample in this
        # case.  It would probably be nicer to handle this better in the
        # future.
        str_sample = json.dumps(sample)

        # NOTE It is very important that we set the SCRIBE_LOG_USAGE
        # environment variable to false. Otherwise, scribe_cat (which is
        # currently a par) will start logging recursively.
        os.execve(scribe_cat, [
            "%s_scribe_usage_log" % os.path.basename(sys.argv[0]),
            "cli_tool_usage",
            str_sample,
        ], {'SCRIBE_LOG_USAGE': 'false'})

    try:
        LogUsageToScribe()
    except Exception:
        # Logging to scribe is basically optional; if anything goes wrong there
        # ignore it.
        pass

    # Hold a file descriptor open to a file inside our XAR to keep it
    # mounted while the xar is running.  We simply open the actual
    # directory rather than any file (which would also work).
    xar_mountpoint = os.getenv('FB_PAR_RUNTIME_FILES')
    if xar_mountpoint:
        fd = os.open(xar_mountpoint, os.O_RDONLY)
        flags = fcntl.fcntl(fd, fcntl.F_GETFD)
        fcntl.fcntl(fd, fcntl.F_SETFD, flags | fcntl.FD_CLOEXEC)

    runpy._run_module_as_main(module, False)


__invoke_main()
