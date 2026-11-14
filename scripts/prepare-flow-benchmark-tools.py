#!/usr/bin/env python3
"""Install pinned benchmark-only tools privately; never changes system packages or av."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.ytbot import flow_benchmark as bench

LOCK = json.loads((Path(__file__).resolve().parents[1] / "docs/performance/benchmark-toolchain.json").read_text())


def install(root, openvino=False):
    tooling = root / "tooling"
    packages = {**LOCK["base_packages"], **(LOCK["opencl_packages"] if openvino else {})}
    for package, (version, sha256) in packages.items():
        folder = tooling / ("nasm" if package == "nasm" else "intel")
        folder.mkdir(parents=True, exist_ok=True, mode=0o700)

        def verified():
            return [file for file in folder.glob(package + "_*.deb")
                    if hashlib.sha256(file.read_bytes()).hexdigest() == sha256]

        if not verified():
            subprocess.run(["apt-get", "download", f"{package}={version}"], cwd=folder, check=True)
        archives = verified()
        if len(archives) != 1:
            raise ValueError("Downloaded package checksum does not match the reviewed version.")
        subprocess.run(["dpkg-deb", "-x", str(archives[0]), str(folder / "root")], check=True)
    environment = tooling / "build-env"
    if not environment.exists():
        subprocess.run([sys.executable, "-m", "venv", str(environment)], check=True)
    subprocess.run([str(environment / "bin/python"), "-m", "pip", "install", "--disable-pip-version-check",
                    *[f"{package}=={version}" for package, version in LOCK["build_packages"].items()]], check=True)
    source, build = tooling / "vmaf-src", tooling / "vmaf-build"
    if not source.exists():
        subprocess.run(["git", "clone", "--depth", "1", "--branch", "v3.0.0", "https://github.com/Netflix/vmaf.git", str(source)], check=True)
    actual = subprocess.check_output(["git", "-C", str(source), "rev-parse", "HEAD"], text=True).strip()
    if actual != LOCK["vmaf_revision"]:
        raise ValueError("VMAF source revision differs from the reviewed version.")
    env = {**os.environ, "PATH": str(tooling / "nasm/root/usr/bin") + ":" + str(environment / "bin") + ":/usr/local/bin:/usr/bin:/bin"}
    if not (build / "build.ninja").exists():
        subprocess.run([str(environment / "bin/meson"), "setup", str(build), str(source / "libvmaf"),
                        "-Denable_tests=false", "-Denable_docs=false", "-Denable_asm=true",
                        "-Denable_avx512=false", "-Ddefault_library=static", "--buildtype=release"], env=env, check=True)
    subprocess.run([str(environment / "bin/ninja"), "-C", str(build), "-j", "2"], env=env, check=True)
    if openvino:
        vendors = tooling / "ocl-vendors"
        vendors.mkdir(exist_ok=True, mode=0o700)
        driver = next((tooling / "intel/root").rglob("libigdrcl.so")).resolve()
        (vendors / "intel.icd").write_text(str(driver) + "\n")
        environment = tooling / "ov-env"
        if not environment.exists():
            subprocess.run([sys.executable, "-m", "venv", str(environment)], check=True)
        subprocess.run([str(environment / "bin/python"), "-m", "pip", "install", "--disable-pip-version-check",
                        *[f"{package}=={version}" for package, version in LOCK["openvino_packages"].items()]], check=True)
        # This explicitly downloads a pinned public model; no private audio is sent.
        os.environ.pop("HF_HUB_OFFLINE", None)
        from huggingface_hub import snapshot_download
        model = LOCK["openvino_model"]
        snapshot_download(model["repo"], revision=model["revision"], local_dir=tooling / "ov-model",
                          token=False, max_workers=2)
    bench.save(tooling / ("openvino-toolchain.json" if openvino else "install-manifest.json"), LOCK)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--production-root", type=Path, required=True)
    parser.add_argument("--openvino", action="store_true", help="also prepare the pinned private OpenVINO/Intel OpenCL experiment")
    parser.add_argument("--runtime-tools", action="store_true", help="install only into PRODUCTION/.local/flow-tools after production is inactive")
    parser.add_argument("--label", default=uuid.uuid4().hex[:8])
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    os.umask(0o077)
    if not re.fullmatch(r"[a-z0-9-]{1,40}", args.label):
        raise ValueError("Installation label must be lowercase letters, digits or hyphens.")
    if args.runtime_tools:
        if args.root.is_symlink() or (args.production_root / ".local").is_symlink():
            raise ValueError("Runtime tools cannot replace a linked owner directory.")
        root = args.root.resolve()
        if root != (args.production_root.resolve() / ".local/flow-tools"):
            raise ValueError("Runtime installation has one fixed private destination.")
        if not args.worker:
            bench.assert_idle(args.production_root)
        root.mkdir(parents=True, exist_ok=True, mode=0o700)
        root.chmod(0o700)
    else:
        root = bench.private_root(args.root, args.production_root)
    if args.worker:
        if "flowbench-" not in Path("/proc/self/cgroup").read_text():
            raise ValueError("Tool installation requires its isolated benchmark unit.")
        install(root, args.openvino)
    else:
        permit = root / "paused-production.json"
        bench.PAUSE_PERMIT = json.loads(permit.read_text()) if permit.exists() else None
        bench.BENCHMARK_ROOT = root
        command = [sys.executable, str(Path(__file__).resolve()), "--root", str(root),
                   "--production-root", str(args.production_root), "--worker"]
        if args.openvino:
            command.append("--openvino")
        if args.runtime_tools:
            command.append("--runtime-tools")
        resources = bench.bounded(command, root / "tooling" / ("install-" + args.label), args.production_root)
        bench.save(root / "tooling" / ("install-resources-" + args.label + ".json"), resources)


if __name__ == "__main__":
    main()
