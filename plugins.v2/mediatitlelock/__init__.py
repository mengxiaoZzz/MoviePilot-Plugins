import threading
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlencode

from pydantic import BaseModel, Field

from app import schemas
from app.core.event import Event, eventmanager
from app.helper.mediaserver import MediaServerHelper
from app.log import logger
from app.plugins import _PluginBase
from app.schemas.types import ChainEventType, EventType

from .database import BindingStore, TitleBinding
from .identity import (
    apply_locked_title,
    emby_media_root,
    extract_media_identity,
    normalize_media_type,
    normalize_source,
    replace_media_root,
)


class BindingRequest(BaseModel):
    """新增或修改固定标题绑定的请求。"""

    media_source: str = Field(default="themoviedb", min_length=1, max_length=40)
    media_type: str = Field(min_length=1, max_length=20)
    media_id: str = Field(min_length=1, max_length=80)
    canonical_title: str = Field(min_length=1, max_length=255)
    canonical_year: str = Field(default="", max_length=20)
    media_root_name: str = Field(default="", max_length=255)


class BindingDeleteRequest(BaseModel):
    """删除固定标题绑定的请求。"""

    media_source: str = Field(default="themoviedb", min_length=1, max_length=40)
    media_type: str = Field(min_length=1, max_length=20)
    media_id: str = Field(min_length=1, max_length=80)


class MediaTitleLock(_PluginBase):
    """按“媒体来源 + 类型 + 来源内 ID”固定整理标题。"""

    plugin_name = "媒体标题固定"
    plugin_desc = "首次入库后固定媒体标题，避免元数据标题变化产生多个目录。"
    plugin_icon = "mediatitlelock.svg"
    plugin_version = "1.0.0"
    plugin_author = "baixiaofei"
    author_url = ""
    plugin_config_prefix = "mediatitlelock_"
    plugin_order = 28
    auth_level = 1

    _enabled = False
    _emby_servers: List[str] = []
    _store: Optional[BindingStore] = None
    _import_lock = threading.Lock()

    def init_plugin(self, config: dict = None) -> None:
        """读取配置并初始化绑定数据库。"""

        current = config or {}
        self._enabled = bool(current.get("enabled"))
        self._emby_servers = list(current.get("emby_servers") or [])
        self._store = BindingStore(self.get_data_path() / "title_bindings.sqlite3")

        if current.get("apply_once"):
            success, message = self._apply_config_operation(current)
            cleaned = dict(current)
            cleaned["apply_once"] = False
            self.update_config(cleaned)
            if success:
                logger.info(f"媒体标题固定：{message}")
            else:
                logger.error(f"媒体标题固定：{message}")

    def get_state(self) -> bool:
        """返回插件启用状态。"""

        return self._enabled

    @staticmethod
    def get_command() -> List[Dict[str, Any]]:
        """当前插件不注册远程命令。"""

        return []

    def get_api(self) -> List[Dict[str, Any]]:
        """注册绑定管理和 Emby 导入接口。"""

        return [
            {
                "path": "/bindings",
                "endpoint": self.api_bindings,
                "methods": ["GET"],
                "auth": "bear",
                "summary": "查询固定标题绑定",
            },
            {
                "path": "/bindings",
                "endpoint": self.api_save_binding,
                "methods": ["POST"],
                "auth": "bear",
                "summary": "新增或修改固定标题绑定",
            },
            {
                "path": "/bindings/delete",
                "endpoint": self.api_delete_binding,
                "methods": ["POST"],
                "auth": "bear",
                "summary": "删除固定标题绑定",
            },
            {
                "path": "/import-emby",
                "endpoint": self.api_import_emby,
                "methods": ["POST"],
                "auth": "bear",
                "summary": "从 Emby 导入现有媒体标题",
            },
        ]

    def get_form(self) -> Tuple[List[dict], Dict[str, Any]]:
        """返回插件配置和人工维护绑定表单。"""

        server_items = [
            {"title": item.name, "value": item.name}
            for item in MediaServerHelper().get_configs().values()
            if item.type == "emby" and item.enabled
        ]
        current = self.get_config() or {}
        defaults = {
            "enabled": False,
            "emby_servers": [],
            "operation": "upsert",
            "media_source": "themoviedb",
            "media_type": "电视剧",
            "media_id": "",
            "canonical_title": "",
            "canonical_year": "",
            "media_root_name": "",
            "apply_once": False,
        }
        defaults.update(current)
        return [
            {
                "component": "VForm",
                "content": [
                    {
                        "component": "VRow",
                        "content": [
                            self._field("VSwitch", "enabled", "启用标题固定", 4),
                            self._field(
                                "VSelect",
                                "emby_servers",
                                "用于导入的 Emby（留空为全部）",
                                8,
                                items=server_items,
                                multiple=True,
                                chips=True,
                                clearable=True,
                            ),
                        ],
                    },
                    {
                        "component": "VAlert",
                        "props": {
                            "type": "info",
                            "variant": "tonal",
                            "class": "mb-4",
                            "text": "绑定键为媒体来源 + 类型 + 来源内 ID。勾选“保存时执行一次”并保存配置，可人工新增、修改或删除绑定。",
                        },
                    },
                    {
                        "component": "VRow",
                        "content": [
                            self._field(
                                "VSelect",
                                "operation",
                                "操作",
                                3,
                                items=[
                                    {"title": "新增或修改", "value": "upsert"},
                                    {"title": "删除", "value": "delete"},
                                ],
                            ),
                            self._field(
                                "VSelect",
                                "media_source",
                                "媒体来源",
                                3,
                                items=[
                                    {"title": "TMDB", "value": "themoviedb"},
                                    {"title": "豆瓣", "value": "douban"},
                                    {"title": "Bangumi", "value": "bangumi"},
                                    {"title": "AniList", "value": "anilist"},
                                ],
                            ),
                            self._field(
                                "VSelect",
                                "media_type",
                                "媒体类型",
                                3,
                                items=[
                                    {"title": "电影", "value": "电影"},
                                    {"title": "电视剧", "value": "电视剧"},
                                ],
                            ),
                            self._field("VTextField", "media_id", "来源内 ID", 3),
                            self._field("VTextField", "canonical_title", "固定标题", 5),
                            self._field("VTextField", "canonical_year", "固定年份", 2),
                            self._field("VTextField", "media_root_name", "现有媒体根目录名（可选）", 5),
                            self._field("VSwitch", "apply_once", "保存时执行一次", 4),
                        ],
                    },
                ],
            }
        ], defaults

    def get_page(self) -> List[dict]:
        """展示固定标题绑定列表与 Emby 导入入口。"""

        store = self._require_store()
        total = store.count()
        rows = []
        for binding in store.list_bindings(limit=500):
            item = binding.to_dict()
            item["identity"] = f"{binding.media_source} / {binding.media_type} / {binding.media_id}"
            item["title"] = binding.canonical_title
            item["year"] = binding.canonical_year or "-"
            item["root"] = binding.media_root_name or "-"
            item["source"] = {
                "automatic": "首次整理",
                "emby": "Emby 导入",
                "manual": "人工维护",
            }.get(binding.origin, binding.origin)
            item["server"] = binding.server_name or "-"
            rows.append(item)

        return [
            {
                "component": "VAlert",
                "props": {
                    "type": "info",
                    "variant": "tonal",
                    "class": "mb-4",
                    "text": f"当前共有 {total} 条标题绑定。列表最多展示最近更新的 500 条。",
                },
            },
            {
                "component": "VBtn",
                "props": {
                    "variant": "tonal",
                    "prepend-icon": "mdi-database-import",
                    "class": "mb-4",
                },
                "text": "从 Emby 导入现有标题",
                "events": {
                    "click": {
                        "api": "plugin/MediaTitleLock/import-emby",
                        "method": "post",
                    }
                },
            },
            {
                "component": "VDataTable",
                "props": {
                    "density": "compact",
                    "headers": [
                        {"title": "媒体身份", "key": "identity"},
                        {"title": "固定标题", "key": "title"},
                        {"title": "年份", "key": "year"},
                        {"title": "媒体根目录", "key": "root"},
                        {"title": "来源", "key": "source"},
                        {"title": "Emby", "key": "server"},
                        {"title": "更新时间", "key": "updated_at"},
                    ],
                    "items": rows,
                    "items-per-page": 25,
                },
            },
        ]

    def stop_service(self) -> None:
        """清理插件内存缓存。"""

        if self._store:
            self._store.clear_cache()

    @eventmanager.register(ChainEventType.TransferRenameBuild, priority=100)
    def lock_rename_context(self, event: Event) -> None:
        """在 MoviePilot 渲染路径前注入固定标题和年份。"""

        if not self._enabled or not event or not event.event_data:
            return
        try:
            rename_dict = getattr(event.event_data, "rename_dict", None)
            if not isinstance(rename_dict, dict):
                return
            identity = extract_media_identity(rename_dict.get("__mediainfo__"))
            if not identity:
                return
            binding = self._require_store().get(
                identity.media_source, identity.media_type, identity.media_id
            )
            if binding:
                apply_locked_title(
                    rename_dict, binding.canonical_title, binding.canonical_year
                )
        except Exception as error:
            logger.exception(f"媒体标题固定：重命名上下文处理失败 - {error}")

    @eventmanager.register(ChainEventType.TransferRename, priority=100)
    def lock_media_root(self, event: Event) -> None:
        """在路径渲染后复用 Emby 中已经存在的媒体根目录名。"""

        if not self._enabled or not event or not event.event_data:
            return
        try:
            data = event.event_data
            rename_dict = getattr(data, "rename_dict", None)
            if not isinstance(rename_dict, dict):
                return
            identity = extract_media_identity(rename_dict.get("__mediainfo__"))
            if not identity:
                return
            binding = self._require_store().get(
                identity.media_source, identity.media_type, identity.media_id
            )
            if not binding or not binding.media_root_name:
                return
            current = data.updated_str if data.updated and data.updated_str else data.render_str
            updated = replace_media_root(current, binding.media_root_name)
            if updated != current:
                data.updated = True
                data.updated_str = updated
                data.source = self.plugin_name
        except Exception as error:
            logger.exception(f"媒体标题固定：媒体根目录处理失败 - {error}")

    @eventmanager.register(EventType.TransferComplete)
    def remember_successful_transfer(self, event: Event) -> None:
        """仅在文件成功整理后建立首次标题绑定。"""

        if not self._enabled or not event or not event.event_data:
            return
        try:
            event_data = event.event_data
            mediainfo = event_data.get("mediainfo")
            transferinfo = event_data.get("transferinfo")
            if not transferinfo or not transferinfo.success:
                return
            identity = extract_media_identity(mediainfo)
            title = str(getattr(mediainfo, "title", "") or "").strip()
            if not identity or not title:
                return
            target_diritem = transferinfo.target_diritem
            root_name = str(getattr(target_diritem, "name", "") or "").strip()
            inserted = self._require_store().insert_if_absent(
                TitleBinding(
                    media_source=identity.media_source,
                    media_type=identity.media_type,
                    media_id=identity.media_id,
                    canonical_title=title,
                    canonical_year=str(getattr(mediainfo, "year", "") or ""),
                    media_root_name=root_name,
                    origin="automatic",
                    media_path=str(getattr(target_diritem, "path", "") or ""),
                )
            )
            if inserted:
                logger.info(
                    f"媒体标题固定：已记录 {identity.media_source}/{identity.media_type}/"
                    f"{identity.media_id} -> {title}"
                )
        except Exception as error:
            logger.exception(f"媒体标题固定：记录整理结果失败 - {error}")

    def api_bindings(self, limit: int = 500) -> schemas.Response:
        """查询固定标题绑定。"""

        bindings = [item.to_dict() for item in self._require_store().list_bindings(limit)]
        return schemas.Response(
            success=True,
            message="查询成功",
            data={"total": self._require_store().count(), "items": bindings},
        )

    def api_save_binding(self, request: BindingRequest) -> schemas.Response:
        """新增或修改人工固定标题绑定。"""

        try:
            binding = self._binding_from_request(request)
        except ValueError as error:
            return schemas.Response(success=False, message=str(error))
        saved = self._require_store().upsert(binding)
        return schemas.Response(
            success=saved,
            message="标题绑定已保存" if saved else "标题绑定保存失败",
            data=binding.to_dict() if saved else None,
        )

    def api_delete_binding(self, request: BindingDeleteRequest) -> schemas.Response:
        """删除一条人工固定标题绑定。"""

        source = normalize_source(request.media_source)
        media_type = normalize_media_type(request.media_type)
        media_id = request.media_id.strip()
        deleted = self._require_store().delete(source, media_type, media_id)
        return schemas.Response(
            success=deleted,
            message="标题绑定已删除" if deleted else "未找到对应标题绑定",
        )

    def api_import_emby(self) -> schemas.Response:
        """从配置的 Emby 服务导入现有标题，已有绑定不覆盖。"""

        if not self._import_lock.acquire(blocking=False):
            return schemas.Response(success=False, message="Emby 导入正在执行")
        try:
            result = self._import_from_emby()
            success = result["servers_failed"] == 0 or result["servers_ok"] > 0
            message = (
                f"Emby 导入完成：扫描 {result['scanned']}，新增 {result['inserted']}，"
                f"已存在 {result['existing']}，跳过 {result['skipped']}"
            )
            if result["servers_failed"]:
                message += f"，失败服务 {result['servers_failed']}"
            return schemas.Response(success=success, message=message, data=result)
        except Exception as error:
            logger.exception(f"媒体标题固定：Emby 导入失败 - {error}")
            return schemas.Response(success=False, message=f"Emby 导入失败：{error}")
        finally:
            self._import_lock.release()

    def _import_from_emby(self) -> dict:
        services = MediaServerHelper().get_services(
            type_filter="emby", name_filters=self._emby_servers or None
        )
        result = {
            "servers_ok": 0,
            "servers_failed": 0,
            "scanned": 0,
            "inserted": 0,
            "existing": 0,
            "skipped": 0,
        }
        if not services:
            raise RuntimeError("没有可用的 Emby 服务")

        for server_name, service_info in services.items():
            instance = service_info.instance
            if not instance or instance.is_inactive():
                result["servers_failed"] += 1
                continue
            try:
                self._import_emby_service(server_name, instance, result)
                result["servers_ok"] += 1
            except Exception as error:
                result["servers_failed"] += 1
                logger.error(f"媒体标题固定：读取 Emby {server_name} 失败 - {error}")
        return result

    def _import_emby_service(self, server_name: str, instance: Any, result: dict) -> None:
        start_index = 0
        page_size = 500
        while True:
            query = urlencode(
                {
                    "Recursive": "true",
                    "IncludeItemTypes": "Movie,Series",
                    "Fields": "ProviderIds,ProductionYear,Path",
                    "StartIndex": start_index,
                    "Limit": page_size,
                    "api_key": "[APIKEY]",
                }
            )
            query = query.replace("%5BAPIKEY%5D", "[APIKEY]")
            response = instance.get_data(f"[HOST]emby/Items?{query}")
            if response is None or not response.ok:
                status = getattr(response, "status_code", "无响应")
                raise RuntimeError(f"HTTP {status}")
            payload = response.json()
            items = payload.get("Items") or []
            for item in items:
                self._import_emby_item(server_name, item, result)
            start_index += len(items)
            total = int(payload.get("TotalRecordCount") or 0)
            if not items or start_index >= total:
                break

    def _import_emby_item(self, server_name: str, item: dict, result: dict) -> None:
        result["scanned"] += 1
        provider_ids = item.get("ProviderIds") or {}
        tmdb_id = provider_ids.get("Tmdb") or provider_ids.get("TMDB")
        title = str(item.get("Name") or "").strip()
        media_type = normalize_media_type(item.get("Type"))
        if not tmdb_id or not title or media_type not in {"电影", "电视剧"}:
            result["skipped"] += 1
            return
        inserted = self._require_store().insert_if_absent(
            TitleBinding(
                media_source="themoviedb",
                media_type=media_type,
                media_id=str(tmdb_id),
                canonical_title=title,
                canonical_year=str(item.get("ProductionYear") or ""),
                media_root_name=emby_media_root(item),
                origin="emby",
                server_name=server_name,
                server_item_id=str(item.get("Id") or ""),
                media_path=str(item.get("Path") or ""),
            )
        )
        result["inserted" if inserted else "existing"] += 1

    def _apply_config_operation(self, config: dict) -> Tuple[bool, str]:
        source = normalize_source(config.get("media_source"))
        media_type = normalize_media_type(config.get("media_type"))
        media_id = str(config.get("media_id") or "").strip()
        if not source or media_type not in {"电影", "电视剧"} or not media_id:
            return False, "人工维护失败：媒体来源、类型和来源内 ID 必填"
        if config.get("operation") == "delete":
            deleted = self._require_store().delete(source, media_type, media_id)
            return deleted, "标题绑定已删除" if deleted else "未找到对应标题绑定"
        try:
            request = BindingRequest(
                media_source=source,
                media_type=media_type,
                media_id=media_id,
                canonical_title=str(config.get("canonical_title") or "").strip(),
                canonical_year=str(config.get("canonical_year") or "").strip(),
                media_root_name=str(config.get("media_root_name") or "").strip(),
            )
            saved = self._require_store().upsert(self._binding_from_request(request))
            return saved, "标题绑定已保存" if saved else "标题绑定保存失败"
        except (ValueError, TypeError) as error:
            return False, f"人工维护失败：{error}"

    @staticmethod
    def _binding_from_request(request: BindingRequest) -> TitleBinding:
        source = normalize_source(request.media_source)
        media_type = normalize_media_type(request.media_type)
        media_id = request.media_id.strip()
        title = request.canonical_title.strip()
        root_name = request.media_root_name.strip()
        if not source or not media_id or not title:
            raise ValueError("媒体来源、来源内 ID 和固定标题不能为空")
        if media_type not in {"电影", "电视剧"}:
            raise ValueError("媒体类型只能是电影或电视剧")
        if root_name in {".", ".."} or "/" in root_name or "\\" in root_name:
            raise ValueError("媒体根目录名不能包含路径分隔符")
        return TitleBinding(
            media_source=source,
            media_type=media_type,
            media_id=media_id,
            canonical_title=title,
            canonical_year=request.canonical_year.strip(),
            media_root_name=root_name,
            origin="manual",
        )

    def _require_store(self) -> BindingStore:
        if self._store is None:
            self._store = BindingStore(self.get_data_path() / "title_bindings.sqlite3")
        return self._store

    @staticmethod
    def _field(
        component: str,
        model: str,
        label: str,
        md: int,
        **props: Any,
    ) -> dict:
        return {
            "component": "VCol",
            "props": {"cols": 12, "md": md},
            "content": [
                {
                    "component": component,
                    "props": {"model": model, "label": label, **props},
                }
            ],
        }
