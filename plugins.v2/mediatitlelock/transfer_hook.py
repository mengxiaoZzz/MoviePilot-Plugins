"""V2/V3 整理阶段的局部适配；不改宿主文件，不重放已经冻结的文件计划。"""

from contextvars import ContextVar
from functools import wraps
from inspect import signature


class TransferCategoryHook:
    def __init__(self, transfer_class, media_class, apply_category):
        self.transfer_class = transfer_class
        self.media_class = media_class
        self.apply_category = apply_category
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
        if "task" not in handle_signature.parameters or not {"mediainfo", "metainfo"}.issubset(supplement_signature.parameters):
            raise RuntimeError("宿主整理接口不匹配，未启用整理分类适配")

        @wraps(handle)
        def handle_transfer(*args, **kwargs):
            task = handle_signature.bind(*args, **kwargs).arguments["task"]
            # 冻结计划可能已经执行过部分文件操作，不能重算其目标路径。
            active_task = task if self.active and getattr(task, "plan_checkpoint", None) is None else None
            token = self._task.set(active_task)
            try:
                if active_task is not None and getattr(task, "planning_context_restored", False):
                    task.mediainfo = self.apply_category(task.mediainfo)
                return handle(*args, **kwargs)
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

        # 同时校验完两个入口再安装；只在本线程的整理上下文内处理分类。
        for owner, name, replacement in (
            (self.media_class, "supplement_tmdb_info", supplement_media),
            (self.transfer_class, handle_name, handle_transfer),
        ):
            self._patches.append((owner, name, owner.__dict__.get(name), replacement))
            setattr(owner, name, replacement)
        self.active = True

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
