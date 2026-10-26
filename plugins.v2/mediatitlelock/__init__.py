import threading
from collections import deque
from copy import copy
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from pydantic import BaseModel, Field

from app import schemas
from app.chain.media import MediaChain
from app.core.event import Event, eventmanager
from app.log import logger
from app.plugins import _PluginBase
from app.schemas.types import ChainEventType, EventType

from .database import BindingStore, TIME_FORMAT, TitleBinding
from .download_hook import DownloadBindingHook
from .identity import (
    MediaIdentity,
    apply_locked_title,
    extract_media_identity,
    normalize_source,
)
from .transfer_hook import TransferCategoryHook


UI_REVISION = "20261026-download-binding"


@dataclass(frozen=True)
class ExecutionRecord:
    """仅保存在本次运行内存中的诊断，不等同于 Emby 入库状态。"""

    timestamp: str
    stage: str
    status: str
    message: str
    media_source: str = ""
    media_id: str = ""
    original_title: str = ""
    effective_title: str = ""
    original_category: str = ""
    effective_category: str = ""


class PluginConfigRequest(BaseModel):
    """主页面保存插件配置的请求。"""

    enabled: bool = False


class BindingRequest(BaseModel):
    """新增或修改固定标题绑定的请求。"""

    media_source: str = Field(default="themoviedb", min_length=1, max_length=40)
    media_id: str = Field(min_length=1, max_length=80)
    canonical_title: str = Field(min_length=1, max_length=255)
    canonical_year: str = Field(default="", max_length=20)
    media_category: str = Field(min_length=1, max_length=255)


class BindingDeleteRequest(BaseModel):
    """删除固定标题绑定的请求。"""

    media_source: str = Field(default="themoviedb", min_length=1, max_length=40)
    media_id: str = Field(min_length=1, max_length=80)


class MediaTitleLock(_PluginBase):
    """按“媒体来源 + 来源内 ID”固定整理标题。"""

    plugin_name = "媒体标题固定"
    plugin_desc = "下载或首次整理时固定媒体标题与分类，避免元数据变化产生多个目录。"
    plugin_icon = "mediatitlelock.svg"
    plugin_version = "1.0.10"
    plugin_author = "baixiaofei"
    author_url = ""
    plugin_config_prefix = "mediatitlelock_"
    plugin_order = 28
    auth_level = 1

    _enabled = False
    _store: Optional[BindingStore] = None

    def __init__(self):
        super().__init__()
        self._records = deque(maxlen=100)
        self._records_lock = threading.Lock()
        self._transfer_hook = None
        self._download_hook = None

    def init_plugin(self, config: dict = None) -> None:
        """读取配置并初始化绑定数据库。"""

        current = config or {}
        self._enabled = bool(current.get("enabled"))
        self._store = BindingStore(self.get_data_path() / "title_bindings.sqlite3")
        with self._records_lock:
            self._records.clear()
        self._configure_transfer_hook()
        self._configure_download_hook()

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
                "path": "/diagnostics",
                "endpoint": self.api_diagnostics,
                "methods": ["GET"],
                "auth": "bear",
                "summary": "查询版本和最近执行诊断",
            },
            {
                "path": "/bindings",
                "endpoint": self.api_bindings,
                "methods": ["GET"],
                "auth": "bear",
                "summary": "查询固定标题绑定",
            },
            {
                "path": "/categories",
                "endpoint": self.api_categories,
                "methods": ["GET"],
                "auth": "bear",
                "summary": "查询 MoviePilot 媒体分类",
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

        return "vue", "dist/v1.0.10/assets"

    def stop_service(self) -> None:
        """清理插件内存缓存。"""

        if self._download_hook:
            self._download_hook.remove()
            self._download_hook = None
        if self._transfer_hook:
            self._transfer_hook.remove()
            self._transfer_hook = None
        if self._store:
            self._store.clear_cache()
        with self._records_lock:
            self._records.clear()

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
                self._record("rename", "skipped", "缺少媒体身份，沿用 MP 识别标题")
                return
            binding = self._require_store().get(identity.media_source, identity.media_id)
            if binding:
                original_title = str(rename_dict.get("title") or "")
                apply_locked_title(
                    rename_dict, binding.canonical_title, binding.canonical_year
                )
                self._record("rename", "applied", "已注入固定标题（含预览，不代表文件整理成功）", identity,
                             original_title=original_title, effective_title=binding.canonical_title)
                logger.info(
                    f"媒体标题固定：标题渲染命中 {identity.media_source}/{identity.media_id}，"
                    f"标题 {original_title!r} -> {binding.canonical_title!r}，绑定来源={binding.origin}，"
                    f"绑定更新时间={binding.updated_at}，源路径={getattr(event.event_data, 'source_path', None)!r}"
                )
            else:
                self._record("rename", "skipped", "尚无绑定，沿用 MP 识别标题", identity)
                logger.info(f"媒体标题固定：标题渲染未命中 {identity.media_source}/{identity.media_id}，沿用识别标题")
        except Exception as error:
            logger.exception(f"媒体标题固定：重命名上下文处理失败 - {error}")
            self._record("rename", "error", "标题处理异常，已交回 MP 继续处理，详见插件日志")

    @eventmanager.register(ChainEventType.ResourceDownload, priority=100)
    def lock_download_category(self, event: Event) -> None:
        """下载任务建立前注入已绑定的固定分类。"""

        if not self._enabled or not event or not event.event_data:
            return
        try:
            data = event.event_data
            context = getattr(data, "context", None)
            mediainfo = getattr(context, "media_info", None)
            identity = extract_media_identity(mediainfo)
            if not identity:
                self._record("download", "skipped", "缺少媒体身份，不覆盖下载分类")
                return
            binding = self._require_store().get(identity.media_source, identity.media_id)
            if not binding or not binding.media_category:
                self._record("download", "skipped", "没有已绑定分类，沿用识别分类", identity)
                return
            recognized_category = str(getattr(mediainfo, "category", "") or "")
            try:
                valid = binding.media_category in self._available_categories(getattr(mediainfo, "type", None))
                reason = "绑定分类已失效" if not valid else ""
            except Exception as error:
                valid = False
                reason = "当前分类配置不可用"
                logger.warning(f"媒体标题固定：分类校验失败，沿用识别分类 - {error}")
            if not valid:
                # 不清空识别结果、不改绑定、不设置 cancel；避免 options 携带失效分类。
                if isinstance(getattr(data, "options", None), dict):
                    data.options["media_category"] = recognized_category
                self._record("download", "fallback", f"{reason}，沿用 MP 识别分类，不拦截下载或整理", identity,
                             original_category=binding.media_category, effective_category=recognized_category)
                return
            self._apply_category(mediainfo, binding.media_category)
            if isinstance(getattr(data, "options", None), dict):
                data.options["media_category"] = binding.media_category
            self._record("download", "applied", "已应用有效的固定分类", identity,
                         original_category=recognized_category, effective_category=binding.media_category)
        except Exception as error:
            logger.exception(f"媒体标题固定：下载分类处理失败 - {error}")
            self._record("download", "error", "下载分类处理异常，未拦截任务，详见插件日志")

    def _configure_download_hook(self) -> None:
        if self._download_hook:
            self._download_hook.remove()
            self._download_hook = None
        if not self._enabled:
            return
        try:
            from app.chain.download import DownloadChain

            hook = DownloadBindingHook(DownloadChain, self.remember_download_binding)
            hook.install()
            self._download_hook = hook
        except Exception as error:
            logger.exception(f"媒体标题固定：下载绑定适配未启用，保留 MP 原流程 - {error}")
            self._record("download_binding", "error", "下载绑定接口不可用，仍在首次整理成功后补充绑定，详见插件日志")

    def remember_download_binding(self, mediainfo: Any, download_hash: str) -> None:
        """下载器已经接收任务；新增绑定失败不改变下载结果。"""

        if not self._enabled or not download_hash:
            return
        try:
            media_type = getattr(mediainfo, "type", None)
            if getattr(media_type, "value", media_type) not in ("电影", "电视剧"):
                return
            identity = extract_media_identity(mediainfo)
            title = str(getattr(mediainfo, "title", "") or "").strip()
            category = str(getattr(mediainfo, "category", "") or "").strip()
            if not identity or not title or not category:
                missing = "媒体身份" if not identity else "标题" if not title else "分类"
                self._record("download_binding", "skipped", f"下载器已接收任务；缺少{missing}，暂不建立绑定", identity)
                return
            store = self._require_store()
            inserted = False
            if not store.get(identity.media_source, identity.media_id):
                inserted = store.insert_if_absent(TitleBinding(
                    media_source=identity.media_source, media_id=identity.media_id,
                    canonical_title=title, canonical_year=str(getattr(mediainfo, "year", "") or ""),
                    media_category=category, origin="download",
                ))
            action = "已保存绑定" if inserted else "保留已有绑定"
            logger.info(
                f"媒体标题固定：下载接收后{action} {identity.media_source}/{identity.media_id}，"
                f"识别标题={title!r}，识别分类={category!r}，下载任务={download_hash}"
            )
            self._record("download_binding", "success", f"下载器已接收任务；{action}", identity)
        except Exception as error:
            logger.exception(f"媒体标题固定：下载接收后保存绑定失败，不影响下载或整理 - {error}")
            self._record("download_binding", "error", "下载器已接收任务；绑定保存失败，整理成功后继续补偿，详见插件日志")

    def _configure_transfer_hook(self) -> None:
        if self._transfer_hook:
            self._transfer_hook.remove()
            self._transfer_hook = None
        if not self._enabled:
            return
        try:
            from app.chain.transfer import TransferChain

            hook = TransferCategoryHook(
                TransferChain, MediaChain, self.lock_transfer_binding, self.remember_transfer_result,
            )
            hook.install()
            self._transfer_hook = hook
        except Exception as error:
            logger.exception(f"媒体标题固定：整理前置适配未启用，保留 MP 原流程 - {error}")
            self._record("transfer_category", "error", "整理前置接口不可用，标题仍由渲染事件处理；分类仅新下载生效，详见插件日志")

    def lock_transfer_binding(self, mediainfo: Any) -> Any:
        """整理前在任务副本上固定标题；分类失败不会撤销标题固定。"""

        candidate = self.lock_transfer_category(mediainfo)
        if not self._enabled or candidate is None:
            return candidate
        try:
            identity = extract_media_identity(candidate)
            if not identity:
                return candidate
            binding = self._require_store().get(identity.media_source, identity.media_id)
            if not binding:
                logger.info(f"媒体标题固定：整理前未命中 {identity.media_source}/{identity.media_id}，沿用识别标题")
                return candidate
            locked = copy(candidate)
            locked.title = binding.canonical_title
            if binding.canonical_year:
                locked.year = binding.canonical_year
            logger.info(
                f"媒体标题固定：整理前命中 {identity.media_source}/{identity.media_id}，"
                f"标题 {getattr(candidate, 'title', '')!r} -> {locked.title!r}，"
                f"年份 {getattr(candidate, 'year', '')!r} -> {getattr(locked, 'year', '')!r}，"
                f"绑定来源={binding.origin}，绑定更新时间={binding.updated_at}"
            )
            return locked
        except Exception as error:
            logger.exception(f"媒体标题固定：整理前标题处理异常，保留识别结果继续整理 - {error}")
            return candidate

    def lock_transfer_category(self, mediainfo: Any) -> Any:
        """识别完成、目录匹配前处理分类，返回任务副本，不改缓存和绑定。"""

        if not self._enabled or mediainfo is None:
            return mediainfo
        try:
            identity = extract_media_identity(mediainfo)
            if not identity:
                return mediainfo
            binding = self._require_store().get(identity.media_source, identity.media_id)
            if not binding or not binding.media_category:
                return mediainfo
            original_category = str(getattr(mediainfo, "category", "") or "")
            try:
                valid = binding.media_category in self._available_categories(getattr(mediainfo, "type", None))
                reason = "绑定分类已失效" if not valid else ""
            except Exception as error:
                valid = False
                reason = "当前分类配置不可用"
                logger.warning(f"媒体标题固定：整理分类校验失败，沿用识别分类 - {error}")
            candidate = copy(mediainfo)
            if valid:
                self._apply_category(candidate, binding.media_category)
            else:
                classification = getattr(mediainfo, "classification", None)
                recommended = getattr(classification, "recommended", None)
                if recommended is not None:
                    # 下载历史可能已覆盖 effective；回退不能继续使用失效的历史绑定。
                    result = classification.model_copy(deep=True)
                    result.effective = result.recommended
                    candidate.classification = result
                    candidate.library_category = "/".join(result.recommended.category_path or [])
                    candidate.category = candidate.library_category
                elif not hasattr(mediainfo, "classification") and original_category == binding.media_category:
                    # V2 不保存 recommended；只用已有 TMDB 元数据重新执行本地分类规则。
                    info = getattr(mediainfo, "tmdb_info", None)
                    if info:
                        from app.modules.themoviedb.category import CategoryHelper

                        helper = CategoryHelper()
                        media_type = getattr(mediainfo.type, "value", mediainfo.type)
                        if media_type == "电视剧":
                            candidate.category = helper.get_tv_category(info)
                        elif media_type == "电影":
                            candidate.category = helper.get_movie_category(info)
            effective = str(getattr(candidate, "category", "") or "")
            message = "整理前已应用有效的固定分类" if valid else f"{reason}，整理沿用识别分类，不拦截入库"
            self._record("transfer_category", "applied" if valid else "fallback", message, identity,
                         original_category=original_category, effective_category=effective)
            logger.info(f"媒体标题固定：{identity.media_source}/{identity.media_id} {message}：{original_category} -> {effective}")
            return candidate
        except Exception as error:
            logger.exception(f"媒体标题固定：整理分类处理异常，保留传入结果继续整理 - {error}")
            self._record("transfer_category", "error", "整理分类处理异常，已交回 MP 继续处理，详见插件日志")
            return mediainfo

    @eventmanager.register(EventType.TransferComplete)
    def remember_successful_transfer(self, event: Event) -> None:
        """异步完成事件仅作补偿；重复或延迟事件不覆盖已有绑定。"""

        if not self._enabled or not event or not event.event_data:
            return
        event_data = event.event_data
        transferinfo = event_data.get("transferinfo")
        if transferinfo and not transferinfo.success:
            self.record_failed_transfer(event)
            return
        self.remember_transfer_result(event_data.get("mediainfo"), transferinfo, via="完成事件补偿")

    def remember_transfer_result(self, mediainfo: Any, transferinfo: Any, via: str = "同步整理完成") -> None:
        """宿主成功回调返回后同步落库；写入异常不改变已完成的整理结果。"""

        if not self._enabled:
            return
        try:
            if not transferinfo:
                self._record("transfer", "skipped", "没有整理结果，未建立绑定")
                return
            if not transferinfo.success:
                return
            identity = extract_media_identity(mediainfo)
            title = str(getattr(mediainfo, "title", "") or "").strip()
            category = str(getattr(mediainfo, "category", "") or "").strip()
            if not identity or not title or not category:
                missing = "媒体身份" if not identity else "标题" if not title else "分类"
                self._record("transfer", "success", f"文件整理成功；缺少{missing}，未建立绑定", identity)
                if identity and title and not category:
                    logger.warning(
                        f"媒体标题固定：未记录 {identity.media_source}/"
                        f"{identity.media_id}，整理结果没有媒体分类"
                    )
                return
            target_diritem = getattr(transferinfo, "target_diritem", None)
            inserted = self._require_store().insert_if_absent(
                TitleBinding(
                    media_source=identity.media_source,
                    media_id=identity.media_id,
                    canonical_title=title,
                    canonical_year=str(getattr(mediainfo, "year", "") or ""),
                    media_category=category,
                    origin="automatic",
                    media_path=str(getattr(target_diritem, "path", "") or ""),
                )
            )
            if inserted:
                logger.info(
                    f"媒体标题固定：{via}已保存绑定 {identity.media_source}/"
                    f"{identity.media_id}，标题={title!r}，分类={category!r}"
                )
            else:
                logger.info(f"媒体标题固定：{via}保留已有绑定 {identity.media_source}/{identity.media_id}")
            self._record("transfer", "success",
                         "文件整理成功；已自动建立绑定" if inserted else "文件整理成功；保留已有绑定",
                         identity)
        except Exception as error:
            logger.exception(f"媒体标题固定：记录整理结果失败 - {error}")
            self._record("transfer", "error", "保存绑定异常，不代表文件整理失败，详见插件日志")

    @eventmanager.register(EventType.TransferFailed)
    def record_failed_transfer(self, event: Event) -> None:
        """只记录 MP 的失败结果，不触发重试或修改任务。"""

        if not self._enabled or not event or not event.event_data:
            return
        data = event.event_data
        identity = extract_media_identity(data.get("mediainfo"))
        reason = str(getattr(data.get("transferinfo"), "message", "") or "MP 未提供失败原因")
        self._record("transfer", "failed", f"文件整理失败：{reason}", identity)

    def _record(
        self, stage: str, status: str, message: str, identity: Optional[MediaIdentity] = None,
        original_title: str = "", effective_title: str = "",
        original_category: str = "", effective_category: str = "",
    ) -> None:
        record = ExecutionRecord(
            timestamp=datetime.now().strftime(TIME_FORMAT), stage=stage, status=status, message=message,
            media_source=identity.media_source if identity else "", media_id=identity.media_id if identity else "",
            original_title=original_title, effective_title=effective_title,
            original_category=original_category, effective_category=effective_category,
        )
        with self._records_lock:
            self._records.appendleft(record)

    def api_diagnostics(self) -> schemas.Response:
        """返回本次运行内存诊断；不查询媒体服务器或修改整理任务。"""

        with self._records_lock:
            records = list(self._records)
        return schemas.Response(success=True, data={
            "backend_version": self.plugin_version,
            "ui_revision": UI_REVISION,
            "items": [asdict(record) for record in records],
            "last_applied_at": next((record.timestamp for record in records if record.status == "applied"), ""),
            "emby_status": "not_checked",
            "category_scope": "downloads_and_transfers" if self._transfer_hook and self._transfer_hook.active else "new_downloads_only",
        })

    def api_config(self) -> schemas.Response:
        """查询主页面配置。"""

        return schemas.Response(
            success=True,
            message="查询成功",
            data={"enabled": self._enabled, "backend_version": self.plugin_version, "ui_revision": UI_REVISION},
        )

    def api_save_config(self, request: PluginConfigRequest) -> schemas.Response:
        """保存主页面配置并立即更新运行状态。"""

        enabled = bool(request.enabled)
        saved = self.update_config({"enabled": enabled})
        if saved:
            self._enabled = enabled
            self._configure_transfer_hook()
            self._configure_download_hook()
        return schemas.Response(
            success=saved,
            message="配置已保存" if saved else "配置保存失败",
            data={"enabled": self._enabled},
        )

    def api_bindings(
        self,
        page: int = 1,
        page_size: int = 25,
        tmdbid: str = "",
        title: str = "",
    ) -> schemas.Response:
        """查询固定标题绑定。"""

        store = self._require_store()
        result = store.paginate(page=page, page_size=page_size, tmdbid=tmdbid, title=title)
        try:
            categories = set(self._available_categories())
            category_error = ""
        except Exception as error:
            logger.warning(f"媒体标题固定：分类列表校验失败 - {error}")
            categories = None
            category_error = "分类配置读取失败，暂无法校验分类；不影响查看绑定"
        items = []
        for item in result.items:
            status = "unknown" if categories is None else "missing" if not item.media_category else (
                "valid" if item.media_category in categories else "invalid"
            )
            items.append({**item.to_dict(), "category_status": status})
        return schemas.Response(
            success=True,
            message="查询成功",
            data={
                "total": result.total,
                "items": items,
                "category_error": category_error,
                "page": result.page,
                "page_size": result.page_size,
                "page_count": result.page_count,
            },
        )

    def api_categories(self) -> schemas.Response:
        """查询 MoviePilot 当前配置的媒体分类。"""

        try:
            categories = self._available_categories()
        except Exception as error:
            logger.warning(f"媒体标题固定：读取分类选项失败 - {error}")
            return schemas.Response(
                success=False,
                message="分类配置读取失败，暂无法维护分类；不影响查看绑定，也不会拦截下载或整理",
                data={"items": []},
            )
        return schemas.Response(
            success=True,
            message="查询成功",
            data={"items": categories},
        )

    def api_save_binding(self, request: BindingRequest) -> schemas.Response:
        """新增或修改人工固定标题绑定。"""

        try:
            binding = self._binding_from_request(request)
        except ValueError as error:
            logger.warning(f"媒体标题固定：手工保存失败，参数无效 - {error}")
            return schemas.Response(success=False, message=str(error))
        try:
            categories = self._available_categories()
        except Exception as error:
            logger.warning(f"媒体标题固定：手工保存失败 {binding.media_source}/{binding.media_id}，分类校验异常 - {error}")
            return schemas.Response(success=False, message="分类配置读取失败，未修改绑定；请稍后重试")
        if binding.media_category not in categories:
            logger.warning(f"媒体标题固定：手工保存失败 {binding.media_source}/{binding.media_id}，分类已失效={binding.media_category!r}")
            return schemas.Response(
                success=False,
                message="所选分类不在 MoviePilot 当前分类配置中",
            )
        try:
            store = self._require_store()
            previous = store.get(binding.media_source, binding.media_id)
            saved = store.upsert(binding)
        except Exception as error:
            logger.exception(f"媒体标题固定：手工保存失败 {binding.media_source}/{binding.media_id}，写入异常 - {error}")
            return schemas.Response(success=False, message="标题绑定保存失败，请查看插件日志")
        if saved:
            logger.info(
                f"媒体标题固定：手工保存成功 {binding.media_source}/{binding.media_id}，"
                f"标题 {previous.canonical_title if previous else None!r} -> {binding.canonical_title!r}，"
                f"年份={binding.canonical_year!r}，分类={binding.media_category!r}"
            )
        else:
            logger.warning(f"媒体标题固定：手工保存失败 {binding.media_source}/{binding.media_id}，未写入记录")
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
        category = request.media_category.strip()
        if not source or not media_id or not title or not category:
            raise ValueError("媒体来源、来源内 ID、固定标题和分类不能为空")
        return TitleBinding(
            media_source=source,
            media_id=media_id,
            canonical_title=title,
            canonical_year=request.canonical_year.strip(),
            media_category=category,
            origin="manual",
        )

    @staticmethod
    def _available_categories(media_type: Any = None) -> List[str]:
        """V2 读取分类列表；V3 读取启用的安全目录路径，不使用显示名称。"""

        legacy_getter = getattr(MediaChain(), "media_category", None)
        if not callable(legacy_getter):
            # MP 3.1.5 的分类 SDK 尚未提供路径列表，复用宿主目录路由的只读解析器。
            from app.application.classification.reference import classification_category_resolver_snapshot

            resolver = classification_category_resolver_snapshot()
            return ["/".join(path) for path in resolver.category_paths(media_type) if path]
        category_config = legacy_getter()
        if not isinstance(category_config, dict):
            raise ValueError("MoviePilot 分类配置不可用")
        type_name = getattr(media_type, "value", media_type)
        categories = []
        seen = set()
        for group_name, group_items in category_config.items():
            if type_name and group_name != type_name:
                continue
            if not isinstance(group_items, (list, tuple, set)):
                continue
            for item in group_items:
                category = str(item or "").strip()
                if category and category not in seen:
                    seen.add(category)
                    categories.append(category)
        return categories

    @staticmethod
    def _apply_category(mediainfo: Any, category: str) -> None:
        """仅在分类校验成功后更新生效结果，保留 V3 自动推荐和其他分类元数据。"""

        if hasattr(mediainfo, "classification"):
            from app.schemas.category import ClassificationResult, ClassificationSelection

            selection = ClassificationSelection(
                category_id=None, category_path=category.split("/"), source="manual",
            )
            current = mediainfo.classification
            result = current.model_copy(deep=True) if current is not None else ClassificationResult(state="complete")
            result.effective = selection
            mediainfo.classification = result
            mediainfo.library_category = category
        mediainfo.category = category

    def _require_store(self) -> BindingStore:
        if self._store is None:
            self._store = BindingStore(self.get_data_path() / "title_bindings.sqlite3")
        return self._store
