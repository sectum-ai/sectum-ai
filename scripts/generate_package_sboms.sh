#!/usr/bin/env bash
# Generate one CycloneDX SBOM per publishable distribution.
#
# Supply-chain integrity (the engineering spec, section 17): every distribution
# the release workflow uploads to PyPI gets its own SBOM so a consumer who
# installs `sectum-ai-spec` (for instance) can audit that package's resolved
# third-party tree, not the union of every package's tree.
#
# Each SBOM is built from the package's own requirements as exported from the
# uv lockfile - the same versions and hashes pip would install - and named
# `<dist-name>-<version>.cdx.json` so it sorts alongside the wheel and sdist
# of the same distribution in the release pipeline's artifact tree.
#
# Usage: scripts/generate_package_sboms.sh [output-dir]   (default: dist/sbom)
set -euo pipefail

out_dir="${1:-dist/sbom}"
mkdir -p "$out_dir"

# The five publishable distributions and their workspace paths.
# Order is fixed so the SBOM filenames are stable across release runs.
packages=(
  "sectum-ai:packages/core"
  "sectum-ai-spec:packages/spec"
  "sectum-ai-probes:packages/probes"
  "sectum-ai-adapters:packages/adapters"
  "sectum-ai-evidence:packages/evidence"
)

# Read each package's [project] version out of pyproject.toml so the SBOM
# filename pins to the same version as the wheel and sdist beside it.
# `uv run` is used so the script works with the workspace's pinned Python
# (3.12+, with the standard-library `tomllib`) regardless of which `python3`
# happens to be on the operator's PATH.
read_version() {
  uv run python -c "
import tomllib, pathlib
p = pathlib.Path('$1/pyproject.toml')
with p.open('rb') as f:
    data = tomllib.load(f)
print(data['project']['version'])
"
}

reqs="$(mktemp)"
trap 'rm -f "$reqs"' EXIT

for entry in "${packages[@]}"; do
  dist_name="${entry%%:*}"
  package_dir="${entry##*:}"
  version="$(read_version "$package_dir")"

  # Export only this package's runtime third-party tree:
  #   --package <dist>          select the workspace member
  #   --no-dev                  drop the workspace's [dependency-groups] dev tree
  #   --no-default-groups       drop the default dependency-groups (docs)
  #   --no-emit-workspace       drop the workspace's own packages (published alongside)
  # The result is what a `pip install <dist>` would resolve in production, which
  # is what the SBOM should describe.
  uv export --package "$dist_name" \
            --no-dev \
            --no-default-groups \
            --no-emit-workspace \
            --no-hashes \
            --format requirements-txt \
            -o "$reqs"

  out_file="$out_dir/${dist_name}-${version}.cdx.json"
  # Pin the SBOM tool's major version so the output format stays reproducible
  # across release runs (a supply-chain product should not let its own SBOM drift).
  uvx --from 'cyclonedx-bom>=7.3,<8' cyclonedx-py requirements "$reqs" \
    --output-file "$out_file" --output-format JSON --validate

  echo "wrote CycloneDX SBOM -> $out_file"
done
