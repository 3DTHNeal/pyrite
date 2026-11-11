#!/usr/bin/env bash
# Installs Ubuntu packages on a runner from the copies CI kept from an earlier run, so a run doesn't fail or stall when
# the runner can't reach Ubuntu's package mirror. Only when nothing is kept, or the kept copies no longer install on
# the runner, does it download them. ci.yml keeps each folder between runs with actions/cache.
#   bash .github/apt-kept.sh <folder name> <package>...
# APT_KEPT_OPTS holds extra options for apt-get install, such as --no-install-recommends.
set -u
name=$1
shift
debs="$HOME/.cache/apt-kept/$name"

# An earlier run found every package already on the runner.
if [ -f "$debs/nothing-needed" ]; then
    echo "Nothing to install for $name: the runner already has it."
    exit 0
fi
if ls "$debs"/*.deb >/dev/null 2>&1 && sudo dpkg -i "$debs"/*.deb; then
    echo "Installed $name from the packages kept from an earlier run."
    exit 0
fi

# Download only, into the folder that's kept, then install from it: what's kept is exactly what was installed.
sudo rm -rf "$debs"
mkdir -p "$debs/partial"
sudo apt-get update
# shellcheck disable=SC2086  # The options are meant to split into words.
sudo apt-get install -y --download-only -o Acquire::Retries=3 -o Dir::Cache::Archives="$debs/" ${APT_KEPT_OPTS:-} "$@" || exit 1
# apt leaves a lock and a partial folder owned by root, which would stop the folder being kept.
sudo rm -rf "$debs/partial" "$debs/lock"
sudo chown -R "$(id -u):$(id -g)" "$debs"
if ls "$debs"/*.deb >/dev/null 2>&1; then
    sudo dpkg -i "$debs"/*.deb || exit 1
else
    touch "$debs/nothing-needed"
fi
