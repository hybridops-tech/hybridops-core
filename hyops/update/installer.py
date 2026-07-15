"""
purpose: Download, verify, and invoke the supported Core replacement installer.
maintainer: HybridOps.Tech
"""

from __future__ import annotations

import hashlib
import platform
import subprocess
import tarfile
import tempfile
from pathlib import Path

import requests


def _download(url: str, destination: Path, timeout: float = 30.0) -> None:
    with requests.get(url, stream=True, timeout=timeout) as response:
        response.raise_for_status()
        with destination.open("wb") as stream:
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    stream.write(chunk)


def _verify(asset: Path, checksum: Path) -> None:
    fields = checksum.read_text(encoding="utf-8").strip().split()
    if len(fields) < 2 or fields[1].lstrip("*") != asset.name:
        raise ValueError("release checksum does not name the downloaded asset")
    expected = fields[0].lower()
    if len(expected) != 64 or any(char not in "0123456789abcdef" for char in expected):
        raise ValueError("release checksum is invalid")
    digest = hashlib.sha256(asset.read_bytes()).hexdigest()
    if digest != expected:
        raise ValueError("release checksum verification failed")


def _safe_extract(archive: Path, destination: Path) -> Path:
    destination.mkdir(parents=True, exist_ok=True)
    destination_resolved = destination.resolve()
    with tarfile.open(archive, "r:gz") as bundle:
        members = bundle.getmembers()
        for member in members:
            target = (destination / member.name).resolve()
            if destination_resolved not in target.parents and target != destination_resolved:
                raise ValueError("release archive contains an unsafe path")
        bundle.extractall(destination, members=members)
    roots = [path for path in destination.iterdir() if path.is_dir()]
    if len(roots) != 1 or not (roots[0] / "install.sh").is_file():
        raise ValueError("release archive does not contain the Core installer")
    return roots[0]


def install_release(version: str, release_url: str) -> int:
    releases_url = release_url.rstrip("/").rsplit("/tag/", 1)[0]
    base_url = f"{releases_url}/download/v{version}"
    with tempfile.TemporaryDirectory(prefix="hyops-update-") as directory:
        workspace = Path(directory)
        if platform.system() == "Darwin":
            architecture = platform.machine()
            if architecture not in {"arm64", "x86_64"}:
                raise ValueError(f"unsupported macOS architecture: {architecture}")
            name = f"hybridops-core-{version}-macos-{architecture}.pkg"
            asset = workspace / name
            checksum = workspace / f"{name}.sha256"
            _download(f"{base_url}/{name}", asset)
            _download(f"{base_url}/{checksum.name}", checksum)
            _verify(asset, checksum)
            return subprocess.run(
                ["sudo", "installer", "-pkg", str(asset), "-target", "/"], check=False
            ).returncode

        name = f"hybridops-core-{version}.tar.gz"
        asset = workspace / name
        checksum = workspace / f"{name}.sha256"
        _download(f"{base_url}/{name}", asset)
        _download(f"{base_url}/{checksum.name}", checksum)
        _verify(asset, checksum)
        root = _safe_extract(asset, workspace / "release")
        return subprocess.run(["bash", str(root / "install.sh"), "--force"], check=False).returncode
