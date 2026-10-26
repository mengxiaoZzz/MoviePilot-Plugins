"""完成事件不投递时，验证同步落库及下一次整理的实际命名输入。"""

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from test_plugin import plugin_module
from mediatitlelock_test_package.transfer_hook import TransferCategoryHook


class TransferBindingTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.database = Path(self.directory.name) / "bindings.sqlite3"
        self.plugin = plugin_module.MediaTitleLock()
        self.plugin._enabled = True
        self.plugin._store = plugin_module.BindingStore(self.database)
        self.enterContext(patch.object(self.plugin, "_available_categories", return_value=["日韩剧"]))

        class HostMediaChain:
            def supplement_tmdb_info(self, mediainfo, metainfo=None):
                return mediainfo

        class HostTransferChain:
            def _is_media_file(self, fileitem):
                return fileitem.extension == "mkv"

            def _TransferChain__handle_transfer(self, task, callback=None):
                if task.plan_checkpoint is None:
                    if not task.planning_context_restored:
                        task.mediainfo = HostMediaChain().supplement_tmdb_info(task.mediainfo, task.meta)
                    task.path = Path("/media") / task.mediainfo.category / f"{task.mediainfo.title} ({task.mediainfo.year})"
                else:
                    task.path = task.plan_checkpoint
                result = SimpleNamespace(success=task.success, target_item=task.path if task.has_target else None,
                                         target_diritem=SimpleNamespace(path=str(task.path)))
                task.result = result
                return callback(task, result) if callback else (result.success, "")

            def _TransferChain__settle_legacy_transfer_result(self, task, transferinfo):
                task.terminal_settled = True

        self.chain_class = HostTransferChain
        self.hook = TransferCategoryHook(
            HostTransferChain, HostMediaChain, self.plugin.lock_transfer_binding,
            self.plugin.remember_transfer_result,
        )
        self.hook.install()
        self.addCleanup(self.hook.remove)

    @staticmethod
    def task(title="首次标题", **kwargs):
        values = dict(meta=SimpleNamespace(), mediainfo=SimpleNamespace(
            media_source="themoviedb", media_id="332649", title=title, year="2026", category="日韩剧", type="电视剧",
        ), fileitem=SimpleNamespace(extension="mkv"), plan_checkpoint=None,
            planning_context_restored=False, preview=False, success=True, has_target=True)
        values.update(kwargs)
        return SimpleNamespace(**values)

    @staticmethod
    def callback(task, transferinfo):
        if hasattr(task, "terminal_settled"):
            task.terminal_settled = True
        return transferinfo.success, "原回调结果"

    def run_task(self, task, callback=None):
        return self.chain_class()._TransferChain__handle_transfer(task, callback or self.callback)

    def binding(self):
        return plugin_module.BindingStore(self.database).get("themoviedb", "332649")

    def test_delayed_completion_event_cannot_leave_next_transfer_unbound(self):
        for v3 in (False, True):
            with self.subTest(v3=v3):
                self.database = Path(self.directory.name) / f"bindings-{v3}.sqlite3"
                self.plugin._store = plugin_module.BindingStore(self.database)
                first = self.task(**({"terminal_settled": False} if v3 else {}))
                self.assertEqual(self.run_task(first), (True, "原回调结果"))
                self.assertEqual(self.binding().canonical_title, "首次标题")
                second = self.task("TMDB新标题")
                cached_media = second.mediainfo
                self.run_task(second)
                self.assertEqual(second.path, Path("/media/日韩剧/首次标题 (2026)"))
                self.assertEqual(cached_media.title, "TMDB新标题")
                self.plugin.remember_successful_transfer(SimpleNamespace(event_data={
                    "mediainfo": second.mediainfo, "transferinfo": second.result,
                }))
                self.assertEqual(self.binding().canonical_title, "首次标题")

    def test_preview_failure_skip_unsettled_and_callback_error_do_not_create_binding(self):
        cases = [dict(preview=True), dict(success=False), dict(has_target=False), dict(terminal_settled=False)]
        for values in cases:
            with self.subTest(values=values):
                self.run_task(self.task(**values), callback=lambda task, info: (info.success, ""))
                self.assertIsNone(self.binding())

        def fail(task, info):
            raise RuntimeError("宿主结算失败")

        with self.assertRaisesRegex(RuntimeError, "宿主结算失败"):
            self.run_task(self.task(), callback=fail)
        self.assertIsNone(self.binding())

    def test_subtitle_completion_cannot_create_the_first_media_binding(self):
        for legacy in (False, True):
            with self.subTest(legacy=legacy):
                task = self.task("字幕识别标题", fileitem=SimpleNamespace(extension="srt"))
                if legacy:
                    self.chain_class()._TransferChain__handle_transfer(task)
                    self.chain_class()._TransferChain__settle_legacy_transfer_result(task, task.result)
                else:
                    self.run_task(task)
                self.assertIsNone(self.binding())
        self.run_task(self.task("正片标题"))
        self.assertEqual(self.binding().canonical_title, "正片标题")

    def test_media_check_error_does_not_fail_a_completed_transfer(self):
        with patch.object(self.chain_class, "_is_media_file", side_effect=OSError("存储不可读")):
            self.assertEqual(self.run_task(self.task()), (True, "原回调结果"))
        self.assertIsNone(self.binding())

    def test_manual_save_and_title_hits_have_persistent_audit_logs(self):
        request = plugin_module.BindingRequest(
            media_source="tmdb", media_id="332649", canonical_title="手工固定", canonical_year="2025",
            media_category="日韩剧",
        )
        with patch.object(plugin_module.logger, "info") as log:
            self.assertTrue(self.plugin.api_save_binding(request).success)
            task = self.task("识别的新标题")
            self.run_task(task)
            # 宿主可在补全后回填历史标题；最终模板事件仍必须恢复绑定。
            rename = {"__mediainfo__": task.mediainfo, "title": "宿主历史标题", "year": "2026"}
            self.plugin.lock_rename_context(SimpleNamespace(event_data=SimpleNamespace(
                rename_dict=rename, source_path="/download/source.mkv",
            )))
        self.assertEqual(rename["title"], "手工固定")
        self.assertEqual(rename["year"], "2025")
        messages = [call.args[0] for call in log.call_args_list]
        for stage in ("手工保存成功", "整理前命中", "标题渲染命中"):
            self.assertTrue(any(stage in text and "themoviedb/332649" in text for text in messages), messages)
        self.assertTrue(any("宿主历史标题" in text and "手工固定" in text and "source.mkv" in text for text in messages))

    def test_manual_write_error_is_reported_and_logged_without_losing_binding(self):
        self.run_task(self.task())
        before = self.binding()
        request = plugin_module.BindingRequest(
            media_source="tmdb", media_id="332649", canonical_title="未成功保存", media_category="日韩剧",
        )
        with patch.object(self.plugin._store, "upsert", side_effect=OSError("数据库不可写")), \
                patch.object(plugin_module.logger, "exception") as log:
            self.assertFalse(self.plugin.api_save_binding(request).success)
        self.assertIn("手工保存失败 themoviedb/332649", log.call_args.args[0])
        self.assertEqual(self.binding(), before)
        with patch.object(self.plugin, "_available_categories", return_value=[]), \
                patch.object(plugin_module.logger, "warning") as log:
            self.assertFalse(self.plugin.api_save_binding(request).success)
        self.assertIn("手工保存失败 themoviedb/332649", log.call_args.args[0])
        self.assertEqual(self.binding(), before)

    def test_old_binding_without_category_still_locks_title_and_keeps_recognized_year(self):
        self.plugin._store.upsert(plugin_module.TitleBinding(
            media_source="themoviedb", media_id="332649", canonical_title="旧绑定标题",
        ))
        before = self.binding()
        task = self.task()
        self.run_task(task)
        self.assertEqual(task.path, Path("/media/日韩剧/旧绑定标题 (2026)"))
        self.assertEqual(self.binding(), before)

    def test_manual_binding_wins_over_delayed_events_and_category_failure(self):
        saved = self.plugin.api_save_binding(plugin_module.BindingRequest(
            media_source="tmdb", media_id="332649", canonical_title="手工固定", canonical_year="2025",
            media_category="日韩剧",
        ))
        self.assertTrue(saved.success)
        before = self.binding()
        for categories in ([], RuntimeError("分类读取失败")):
            with self.subTest(categories=categories), patch.object(
                self.plugin, "_available_categories", return_value=categories if isinstance(categories, list) else [],
                side_effect=categories if isinstance(categories, Exception) else None,
            ):
                task = self.task("新标题", planning_context_restored=True)
                task.mediainfo.category = "识别分类"
                self.run_task(task)
                self.assertEqual(task.path, Path("/media/识别分类/手工固定 (2025)"))
        delayed = self.task("过时事件标题")
        self.plugin.remember_successful_transfer(SimpleNamespace(event_data={
            "mediainfo": delayed.mediainfo, "transferinfo": SimpleNamespace(success=True),
        }))
        self.assertEqual(self.binding(), before)

    def test_legacy_v3_settlement_records_only_after_successful_commit(self):
        task = self.task(terminal_settled=False)
        self.chain_class()._TransferChain__handle_transfer(task)
        self.assertIsNone(self.binding())
        self.chain_class()._TransferChain__settle_legacy_transfer_result(task, task.result)
        self.assertEqual(self.binding().canonical_title, "首次标题")

    def test_frozen_plan_is_not_rewritten_and_existing_binding_is_preserved(self):
        self.run_task(self.task())
        before = self.binding()
        task = self.task("冻结标题", plan_checkpoint=Path("/media/冻结目录"))
        self.run_task(task)
        self.assertEqual(task.path, Path("/media/冻结目录"))
        self.assertEqual(task.mediainfo.title, "冻结标题")
        self.assertEqual(self.binding(), before)

    def test_binding_write_failure_does_not_turn_successful_transfer_into_failure(self):
        with patch.object(self.plugin._store, "insert_if_absent", side_effect=OSError("磁盘写入失败")):
            self.assertEqual(self.run_task(self.task()), (True, "原回调结果"))
        self.assertIsNone(self.binding())
        self.assertEqual(self.plugin.api_diagnostics().data["items"][0]["status"], "error")

    def test_stopped_hook_does_not_record_through_a_retained_wrapper(self):
        wrapped = self.chain_class._TransferChain__handle_transfer
        self.hook.remove()
        self.assertEqual(wrapped(self.chain_class(), self.task(), self.callback), (True, "原回调结果"))
        self.assertIsNone(self.binding())


if __name__ == "__main__":
    unittest.main()
