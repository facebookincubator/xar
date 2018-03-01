#!/usr/bin/env bash
{
  echo '#!/usr/bin/env bash'
  echo 'BOOTSTRAP_PATH="$0"'
  echo 'shift'
  echo 'DIR=$(dirname "$BOOTSTRAP_PATH")'
  echo '"${DIR}/'$1'" "${DIR}/asar/'$2'" "$@"'
} > $3
chmod +x $3
