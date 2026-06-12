#!/bin/sh
for arg in "$@"; do
  if [ "$arg" = "--help" ] || [ "$arg" = "-h" ]; then
    $TUDA_WSS_BASE_SCRIPTS/_clean.py "$@"
    return 0
  fi
done

# Computed before cleaning so package resolution (e.g. --this) runs in the
# user's current directory, not the scripts directory.
TMP_REMOVAL_EXPORT=$(python3 "$TUDA_WSS_BASE_SCRIPTS/helpers/remove_packages_from_env.py" "$@")
if $TUDA_WSS_BASE_SCRIPTS/_clean.py "$@"; then
  eval "$TMP_REMOVAL_EXPORT"
fi
unset TMP_REMOVAL_EXPORT
