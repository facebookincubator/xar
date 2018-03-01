#!/usr/bin/env bash

# Makes a dummy XAR for dev mode

{
  echo '#!/usr/bin/env bash'
  echo '# If somebody builds a XAR file for a python or lua binary'
  echo '# in dev mode, then they get this script which simply emits'
  echo '# an error message and then fails'
  echo 'echo "XAR building requires buck @mode/opt" >&2'
  echo 'exit 1'
} > "$1"
chmod +x "$1"
