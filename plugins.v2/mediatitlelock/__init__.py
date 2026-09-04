from typing import Any, Dict, List, Optional, Tuple

from pydantic import BaseModel, Field

from app import schemas
from app.core.event import Event, eventmanager
from app.log import logger
from app.plugins import _PluginBase
from app.schemas.types import ChainEventType, EventType

from .database import BindingStore, TitleBinding
from .identity import (
    apply_locked_title,
    extract_media_identity,
    normalize_source,
    replace_media_root,
)


class PluginConfigRequest(BaseModel):
    """主页面保存插件配置的请求。"""

    enabled: bool = False


class BindingRequest(BaseModel):
    """新增或修改固定标题绑定的请求。"""

    media_source: str = Field(default="themoviedb", min_length=1, max_length=40)
    media_id: str = Field(min_length=1, max_length=80)
    canonical_title: str = Field(min_length=1, max_length=255)
    canonical_year: str = Field(default="", max_length=20)
    media_root_name: str = Field(default="", max_length=255)


class BindingDeleteRequest(BaseModel):
    """删除固定标题绑定的请求。"""

    media_source: str = Field(default="themoviedb", min_length=1, max_length=40)
    media_id: str = Field(min_length=1, max_length=80)


class MediaTitleLock(_PluginBase):
    """按“媒体来源 + 来源内 ID”固定整理标题。"""

    plugin_name = "媒体标题固定"
    plugin_desc = "首次入库后固定媒体标题，避免元数据标题变化产生多个目录。"
    plugin_icon = "mediatitlelock.svg"
    plugin_version = "1.0.2"
    plugin_author = "baixiaofei"
    author_url = ""
    plugin_config_prefix = "mediatitlelock_"
    plugin_order = 28
    auth_level = 1

    _enabled = False
    _store: Optional[BindingStore] = None

    def init_plugin(self, config: dict = None) -> None:
        """读取配置并初始化绑定数据库。"""

        current = config or {}
        self._enabled = bool(current.get("enabled"))
        self._store = BindingStore(self.get_data_path() / "title_bindings.sqlite3")

    def get_state(self) -> bool:
        """返回插件启用状态。"""

        return self._enabled

    @staticmethod
    def get_command() -> List[Dict[str, Any]]:
        """当前插件不注册远程命令。"""

        return []

    def get_api(self) -> List[Dict[str, Any]]:
        """注册主页面配置与绑定管理接口。"""

        return [
            {
                "path": "/config",
                "endpoint": self.api_config,
                "methods": ["GET"],
                "auth": "bear",
                "summary": "查询媒体标题固定配置",
            },
            {
                "path": "/config",
                "endpoint": self.api_save_config,
                "methods": ["POST"],
                "auth": "bear",
                "summary": "保存媒体标题固定配置",
            },
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
        ]

    def get_form(self) -> Tuple[Optional[List[dict]], Dict[str, Any]]:
        """不再提供独立设置页。"""

        return None, {}

    def get_page(self) -> Optional[List[dict]]:
        """主页面由 Vue 联邦组件提供。"""

        return None

    @staticmethod
    def get_render_mode() -> Tuple[str, Optional[str]]:
        """使用 Vue 主页面承载配置和绑定管理。"""

        return "vue", "dist/assets"

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
            binding = self._require_store().get(identity.media_source, identity.media_id)
            if binding:
                apply_locked_title(
                    rename_dict, binding.canonical_title, binding.canonical_year
                )
        except Exception as error:
            logger.exception(f"媒体标题固定：重命名上下文处理失败 - {error}")

    @eventmanager.register(ChainEventType.TransferRename, priority=100)
    def lock_media_root(self, event: Event) -> None:
        """在路径渲染后复用绑定中保存的媒体根目录名。"""

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
            binding = self._require_store().get(identity.media_source, identity.media_id)
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
                    f"媒体标题固定：已记录 {identity.media_source}/"
                    f"{identity.media_id} -> {title}"
                )
        except Exception as error:
            logger.exception(f"媒体标题固定：记录整理结果失败 - {error}")

    def api_config(self) -> schemas.Response:
        """查询主页面配置。"""

        return schemas.Response(
            success=True,
            message="查询成功",
            data={"enabled": self._enabled},
        )

    def api_save_config(self, request: PluginConfigRequest) -> schemas.Response:
        """保存主页面配置并立即更新运行状态。"""

        enabled = bool(request.enabled)
        saved = self.update_config({"enabled": enabled})
        if saved:
            self._enabled = enabled
        return schemas.Response(
            success=saved,
            message="配置已保存" if saved else "配置保存失败",
            data={"enabled": self._enabled},
        )

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
        media_id = request.media_id.strip()
        deleted = self._require_store().delete(source, media_id)
        return schemas.Response(
            success=deleted,
            message="标题绑定已删除" if deleted else "未找到对应标题绑定",
        )

    @staticmethod
    def _binding_from_request(request: BindingRequest) -> TitleBinding:
        source = normalize_source(request.media_source)
        media_id = request.media_id.strip()
        title = request.canonical_title.strip()
        root_name = request.media_root_name.strip()
        if not source or not media_id or not title:
            raise ValueError("媒体来源、来源内 ID 和固定标题不能为空")
        if root_name in {".", ".."} or "/" in root_name or "\\" in root_name:
            raise ValueError("媒体根目录名不能包含路径分隔符")
        return TitleBinding(
            media_source=source,
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
