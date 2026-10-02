"""Build on the target OS/CPU; end users need only the generated .run file."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import tarfile
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run(*args, cwd=ROOT, capture=False, env=None):
    result = subprocess.run(
        [str(arg) for arg in args],
        cwd=cwd,
        check=True,
        text=True,
        stdout=subprocess.PIPE if capture else None,
        env=env,
    )
    return result.stdout.strip() if capture else None


def sha256(path):
    with Path(path).open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def download(url, checksum, cache):
    path = cache / url.rsplit("/", 1)[-1]
    if not path.exists() or sha256(path) != checksum:
        temporary = path.with_suffix(".partial")
        run(
            "curl",
            "--fail",
            "--location",
            "--silent",
            "--show-error",
            "--connect-timeout",
            "20",
            "--max-time",
            "300",
            "--retry",
            "3",
            "--proto",
            "=https",
            "--tlsv1.2",
            "--output",
            temporary,
            url,
        )
        if sha256(temporary) != checksum:
            temporary.unlink()
            raise RuntimeError(f"Runtime checksum mismatch: {path.name}")
        temporary.replace(path)
    return path


def extract(path, target):
    with tarfile.open(path) as archive:
        archive.extractall(target, filter="data")


def intel_crypto_build(bundle, staging, cache, source, env):
    """Build the locked cryptography sdist against a private static OpenSSL."""
    for command in ("cargo", "rustc", "clang", "make", "perl"):
        if not shutil.which(command):
            raise RuntimeError(f"Intel Mac build requires {command}; end users do not need it")
    archive = download(source["url"], source["sha256"], cache)
    extract(archive, staging)
    directory = staging / f"openssl-{source['version']}"
    prefix = staging / "openssl-static"
    run(
        "perl",
        "Configure",
        "darwin64-x86_64-cc",
        "no-shared",
        "no-module",
        "no-tests",
        f"--prefix={prefix}",
        cwd=directory,
        env=env,
    )
    run("make", "-s", f"-j{min(os.cpu_count() or 2, 4)}", cwd=directory, env=env)
    run("make", "-s", "install_sw", cwd=directory, env=env)
    (bundle / "licenses").mkdir(exist_ok=True)
    shutil.copy2(directory / "LICENSE.txt", bundle / "licenses/openssl.txt")
    return {**env, "OPENSSL_DIR": str(prefix), "OPENSSL_STATIC": "1"}


def check_static_crypto(site):
    binaries = list((site / "cryptography/hazmat/bindings").glob("_rust*.so"))
    if not binaries:
        raise RuntimeError("Missing cryptography native module")
    for binary in binaries:
        # MH_DYLIB modules list their own LC_ID_DYLIB in `otool -L` as well.
        # This identifier is not a dependency that must exist elsewhere on disk.
        identifiers = {
            line.strip() for line in run("otool", "-D", binary, capture=True).splitlines()[1:]
        }
        dependencies = run("otool", "-L", binary, capture=True).splitlines()[1:]
        for line in dependencies:
            library = line.strip().split(" (", 1)[0]
            if library not in identifiers and not library.startswith(
                ("/usr/lib/", "/System/Library/")
            ):
                raise RuntimeError(f"Non-portable cryptography library dependency: {library}")


def write_manifest(bundle, version, target, lock, sources):
    files = {}
    for path in sorted(bundle.rglob("*")):
        key = path.relative_to(bundle).as_posix()
        if path.is_symlink():
            link = os.readlink(path)
            if Path(link).is_absolute() or not path.resolve().is_relative_to(bundle.resolve()):
                raise RuntimeError(f"Non-portable symlink: {key}")
            files[key] = {"link": link}
        elif path.is_file():
            files[key] = {"sha256": sha256(path), "executable": path.stat().st_mode & 0o111}
    manifest = {
        "format": 1,
        "version": version,
        "platform": target,
        "node": lock["node_version"],
        "python": lock["python_version"],
        "runtimes": sources,
        "files": files,
    }
    (bundle / "bundle.json").write_text(json.dumps(manifest, indent=2) + "\n")


def self_extractor(archive, output, folder):
    checksum = sha256(archive)
    header = f'''#!/bin/sh
set -eu
temporary=$(mktemp -d "${{TMPDIR:-/tmp}}/research-install.XXXXXXXX")
trap 'rm -rf "$temporary"' 0
trap 'exit 130' INT
trap 'exit 143' TERM HUP
tail -n +__PAYLOAD_LINE__ "$0" > "$temporary/payload.tar.gz"
if command -v shasum >/dev/null 2>&1; then
  actual=$(shasum -a 256 "$temporary/payload.tar.gz")
elif command -v sha256sum >/dev/null 2>&1; then
  actual=$(sha256sum "$temporary/payload.tar.gz")
else
  echo "Missing system SHA-256 utility (shasum or sha256sum)." >&2; exit 1
fi
actual=${{actual%% *}}
if [ "$actual" != "{checksum}" ]; then
  echo "Installer checksum failed. Download the complete file again." >&2; exit 1
fi
tar -xzf "$temporary/payload.tar.gz" -C "$temporary"
sh "$temporary/{folder}/install.sh" "$@"
exit 0
'''
    header = header.replace("__PAYLOAD_LINE__", str(header.count("\n") + 1))
    with output.open("wb") as handle, archive.open("rb") as payload:
        handle.write(header.encode())
        shutil.copyfileobj(payload, handle)
    output.chmod(0o755)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "dist" / "standalone")
    parser.add_argument("--cache", type=Path, default=ROOT / "build" / "runtime-cache")
    args = parser.parse_args()
    output, cache = args.output.resolve(), args.cache.resolve()
    output.mkdir(parents=True, exist_ok=True)
    cache.mkdir(parents=True, exist_ok=True)
    system = {"Darwin": "darwin", "Linux": "linux"}.get(platform.system())
    arch = {"arm64": "arm64", "aarch64": "arm64", "x86_64": "x64"}.get(platform.machine())
    target = f"{system}-{arch}"
    lock = json.loads((ROOT / "packaging/runtimes.json").read_text())
    if target not in lock["targets"]:
        raise SystemExit(
            f"Unsupported build host: {target}. Build natively on macOS/Linux x64/arm64."
        )
    package = json.loads((ROOT / "package.json").read_text())
    version = package["version"]
    pin = lock["targets"][target]
    node_name = f"node-v{lock['node_version']}-{target}"
    python_name = f"cpython-{lock['python_version']}%2B{lock['python_release']}-{pin['python_triple']}-install_only_stripped.tar.gz"
    sources = {
        "node": {
            "url": f"https://nodejs.org/dist/v{lock['node_version']}/{node_name}.tar.gz",
            "sha256": pin["node_sha256"],
        },
        "python": {
            "url": f"https://github.com/astral-sh/python-build-standalone/releases/download/{lock['python_release']}/{python_name}",
            "sha256": pin["python_sha256"],
        },
    }
    runtime_archives = {
        name: download(item["url"], item["sha256"], cache) for name, item in sources.items()
    }
    folder = f"research-cli-{version}-{target}"
    with tempfile.TemporaryDirectory(prefix="research-build-") as temporary:
        staging = Path(temporary)
        bundle = staging / folder
        runtime = bundle / "runtime"
        runtime.mkdir(parents=True)
        extract(runtime_archives["node"], runtime)
        (runtime / node_name).rename(runtime / "node")
        extract(runtime_archives["python"], runtime)
        node = runtime / "node" / "bin" / "node"
        npm = runtime / "node" / "lib" / "node_modules" / "npm" / "bin" / "npm-cli.js"
        python = runtime / "python" / "bin" / "python3"
        env = {
            **os.environ,
            "PATH": str(node.parent) + os.pathsep + os.environ.get("PATH", ""),
            "PYTHONDONTWRITEBYTECODE": "1",
        }
        # Only npm's explicit distribution file list enters the bundle, never the checkout.
        info = json.loads(
            run(
                node,
                npm,
                "pack",
                "--ignore-scripts",
                "--pack-destination",
                staging,
                "--json",
                capture=True,
                env=env,
            )
        )[0]
        extract(staging / info["filename"], bundle)
        app = bundle / "app"
        (bundle / "package").rename(app)
        shutil.copy2(ROOT / "package-lock.json", app / "package-lock.json")
        run(
            node,
            npm,
            "ci",
            "--omit=dev",
            "--ignore-scripts",
            "--no-audit",
            "--no-fund",
            cwd=app,
            env=env,
        )
        requirements = staging / "requirements.txt"
        run(
            "uv",
            "export",
            "--frozen",
            "--no-dev",
            "--all-extras",
            "--no-emit-project",
            "--output-file",
            requirements,
            capture=True,
        )
        site = runtime / "python" / "lib" / "python3.12" / "site-packages"
        build_policy = ["--no-build"]
        if target == "darwin-x64":
            # Upstream stopped publishing Intel Mac wheels. Keep the locked version;
            # build only this package and statically link OpenSSL, never Homebrew paths.
            sources["openssl"] = lock["intel_macos_openssl"]
            env = intel_crypto_build(bundle, staging, cache, sources["openssl"], env)
            binary_packages = sorted(
                set(re.findall(r"^([a-zA-Z0-9][\w.-]*)==", requirements.read_text(), re.M))
                - {"cryptography"}
            )
            build_policy = [
                "--only-binary",
                ",".join(binary_packages),
                "--no-binary",
                "cryptography",
            ]
        run(
            "uv",
            "pip",
            "install",
            "--python",
            python,
            "--target",
            site,
            "--require-hashes",
            *build_policy,
            "--link-mode",
            "copy",
            "-r",
            requirements,
            env=env,
        )
        if target == "darwin-x64":
            check_static_crypto(site)
        run("uv", "build", "--wheel", "--no-sources", "--out-dir", staging, env=env)
        wheel = next(staging.glob("research_terminal-*.whl"))
        run(
            "uv",
            "pip",
            "install",
            "--python",
            python,
            "--target",
            site,
            "--no-deps",
            "--link-mode",
            "copy",
            wheel,
            env=env,
        )
        # Local wheel provenance contains temporary build paths; manifest records shipped bytes instead.
        for path in site.glob("research_terminal-*.dist-info/direct_url.json"):
            path.unlink()
        for path in bundle.rglob("__pycache__"):
            shutil.rmtree(path)
        (bundle / "bin").mkdir()
        shutil.copy2(ROOT / "packaging/research", bundle / "bin/research")
        shutil.copy2(ROOT / "packaging/install.sh", bundle / "install.sh")
        shutil.copy2(ROOT / "packaging/install.mjs", bundle / "install.mjs")
        for name in ("bin/research", "install.sh"):
            (bundle / name).chmod(0o755)
        for name in ("LICENSE", "THIRD_PARTY_NOTICES.md"):
            shutil.copy2(ROOT / name, bundle / name)
        shutil.copy2(ROOT / "docs/standalone.md", bundle / "INSTALL.md")
        shutil.copy2(requirements, bundle / "python-requirements.txt")
        # Pi's package manager uses the bundled npm/npx for explicit package installs.
        # Preserve node/lib and their relative links so standalone users need no npm.
        for name in ("corepack",):
            (runtime / "node" / "bin" / name).unlink(missing_ok=True)
        write_manifest(bundle, version, target, lock, sources)
        archive = output / f"{folder}.tar.gz"
        with tarfile.open(archive, "w:gz", compresslevel=6) as tar:
            tar.add(bundle, arcname=folder)
        installer = output / f"{folder}.run"
        self_extractor(archive, installer, folder)
        for path in (archive, installer):
            path.with_name(path.name + ".sha256").write_text(f"{sha256(path)}  {path.name}\n")
        print(
            json.dumps(
                {"platform": target, "installer": str(installer), "bytes": installer.stat().st_size}
            )
        )


if __name__ == "__main__":
    main()
