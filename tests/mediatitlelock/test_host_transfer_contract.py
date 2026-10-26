"""执行官方整理方法的原始 AST；隔离存储服务，不访问媒体文件。"""

import ast
import os
import tempfile
import unittest
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from test_plugin import plugin_module
from mediatitlelock_test_package.transfer_hook import TransferCategoryHook


class DirectoryReached(Exception):
    pass


def load_host_class(path, owner, names, namespace):
    tree = ast.parse(Path(path).read_text())
    host_class = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == owner)
    methods = [node for node in host_class.body if isinstance(node, ast.FunctionDef) and node.name in names]
    if len(methods) != len(names):
        raise AssertionError("宿主整理方法已变化，需要重新核对适配入口")
    # 保留原方法体和类名（包括 V2 私有属性的名称修饰），只隔离外部服务依赖。
    isolated = ast.Module(body=[
        ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0),
        ast.ClassDef(name=owner, bases=[], keywords=[], body=methods, decorator_list=[]),
    ], type_ignores=[])
    exec(compile(ast.fix_missing_locations(isolated), str(path), "exec"), namespace)
    return namespace[owner]


class HostTransferContractTest(unittest.TestCase):
    @unittest.skipUnless(os.environ.get("MOVIEPILOT_V3_SOURCE"), "未指定 MP V3 源码目录")
    def test_v3_315_applies_category_before_actual_directory_selection(self):
        path = Path(os.environ["MOVIEPILOT_V3_SOURCE"]) / "app/chain/transfer/execution.py"
        self.check_routing(path, "TransferExecutionOwner", ["_TransferChain__handle_transfer", "_TransferChain__perform_transfer"])

    @unittest.skipUnless(os.environ.get("MOVIEPILOT_V2_TRANSFER_SOURCE"), "未指定 MP V2 整理源码文件")
    def test_v2_applies_category_before_actual_directory_selection(self):
        self.check_routing(os.environ["MOVIEPILOT_V2_TRANSFER_SOURCE"], "TransferChain", ["__handle_transfer"])

    def check_routing(self, path, owner, methods):
        routed = []
        media_type = SimpleNamespace(TV=SimpleNamespace(value="电视剧"))
        source = SimpleNamespace(TMDB="themoviedb")

        class HostMediaChain:
            def supplement_tmdb_info(self, mediainfo, metainfo=None):
                return mediainfo

        class DirectoryHelper:
            def get_dir(self, media, **kwargs):
                routed.append((Path("/media") / media.category, media.title, media.year))
                raise DirectoryReached()

        namespace = dict(
            MediaChain=HostMediaChain, DirectoryHelper=DirectoryHelper,
            MediaType=media_type, MediaSource=source, TransferHistoryOper=Mock(),
            settings=SimpleNamespace(SCRAP_FOLLOW_TMDB=True),
            defer_music_recognition=lambda *_: None, refresh_music_retry_context=lambda *_: None,
            use_music_cue=lambda *_: nullcontext(),
            logger=Mock(), Path=Path,
        )
        chain_class = load_host_class(path, owner, methods, namespace)
        chain = chain_class()
        chain.transfer_history_repository = Mock()
        chain.runtime_config = SimpleNamespace(scrape_follow_tmdb=True)
        chain.jobview = Mock()
        chain._finish_scrape_batch_task = Mock()
        chain._TransferChain__finish_scrape_batch_task = Mock()
        chain._TransferChain__record_uncheckpointed_failure = Mock()
        with tempfile.TemporaryDirectory() as directory:
            plugin = plugin_module.MediaTitleLock()
            plugin._enabled = True
            plugin._store = plugin_module.BindingStore(Path(directory) / "bindings.sqlite3")
            plugin._store.upsert(plugin_module.TitleBinding(
                media_source="themoviedb", media_id="333553", canonical_title="神之手", canonical_year="2025",
                media_category="剧集/港台剧集",
            ))
            binding = plugin._store.get("themoviedb", "333553")
            hook = TransferCategoryHook(chain_class, HostMediaChain, plugin.lock_transfer_binding)
            hook.install()
            try:
                for state in ("valid", "invalid", "unavailable"):
                    for manual in (False, True):
                        with self.subTest(host=owner, state=state, manual=manual):
                            media = SimpleNamespace(media_source=source.TMDB, source=source.TMDB, media_id="333553",
                                                    type=media_type.TV, tmdb_id=None, category="剧集/南亚剧集",
                                                    title="识别新标题", year="2026")
                            task = SimpleNamespace(mediainfo=media, meta=SimpleNamespace(), plan_checkpoint=None,
                                                   planning_input=None, planning_context_restored=False,
                                                   target_directory=None, target_storage=None,
                                                   target_path=Path("/media") if manual else None,
                                                   fileitem=SimpleNamespace(storage="local", path="/download/S01E18.mkv"))
                            with patch.object(plugin, "_available_categories",
                                              return_value=["剧集/港台剧集"] if state == "valid" else [],
                                              side_effect=RuntimeError("分类不可读") if state == "unavailable" else None):
                                with self.assertRaises(DirectoryReached):
                                    chain._TransferChain__handle_transfer(task)
                            expected = "剧集/港台剧集" if state == "valid" else "剧集/南亚剧集"
                            self.assertEqual(routed[-1], (Path("/media") / expected, "神之手", "2025"))
                            self.assertEqual(media.category, "剧集/南亚剧集")
                            self.assertEqual(media.title, "识别新标题")
                            self.assertEqual(plugin._store.get("themoviedb", "333553"), binding)
            finally:
                hook.remove()

    @unittest.skipUnless(os.environ.get("MOVIEPILOT_V3_SOURCE"), "未指定 MP V3 源码目录")
    def test_v3_real_execution_callback_saves_before_return_without_broadcast(self):
        path = Path(os.environ["MOVIEPILOT_V3_SOURCE"]) / "app/chain/transfer/execution.py"
        self.check_completion(path, "TransferExecutionOwner", ["_TransferChain__handle_transfer", "_TransferChain__perform_transfer"])

    @unittest.skipUnless(os.environ.get("MOVIEPILOT_V2_TRANSFER_SOURCE"), "未指定 MP V2 整理源码文件")
    def test_v2_real_execution_callback_saves_before_return_without_broadcast(self):
        self.check_completion(os.environ["MOVIEPILOT_V2_TRANSFER_SOURCE"], "TransferChain", ["__handle_transfer"])

    def check_completion(self, path, owner, methods):
        media_type = SimpleNamespace(TV=SimpleNamespace(value="电视剧"))

        class HostMediaChain:
            def supplement_tmdb_info(self, mediainfo, metainfo=None):
                return mediainfo

        namespace = dict(
            MediaChain=HostMediaChain, MediaType=media_type, TransferHistoryOper=Mock(),
            settings=SimpleNamespace(SCRAP_FOLLOW_TMDB=True),
            defer_music_recognition=lambda *_: None, refresh_music_retry_context=lambda *_: None,
            use_music_cue=lambda *_: nullcontext(), logger=Mock(),
            StorageOperSelectionEventData=lambda **kwargs: SimpleNamespace(**kwargs),
            eventmanager=SimpleNamespace(send_event=lambda *_: None),
            ChainEventType=SimpleNamespace(StorageOperSelection="storage"),
        )
        chain_class = load_host_class(path, owner, methods, namespace)
        chain = chain_class()
        chain.transfer_history_repository = Mock()
        chain.runtime_config = SimpleNamespace(scrape_follow_tmdb=True)
        chain.jobview = Mock()
        chain._finish_scrape_batch_task = Mock()
        chain._TransferChain__finish_scrape_batch_task = Mock()
        chain._TransferChain__record_uncheckpointed_failure = Mock()
        chain._transfer_validation_error = lambda _: None
        chain._requires_automatic_category = lambda _: False
        chain._TransferChain__select_storage_oper = lambda _: None
        info = SimpleNamespace(success=True, message="完成", target_item=object(), target_diritem=None)
        chain.transfer = lambda **_: info
        chain._plan_checkpoint_and_execute = lambda *args, **kwargs: info
        predicate = "_TransferChain__is_media_file" if owner == "TransferChain" else "_is_media_file"
        setattr(chain, predicate, lambda fileitem: fileitem.extension == "mkv")
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "bindings.sqlite3"
            plugin = plugin_module.MediaTitleLock()
            plugin._enabled = True
            plugin._store = plugin_module.BindingStore(database)
            hook = TransferCategoryHook(chain_class, HostMediaChain, plugin.lock_transfer_binding, plugin.remember_transfer_result)
            hook.install()
            try:
                media = SimpleNamespace(media_source="themoviedb", source="themoviedb", media_id="332649",
                                        type=media_type.TV, tmdb_id=None, title="首次标题", year="2026", category="日韩剧")
                task = SimpleNamespace(mediainfo=media, meta=SimpleNamespace(), plan_checkpoint=None,
                                       planning_input=None, planning_context_restored=False, preview=False,
                                       target_directory=object(), target_storage="local", target_path=None,
                                       fileitem=SimpleNamespace(storage="local", path="/download/S01E01.mkv", extension="mkv"),
                                       transfer_type="move", episodes_info=None, scrape=False,
                                       library_type_folder=False, library_category_folder=True)
                if owner != "TransferChain":
                    task.terminal_settled = False

                def callback(completed, result):
                    if hasattr(completed, "terminal_settled"):
                        completed.terminal_settled = True
                    return result.success, result.message

                self.assertEqual(chain._TransferChain__handle_transfer(task, callback), (True, "完成"))
                saved = plugin_module.BindingStore(database).get("themoviedb", "332649")
                self.assertIsNotNone(saved)
                self.assertEqual(saved.canonical_title, "首次标题")
            finally:
                hook.remove()
