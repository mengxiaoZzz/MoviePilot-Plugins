import importlib.util
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch


class Response:
    def __init__(self, success, message=None, data=None):
        self.success = success
        self.message = message
        self.data = data


class EventManager:
    @staticmethod
    def register(*args, **kwargs):
        return lambda function: function


class PluginBase:
    def update_config(self, config):
        self.saved_config = config
        return True


class BaseModel:
    def __init__(self, **values):
        for name in self.__class__.__annotations__:
            if name in values:
                value = values[name]
            else:
                value = getattr(self.__class__, name, None)
            setattr(self, name, value)


def field(default=None, **kwargs):
    return default


app_module = types.ModuleType("app")
app_module.schemas = types.SimpleNamespace(Response=Response)
core_module = types.ModuleType("app.core")
event_module = types.ModuleType("app.core.event")
event_module.Event = object
event_module.eventmanager = EventManager()
log_module = types.ModuleType("app.log")
log_module.logger = types.SimpleNamespace(
    info=lambda *args: None,
    warning=lambda *args: None,
    exception=lambda *args: None,
)
plugins_module = types.ModuleType("app.plugins")
plugins_module._PluginBase = PluginBase
chain_module = types.ModuleType("app.chain")
media_chain_module = types.ModuleType("app.chain.media")


class MediaChain:
    def media_category(self):
        return {"电影": ["华语电影", "外语电影"], "电视剧": ["国产剧", "日韩剧"]}


media_chain_module.MediaChain = MediaChain
schemas_module = types.ModuleType("app.schemas")
types_module = types.ModuleType("app.schemas.types")
types_module.ChainEventType = types.SimpleNamespace(
    TransferRenameBuild="TransferRenameBuild",
    ResourceDownload="ResourceDownload",
)
types_module.EventType = types.SimpleNamespace(TransferComplete="TransferComplete", TransferFailed="TransferFailed")
pydantic_module = types.ModuleType("pydantic")
pydantic_module.BaseModel = BaseModel
pydantic_module.Field = field

sys.modules.update(
    {
        "app": app_module,
        "app.chain": chain_module,
        "app.chain.media": media_chain_module,
        "app.core": core_module,
        "app.core.event": event_module,
        "app.log": log_module,
        "app.plugins": plugins_module,
        "app.schemas": schemas_module,
        "app.schemas.types": types_module,
        "pydantic": pydantic_module,
    }
)

plugin_dir = Path(__file__).resolve().parents[2] / "plugins.v2" / "mediatitlelock"
spec = importlib.util.spec_from_file_location(
    "mediatitlelock_test_package",
    plugin_dir / "__init__.py",
    submodule_search_locations=[str(plugin_dir)],
)
plugin_module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = plugin_module
spec.loader.exec_module(plugin_module)


class PluginTest(unittest.TestCase):
    def setUp(self):
        self.plugin = plugin_module.MediaTitleLock()

    def test_uses_vue_main_page_without_separate_form(self):
        render_mode, dist_path = self.plugin.get_render_mode()

        self.assertEqual(render_mode, "vue")
        self.assertEqual(dist_path, "dist/v1.0.7/assets")
        self.assertTrue((plugin_dir / dist_path / "remoteEntry.js").is_file())
        self.assertEqual(self.plugin.get_form(), (None, {}))
        self.assertIsNone(self.plugin.get_page())

    def test_api_contract_has_config_and_bindings_without_emby_import(self):
        routes = {
            (item["path"], tuple(item["methods"]))
            for item in self.plugin.get_api()
        }

        self.assertEqual(
            routes,
            {
                ("/config", ("GET",)),
                ("/config", ("POST",)),
                ("/bindings", ("GET",)),
                ("/categories", ("GET",)),
                ("/diagnostics", ("GET",)),
                ("/bindings", ("POST",)),
                ("/bindings/delete", ("POST",)),
            },
        )

    def test_main_page_config_save_updates_persisted_and_runtime_state(self):
        self.plugin._enabled = False

        response = self.plugin.api_save_config(
            plugin_module.PluginConfigRequest(enabled=True)
        )

        self.assertTrue(response.success)
        self.assertEqual(self.plugin.saved_config, {"enabled": True})
        self.assertTrue(self.plugin.get_state())
        self.assertEqual(response.data, {"enabled": True})

    def test_main_page_can_save_query_and_delete_binding(self):
        with tempfile.TemporaryDirectory() as directory:
            self.plugin._store = plugin_module.BindingStore(
                Path(directory) / "bindings.sqlite3"
            )
            saved = self.plugin.api_save_binding(
                plugin_module.BindingRequest(
                    media_source="tmdb",
                    media_id="330150",
                    canonical_title="固定标题",
                    canonical_year="2026",
                    media_category="日韩剧",
                )
            )
            queried = self.plugin.api_bindings()
            deleted = self.plugin.api_delete_binding(
                plugin_module.BindingDeleteRequest(
                    media_source="themoviedb",
                    media_id="330150",
                )
            )

        self.assertTrue(saved.success)
        self.assertEqual(queried.data["total"], 1)
        self.assertEqual(queried.data["items"][0]["canonical_title"], "固定标题")
        self.assertEqual(queried.data["items"][0]["media_category"], "日韩剧")
        self.assertTrue(deleted.success)

    def test_categories_come_from_moviepilot(self):
        response = self.plugin.api_categories()

        self.assertTrue(response.success)
        self.assertEqual(
            response.data["items"],
            ["华语电影", "外语电影", "国产剧", "日韩剧"],
        )

    def test_bound_category_is_applied_before_automatic_download(self):
        with tempfile.TemporaryDirectory() as directory:
            self.plugin._store = plugin_module.BindingStore(
                Path(directory) / "bindings.sqlite3"
            )
            self.plugin._enabled = True
            self.plugin._store.upsert(
                plugin_module.TitleBinding(
                    media_source="themoviedb",
                    media_id="330150",
                    canonical_title="固定标题",
                    media_category="日韩剧",
                    origin="manual",
                )
            )
            mediainfo = types.SimpleNamespace(
                source="themoviedb",
                media_id="330150",
                category="欧美剧",
            )
            event = types.SimpleNamespace(
                event_data=types.SimpleNamespace(
                    context=types.SimpleNamespace(media_info=mediainfo),
                    options={"media_category": "欧美剧"},
                )
            )

            self.plugin.lock_download_category(event)

        self.assertEqual(mediainfo.category, "日韩剧")
        self.assertEqual(event.event_data.options["media_category"], "日韩剧")

    def test_first_successful_transfer_automatically_records_category(self):
        with tempfile.TemporaryDirectory() as directory:
            self.plugin._store = plugin_module.BindingStore(
                Path(directory) / "bindings.sqlite3"
            )
            self.plugin._enabled = True
            mediainfo = types.SimpleNamespace(
                source="themoviedb",
                media_id="330150",
                title="首次标题",
                year="2026",
                category="日韩剧",
            )
            transferinfo = types.SimpleNamespace(
                success=True,
                target_diritem=types.SimpleNamespace(path="/media/电视剧/日韩剧/首次标题"),
            )

            self.plugin.remember_successful_transfer(
                types.SimpleNamespace(
                    event_data={"mediainfo": mediainfo, "transferinfo": transferinfo}
                )
            )
            saved = self.plugin._store.get("themoviedb", "330150")

        self.assertIsNotNone(saved)
        self.assertEqual(saved.canonical_title, "首次标题")
        self.assertEqual(saved.media_category, "日韩剧")

    def test_invalid_category_and_configuration_errors_preserve_recognized_category(self):
        with tempfile.TemporaryDirectory() as directory:
            self.plugin._store = plugin_module.BindingStore(Path(directory) / "bindings.sqlite3")
            self.plugin._enabled = True
            self.plugin._store.upsert(plugin_module.TitleBinding(
                media_source="themoviedb", media_id="42", canonical_title="固定标题",
                media_category="已经删除的分类",
            ))
            for error in (False, True):
                with self.subTest(configuration_error=error):
                    media = types.SimpleNamespace(source="themoviedb", media_id="42", category="国产剧")
                    data = types.SimpleNamespace(context=types.SimpleNamespace(media_info=media),
                                                 options={"media_category": "已经删除的分类", "other": 1})
                    with patch.object(self.plugin, "_available_categories", side_effect=RuntimeError("不可用") if error else None,
                                      return_value=["国产剧"]):
                        self.plugin.lock_download_category(types.SimpleNamespace(event_data=data))
                    self.assertEqual(media.category, "国产剧")
                    self.assertEqual(data.options, {"media_category": "国产剧", "other": 1})
                    self.assertEqual(self.plugin._store.get("themoviedb", "42").media_category, "已经删除的分类")
            self.assertEqual(self.plugin.api_diagnostics().data["items"][0]["status"], "fallback")

    def test_category_lookup_failure_does_not_break_list_and_reports_unknown_validity(self):
        with tempfile.TemporaryDirectory() as directory:
            self.plugin._store = plugin_module.BindingStore(Path(directory) / "bindings.sqlite3")
            self.plugin._store.upsert(plugin_module.TitleBinding(
                media_source="themoviedb", media_id="42", canonical_title="固定标题", media_category="旧分类",
            ))
            result = self.plugin.api_bindings()
            self.assertEqual(result.data["items"][0]["category_status"], "invalid")
            with patch.object(self.plugin, "_available_categories", side_effect=RuntimeError("不可用")):
                result = self.plugin.api_bindings()
            self.assertTrue(result.success)
            self.assertEqual(result.data["items"][0]["category_status"], "unknown")

    def test_diagnostics_distinguish_rename_transfer_and_emby(self):
        with tempfile.TemporaryDirectory() as directory:
            self.plugin._store = plugin_module.BindingStore(Path(directory) / "bindings.sqlite3")
            self.plugin._enabled = True
            self.plugin._store.upsert(plugin_module.TitleBinding(
                media_source="themoviedb", media_id="42", canonical_title="固定标题", media_category="国产剧",
            ))
            media = types.SimpleNamespace(source="themoviedb", media_id="42", title="识别标题", category="国产剧")
            rename = {"__mediainfo__": media, "title": "识别标题"}
            self.plugin.lock_rename_context(types.SimpleNamespace(event_data=types.SimpleNamespace(rename_dict=rename)))
            self.plugin.remember_successful_transfer(types.SimpleNamespace(event_data={
                "mediainfo": media, "transferinfo": types.SimpleNamespace(success=True, target_diritem=None),
            }))
            items = self.plugin.api_diagnostics().data["items"]
            self.assertEqual(items[0]["stage"], "transfer")
            self.assertEqual(items[0]["status"], "success")
            self.assertEqual(items[1]["original_title"], "识别标题")
            self.assertEqual(items[1]["effective_title"], "固定标题")
            self.assertEqual(self.plugin.api_diagnostics().data["emby_status"], "not_checked")
            self.assertRegex(items[0]["timestamp"], r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$")
            self.assertEqual(media.title, "识别标题")

    def test_missing_category_and_failed_transfer_have_diagnostic_reasons(self):
        with tempfile.TemporaryDirectory() as directory:
            self.plugin._store = plugin_module.BindingStore(Path(directory) / "bindings.sqlite3")
            self.plugin._enabled = True
            media = types.SimpleNamespace(source="themoviedb", media_id="42", title="识别标题", category="")
            self.plugin.remember_successful_transfer(types.SimpleNamespace(event_data={
                "mediainfo": media, "transferinfo": types.SimpleNamespace(success=True),
            }))
            self.assertIn("分类", self.plugin.api_diagnostics().data["items"][0]["message"])
            self.plugin.record_failed_transfer(types.SimpleNamespace(event_data={
                "mediainfo": media, "transferinfo": types.SimpleNamespace(success=False, message="目标路径不可写"),
            }))
            item = self.plugin.api_diagnostics().data["items"][0]
            self.assertEqual(item["status"], "failed")
            self.assertIn("目标路径不可写", item["message"])
            self.assertEqual(self.plugin._store.count(), 0)

    def test_diagnostics_are_bounded_and_not_shared_between_plugin_instances(self):
        for _ in range(110):
            self.plugin._record("rename", "skipped", "未找到身份")
        self.assertEqual(len(self.plugin.api_diagnostics().data["items"]), 100)
        other = plugin_module.MediaTitleLock()
        self.assertEqual(other.api_diagnostics().data["items"], [])
        config = self.plugin.api_config().data
        self.assertEqual(config["backend_version"], self.plugin.plugin_version)
        self.assertTrue(config["ui_revision"])

    def test_fallback_preserves_title_lock_and_transfer_can_finish(self):
        with tempfile.TemporaryDirectory() as directory:
            self.plugin._store = plugin_module.BindingStore(Path(directory) / "bindings.sqlite3")
            self.plugin._enabled = True
            self.plugin._store.upsert(plugin_module.TitleBinding(
                media_source="themoviedb", media_id="42", canonical_title="固定标题", media_category="已删除",
            ))
            media = types.SimpleNamespace(source="themoviedb", media_id="42", title="识别标题", category="国产剧")
            data = types.SimpleNamespace(context=types.SimpleNamespace(media_info=media), options={}, cancel=False)
            self.plugin.lock_download_category(types.SimpleNamespace(event_data=data))
            self.assertFalse(data.cancel)
            self.assertEqual(media.category, "国产剧")
            rename = {"__mediainfo__": media, "title": media.title}
            self.plugin.lock_rename_context(types.SimpleNamespace(event_data=types.SimpleNamespace(rename_dict=rename)))
            self.assertEqual(rename["title"], "固定标题")
            self.plugin.remember_successful_transfer(types.SimpleNamespace(event_data={
                "mediainfo": media, "transferinfo": types.SimpleNamespace(success=True, target_diritem=None),
            }))
            self.assertEqual(self.plugin.api_diagnostics().data["items"][0]["status"], "success")
            self.assertEqual(self.plugin._store.get("themoviedb", "42").media_category, "已删除")

    def test_empty_recognition_is_not_replaced_by_invalid_binding_and_does_not_cancel(self):
        with tempfile.TemporaryDirectory() as directory:
            self.plugin._store = plugin_module.BindingStore(Path(directory) / "bindings.sqlite3")
            self.plugin._enabled = True
            self.plugin._store.upsert(plugin_module.TitleBinding(
                media_source="themoviedb", media_id="42", canonical_title="固定标题", media_category="已删除",
            ))
            for options in ({"media_category": "已删除"}, None):
                media = types.SimpleNamespace(source="themoviedb", media_id="42", category="")
                data = types.SimpleNamespace(context=types.SimpleNamespace(media_info=media), options=options, cancel=False)
                self.plugin.lock_download_category(types.SimpleNamespace(event_data=data))
                self.assertEqual(media.category, "")
                self.assertFalse(data.cancel)
                if options is not None:
                    self.assertEqual(options["media_category"], "")

    def test_api_uses_server_page_and_does_not_sort_or_filter_only_a_page(self):
        with tempfile.TemporaryDirectory() as directory:
            self.plugin._store = plugin_module.BindingStore(Path(directory) / "bindings.sqlite3")
            for index in range(52):
                self.plugin._store.insert_if_absent(plugin_module.TitleBinding(
                    media_source="themoviedb", media_id=str(index), canonical_title="共同标题", media_category="国产剧",
                ))
            result = self.plugin.api_bindings(page=3, page_size=25, title="共同")
            self.assertEqual((result.data["page"], result.data["page_count"], result.data["total"]), (3, 3, 52))
            self.assertEqual(len(result.data["items"]), 2)
            self.assertEqual(self.plugin.api_bindings(page=9, title="不存在").data["page"], 1)

    def test_frontend_and_backend_declare_matching_build_identity(self):
        source = (plugin_dir / "src/components/Page.vue").read_text()
        self.assertIn(f"const frontendVersion = '{self.plugin.plugin_version}'", source)
        self.assertIn(f"const frontendRevision = '{plugin_module.UI_REVISION}'", source)


if __name__ == "__main__":
    unittest.main()
