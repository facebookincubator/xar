# SquashFS 101

SquashFS images are a form of loopback mounting available in the Linux
kernel.  They are read-only and support high levels of compression,
which can significantly reduce space (3-5x in many cases) while also
allowing the distribution of a single file rather than thousands.
They are often used for holding root filesystems for, say, LiveCD
distributions; in other words, the codepaths are very well tested.
In addition, Facebook already makes heavy use of SquashFS files for
distributing new versions of facebook.com to Web machines.


# XAR file details

A XAR file is a header (typically 4k) followed by a SquashFS file.
The header contains metadata such as unique IDs, build timestamps,
etc, which aid in mounting each XAR file deterministically.  The
header is actually valid shell scripts, so the XAR file can be
executable and easily parsed by tools.  If the shebang points to
xarexec then, when executed, the XAR file will be mounted and an inner
executable will be invoked.


# Dependencies

A XAR file can list one or more other XAR files as dependencies; these
will be mounted when the XAR file is mounted.  Soft and hard
dependencies are supported for debuginfo files (optional and not
necessary to function) and required files (required for the XAR to
execute properly).  The use case for hard dependencies is to allow reuse
of libraries that many other XARs depend on.  For example, you could
distribute your Python applications in a XAR that depends on another
XAR which holds the Python distribution with the standard library and
so on.

## How Dependencies Work

The idea is to move some files from the main XAR into dependent XARs.
The files in the original XAR are replaced with relative symlinks that
point to where the other XARs would be mounted.  In some cases (such
as debuginfo XARs), the symlinks may dangle.  In the future, when sparse
XARs are implemented, the symlinks should not dangle.
