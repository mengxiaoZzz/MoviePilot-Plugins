import tempfile
import types
import unittest
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from pathlib import Path
from threading import Barrier
from unittest.mock import patch

from test_plugin import ClassificationResult, plugin_module
from mediatitlelock_test_package.transfer_hook import TransferCategoryHook


class TransferCategoryTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.plugin = plugin_module.MediaTitleLock()
        self.plugin._enabled = True
        self.plugin._store = plugin_module.BindingStore(Path(self.directory.name) / "bindings.sqlite3")
        self.plugin._store.upsert(plugin_module.TitleBinding(
            media_source="themoviedb", media_id="333553", canonical_title="神之手",
            canonical_year="2026", media_category="剧集/港台剧集", origin="manual",
            media_root_name="保留旧字段", media_path="/media/existing", server_item_id="emby-42",
        ))
        self.binding = self.plugin._store.get("themoviedb", "333553")
        self.category_module = types.ModuleType("app.schemas.category")
        self.category_module.ClassificationSelection = types.SimpleNamespace
        self.category_module.ClassificationResult = ClassificationResult
        self.enterContext(patch.dict("sys.modules", {self.category_module.__name__: self.category_module}))

    @staticmethod
    def media(v3=True, historical_category=False):
        recognized = "剧集/南亚剧集"
        category = "剧集/港台剧集" if historical_category else recognized
        media = types.SimpleNamespace(
            media_source="themoviedb", source="themoviedb", media_id="333553", type="电视剧",
            title="神之手", year="2026", category=category,
        )
        if v3:
            recommended = types.SimpleNamespace(category_id="tv.south", category_path=recognized.split("/"),
                                                source="automatic")
            effective = types.SimpleNamespace(category_id=None, category_path=category.split("/"),
                                              source="manual") if historical_category else recommended
            media.library_category = category
            media.classification = ClassificationResult(
                recommended=recommended, effective=effective, labels=["保留"], policy_revision=7, state="complete",
            )
        return media

    def assert_binding_unchanged(self):
        reopened = plugin_module.BindingStore(Path(self.directory.name) / "bindings.sqlite3")
        self.assertEqual(reopened.get("themoviedb", "333553"), self.binding)
        self.assertEqual(reopened.count(), 1)

    def test_valid_binding_applies_before_directory_routing_without_mutating_cached_media(self):
        for v3 in (False, True):
            with self.subTest(v3=v3):
                original = self.media(v3)
                snapshot = deepcopy(original)
                with patch.object(self.plugin, "_available_categories", return_value=["剧集/港台剧集"]) as available:
                    result = self.plugin.lock_transfer_category(original)
                available.assert_called_once_with("电视剧")
                self.assertEqual(result.category, "剧集/港台剧集")
                self.assertIsNot(result, original)
                self.assertEqual(original, snapshot)
                if v3:
                    self.assertEqual(result.library_category, result.category)
                    self.assertEqual(result.classification.effective.category_path, ["剧集", "港台剧集"])
                    self.assertEqual(result.classification.recommended, snapshot.classification.recommended)
                record = self.plugin.api_diagnostics().data["items"][0]
                self.assertEqual((record["stage"], record["status"]), ("transfer_category", "applied"))
                self.assert_binding_unchanged()

    def test_missing_category_or_read_failure_keeps_recognition_and_title_binding(self):
        for v3 in (False, True):
            for read_error in (False, True):
                with self.subTest(v3=v3, read_error=read_error):
                    original = self.media(v3)
                    snapshot = deepcopy(original)
                    with patch.object(self.plugin, "_available_categories", return_value=["剧集/南亚剧集"],
                                      side_effect=RuntimeError("分类不可读") if read_error else None):
                        result = self.plugin.lock_transfer_category(original)
                    self.assertEqual(result.category, "剧集/南亚剧集")
                    self.assertEqual(original, snapshot)
                    rename = {"__mediainfo__": result, "title": "原识别标题"}
                    self.plugin.lock_rename_context(types.SimpleNamespace(event_data=types.SimpleNamespace(rename_dict=rename)))
                    self.assertEqual(rename["title"], "神之手")
                    self.plugin.remember_successful_transfer(types.SimpleNamespace(event_data={
                        "mediainfo": result, "transferinfo": types.SimpleNamespace(success=True, target_diritem=None),
                    }))
                    self.assert_binding_unchanged()

    def test_v3_invalid_historical_binding_falls_back_to_automatic_recommendation(self):
        for read_error in (False, True):
            with self.subTest(read_error=read_error):
                original = self.media(historical_category=True)
                snapshot = deepcopy(original)
                with patch.object(self.plugin, "_available_categories", return_value=["剧集/南亚剧集"],
                                  side_effect=RuntimeError("分类不可读") if read_error else None):
                    result = self.plugin.lock_transfer_category(original)
                self.assertEqual(result.category, "剧集/南亚剧集")
                self.assertEqual(result.library_category, "剧集/南亚剧集")
                self.assertEqual(result.classification.effective, result.classification.recommended)
                self.assertEqual(result.classification.labels, ["保留"])
                self.assertEqual(original, snapshot)
                self.assert_binding_unchanged()

    def test_disabled_unbound_or_missing_identity_does_not_change_media(self):
        for enabled, media in ((False, self.media()), (True, types.SimpleNamespace(category="原分类")),
                               (True, types.SimpleNamespace(source="themoviedb", media_id="999", category="原分类")),
                               (True, None)):
            with self.subTest(enabled=enabled, media=media):
                self.plugin._enabled = enabled
                with patch.object(self.plugin, "_available_categories") as available:
                    self.assertIs(self.plugin.lock_transfer_category(media), media)
                available.assert_not_called()

    def test_partial_category_write_failure_does_not_leak_or_block_transfer(self):
        original = self.media()
        snapshot = deepcopy(original)

        def fail(candidate, category):
            candidate.category = category
            raise ValueError("模拟模型写入异常")

        with patch.object(self.plugin, "_available_categories", return_value=["剧集/港台剧集"]), \
                patch.object(self.plugin, "_apply_category", side_effect=fail):
            self.assertIs(self.plugin.lock_transfer_category(original), original)
        self.assertEqual(original, snapshot)
        self.assert_binding_unchanged()

    def test_v2_invalid_history_reuses_local_recognition_rules_without_network(self):
        original = self.media(v3=False, historical_category=True)
        original.tmdb_info = {"id": 333553, "origin_country": ["TH"]}
        category_module = types.ModuleType("app.modules.themoviedb.category")
        category_module.CategoryHelper = lambda: types.SimpleNamespace(get_tv_category=lambda info: "剧集/南亚剧集")
        with patch.dict("sys.modules", {category_module.__name__: category_module}), \
                patch.object(self.plugin, "_available_categories", side_effect=RuntimeError("分类列表不可读")):
            result = self.plugin.lock_transfer_category(original)
        self.assertEqual(result.category, "剧集/南亚剧集")
        self.assertEqual(original.category, "剧集/港台剧集")
        self.assert_binding_unchanged()


class TransferHookTest(unittest.TestCase):
    def setUp(self):
        class HostMediaChain:
            def supplement_tmdb_info(self, mediainfo, metainfo=None):
                if getattr(metainfo, "barrier", None):
                    metainfo.barrier.wait(timeout=5)
                return mediainfo

        class TransferOwner:
            def _TransferChain__handle_transfer(self, task, callback=None):
                if task.plan_checkpoint is not None:
                    return task.plan_checkpoint
                if task.mediainfo is None:
                    task.mediainfo = types.SimpleNamespace(category="识别分类")
                if not task.planning_context_restored:
                    task.mediainfo = HostMediaChain().supplement_tmdb_info(task.mediainfo, task.meta)
                result = Path("/media") / task.mediainfo.category
                return callback(task, result) if callback else result

        class HostTransferChain(TransferOwner):
            pass

        self.media_class = HostMediaChain
        self.transfer_class = HostTransferChain
        self.calls = []

        def apply(media):
            self.calls.append(media)
            return types.SimpleNamespace(category="绑定分类")

        self.hook = TransferCategoryHook(HostTransferChain, HostMediaChain, apply)
        self.hook.install()
        self.addCleanup(self.hook.remove)

    @staticmethod
    def task(**kwargs):
        values = dict(meta=types.SimpleNamespace(), mediainfo=None, plan_checkpoint=None,
                      planning_context_restored=False)
        values.update(kwargs)
        return types.SimpleNamespace(**values)

    def test_old_download_manual_and_preview_route_after_application(self):
        for scenario in ("old_download", "manual", "preview"):
            with self.subTest(scenario=scenario):
                task = self.task(mediainfo=types.SimpleNamespace(category="历史分类") if scenario == "old_download" else None)
                result = self.transfer_class()._TransferChain__handle_transfer(task=task)
                self.assertEqual(result, Path("/media/绑定分类"))
        self.assertEqual(len(self.calls), 3)

    def test_non_transfer_supplement_does_not_apply_binding(self):
        media = types.SimpleNamespace(category="识别分类")
        self.assertIs(self.media_class().supplement_tmdb_info(media, types.SimpleNamespace()), media)
        self.assertEqual(self.calls, [])

    def test_restored_accepted_task_applies_but_frozen_plan_is_untouched(self):
        accepted = self.task(planning_context_restored=True, mediainfo=types.SimpleNamespace(category="历史分类"))
        self.assertEqual(self.transfer_class()._TransferChain__handle_transfer(accepted), Path("/media/绑定分类"))
        checkpoint = object()
        planned = self.task(plan_checkpoint=checkpoint, mediainfo=types.SimpleNamespace(category="冻结分类"))
        self.assertIs(self.transfer_class()._TransferChain__handle_transfer(planned), checkpoint)
        self.assertEqual(planned.mediainfo.category, "冻结分类")
        self.assertEqual(len(self.calls), 1)

    def test_thread_context_does_not_leak_to_other_tasks_or_search(self):
        barrier = Barrier(2)
        task = self.task(meta=types.SimpleNamespace(barrier=barrier))

        def search():
            return self.media_class().supplement_tmdb_info(
                types.SimpleNamespace(category="搜索分类"), types.SimpleNamespace(barrier=barrier),
            ).category

        with ThreadPoolExecutor(max_workers=2) as executor:
            transfer = executor.submit(self.transfer_class()._TransferChain__handle_transfer, task)
            ordinary = executor.submit(search)
            self.assertEqual(transfer.result(timeout=5), Path("/media/绑定分类"))
            self.assertEqual(ordinary.result(timeout=5), "搜索分类")
        self.assertEqual(len(self.calls), 1)

    def test_host_error_is_not_swallowed_and_context_is_cleaned(self):
        def fail(*args):
            raise ValueError("宿主整理错误")

        with self.assertRaisesRegex(ValueError, "宿主整理错误"):
            self.transfer_class()._TransferChain__handle_transfer(self.task(), callback=fail)
        self.calls.clear()
        self.test_non_transfer_supplement_does_not_apply_binding()

    def test_stop_restores_inherited_method_and_reinstall_does_not_stack(self):
        replacement = self.transfer_class._TransferChain__handle_transfer
        self.hook.install()
        self.assertIs(self.transfer_class._TransferChain__handle_transfer, replacement)
        self.hook.remove()
        self.assertNotIn("_TransferChain__handle_transfer", self.transfer_class.__dict__)
        self.assertEqual(self.transfer_class()._TransferChain__handle_transfer(self.task()), Path("/media/识别分类"))
        self.hook.install()
        self.assertEqual(self.transfer_class()._TransferChain__handle_transfer(self.task()), Path("/media/绑定分类"))
        self.assertEqual(len(self.calls), 1)

    def test_stop_does_not_overwrite_other_plugin_wrapper(self):
        previous = self.transfer_class._TransferChain__handle_transfer

        def other(*args, **kwargs):
            return previous(*args, **kwargs)

        self.transfer_class._TransferChain__handle_transfer = other
        self.hook.remove()
        self.assertIs(self.transfer_class._TransferChain__handle_transfer, other)
        self.assertEqual(self.transfer_class()._TransferChain__handle_transfer(self.task()), Path("/media/识别分类"))
        self.assertEqual(self.calls, [])

    def test_unknown_interface_does_not_install_partial_hook(self):
        class UnknownTransfer:
            def _TransferChain__handle_transfer(self, unknown):
                return unknown

        original = self.media_class.supplement_tmdb_info
        hook = TransferCategoryHook(UnknownTransfer, self.media_class, lambda media: media)
        with self.assertRaisesRegex(RuntimeError, "接口不匹配"):
            hook.install()
        self.assertIs(self.media_class.supplement_tmdb_info, original)
        self.assertFalse(hook.active)

    def test_plugin_init_config_toggle_and_stop_manage_hook_without_changing_bindings(self):
        self.hook.remove()
        module = types.ModuleType("app.chain.transfer")
        module.TransferChain = self.transfer_class
        plugin = plugin_module.MediaTitleLock()
        self.addCleanup(plugin.stop_service)
        with tempfile.TemporaryDirectory() as directory, \
                patch.dict("sys.modules", {module.__name__: module}), \
                patch.object(plugin_module, "MediaChain", self.media_class), \
                patch.object(plugin, "get_data_path", return_value=Path(directory), create=True):
            plugin.init_plugin({"enabled": True})
            plugin._store.upsert(plugin_module.TitleBinding(
                media_source="themoviedb", media_id="333553", canonical_title="神之手", media_category="港台剧集",
            ))
            original = plugin._store.get("themoviedb", "333553")
            self.assertEqual(plugin.api_diagnostics().data["category_scope"], "downloads_and_transfers")
            plugin.api_save_config(plugin_module.PluginConfigRequest(enabled=False))
            self.assertEqual(plugin.api_diagnostics().data["category_scope"], "new_downloads_only")
            self.assertNotIn("_TransferChain__handle_transfer", self.transfer_class.__dict__)
            plugin.api_save_config(plugin_module.PluginConfigRequest(enabled=True))
            self.assertEqual(plugin.api_diagnostics().data["category_scope"], "downloads_and_transfers")
            plugin.stop_service()
            self.assertNotIn("_TransferChain__handle_transfer", self.transfer_class.__dict__)
            reopened = plugin_module.BindingStore(Path(directory) / "title_bindings.sqlite3")
            self.assertEqual(reopened.get("themoviedb", "333553"), original)


if __name__ == "__main__":
    unittest.main()
