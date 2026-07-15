"""Tests for verified Core update assets."""

from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path

from hyops.update.installer import _verify


class UpdateInstallerTests(unittest.TestCase):
    def test_checksum_verification(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            asset = Path(directory) / "release.tar.gz"
            asset.write_bytes(b"release")
            digest = hashlib.sha256(asset.read_bytes()).hexdigest()
            checksum = Path(directory) / "release.tar.gz.sha256"
            checksum.write_text(f"{digest}  {asset.name}\n", encoding="utf-8")
            _verify(asset, checksum)

    def test_checksum_name_must_match_asset(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            asset = Path(directory) / "release.tar.gz"
            asset.write_bytes(b"release")
            checksum = Path(directory) / "release.tar.gz.sha256"
            checksum.write_text(f"{'0' * 64}  another.tar.gz\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "does not name"):
                _verify(asset, checksum)


if __name__ == "__main__":
    unittest.main()
