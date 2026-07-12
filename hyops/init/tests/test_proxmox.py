import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from hyops.init.targets.proxmox import _remote_token_controls


class ProxmoxTokenRotationTest(unittest.TestCase):
    def test_known_secret_reuses_token(self):
        self.assertEqual(
            _remote_token_controls(token_secret="known", force=False),
            ["SKIP_TOKEN_GEN=1"],
        )

    def test_force_explicitly_allows_rotation(self):
        self.assertEqual(
            _remote_token_controls(token_secret="", force=True),
            ["ALLOW_TOKEN_ROTATION=1"],
        )

    def test_unknown_existing_token_is_not_rotated(self):
        script = (
            Path(__file__).parents[2]
            / "assets"
            / "init"
            / "proxmox"
            / "bootstrap-proxmox-remote.sh"
        )
        with tempfile.TemporaryDirectory() as tmp:
            fake_pveum = Path(tmp) / "pveum"
            fake_pveum.write_text(
                """#!/usr/bin/env bash
if [[ "$*" == *"user list"* ]]; then
  printf '%s\n' '[{"userid":"automation@pam"}]'
elif [[ "$*" == *"token list"* ]]; then
  printf '%s\n' '[{"tokenid":"infra-token"}]'
else
  exit 99
fi
""",
                encoding="utf-8",
            )
            fake_pveum.chmod(0o755)
            fake_pvesh = Path(tmp) / "pvesh"
            fake_pvesh.write_text("#!/usr/bin/env bash\nexit 99\n", encoding="utf-8")
            fake_pvesh.chmod(0o755)
            env = dict(os.environ)
            env.update(
                {
                    "PATH": f"{tmp}:{env['PATH']}",
                    "USER_FQ": "automation@pam",
                    "TOKEN_NAME": "infra-token",
                }
            )
            result = subprocess.run(
                ["bash", str(script)],
                env=env,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )

        self.assertEqual(result.returncode, 3)
        self.assertIn("rotation was not authorised", result.stderr)
        self.assertNotIn("Rotating token", result.stderr)


if __name__ == "__main__":
    unittest.main()
