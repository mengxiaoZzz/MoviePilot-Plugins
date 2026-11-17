"""仅替换本地原子复制的临时路径生成，不改变最终路径和存储流程。"""

import uuid
from functools import wraps
from inspect import Parameter, iscoroutinefunction, signature


class ShortPartialPathHook:
    def __init__(self, storage_class):
        self.storage_class = storage_class
        self.active = False
        self._original = None
        self._replacement = None

    def install(self):
        if self.active:
            return
        original = self.storage_class.__dict__.get("_partial_path")
        parameters = tuple(signature(original.__func__, follow_wrapped=False).parameters.values()) if isinstance(original, classmethod) else ()
        writer = getattr(self.storage_class, "_write_atomically", None)
        writer_code = getattr(writer, "__code__", None)
        if (not isinstance(original, classmethod)
                or iscoroutinefunction(original.__func__) or iscoroutinefunction(writer)
                or tuple(parameter.name for parameter in parameters) != ("cls", "dest")
                or any(parameter.kind != Parameter.POSITIONAL_OR_KEYWORD for parameter in parameters)
                or getattr(self.storage_class, "PARTIAL_SUFFIX", None) != ".mp-partial"
                or writer_code is None or "_partial_path" not in writer_code.co_names):
            raise RuntimeError("宿主未提供兼容的本地原子复制临时路径接口")

        @wraps(original.__func__)
        def partial_path(cls, dest):
            # 后装插件可能仍持有本包装器；停用后透传原实现。
            if not self.active:
                return original.__func__(cls, dest)
            return dest.parent / f".{uuid.uuid4().hex}{cls.PARTIAL_SUFFIX}"

        self._original = original
        self._replacement = classmethod(partial_path)
        self.storage_class._partial_path = self._replacement
        self.active = True

    def remove(self):
        self.active = False
        # classmethod 每次访问会生成 bound method，须比较原始描述符。
        if self._replacement is not None and self.storage_class.__dict__.get("_partial_path") is self._replacement:
            self.storage_class._partial_path = self._original
        self._original = None
        self._replacement = None
