#!/usr/bin/env bash
# Refresh the vendored dbxcarta wheels in ./dbxcarta-dist from a dbxcarta build.
#
# ./dbxcarta-dist is committed: it is the simulate-publish index that both uv
# (locally, via uv.toml find-links) and the databricks.yml jobs (as `whl:`
# libraries) resolve dbxcarta from while it is not on PyPI. A new developer needs
# only `uv sync` and never runs this script.
#
# Run this only as a maintainer, when dbxcarta source changes and the vendored
# wheels need to be rebuilt. Build the wheels first in the dbxcarta checkout:
#   cd <dbxcarta> && uv build --package dbxcarta-core \
#     && uv build --package dbxcarta-client && uv build --package dbxcarta-spark
#
# Then run this script (override the dbxcarta dist location with DBXCARTA_DIST if
# the dbxcarta checkout is not the default sibling path):
#   ./scripts/refresh_dbxcarta_dist.sh
#   DBXCARTA_DIST=/path/to/dbxcarta/dist ./scripts/refresh_dbxcarta_dist.sh
#
# Commit the refreshed ./dbxcarta-dist afterward. When dbxcarta is published to
# PyPI, delete this script and ./dbxcarta-dist and flip databricks.yml from
# `whl:` to `pypi:`.
set -euo pipefail

# Resolve paths from the script location, not the caller's working directory, so
# the script works regardless of where it is invoked from.
here="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
dist="${DBXCARTA_DIST:-${here}/../../../dbxcarta/dist}"
vendored="${here}/dbxcarta-dist"

if [[ ! -d "${dist}" ]]; then
  echo "error: dbxcarta dist not found at ${dist}" >&2
  echo "       build the wheels (uv build --package dbxcarta-{core,client,spark})" >&2
  echo "       or set DBXCARTA_DIST to the dbxcarta dist directory." >&2
  exit 1
fi

mkdir -p "${vendored}"
rm -f "${vendored}"/dbxcarta_*.whl "${vendored}"/dbxcarta_*.tar.gz

count=0
for pkg in dbxcarta_core dbxcarta_spark dbxcarta_client; do
  # Pick the most recent matching wheel so a rebuilt dist with several versions
  # still vendors exactly one wheel per package, and the matching sdist.
  wheel="$(ls -t "${dist}/${pkg}"-*.whl 2>/dev/null | head -n 1 || true)"
  if [[ -z "${wheel}" ]]; then
    echo "error: no wheel for ${pkg} in ${dist}" >&2
    exit 1
  fi
  cp "${wheel}" "${vendored}/"
  echo "vendored $(basename "${wheel}") -> dbxcarta-dist/"
  sdist="$(ls -t "${dist}/${pkg}"-*.tar.gz 2>/dev/null | head -n 1 || true)"
  [[ -n "${sdist}" ]] && cp "${sdist}" "${vendored}/"
  count=$((count + 1))
done

echo "vendored ${count} dbxcarta wheel(s) into ${vendored}"
echo "commit ./dbxcarta-dist to share the refreshed build with other developers."
