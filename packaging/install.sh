#!/bin/sh
set -eu
bundle=$(CDPATH= cd -P -- "$(dirname -- "$0")" && pwd)
if [ ! -x "$bundle/runtime/node/bin/node" ]; then
  echo "Incomplete archive: extract the entire installer before running install.sh." >&2
  exit 1
fi
exec "$bundle/runtime/node/bin/node" "$bundle/install.mjs" "$@"
