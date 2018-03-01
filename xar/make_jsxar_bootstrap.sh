#!/usr/bin/env bash
{
  echo '#!/usr/bin/env bash'
  echo 'BOOTSTRAP_PATH="$0"'
  echo 'shift'
  echo 'DIR=$(dirname "$BOOTSTRAP_PATH")'
  echo 'node "${DIR}/'$1'" "$@"'
} > $2
chmod +x $2
