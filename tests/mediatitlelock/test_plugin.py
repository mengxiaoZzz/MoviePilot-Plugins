import importlib.util
import sys
import tempfile
import types
import unittest
from pathlib import Path


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
log_module.logger = types.SimpleNamespace(info=lambda *args: None, exception=lambda *args: None)
plugins_module = types.ModuleType("app.plugins")
plugins_module._PluginBase = PluginBase
schemas_module = types.ModuleType("app.schemas")
types_module = types.ModuleType("app.schemas.types")
types_module.ChainEventType = types.SimpleNamespace(
    TransferRenameBuild="TransferRenameBuild",
    TransferRename="TransferRename",
)
types_module.EventType = types.SimpleNamespace(TransferComplete="TransferComplete")
pydantic_module = types.ModuleType("pydantic")
pydantic_module.BaseModel = BaseModel
pydantic_module.Field = field

sys.modules.update(
    {
        "app": app_module,
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
        self.assertEqual(self.plugin.get_render_mode(), ("vue", "dist/assets"))
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
        self.assertTrue(deleted.success)


if __name__ == "__main__":
    unittest.main()
