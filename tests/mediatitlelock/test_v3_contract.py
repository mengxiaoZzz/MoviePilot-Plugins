"""可选的 MP V3 源码合同测试；不启动 MP、不访问服务器或用户数据库。"""

import importlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


class V3ContractTest(unittest.TestCase):
    def test_market_manifest_declares_v3_compatibility(self):
        manifest = Path(__file__).resolve().parents[2] / "package.v2.json"
        plugin = json.loads(manifest.read_text())["MediaTitleLock"]
        self.assertIs(plugin.get("v3"), True)

    @unittest.skipUnless(os.environ.get("MOVIEPILOT_V3_SOURCE"), "未指定 MP V3 源码目录")
    def test_real_category_resolver_and_classification_models(self):
        # 隔离现有测试的 app/pydantic 替身，使用宿主真实分类模型和路径解析器。
        result = subprocess.run(
            [sys.executable, "-B", str(Path(__file__).resolve()), "--check-host"],
            capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


def check_host_contract():
    import pydantic

    source = Path(os.environ["MOVIEPILOT_V3_SOURCE"])
    fixture = importlib.import_module("test_plugin")
    plugin_module = fixture.plugin_module
    sys.modules["pydantic"] = pydantic
    sys.modules["app"].__path__ = [str(source / "app")]
    sys.modules["app.schemas"].__path__ = [str(source / "app/schemas")]
    domain = importlib.import_module("app.domain.plugin")
    manifest = Path(__file__).resolve().parents[2] / "package.v2.json"
    metadata = json.loads(manifest.read_text())["MediaTitleLock"]
    assert domain.is_plugin_generation_compatible(metadata, "v2", current_generation="v3")
    assert domain.is_plugin_generation_compatible(metadata, "v2", current_generation="v2")
    assert not domain.is_plugin_generation_compatible({**metadata, "v3": False}, "v2", current_generation="v3")
    del sys.modules["app.schemas.types"]
    host_types = importlib.import_module("app.schemas.types")
    category = importlib.import_module("app.schemas.category")
    reference = importlib.import_module("app.application.classification.reference")
    from test_host_transfer_contract import load_host_class

    # 采用真实 category/library_category 同步语义，不加载 MediaInfo 的无关 YAML 依赖。
    context_contract = load_host_class(source / "app/domain/context.py", "MediaInfo", ["__setattr__"], {})

    class ContractMedia(SimpleNamespace):
        __setattr__ = context_contract.__setattr__

    policy = category.ClassificationPolicy(revision=7, categories=[
        category.ClassificationCategory(id="tv.jp", media_type="电视剧", name="显示名称与路径不同",
                                        path=["剧集", "日韩剧"]),
        category.ClassificationCategory(id="tv.cn", media_type="电视剧", name="国产剧", path=["剧集", "国产剧"]),
        category.ClassificationCategory(id="movie.cn", media_type="电影", name="国产电影", path=["电影", "国产电影"]),
        category.ClassificationCategory(id="tv.disabled", media_type="电视剧", name="禁用", path=["禁用"], enabled=False),
        category.ClassificationCategory(id="tv.unsafe", media_type="电视剧", name="非法路径", path=[".."]),
    ])
    resolver = reference.ClassificationCategoryResolver(lambda: policy)
    reference.configure_classification_category_resolver(resolver)
    plugin = plugin_module.MediaTitleLock()
    plugin._enabled = True
    with tempfile.TemporaryDirectory() as directory, patch.object(plugin_module, "MediaChain", return_value=object()):
        plugin._store = plugin_module.BindingStore(Path(directory) / "bindings.sqlite3")
        plugin._store.upsert(plugin_module.TitleBinding(
            media_source="themoviedb", media_id="42", canonical_title="固定标题", media_category="剧集/日韩剧",
        ))
        original_binding = plugin._store.get("themoviedb", "42")
        assert plugin.api_categories().data["items"] == ["剧集/日韩剧", "剧集/国产剧", "电影/国产电影"]
        assert plugin._available_categories(host_types.MediaType.TV) == ["剧集/日韩剧", "剧集/国产剧"]
        assert plugin.api_bindings().data["items"][0]["category_status"] == "valid"

        def download_event():
            recommended = category.ClassificationSelection(category_id="tv.cn", category_path=["剧集", "国产剧"],
                                                           rule_id="rule.cn", source="automatic")
            media = ContractMedia(
                media_source=host_types.MediaSource.TMDB, media_id="42", type=host_types.MediaType.TV,
                title="识别标题", category="剧集/国产剧", library_category="剧集/国产剧",
                classification=category.ClassificationResult(recommended=recommended, effective=recommended,
                                                            labels=["保留"], policy_revision=7, state="complete"),
                _category_semantics_ready=True,
            )
            return SimpleNamespace(event_data=SimpleNamespace(
                context=SimpleNamespace(media_info=media), options={"media_category": media.category}, cancel=False,
            ))

        event = download_event()
        media = event.event_data.context.media_info
        original_result = media.classification.model_copy(deep=True)
        plugin.lock_download_category(event)
        assert not event.event_data.cancel
        assert reference.effective_classification_snapshot(media).path == "剧集/日韩剧"
        assert resolver.resolve_media(media).path == ("剧集", "日韩剧")
        assert media.classification.recommended == original_result.recommended
        assert media.classification.labels == ["保留"]
        assert media.classification.effective.category_id is None
        assert media.classification.effective.source == "manual"
        assert media.library_category == media.category == "剧集/日韩剧"

        transfer_media = download_event().event_data.context.media_info
        transferred = plugin.lock_transfer_category(transfer_media)
        assert resolver.resolve_media(transferred).path == ("剧集", "日韩剧")
        assert transfer_media.category == "剧集/国产剧"
        assert transferred.classification.recommended == transfer_media.classification.recommended

        # 删除、禁用、改路径或改媒体类型后，旧路径不能继续被固定。
        active_categories = policy.categories
        for update in (None, {"enabled": False}, {"path": ["新路径"]}, {"media_type": "电影"}):
            policy.categories = active_categories[1:] if update is None else [
                active_categories[0].model_copy(update=update), *active_categories[1:],
            ]
            event = download_event()
            media = event.event_data.context.media_info
            original_result = media.classification.model_copy(deep=True)
            plugin.lock_download_category(event)
            assert not event.event_data.cancel
            assert media.classification == original_result
            assert reference.effective_classification_snapshot(media).path == "剧集/国产剧"
            assert event.event_data.options["media_category"] == "剧集/国产剧"
            assert plugin._store.get("themoviedb", "42") == original_binding

            # 模拟 V3 将旧下载绑定恢复为 effective；整理必须退回自动识别分类。
            historical = reference.apply_persisted_classification_snapshot(media, reference.persisted_classification_snapshot(
                category_path="剧集/日韩剧", source="manual",
            ))
            transferred = plugin.lock_transfer_category(historical)
            assert reference.effective_classification_snapshot(transferred).path == "剧集/国产剧"
            assert resolver.resolve_media(transferred).path == ("剧集", "国产剧")
            assert transferred.classification.effective.source == "automatic"
            assert historical.category == "剧集/日韩剧"

        event = download_event()
        media = event.event_data.context.media_info
        original_result = media.classification.model_copy(deep=True)
        with patch.object(resolver, "category_paths", side_effect=RuntimeError("模拟分类服务读取失败")):
            plugin.lock_download_category(event)
            historical = reference.apply_persisted_classification_snapshot(media, reference.persisted_classification_snapshot(
                category_path="剧集/日韩剧", source="manual",
            ))
            transferred = plugin.lock_transfer_category(historical)
            assert reference.effective_classification_snapshot(transferred).path == "剧集/国产剧"
            assert resolver.resolve_media(transferred).path == ("剧集", "国产剧")
            assert plugin.api_bindings().data["items"][0]["category_status"] == "unknown"
            assert not plugin.api_categories().success
        assert not event.event_data.cancel
        assert media.classification == original_result
        assert reference.effective_classification_snapshot(media).path == "剧集/国产剧"
        assert plugin._store.get("themoviedb", "42") == original_binding
        reopened = plugin_module.BindingStore(Path(directory) / "bindings.sqlite3")
        assert reopened.get("themoviedb", "42") == original_binding


if __name__ == "__main__":
    if sys.argv[1:] == ["--check-host"]:
        check_host_contract()
    else:
        unittest.main()
