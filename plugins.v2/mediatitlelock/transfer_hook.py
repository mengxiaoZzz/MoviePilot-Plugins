"""V2/V3 整理阶段的局部适配；不改宿主文件，不重放已经冻结的文件计划。"""

from contextvars import ContextVar
from functools import wraps
from inspect import signature

from app.log import logger


class TransferCategoryHook:
    def __init__(self, transfer_class, media_class, apply_category, remember_transfer=None):
        self.transfer_class = transfer_class
        self.media_class = media_class
        self.apply_category = apply_category
        self.remember_transfer = remember_transfer
        self.active = False
        self._task = ContextVar("mediatitlelock_transfer_task", default=None)
        self._patches = []

    def install(self):
        if self.active:
            return
        handle_name = "_TransferChain__handle_transfer"
        handle = getattr(self.transfer_class, handle_name)
        supplement = self.media_class.supplement_tmdb_info
        handle_signature = signature(handle)
        supplement_signature = signature(supplement)
        if not {"task", "callback"}.issubset(handle_signature.parameters) or not {"mediainfo", "metainfo"}.issubset(supplement_signature.parameters):
            raise RuntimeError("宿主整理接口不匹配，未启用整理分类适配")

        legacy_name = "_TransferChain__settle_legacy_transfer_result"
        legacy = getattr(self.transfer_class, legacy_name, None) if self.remember_transfer else None
        if legacy:
            legacy_signature = signature(legacy)
            if not {"task", "transferinfo"}.issubset(legacy_signature.parameters):
                raise RuntimeError("宿主整理结算接口不匹配，未启用整理适配")

        @wraps(handle)
        def handle_transfer(*args, **kwargs):
            bound = handle_signature.bind(*args, **kwargs)
            task = bound.arguments["task"]
            callback = bound.arguments.get("callback")
            if self.active and self.remember_transfer and callback and not getattr(task, "preview", False):
                # 包装本次任务实际持有的回调，已在队列中的旧 bound method 也能覆盖。
                @wraps(callback)
                def completed(completed_task, transferinfo):
                    result = callback(completed_task, transferinfo)
                    if result and result[0]:
                        self._remember_completed(bound.arguments["self"], completed_task, transferinfo)
                    return result

                bound.arguments["callback"] = completed
            # 冻结计划可能已经执行过部分文件操作，不能重算其目标路径。
            active_task = task if self.active and getattr(task, "plan_checkpoint", None) is None else None
            token = self._task.set(active_task)
            try:
                if active_task is not None and getattr(task, "planning_context_restored", False):
                    task.mediainfo = self.apply_category(task.mediainfo)
                return handle(*bound.args, **bound.kwargs)
            finally:
                self._task.reset(token)

        @wraps(supplement)
        def supplement_media(*args, **kwargs):
            media = supplement(*args, **kwargs)
            task = self._task.get()
            if self.active and task is not None:
                arguments = supplement_signature.bind(*args, **kwargs).arguments
                if arguments.get("metainfo") is task.meta:
                    media = self.apply_category(media)
            return media

        replacements = [
            (self.media_class, "supplement_tmdb_info", supplement_media),
            (self.transfer_class, handle_name, handle_transfer),
        ]
        if legacy:
            @wraps(legacy)
            def settle_legacy(*args, **kwargs):
                result = legacy(*args, **kwargs)
                arguments = legacy_signature.bind(*args, **kwargs).arguments
                self._remember_completed(arguments["self"], arguments["task"], arguments["transferinfo"])
                return result

            replacements.append((self.transfer_class, legacy_name, settle_legacy))

        # 所有入口校验通过再安装；仅处理当前任务，不改宿主返回值或异常。
        for owner, name, replacement in replacements:
            self._patches.append((owner, name, owner.__dict__.get(name), replacement))
            setattr(owner, name, replacement)
        self.active = True

    def _remember_completed(self, chain, task, transferinfo):
        if (not self.active or not self.remember_transfer or getattr(task, "preview", False)
                or not getattr(transferinfo, "success", False)
                or getattr(transferinfo, "target_item", None) is None
                or not getattr(task, "terminal_settled", True)):
            return
        try:
            media = task.mediainfo
            media_type = getattr(media, "type", None)
            if getattr(media_type, "value", media_type) not in ("电影", "电视剧"):
                return
            is_media = getattr(chain, "_is_media_file", None) or getattr(chain, "_TransferChain__is_media_file")
            if is_media(task.fileitem):
                self.remember_transfer(media, transferinfo)
        except Exception as error:
            logger.exception(f"媒体标题固定：同步完成记录失败，保留宿主成功结果 - {error}")

    def remove(self):
        self.active = False
        for owner, name, original, replacement in reversed(self._patches):
            # 不覆盖后装的其他插件；若对方仍引用本包装器，它也只透传。
            if getattr(owner, name) is replacement:
                if original is None:
                    delattr(owner, name)
                else:
                    setattr(owner, name, original)
        self._patches.clear()
