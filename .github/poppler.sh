#!/usr/bin/env bash
# Installs poppler-utils on an Ubuntu runner from packages CI kept from an earlier run, so a run doesn't fail when the
# runner can't reach Ubuntu's package mirror. Only when nothing is kept, or the kept packages no longer fit the runner,
# does it download them. ci.yml keeps the folder between runs with actions/cache.
set -u
debs="$HOME/.cache/poppler-debs"

if ls "$debs"/*.deb >/dev/null 2>&1 && sudo dpkg -i "$debs"/*.deb && command -v pdftotext >/dev/null; then
    echo "Installed poppler-utils from the packages kept from an earlier run."
    exit 0
fi

# Download only, into the folder that's kept, then install from it: what's kept is exactly what was installed.
sudo rm -rf "$debs"
mkdir -p "$debs/partial"
sudo apt-get update
sudo apt-get install -y --download-only -o Acquire::Retries=3 -o Dir::Cache::Archives="$debs/" poppler-utils || exit 1
sudo dpkg -i "$debs"/*.deb || exit 1
# apt leaves a lock and a partial folder owned by root, which would stop the folder being kept.
sudo rm -rf "$debs/partial" "$debs/lock"
sudo chown -R "$(id -u):$(id -g)" "$debs"
command -v pdftotext >/dev/null
