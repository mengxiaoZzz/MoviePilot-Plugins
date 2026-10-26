"""仅在当前媒体下载上下文中，下载器确认接收后同步保存绑定。"""

from contextvars import ContextVar
from functools import wraps
from inspect import signature

from app.log import logger


class DownloadBindingHook:
    def __init__(self, download_class, remember_download):
        self.download_class = download_class
        self.remember_download = remember_download
        self.active = False
        self._context = ContextVar("mediatitlelock_download_context", default=None)
        self._patches = []

    def install(self):
        if self.active:
            return
        single = self.download_class.download_single
        download = self.download_class.download
        single_signature = signature(single)
        if "context" not in single_signature.parameters or "content" not in signature(download).parameters:
            raise RuntimeError("宿主下载接口不匹配，未启用下载绑定适配")

        @wraps(single)
        def download_single(chain, *args, **kwargs):
            context = single_signature.bind(chain, *args, **kwargs).arguments["context"]
            token = self._context.set((chain, context) if self.active else None)
            try:
                return single(chain, *args, **kwargs)
            finally:
                self._context.reset(token)

        @wraps(download)
        def accept_download(chain, *args, **kwargs):
            result = download(chain, *args, **kwargs)
            current = self._context.get()
            # 返回契约为 (下载器, hash, 布局, 错误消息)，有 hash 才表示已接收。
            if (self.active and current is not None and current[0] is chain
                    and isinstance(result, tuple) and len(result) == 4 and result[1]):
                try:
                    self.remember_download(current[1].media_info, result[1])
                except Exception as error:
                    logger.exception(f"媒体标题固定：下载绑定处理异常，保留下载器接收结果 - {error}")
            return result

        for name, replacement in (("download", accept_download), ("download_single", download_single)):
            self._patches.append((name, self.download_class.__dict__.get(name), replacement))
            setattr(self.download_class, name, replacement)
        self.active = True

    def remove(self):
        self.active = False
        for name, original, replacement in reversed(self._patches):
            if getattr(self.download_class, name) is replacement:
                if original is None:
                    delattr(self.download_class, name)
                else:
                    setattr(self.download_class, name, original)
        self._patches.clear()
