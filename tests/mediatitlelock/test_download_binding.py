"""下载器接收后同步保存；不依赖下载广播事件或文件整理。"""

import tempfile
import types
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier
from unittest.mock import patch

from test_plugin import plugin_module
from mediatitlelock_test_package.download_hook import DownloadBindingHook


class DownloadBindingTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.database = Path(self.directory.name) / "title_bindings.sqlite3"
        self.plugin = plugin_module.MediaTitleLock()

        class DownloaderBase:
            def download(self, content, **kwargs):
                if getattr(content, "barrier", None):
                    content.barrier.wait(timeout=5)
                if isinstance(content.result, Exception):
                    raise content.result
                return content.result

        class DownloadChain(DownloaderBase):
            def download_single(host, context, return_detail=False):
                if context.cancel:
                    return (None, "已取消") if return_detail else None
                self.plugin.lock_download_category(types.SimpleNamespace(event_data=types.SimpleNamespace(
                    context=context, options={}, cancel=False,
                )))
                result = host.download(content=context)
                self.after_submit(context, result)
                download_hash = result[1] if result else None
                return (download_hash, "原返回消息") if return_detail else download_hash

        self.chain_class = DownloadChain
        self.base_class = DownloaderBase
        self.after_submit = lambda context, result: None
        module = types.ModuleType("app.chain.download")
        module.DownloadChain = DownloadChain
        self.enterContext(patch.dict("sys.modules", {module.__name__: module}))
        self.enterContext(patch.object(self.plugin, "get_data_path", return_value=Path(self.directory.name), create=True))
        self.enterContext(patch.object(self.plugin, "_available_categories", return_value=["日韩剧"]))
        self.plugin.init_plugin({"enabled": True})
        self.addCleanup(self.plugin.stop_service)

    @staticmethod
    def context(media_id="332649", title="下载时标题", **kwargs):
        values = dict(media_info=types.SimpleNamespace(
            media_source="themoviedb", media_id=media_id, title=title, year="2026", category="日韩剧", type="电视剧",
        ), result=("下载器", f"hash-{media_id}", "Original", ""), cancel=False)
        values.update(kwargs)
        return types.SimpleNamespace(**values)

    def binding(self, media_id="332649"):
        return plugin_module.BindingStore(self.database).get("themoviedb", media_id)

    def test_binding_is_committed_before_notifications_or_broadcasts(self):
        def after_submit(context, result):
            saved = self.binding()
            self.assertIsNotNone(saved)
            self.assertEqual((saved.canonical_title, saved.origin), ("下载时标题", "download"))

        self.after_submit = after_submit
        self.assertEqual(self.chain_class().download_single(self.context(), return_detail=True),
                         ("hash-332649", "原返回消息"))
        saved = self.binding()
        with patch.object(plugin_module.logger, "info") as log:
            self.after_submit = lambda *_: None
            self.chain_class().download_single(self.context(title="稍后的新标题"))
        self.assertEqual(self.binding(), saved)
        self.assertTrue(any("下载接收后保留已有绑定 themoviedb/332649" in call.args[0] for call in log.call_args_list))
        task_media = self.context(title="整理时新标题").media_info
        self.assertEqual(self.plugin.lock_transfer_binding(task_media).title, "下载时标题")
        self.assertEqual(task_media.title, "整理时新标题")

    def test_rejection_cancel_and_downloader_exception_do_not_create_binding(self):
        for context in (self.context(result=None), self.context(result=("下载器", None, None, "拒绝")),
                        self.context(cancel=True)):
            self.assertIsNone(self.chain_class().download_single(context))
            self.assertIsNone(self.binding())
        with self.assertRaisesRegex(RuntimeError, "下载器异常"):
            self.chain_class().download_single(self.context(result=RuntimeError("下载器异常")))
        self.assertIsNone(self.binding())
        # 异常退出不能让下一次独立下载错误沿用此媒体上下文。
        self.chain_class().download(content=self.context())
        self.assertIsNone(self.binding())

    def test_postprocessing_error_or_later_transfer_failure_keeps_accepted_binding(self):
        def fail(*_):
            raise RuntimeError("宿主通知异常")

        self.after_submit = fail
        with self.assertRaisesRegex(RuntimeError, "宿主通知异常"):
            self.chain_class().download_single(self.context())
        before = self.binding()
        self.assertIsNotNone(before)
        self.plugin.record_failed_transfer(types.SimpleNamespace(event_data={
            "mediainfo": self.context().media_info, "transferinfo": types.SimpleNamespace(message="下载后整理失败"),
        }))
        self.assertEqual(self.binding(), before)

    def test_existing_manual_binding_and_invalid_category_are_preserved(self):
        self.plugin._store.upsert(plugin_module.TitleBinding(
            media_source="themoviedb", media_id="332649", canonical_title="手工固定", canonical_year="2025",
            media_category="已删除分类", origin="manual", media_root_name="旧字段", media_path="/media/原目录",
        ))
        before = self.binding()
        for error in (None, RuntimeError("分类读取失败")):
            with patch.object(self.plugin, "_available_categories", return_value=["日韩剧"], side_effect=error):
                context = self.context()
                self.assertEqual(self.chain_class().download_single(context), "hash-332649")
                media = self.plugin.lock_transfer_binding(context.media_info)
                self.assertEqual((media.title, media.year, media.category), ("手工固定", "2025", "日韩剧"))
                self.assertEqual(self.binding(), before)

    def test_category_read_error_does_not_prevent_new_binding_or_transfer(self):
        with patch.object(self.plugin, "_available_categories", side_effect=RuntimeError("分类读取失败")):
            self.chain_class().download_single(self.context())
            media = self.plugin.lock_transfer_binding(self.context(title="整理新标题").media_info)
        self.assertEqual((media.title, media.category), ("下载时标题", "日韩剧"))

    def test_write_error_does_not_fail_download_and_transfer_can_compensate(self):
        with patch.object(self.plugin._store, "insert_if_absent", side_effect=OSError("数据库不可写")):
            self.assertEqual(self.chain_class().download_single(self.context()), "hash-332649")
        self.assertIsNone(self.binding())
        self.assertEqual(self.plugin.api_diagnostics().data["items"][0]["status"], "error")
        self.plugin.remember_transfer_result(self.context().media_info, types.SimpleNamespace(success=True))
        self.assertEqual(self.binding().origin, "automatic")

    def test_incomplete_identity_title_category_and_music_do_not_create_binding(self):
        for field, value in (("media_id", ""), ("title", ""), ("category", ""), ("type", "音乐")):
            context = self.context()
            setattr(context.media_info, field, value)
            self.chain_class().download_single(context)
            self.assertIsNone(self.binding())

    def test_concurrent_downloads_do_not_mix_media_and_first_record_wins(self):
        barrier = Barrier(2)
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(lambda context: self.chain_class().download_single(context), [
                self.context("11", "剧一", barrier=barrier), self.context("22", "剧二", barrier=barrier),
            ]))
        self.assertEqual(results, ["hash-11", "hash-22"])
        self.assertEqual(self.binding("11").canonical_title, "剧一")
        self.assertEqual(self.binding("22").canonical_title, "剧二")
        barrier = Barrier(2)
        with ThreadPoolExecutor(max_workers=2) as executor:
            list(executor.map(lambda context: self.chain_class().download_single(context), [
                self.context(title="标题甲", barrier=barrier), self.context(title="标题乙", barrier=barrier),
            ]))
        before = self.binding()
        self.assertIn(before.canonical_title, ("标题甲", "标题乙"))
        self.plugin.remember_transfer_result(self.context().media_info, types.SimpleNamespace(success=True))
        self.assertEqual(self.binding(), before)

    def test_disable_reload_and_stop_restore_inherited_download_method(self):
        self.plugin.api_save_config(plugin_module.PluginConfigRequest(enabled=False))
        self.chain_class().download_single(self.context())
        self.assertIsNone(self.binding())
        self.assertNotIn("download", self.chain_class.__dict__)
        self.plugin.api_save_config(plugin_module.PluginConfigRequest(enabled=True))
        self.plugin.init_plugin({"enabled": True})
        self.chain_class().download_single(self.context())
        before = self.binding()
        wrapped = self.chain_class.download_single
        self.plugin.stop_service()
        self.assertNotIn("download", self.chain_class.__dict__)
        wrapped(self.chain_class(), self.context("other"))
        self.assertIsNone(self.binding("other"))
        self.assertEqual(self.binding(), before)

    def test_unrelated_download_and_other_plugin_wrapper_are_preserved(self):
        self.after_submit = lambda *_: self.chain_class().download(content=self.context("other"))
        self.chain_class().download_single(self.context())
        self.assertIsNone(self.binding("other"))
        wrapped = self.chain_class.download_single

        def other_plugin(*args, **kwargs):
            return wrapped(*args, **kwargs)

        self.chain_class.download_single = other_plugin
        self.plugin.stop_service()
        self.assertIs(self.chain_class.download_single, other_plugin)
        self.after_submit = lambda *_: None
        self.chain_class().download_single(self.context("new"))
        self.assertIsNone(self.binding("new"))

    def test_incompatible_interface_does_not_install_partial_wrapper(self):
        class UnknownDownload:
            def download_single(self, unknown):
                return unknown

            def download(self, content):
                return content

        original = UnknownDownload.download
        hook = DownloadBindingHook(UnknownDownload, self.plugin.remember_download_binding)
        with self.assertRaisesRegex(RuntimeError, "接口不匹配"):
            hook.install()
        self.assertIs(UnknownDownload.download, original)
        self.assertFalse(hook.active)


if __name__ == "__main__":
    unittest.main()
