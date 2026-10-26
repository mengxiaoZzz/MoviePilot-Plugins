"""执行官方下载方法，下载器和通知使用替身，不创建真实下载任务。"""

import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import Mock, patch

from test_host_transfer_contract import load_host_class
from test_plugin import plugin_module
from mediatitlelock_test_package.download_hook import DownloadBindingHook


class SettlementReached(Exception):
    pass


class HostDownloadContractTest(unittest.TestCase):
    @unittest.skipUnless(os.environ.get("MOVIEPILOT_V2_DOWNLOAD_SOURCE"), "未指定 MP V2 下载源码文件")
    def test_v2_saves_after_acceptance_before_history_and_broadcast(self):
        self.check_download(os.environ["MOVIEPILOT_V2_DOWNLOAD_SOURCE"], "DownloadChain", ["download_single"])

    @unittest.skipUnless(os.environ.get("MOVIEPILOT_V3_SOURCE"), "未指定 MP V3 源码目录")
    def test_v3_315_saves_after_acceptance_before_settlement_and_broadcast(self):
        path = Path(os.environ["MOVIEPILOT_V3_SOURCE"]) / "app/chain/download/submission.py"
        self.check_download(path, "DownloadSubmissionOwner", [
            "download_single", "_execute_download_single", "_prepare_download_single",
            "_submit_prepared_download", "_subscription_download_cancelled",
        ])

    def check_download(self, path, owner, methods):
        class Media(SimpleNamespace):
            def get_message_image(self):
                return ""

        class MediaChain:
            def supplement_tmdb_info(self, mediainfo, metainfo=None):
                return mediainfo

        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "bindings.sqlite3"
            plugin = plugin_module.MediaTitleLock()
            plugin._enabled = True
            plugin._store = plugin_module.BindingStore(database)

            def send_event(kind, data):
                plugin.lock_download_category(SimpleNamespace(event_data=data))
                data.cancel = data.context.cancel
                return SimpleNamespace(event_data=data)

            def settle(*args, **kwargs):
                saved = plugin_module.BindingStore(database).get("themoviedb", "332649")
                self.assertEqual((saved.canonical_title, saved.media_category, saved.origin),
                                 ("下载时标题", "日韩剧", "download"))
                raise SettlementReached()

            namespace = dict(
                MediaInfo=Media, MusicInfo=type("MusicInfo", (), {}), MediaChain=MediaChain,
                ResourceDownloadEventData=lambda **kwargs: SimpleNamespace(cancel=False, source="", reason="", **kwargs),
                eventmanager=SimpleNamespace(send_event=send_event),
                ChainEventType=SimpleNamespace(ResourceDownload="resource.download"),
                TorrentHelper=lambda: SimpleNamespace(get_fileinfo_from_torrent_content=lambda _: ("剧集", [])),
                FileURI=lambda storage, path: SimpleNamespace(uri=path),
                DownloadHistoryOper=settle, _PreparedDownload=lambda **kwargs: SimpleNamespace(**kwargs),
                logger=Mock(), Path=Path, cast=cast, Any=Any, Set=set,
                Notification=lambda **kwargs: kwargs, NotificationType=SimpleNamespace(Manual="manual"),
            )
            chain_class = load_host_class(path, owner, methods, namespace)

            def download(chain, content, **kwargs):
                self.assertEqual(content, b"torrent")
                self.assertIsNone(plugin_module.BindingStore(database).get("themoviedb", chain.context.media_info.media_id))
                if chain.state == "exception":
                    raise RuntimeError("下载器未返回")
                return ("下载器", "hash" if chain.state == "accepted" else None, "Original", "原消息")

            chain_class.download = download
            chain = chain_class()
            chain._resolve_media_download_dir = lambda **_: ("local", Path("/download"), "")
            chain._record_download_failure = Mock()
            chain._record_rejected_download = Mock()
            chain._record_music_album_track_keys = Mock()
            chain._settle_accepted_download = settle
            chain.post_message = Mock()

            def apply_event(context, *args):
                if context.cancel:
                    return None, "已取消"
                plugin.lock_download_category(SimpleNamespace(event_data=SimpleNamespace(context=context, options={})))
                return None, None

            chain._apply_resource_download_event = apply_event
            hook = DownloadBindingHook(chain_class, plugin.remember_download_binding)
            hook.install()
            try:
                for detail in (False, True):
                    for state in ("rejected", "cancelled", "exception", "accepted"):
                        with self.subTest(host=owner, detail=detail, state=state):
                            # 每个场景使用独立存储，验证当前任务之前没有绑定。
                            database = Path(directory) / f"{detail}-{state}.sqlite3"
                            plugin._store = plugin_module.BindingStore(database)
                            chain.state = state
                            media = Media(media_source="themoviedb", media_id="332649", title="下载时标题", year="2026",
                                          category="日韩剧", type=SimpleNamespace(value="电视剧"), title_year="下载时标题 (2026)")
                            chain.context = SimpleNamespace(
                                media_info=media, cancel=state == "cancelled",
                                meta_info=SimpleNamespace(episode_list=[], season_episode="", org_string="source"),
                                torrent_info=SimpleNamespace(site_downloader="下载器", site_cookie="", title="资源", enclosure="", site_name="站点"),
                            )
                            with patch.object(plugin, "_available_categories", return_value=["日韩剧"]):
                                if state == "accepted":
                                    with self.assertRaises(SettlementReached):
                                        chain.download_single(chain.context, torrent_content=b"torrent", return_detail=detail)
                                elif state == "exception":
                                    with self.assertRaisesRegex(RuntimeError, "下载器未返回"):
                                        chain.download_single(chain.context, torrent_content=b"torrent", return_detail=detail)
                                else:
                                    result = chain.download_single(chain.context, torrent_content=b"torrent", return_detail=detail)
                                    self.assertIsNone(result[0] if detail else result)
                            saved = plugin_module.BindingStore(database).get("themoviedb", "332649")
                            self.assertEqual(saved is not None, state == "accepted")
            finally:
                hook.remove()
