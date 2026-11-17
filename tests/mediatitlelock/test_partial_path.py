"""短临时名回归：执行官方存储方法，只在测试临时目录读写。"""

import errno
import os
import runpy
import shutil
import tempfile
import time
import types
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor
from inspect import signature
from pathlib import Path
from threading import Barrier
from unittest.mock import Mock, patch

from test_plugin import plugin_module
from mediatitlelock_test_package.partial_path_hook import ShortPartialPathHook


class PartialPathTest(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.source = self.root / "download.mkv"
        self.source.write_bytes(b"test media content" * 128)
        self.target = self.root / "Season 1"
        self.target.mkdir()
        self.partial_paths = []

        def copy(src, dest, **kwargs):
            self.check_name(dest)
            self.partial_paths.append(dest)
            shutil.copyfile(src, dest)
            return True

        def replace(src, dest):
            self.check_name(dest)
            os.replace(src, dest)

        self.proxy = types.SimpleNamespace(copy=Mock(side_effect=copy))
        self.os = types.SimpleNamespace(replace=Mock(side_effect=replace))
        self.stop = types.SimpleNamespace(consume_transfer_stop=Mock(return_value=False))
        fixture = Path(__file__).with_name("fixtures") / "local_storage_v3.py"
        namespace = runpy.run_path(str(fixture), init_globals={
            "Path": Path, "uuid": uuid, "time": time, "os": self.os,
            "fsproxy": self.proxy, "runtime_stop_state": self.stop, "logger": Mock(),
            "get_runtime_setting": lambda *args: False, "transfer_process": Mock(),
        })
        self.storage_class = namespace["LocalStorage"]
        self.storage = self.storage_class()
        self.storage._LocalStorage__should_show_progress = lambda *args: False
        self.storage._try_reflink_copy = Mock(return_value=False)
        self.hook = ShortPartialPathHook(self.storage_class)
        self.addCleanup(self.hook.remove)

    @staticmethod
    def check_name(path):
        # macOS 等文件系统的字符限制不同，显式模拟目标 Linux 的 255 字节限制。
        if len(path.name.encode("utf-8")) > 255:
            raise OSError(errno.ENAMETOOLONG, "File name too long", str(path))

    def test_long_names_reproduce_failure_then_keep_exact_final_name(self):
        for prefix, length in (("Fixed title ", 245), ("固定标题" * 18, 245), ("边界标题", 255)):
            with self.subTest(prefix=prefix, length=length):
                name = prefix + "a" * (length - len(prefix.encode("utf-8")) - 4) + ".mkv"
                dest = self.target / name
                self.hook.remove()
                self.assertFalse(self.storage.copy(types.SimpleNamespace(path=str(self.source)), self.target, name))
                self.assertFalse(dest.exists())
                self.hook.install()
                self.assertTrue(self.storage.copy(types.SimpleNamespace(path=str(self.source)), self.target, name))
                self.assertEqual(dest.read_bytes(), self.source.read_bytes())
                self.assertEqual(dest.name, name)
                self.assertEqual(len(self.partial_paths[-1].name.encode("utf-8")), 44)
                self.assertFalse(list(self.target.glob("*.mp-partial")))

    def test_final_name_over_limit_is_not_silently_shortened(self):
        self.hook.install()
        name = "a" * 252 + ".mkv"
        self.assertFalse(self.storage.copy(types.SimpleNamespace(path=str(self.source)), self.target, name))
        self.assertTrue(self.source.exists())
        self.assertEqual(list(self.target.iterdir()), [])

    def test_copy_failure_cancel_and_rename_failure_preserve_source_and_existing_target(self):
        self.hook.install()
        dest = self.target / "existing.mkv"
        for failure in ("cancel", "copy_false", "copy_error", "rename_error"):
            with self.subTest(failure=failure):
                dest.write_bytes(b"existing media")

                def copy(src, partial, **kwargs):
                    self.assertEqual(dest.read_bytes(), b"existing media")
                    partial.write_bytes(b"incomplete media")
                    if failure == "copy_error":
                        raise OSError("copy failed")
                    return failure == "rename_error"

                self.proxy.copy.side_effect = copy
                self.proxy.copy.reset_mock()
                self.stop.consume_transfer_stop.return_value = failure == "cancel"
                with patch.object(self.os, "replace", side_effect=OSError("rename failed")):
                    self.assertFalse(self.storage._write_atomically(self.source, dest))
                if failure == "cancel":
                    self.proxy.copy.assert_not_called()
                self.assertTrue(self.source.exists())
                self.assertEqual(dest.read_bytes(), b"existing media")
                self.assertFalse(list(self.target.glob("*.mp-partial")))

    def test_cross_device_move_deletes_source_only_after_successful_final_rename(self):
        self.hook.install()
        dest = self.target / ("a" * 241 + ".mkv")

        def replace(src, target):
            if src == self.source:
                raise OSError(errno.EXDEV, "cross-device move")
            self.assertTrue(self.source.exists())
            os.replace(src, target)

        self.os.replace.side_effect = replace
        source_bytes = self.source.read_bytes()
        self.assertTrue(self.storage.move(types.SimpleNamespace(path=str(self.source)), self.target, dest.name))
        self.assertFalse(self.source.exists())
        self.assertEqual(dest.read_bytes(), source_bytes)
        self.assertFalse(list(self.target.glob("*.mp-partial")))

    def test_cross_device_move_failure_keeps_source(self):
        self.hook.install()
        self.os.replace.side_effect = OSError(errno.EXDEV, "cross-device move")
        self.proxy.copy.return_value = False
        self.proxy.copy.side_effect = None
        self.assertFalse(self.storage.move(types.SimpleNamespace(path=str(self.source)), self.target, "final.mkv"))
        self.assertTrue(self.source.exists())
        self.assertEqual(list(self.target.iterdir()), [])

    def test_local_upload_keeps_final_name_and_host_result(self):
        self.hook.install()
        name = "a" * 241 + ".mkv"
        self.storage.get_item = lambda path: path
        expected = self.source.read_bytes()
        result = self.storage.upload(types.SimpleNamespace(path=str(self.target)), self.source, name)
        self.assertEqual(result, self.target / name)
        self.assertEqual(result.read_bytes(), expected)
        self.assertFalse(self.source.exists())

    def test_concurrent_names_are_unique_and_in_target_directory(self):
        self.hook.install()
        dest = self.target / "same final title.mkv"
        with ThreadPoolExecutor(max_workers=8) as executor:
            paths = list(executor.map(lambda _: self.storage._partial_path(dest), range(128)))
        self.assertEqual(len(set(paths)), 128)
        for path in paths:
            self.assertEqual(path.parent, dest.parent)
            self.assertRegex(path.name, r"^\.[0-9a-f]{32}\.mp-partial$")

    def test_concurrent_copies_in_same_directory_do_not_mix_content(self):
        self.hook.install()
        barrier = Barrier(2)
        sources = [self.source, self.root / "other.mkv"]
        sources[1].write_bytes(b"different media")

        def copy(src, partial, **kwargs):
            partial.write_bytes(src.read_bytes())
            barrier.wait(timeout=5)
            return True

        self.proxy.copy.side_effect = copy
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(lambda src: self.storage.copy(
                types.SimpleNamespace(path=str(src)), self.target, src.name,
            ), sources))
        self.assertEqual(results, [True, True])
        for source in sources:
            self.assertEqual((self.target / source.name).read_bytes(), source.read_bytes())
        self.assertFalse(list(self.target.glob("*.mp-partial")))

    def test_unload_during_copy_keeps_the_selected_temporary_path(self):
        self.hook.install()

        def copy(src, partial, **kwargs):
            self.hook.remove()
            partial.write_bytes(src.read_bytes())
            return True

        self.proxy.copy.side_effect = copy
        self.assertTrue(self.storage.copy(types.SimpleNamespace(path=str(self.source)), self.target, "final.mkv"))
        self.assertEqual((self.target / "final.mkv").read_bytes(), self.source.read_bytes())
        self.assertFalse(list(self.target.glob("*.mp-partial")))

    def test_install_is_idempotent_and_remove_restores_exact_descriptor(self):
        original = self.storage_class.__dict__["_partial_path"]
        original_signature = signature(self.storage._partial_path)
        self.hook.install()
        installed = self.storage_class.__dict__["_partial_path"]
        self.hook.install()
        self.assertIs(self.storage_class.__dict__["_partial_path"], installed)
        self.assertEqual(signature(self.storage._partial_path), original_signature)
        self.hook.remove()
        self.hook.remove()
        self.assertIs(self.storage_class.__dict__["_partial_path"], original)

    def test_remove_does_not_replace_later_plugin_wrapper(self):
        original = self.storage_class.__dict__["_partial_path"]
        self.hook.install()
        wrapped = self.storage_class.__dict__["_partial_path"]

        @classmethod
        def later(cls, dest):
            return wrapped.__func__(cls, dest)

        self.storage_class._partial_path = later
        self.hook.remove()
        self.assertIs(self.storage_class.__dict__["_partial_path"], later)
        dest = self.target / "final.mkv"
        self.assertTrue(self.storage._partial_path(dest).name.startswith(".final.mkv."))
        self.storage_class._partial_path = original

    def test_incompatible_hosts_are_not_modified(self):
        async def async_partial(cls, dest):
            return dest

        for changes in (
            {"_partial_path": None},  # V2 没有原子复制临时名接口。
            {"_partial_path": staticmethod(lambda dest: dest)},
            {"_partial_path": classmethod(lambda cls, dest, required: dest)},
            {"_partial_path": classmethod(lambda cls, *, dest: dest)},
            {"PARTIAL_SUFFIX": ".different"},
            {"_write_atomically": None},
            {"_write_atomically": lambda self, src, dest: True},
            {"_partial_path": classmethod(async_partial)},
        ):
            with self.subTest(changes=changes), patch.multiple(self.storage_class, **changes):
                original = self.storage_class.__dict__["_partial_path"]
                with self.assertRaises(RuntimeError):
                    self.hook.install()
                self.assertFalse(self.hook.active)
                self.assertIs(self.storage_class.__dict__["_partial_path"], original)

    def test_existing_short_name_patch_is_restored_on_unload(self):
        @classmethod
        def already_short(cls, dest):
            return dest.parent / f".{uuid.uuid4().hex}.mp-partial"

        self.storage_class._partial_path = already_short
        self.hook.install()
        self.assertRegex(self.storage._partial_path(self.target / "final.mkv").name, r"^\.[0-9a-f]{32}\.mp-partial$")
        self.hook.remove()
        self.assertIs(self.storage_class.__dict__["_partial_path"], already_short)

    def test_plugin_enable_reload_disable_preserves_bindings_and_existing_files(self):
        module = types.ModuleType("app.modules.filemanager.storages.local")
        module.LocalStorage = self.storage_class
        plugin = plugin_module.MediaTitleLock()
        self.addCleanup(plugin.stop_service)
        original = self.storage_class.__dict__["_partial_path"]
        dest = self.target / "already organized.mkv"
        dest.write_bytes(b"existing media")
        with patch.dict("sys.modules", {module.__name__: module}), \
                patch.object(plugin, "get_data_path", return_value=self.root, create=True):
            plugin.init_plugin({"enabled": False})
            self.assertIs(self.storage_class.__dict__["_partial_path"], original)
            plugin.init_plugin({"enabled": True})
            binding = plugin_module.TitleBinding(media_source="themoviedb", media_id="42",
                                                canonical_title="原固定标题", media_category="日韩剧")
            plugin._store.upsert(binding)
            saved = plugin._store.get("themoviedb", "42")
            plugin.init_plugin({"enabled": True})
            self.assertTrue(plugin._partial_path_hook.active)
            self.assertRegex(self.storage._partial_path(dest).name, r"^\.[0-9a-f]{32}\.mp-partial$")
            self.assertTrue(plugin.api_save_config(plugin_module.PluginConfigRequest(enabled=False)).success)
            self.assertIs(self.storage_class.__dict__["_partial_path"], original)
            self.assertTrue(plugin.api_save_config(plugin_module.PluginConfigRequest(enabled=True)).success)
            self.assertTrue(plugin._partial_path_hook.active)
            plugin.stop_service()
            self.assertIs(self.storage_class.__dict__["_partial_path"], original)
            reopened = plugin_module.BindingStore(self.root / "title_bindings.sqlite3")
            self.assertEqual(reopened.get("themoviedb", "42"), saved)
            self.assertEqual(dest.read_bytes(), b"existing media")
            self.assertEqual(list(self.target.iterdir()), [dest])

    def test_incompatible_plugin_adapter_logs_and_keeps_other_functionality(self):
        module = types.ModuleType("app.modules.filemanager.storages.local")
        module.LocalStorage = type("V2LocalStorage", (), {})
        plugin = plugin_module.MediaTitleLock()
        plugin._enabled = True
        with patch.dict("sys.modules", {module.__name__: module}), patch.object(plugin_module.logger, "warning") as log:
            plugin._configure_partial_path_hook()
        self.assertIsNone(plugin._partial_path_hook)
        self.assertTrue(plugin.get_state())
        self.assertIn("临时文件名", log.call_args.args[0])
        self.assertIn("保留 MP 原流程", plugin.api_diagnostics().data["items"][0]["message"])
