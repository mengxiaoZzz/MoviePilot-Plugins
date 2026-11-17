"""Official MoviePilot LocalStorage method excerpts (GPL-3.0).
Source: https://github.com/jxxghp/MoviePilot/blob/371cf18c90ff504d6f9bd2334e7f78a2218b2514/app/modules/filemanager/storages/local.py
Method bodies are unchanged; tests inject filesystem/service dependencies.
"""

from __future__ import annotations


class LocalStorage:
    PARTIAL_SUFFIX = ".mp-partial"
    PARTIAL_STALE_SECONDS = 24 * 3600
    chunk_size = 10 * 1024 * 1024

    @classmethod
    def _partial_path(cls, dest: Path) -> Path:
        """
        生成同目录、每次调用独立的中间写入路径。

        同目录便于完成后原子替换；随机标识隔离同进程和跨进程的同目标任务。

        :param dest: 最终文件路径
        :return: 隐藏的 .mp-partial 文件路径
        """
        return dest.parent / f".{dest.name}.{uuid.uuid4().hex}{cls.PARTIAL_SUFFIX}"

    @classmethod
    def _cleanup_stale_partials(cls, directory: Path) -> None:
        """
        清理目录下中断残留的临时文件。

        只做局部清理而不是全库扫描：在网络挂载上遍历整个媒体库代价不可接受，
        而残留只可能出现在曾经写入过的目录里，因此每次写入时顺带清理即可。
        本方法是尽力而为的旁路操作，任何失败都不影响主流程。

        :param directory: 目标目录
        """
        try:
            threshold = time.time() - cls.PARTIAL_STALE_SECONDS
            for item in directory.glob(f"*{cls.PARTIAL_SUFFIX}"):
                try:
                    if item.stat().st_mtime < threshold:
                        item.unlink()
                        logger.info(f"【本地】已清理中断残留的临时文件：{item}")
                except OSError:
                    continue
        except Exception as err:
            logger.debug(f"【本地】清理临时文件失败：{directory} - {err}")

    def _write_atomically(
        self,
        src: Path,
        dest: Path,
        *,
        try_reflink: Optional[bool] = None,
    ) -> bool:
        """
        先复制到同目录中间文件，完成后原子替换目标名称。

        目标已有内容在替换前保留；此处保证名称替换的原子性，不额外执行断电持久化同步。
        结束时尽力删除中间文件，进度展示会收尾到 100，不能仅据此判断复制成功。
        同一文件系统且支持写时复制时优先使用 reflink，失败或不支持时自动回退为常规复制。

        :param src: 源文件路径，成功后仍保留
        :param dest: 完整目标文件路径；父目录需已存在
        :param try_reflink: 是否优先尝试写时复制引用链接克隆；None 时遵循系统运行期配置
        :return: 复制和替换均完成返回 True；取消或失败返回 False
        """
        self._cleanup_stale_partials(dest.parent)
        partial = self._partial_path(dest)
        if runtime_stop_state.consume_transfer_stop(src.as_posix()):
            logger.info(f"【本地】{src} 复制已取消")
            return False

        should_try = (
            get_runtime_setting("TRANSFER_COPY_TRY_REFLINK", True)
            if try_reflink is None
            else try_reflink
        )
        # 同一文件系统优先尝试写时复制克隆，成功即完成原子替换
        if should_try and self._try_reflink_copy(src, partial):
            os.replace(partial, dest)
            return True
        # 进度只在需要展示时才回调 UI，但代理内部始终按固定间隔上报——那是判定
        # 「传输是否还在推进」的心跳，不能因为不展示进度就关掉
        progress_callback = (
            transfer_process(src.as_posix())
            if self.__should_show_progress(src, dest) else None
        )
        try:
            copied = fsproxy.copy(
                src, partial,
                progress_cb=progress_callback,
                cancel_cb=lambda: runtime_stop_state.consume_transfer_stop(src.as_posix()),
                chunk_size=self.chunk_size,
            )
            if not copied:
                logger.info(f"【本地】{src} 复制未完成")
                return False
            os.replace(partial, dest)
            return True
        except Exception as err:
            logger.error(f"【本地】复制文件失败：{err}")
            return False
        finally:
            if progress_callback:
                progress_callback(100)
            # 失败路径留下的临时文件就地清掉；成功时 replace 已经把它移走
            try:
                if partial.exists():
                    partial.unlink()
            except OSError:
                pass

    def upload(
            self,
            fileitem: _SchemaFileItem,
            path: Path,
            new_name: Optional[str] = None
    ) -> Optional[_SchemaFileItem]:
        """
        原子复制本地上传文件到目标目录，并删除上传源。

        :param fileitem: 必须已经存在的目标目录项
        :param path: 上传源文件，复制成功后会删除
        :param new_name: 可选目标文件名，默认使用源文件名
        :return: 目标文件项；复制、删除源文件或后续查询失败返回 None，目标文件可能已经写入
        """
        try:
            if not fileitem.path:
                return None
            dir_path = Path(fileitem.path)
            target_path = dir_path / (new_name or path.name)
            # 先原子地把内容落到目标，确认完整之后才删源
            if self._write_atomically(path, target_path):
                path.unlink()
                return self.get_item(target_path)
        except Exception as err:
            logger.error(f"【本地】上传文件失败：{err}")
        return None

    def copy(
        self,
        fileitem: _SchemaFileItem,
        path: Path,
        new_name: str,
        *,
        try_reflink: Optional[bool] = None,
        **_kwargs: Any,
    ) -> bool:
        """
        通过同目录中间文件复制并替换目标。

        :param fileitem: 源文件项
        :param path: 已存在的目标目录
        :param new_name: 目标文件名
        :param try_reflink: 是否优先尝试写时复制引用链接克隆；None 时遵循系统运行期配置
        :param _kwargs: 忽略多余的扩展参数
        :return: 目标写入完成返回 True，取消或失败返回 False
        """
        if not fileitem.path:
            return False
        return self._write_atomically(
            Path(fileitem.path),
            path / new_name,
            try_reflink=try_reflink,
        )

    def move(
            self,
            fileitem: _SchemaFileItem,
            path: Path,
            new_name: str
    ) -> bool:
        """
        先尝试直接替换目标，失败后复制完成再删除源文件。

        复制成功但删除源失败时只记录警告，仍返回 True，此时源和目标可能同时存在。

        :param fileitem: 源文件项
        :param path: 已存在的目标目录
        :param new_name: 目标文件名
        :return: 目标完成或源目标路径相同返回 True；复制失败返回 False
        """
        if not fileitem.path:
            return False
        src = Path(fileitem.path)
        dest = path / new_name
        if src == dest:
            return True
        try:
            # 同一文件系统内 rename 是原子操作：中断后要么完全成功、要么完全
            # 没发生，既不需要临时文件也不会留下半成品。直接尝试而不预先比较
            # st_dev，省掉挂载上的两次 stat——跨设备会以 EXDEV 失败并落到下面
            os.replace(src, dest)
            return True
        except OSError as err:
            logger.debug(f"【本地】直接移动未成功，降级为复制：{src} -> {dest} - {err}")
        # 跨文件系统：先原子地把内容落到目标，确认完整之后才删源。
        # 顺序不能反——先删源再失败就是永久丢件
        if not self._write_atomically(src, dest):
            return False
        try:
            src.unlink()
        except OSError as err:
            logger.warn(f"【本地】移动已完成但删除源文件失败：{src} - {err}")
        return True
