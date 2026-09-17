#!/usr/bin/env bash
#
# SUPERSEDED: the release workflow calls generate_package_sboms.sh, which emits
# one CycloneDX SBOM per published package. This whole-workspace script is kept
# for local one-off use and is referenced by no workflow or doc.
# Generate a CycloneDX SBOM of the workspace's locked dependencies.
#
# Supply-chain integrity (the engineering spec, section 17): a release ships an
# SBOM so consumers can audit exactly what they install. The SBOM is built from
# the resolved uv lockfile - the same versions and hashes that get installed -
# and excludes the workspace's own packages (`--no-emit-workspace`), leaving the
# third-party dependency set.
#
# Usage: scripts/generate_sbom.sh [output-path]   (default: dist/sbom.cdx.json)
set -euo pipefail

out="${1:-dist/sbom.cdx.json}"
mkdir -p "$(dirname "$out")"

reqs="$(mktemp)"
trap 'rm -f "$reqs"' EXIT

uv export --format requirements-txt --no-emit-workspace -o "$reqs"
# Pin the SBOM tool's major version so the output format stays reproducible
# across release runs (a supply-chain product should not let its own SBOM drift).
uvx --from 'cyclonedx-bom>=7.3,<8' cyclonedx-py requirements "$reqs" \
  --output-file "$out" --output-format JSON --validate

echo "wrote CycloneDX SBOM -> $out"
