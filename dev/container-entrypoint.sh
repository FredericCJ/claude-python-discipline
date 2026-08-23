#!/bin/sh
set -eu

# Docker supplies an arbitrary numeric uid/gid so bind-mounted files retain the
# developer's ownership. Such an identity need not have an /etc/passwd entry;
# give tools a disposable writable home instead of requiring one.
mkdir -p "$HOME" "$XDG_CACHE_HOME" "$XDG_CONFIG_HOME"

# A Windows/WSL bind mount is owned outside the image. Trust exactly the mounted
# workspace for Git's ownership check, not every repository in the container.
git config --global --replace-all safe.directory /workspace

# PID 1 is the requested tool, so Docker stop signals reach it directly.
exec "$@"
