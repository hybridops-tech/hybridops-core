from __future__ import annotations

import errno
import json
import unittest
from contextlib import chdir
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from hyops.continuity import storage


class FileOperationStoreTests(unittest.TestCase):
    def test_lease_rejects_missing_changed_or_replaced_claim(self) -> None:
        with TemporaryDirectory() as tmp:
            store = storage.FileOperationStore(Path(tmp))
            record = {"status": "succeeded"}
            for mode in ("missing", "changed", "replaced"):
                for committed in (False, True):
                    with self.subTest(mode=mode, committed=committed):
                        operation_id = f"{mode}-{committed}"
                        lease = store.acquire(
                            operation_id, {"operation_id": operation_id}
                        )
                        if committed:
                            store.publish(lease, record)
                        claim = lease.record_path.with_name("claim.json")
                        if mode == "missing":
                            claim.unlink()
                        elif mode == "changed":
                            claim.write_text("{}\n")
                        else:
                            archived = claim.rename(claim.with_suffix(".old"))
                            claim.write_bytes(archived.read_bytes())
                        with self.assertRaises(OSError):
                            store.publish(lease, record)
                        self.assertIs(
                            store.probe(lease, record), storage.PublicationState.UNKNOWN
                        )
                        self.assertEqual(lease.record_path.exists(), committed)

    def test_acquisitions_are_distinct_even_if_inode_numbers_are_reused(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp) / "operations"
            store = storage.FileOperationStore(root)
            claim = {"operation_id": "run"}
            old = store.acquire("run", claim)
            root.rename(root.with_name("archived"))
            new = store.acquire("run", claim)
            old = replace(
                old,
                directory_identity=new.directory_identity,
                claim_identity=new.claim_identity,
            )
            self.assertIs(store.probe(old, {}), storage.PublicationState.UNKNOWN)
            with self.assertRaises(OSError):
                store.publish(old, {})
            self.assertIs(store.probe(new, {}), storage.PublicationState.ABSENT)

    def test_claim_lost_while_syncing_terminal_is_not_acknowledged(self) -> None:
        with TemporaryDirectory() as tmp:
            store = storage.FileOperationStore(Path(tmp))
            lease = store.acquire("run", {"operation_id": "run"})
            claim = lease.record_path.with_name("claim.json")
            sync = storage._sync_directory

            def lose_claim(path, directory):
                sync(path, directory)
                claim.unlink()

            with (
                patch.object(storage, "_sync_directory", side_effect=lose_claim),
                self.assertRaises(OSError),
            ):
                store.publish(lease, {})
            self.assertTrue(lease.record_path.exists())
            self.assertIs(store.probe(lease, {}), storage.PublicationState.UNKNOWN)

    def test_nonregular_record_is_unknown_and_its_descriptor_is_closed(self) -> None:
        with TemporaryDirectory() as tmp:
            store = storage.FileOperationStore(Path(tmp))
            lease = store.acquire("run", {"operation_id": "run"})
            lease.record_path.mkdir()
            opened = []
            open_fd = storage.os.open

            def capture_fd(path, *args, **kwargs):
                fd = open_fd(path, *args, **kwargs)
                if path == lease.record_path.name:
                    opened.append(fd)
                return fd

            with patch.object(storage.os, "open", side_effect=capture_fd):
                self.assertIs(store.probe(lease, {}), storage.PublicationState.UNKNOWN)
            self.assertEqual(len(opened), 1)
            with self.assertRaises(OSError) as error:
                storage.os.fstat(opened[0])
            self.assertEqual(error.exception.errno, errno.EBADF)

    def test_old_lease_cannot_use_a_replacement_store(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp) / "operations"
            store = storage.FileOperationStore(root)
            claim = {"operation_id": "run"}
            record = {"status": "succeeded"}
            old = store.acquire("run", claim)
            root.rename(Path(tmp) / "archived")
            self.assertIs(store.probe(old, record), storage.PublicationState.UNKNOWN)
            new = store.acquire("run", claim)
            with self.assertRaisesRegex(OSError, "no longer matches"):
                store.publish(old, record)
            self.assertFalse(new.record_path.exists())
            self.assertIs(store.probe(old, record), storage.PublicationState.UNKNOWN)
            self.assertIs(store.probe(new, record), storage.PublicationState.ABSENT)
            store.publish(new, record)
            self.assertIs(store.probe(old, record), storage.PublicationState.UNKNOWN)
            self.assertIs(store.probe(new, record), storage.PublicationState.COMMITTED)

    def test_directory_replaced_during_terminal_link_is_not_written(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp) / "operations"
            archived = Path(tmp) / "archived"
            store = storage.FileOperationStore(root)
            claim = {"operation_id": "run"}
            record = {"status": "succeeded"}
            old = store.acquire("run", claim)
            link = storage.os.link

            def swap_before_link(src, dst, **kwargs):
                if dst == "terminal.json":
                    root.rename(archived)
                    store.acquire("run", claim)
                link(src, dst, **kwargs)

            with (
                patch.object(storage.os, "link", side_effect=swap_before_link),
                self.assertRaisesRegex(OSError, "directory changed"),
            ):
                store.publish(old, record)
            self.assertFalse(old.record_path.exists())
            self.assertIs(store.probe(old, record), storage.PublicationState.UNKNOWN)
            original = archived / old.record_path.relative_to(root)
            self.assertEqual(json.loads(original.read_text()), record)

    def test_relative_root_binds_claim_and_lease_to_one_directory(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            other = root / "other"
            other.mkdir()
            with chdir(root):
                store = storage.FileOperationStore(Path("operations"))
            with chdir(other):
                lease = store.acquire("run", {"operation_id": "run"})
            record = {"status": "succeeded"}
            with chdir(root):
                store.publish(lease, record)
            with chdir(other):
                self.assertIs(
                    store.probe(lease, record), storage.PublicationState.COMMITTED
                )
                self.assertEqual(store.terminal_path("run"), lease.record_path)
                with self.assertRaises(FileExistsError):
                    store.acquire("run", {"operation_id": "run"})
            claim = json.loads(lease.record_path.with_name("claim.json").read_text())
            self.assertEqual(lease.record_path, Path(claim["terminal_record"]))
            self.assertTrue(lease.record_path.is_relative_to(root / "operations"))
            self.assertFalse((other / "operations").exists())

    def test_first_acquire_syncs_new_directory_entries_before_claim(self) -> None:
        with TemporaryDirectory() as tmp:
            anchor = Path(tmp) / "existing"
            anchor.mkdir()
            parent = anchor / "state"
            store = storage.FileOperationStore(parent / "operations")
            with patch.object(
                storage, "_sync_directory", wraps=storage._sync_directory
            ) as sync:
                lease = store.acquire("run", {"operation_id": "run"})
            synced = [call.args[0] for call in sync.call_args_list]
            self.assertEqual(
                synced[-4:],
                [anchor, parent, parent / "operations", lease.record_path.parent],
            )

    def test_existing_store_does_not_require_reading_its_parent(
        self,
    ) -> None:
        with TemporaryDirectory() as tmp:
            parent = Path(tmp) / "private"
            root = parent / "operations"
            root.mkdir(parents=True)
            try:
                for mode in (0o111, 0o300):
                    with self.subTest(mode=oct(mode)):
                        parent.chmod(mode)
                        operation_id = str(mode)
                        lease = storage.FileOperationStore(root).acquire(
                            operation_id, {"operation_id": operation_id}
                        )
                        self.assertTrue(
                            lease.record_path.with_name("claim.json").is_file()
                        )
            finally:
                parent.chmod(0o700)

    def test_new_store_is_not_created_if_parent_cannot_be_opened_for_sync(self) -> None:
        with TemporaryDirectory() as tmp:
            parent = Path(tmp)
            root = parent / "operations"
            open_fd = storage.os.open

            def deny_parent(path, *args, **kwargs):
                if path == parent:
                    raise PermissionError("parent cannot be opened for sync")
                return open_fd(path, *args, **kwargs)

            with patch.object(storage.os, "open", side_effect=deny_parent):
                for _ in range(2):
                    with self.assertRaises(PermissionError):
                        storage.FileOperationStore(root).acquire(
                            "run", {"operation_id": "run"}
                        )
                    self.assertFalse(root.exists())

    def test_failed_parent_sync_blocks_claim_and_is_retried(self) -> None:
        with TemporaryDirectory() as tmp:
            anchor = Path(tmp) / "existing"
            anchor.mkdir()
            root = anchor / "state" / "operations"
            sync = storage._sync_directory

            def fail_parent(path: Path, directory: int | None = None) -> None:
                if path == anchor:
                    raise OSError("directory sync failed")
                sync(path, directory)

            with (
                patch.object(storage, "_sync_directory", side_effect=fail_parent),
                self.assertRaisesRegex(OSError, "directory sync failed"),
            ):
                storage.FileOperationStore(root).acquire("run", {"operation_id": "run"})
            self.assertFalse(root.exists())
            with patch.object(storage, "_sync_directory", wraps=sync) as retry:
                lease = storage.FileOperationStore(root).acquire(
                    "run", {"operation_id": "run"}
                )
            retry.assert_any_call(anchor)
            self.assertTrue(lease.record_path.with_name("claim.json").is_file())
