# MoviePilot 媒体标题固定

适用于 MoviePilot V2 的整理标题固定插件。它按“媒体来源 + 媒体类型 + 来源内 ID”保存固定标题，避免 TMDB 等元数据源改名后，同一媒体被整理到多个不同名称的目录。

## 工作方式

1. 整理路径渲染前查询标题绑定；存在绑定时覆盖 `title`、`year` 和 `title_year`。
2. 路径渲染后，如绑定中保存了现有媒体根目录名，则只替换相对路径的第一级目录。
3. 仅在 MoviePilot 发出“整理完成”事件后，才把首次成功整理使用的标题写入数据库；预览或整理失败不会建立绑定。
4. 可主动从 MoviePilot 已配置的 Emby 服务读取 Movie、Series 条目，导入 Emby 当前标题、年份及媒体根目录名。已有绑定不会被导入覆盖。

绑定主键包含媒体类型，是为了避免 TMDB 电影与电视剧恰好使用相同数字 ID 时发生冲突。

## 所在仓库结构

```text
MoviePilot-Plugins/
├── icons/
│   └── mediatitlelock.svg
├── plugins.v2/
│   └── mediatitlelock/       # 当前插件
├── tests/
│   └── mediatitlelock/
└── package.v2.json
```

仓库根目录是一套 MoviePilot V2 插件市场；后续插件与 `mediatitlelock` 并列放入 `plugins.v2/`。

## 安装

将 `MoviePilot-Plugins` 根目录发布为 GitHub 仓库，然后在 MoviePilot V2 的插件市场设置中添加该仓库地址。安装“媒体标题固定”后：

1. 在插件配置中启用“标题固定”。
2. 如需沿用已有 Emby 目录名，选择 Emby 服务；留空表示导入全部已启用的 Emby 服务。
3. 打开插件详情页，点击“从 Emby 导入现有标题”。
4. 后续整理会复用已保存的标题；其他元数据仍由 MoviePilot 正常更新。

插件通过 MoviePilot 的媒体服务器实例访问 Emby，不会另行保存或输出 Emby 地址、账号或 API Key。

## 人工维护

插件提供以下 Bearer Token 鉴权接口：

- `GET /api/v1/plugin/MediaTitleLock/bindings`
- `POST /api/v1/plugin/MediaTitleLock/bindings`
- `POST /api/v1/plugin/MediaTitleLock/bindings/delete`
- `POST /api/v1/plugin/MediaTitleLock/import-emby`

也可以在插件配置的人工维护区域输入媒体身份和固定标题，勾选“保存时执行一次”后保存配置。删除只需要媒体来源、类型和来源内 ID。

新增或修改绑定示例：

```json
{
  "media_source": "themoviedb",
  "media_type": "电视剧",
  "media_id": "330150",
  "canonical_title": "死灵法师！我即是天灾",
  "canonical_year": "2026",
  "media_root_name": "死灵法师！我即是天灾 (2026)"
}
```

## 数据与限制

- 数据库位置：MoviePilot 插件数据目录下的 `MediaTitleLock/title_bindings.sqlite3`。
- Emby 条目必须带有 TMDB Provider ID 才能导入；没有 TMDB ID 的条目会跳过。
- Emby 电影条目取视频文件父目录为媒体根目录；剧集条目取 Series 路径自身目录名。
- 插件只替换相对整理结果的第一级目录。完全自定义且不以媒体根目录开头的命名模板，不保证能复用 Emby 目录名。
- 当前实现面向 MoviePilot V2，并依赖 `TransferRenameBuild`、`TransferRename` 与 `TransferComplete` 事件。V3 需要单独适配，不能直接复用本包。

## 验证

```bash
python3 -m unittest discover -s tests/mediatitlelock -v
python3 -m compileall plugins.v2/mediatitlelock
```

## 回滚

关闭插件即可停止标题覆盖，数据库绑定会保留。完整回滚时可在停用插件后备份并删除 `title_bindings.sqlite3`；该操作不会移动或删除任何媒体文件。
