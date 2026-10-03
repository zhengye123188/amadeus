#!/bin/sh
# Public download entry point; the downloaded installer includes its runtimes.
set -eu

VERSION=0.6.4
repository=zhengye123188/amadeus

if [ "${1:-}" = "--help" ] || [ "${1:-}" = "-h" ]; then
  printf '%s\n' \
    'Download and install Amadeus for macOS or Linux with glibc (arm64 / x64).' \
    'Usage: sh download.sh [--prefix DIRECTORY] [--bin-dir DIRECTORY]' \
    'All arguments are passed to the verified standalone installer.'
  exit 0
fi

case $(uname -s) in
  Darwin) system=darwin ;;
  Linux) system=linux ;;
  *) echo 'Unsupported operating system: Amadeus supports macOS and Linux.' >&2; exit 1 ;;
esac
case $(uname -m) in
  arm64|aarch64) architecture=arm64 ;;
  x86_64|amd64) architecture=x64 ;;
  *) echo 'Unsupported architecture: Amadeus supports arm64 and x64.' >&2; exit 1 ;;
esac

if ! command -v curl >/dev/null 2>&1; then
  echo 'Missing curl. Install curl and run this command again.' >&2
  exit 1
fi
if command -v shasum >/dev/null 2>&1; then
  checksum_tool=shasum
elif command -v sha256sum >/dev/null 2>&1; then
  checksum_tool=sha256sum
else
  echo 'Missing SHA-256 utility (shasum or sha256sum).' >&2
  exit 1
fi

asset=amadeus-${VERSION}-${system}-${architecture}.run
base_url=https://github.com/${repository}/releases/download/v${VERSION}
temporary=$(mktemp -d "${TMPDIR:-/tmp}/amadeus-download.XXXXXX")
trap 'rm -rf "$temporary"' 0
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM

download() {
  curl --fail --show-error --location --retry 3 --connect-timeout 15 \
    --proto '=https' --proto-redir '=https' --output "$2" "$1"
}

printf 'Downloading Amadeus %s for %s/%s...\n' "$VERSION" "$system" "$architecture"
download "$base_url/$asset" "$temporary/$asset"
download "$base_url/$asset.sha256" "$temporary/$asset.sha256"

# Parse only our exact basename, never filenames or shell text supplied remotely.
record=$(cat "$temporary/$asset.sha256")
case $record in
  *"  $asset") expected=${record%"  $asset"} ;;
  *) echo 'Invalid installer checksum file.' >&2; exit 1 ;;
esac
case $expected in
  ''|*[!0-9a-f]*) echo 'Invalid installer checksum file.' >&2; exit 1 ;;
esac
if [ "${#expected}" -ne 64 ]; then
  echo 'Invalid installer checksum file.' >&2
  exit 1
fi

# Hash stdin so temporary directory names cannot alter checksum output escaping.
if [ "$checksum_tool" = shasum ]; then
  actual=$(shasum -a 256 < "$temporary/$asset")
else
  actual=$(sha256sum < "$temporary/$asset")
fi
actual=${actual%% *}
if [ "$actual" != "$expected" ]; then
  echo 'Installer checksum failed. Download the complete file again.' >&2
  exit 1
fi

# A piped download entry point must not feed its script text into the installer.
sh "$temporary/$asset" "$@" < /dev/null
