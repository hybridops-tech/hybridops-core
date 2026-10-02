"""Shared init options must work on either side of the target name."""

import unittest

from hyops.cli import build_parser


TARGETS = (
    "aws", "azure", "gcp", "hashicorp-vault", "hetzner", "proxmox",
    "terraform-cloud", "status",
)
BOOLEAN_OPTIONS = ("non-interactive", "with-cli-login", "logout-after", "force", "dry-run")
VALUE_OPTIONS = {
    "root": "/tmp/hyops-test",
    "env": "ci-check",
    "out-dir": "/tmp/hyops-evidence",
    "config": "/tmp/hyops.conf",
    "vault-file": "/tmp/bootstrap.vault.env",
    "vault-password-file": "/tmp/vault-password",
    "vault-password-command": "test-password-helper",
}


class InitSharedArgsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.parser = build_parser()

    def test_shared_options_work_before_and_after_each_target(self):
        options = [f"--{name}" for name in BOOLEAN_OPTIONS]
        for name, value in VALUE_OPTIONS.items():
            options.extend([f"--{name}", value])
        for target in TARGETS:
            for before in (True, False):
                with self.subTest(target=target, before=before):
                    args = ["init", *options, target] if before else ["init", target, *options]
                    ns = self.parser.parse_args(args)
                    for name in BOOLEAN_OPTIONS:
                        self.assertTrue(getattr(ns, name.replace("-", "_")), name)
                    for name, value in VALUE_OPTIONS.items():
                        self.assertEqual(getattr(ns, name.replace("-", "_")), value, name)

    def test_options_can_be_split_across_the_target(self):
        for target in TARGETS:
            with self.subTest(target=target):
                ns = self.parser.parse_args([
                    "init", "--non-interactive", "--env", "ci-check",
                    target, "--dry-run", "--root", "/tmp/hyops-test",
                ])
                self.assertTrue(ns.non_interactive)
                self.assertTrue(ns.dry_run)
                self.assertEqual(ns.env, "ci-check")
                self.assertEqual(ns.root, "/tmp/hyops-test")

    def test_explicit_value_after_target_takes_precedence(self):
        for target in TARGETS:
            for name in VALUE_OPTIONS:
                with self.subTest(target=target, option=name):
                    ns = self.parser.parse_args([
                        "init", f"--{name}", "before", target, f"--{name}", "after",
                    ])
                    self.assertEqual(getattr(ns, name.replace("-", "_")), "after")

    def test_omitted_options_keep_their_defaults(self):
        for target in TARGETS:
            with self.subTest(target=target):
                ns = self.parser.parse_args(["init", target])
                for name in BOOLEAN_OPTIONS:
                    self.assertIs(getattr(ns, name.replace("-", "_")), False)
                for name in VALUE_OPTIONS:
                    self.assertIsNone(getattr(ns, name.replace("-", "_")))


if __name__ == "__main__":
    unittest.main()
