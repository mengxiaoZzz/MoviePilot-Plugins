# MoviePilot 媒体标题固定

适用于 MoviePilot V2 的整理标题固定插件。它按“媒体来源 + 来源内 ID”保存固定标题，避免 TMDB 等元数据源改名后，同一媒体被整理到多个不同名称的目录。

## 工作方式

1. 整理路径渲染前查询标题绑定；存在绑定时覆盖 `title`、`year` 和 `title_year`。
2. 路径渲染后，如绑定中保存了现有媒体根目录名，则只替换相对路径的第一级目录。
3. 仅在 MoviePilot 发出“整理完成”事件后，才把首次成功整理使用的标题写入数据库；预览或整理失败不会建立绑定。

绑定主键不区分电影和电视剧；同一媒体来源下，相同来源内 ID 只保留一条绑定。

## 所在仓库结构

```text
MoviePilot-Plugins/
├── icons/
│   └── mediatitlelock.svg
├── plugins.v2/
│   └── mediatitlelock/       # 当前插件及主页面前端
├── tests/
│   └── mediatitlelock/
└── package.v2.json
```

仓库根目录是一套 MoviePilot V2 插件市场；后续插件与 `mediatitlelock` 并列放入 `plugins.v2/`。

## 安装

将 `MoviePilot-Plugins` 根目录发布为 GitHub 仓库，然后在 MoviePilot V2 的插件市场设置中添加该仓库地址。安装“媒体标题固定”后：

1. 打开插件主页面，启用“标题固定”并保存设置。
2. 后续整理会自动记录并复用首次成功整理的标题；其他元数据仍由 MoviePilot 正常更新。

## 人工维护

插件提供以下 Bearer Token 鉴权接口：

- `GET /api/v1/plugin/MediaTitleLock/config`
- `POST /api/v1/plugin/MediaTitleLock/config`
- `GET /api/v1/plugin/MediaTitleLock/bindings`
- `POST /api/v1/plugin/MediaTitleLock/bindings`
- `POST /api/v1/plugin/MediaTitleLock/bindings/delete`

插件不再提供独立设置页。启用设置、人工新增、修改、删除和绑定列表均位于插件主页面；操作成功后表单会自动清空并刷新列表。

新增或修改绑定示例：

```json
{
  "media_source": "themoviedb",
  "media_id": "330150",
  "canonical_title": "死灵法师！我即是天灾",
  "canonical_year": "2026",
  "media_root_name": "死灵法师！我即是天灾 (2026)"
}
```

## 数据与限制

- 数据库位置：MoviePilot 插件数据目录下的 `MediaTitleLock/title_bindings.sqlite3`。
- 从 `1.0.0` 升级时会把旧主键自动迁移为“媒体来源 + 来源内 ID”，并在同目录生成 `title_bindings.sqlite3.before-source-id-v2.bak`。旧库存在同来源同 ID 的电影、剧集记录时保留更新时间较新的记录。
- 插件只替换相对整理结果的第一级目录。完全自定义且不以媒体根目录开头的命名模板，不保证能复用已绑定的目录名。
- 升级不会删除旧版本已经保存的标题绑定。
- 当前实现面向 MoviePilot V2，并依赖 `TransferRenameBuild`、`TransferRename` 与 `TransferComplete` 事件。V3 需要单独适配，不能直接复用本包。

## 验证

```bash
cd plugins.v2/mediatitlelock && npm install --no-package-lock && npm run build
python3 -m unittest discover -s tests/mediatitlelock -v
python3 -m compileall plugins.v2/mediatitlelock
```

## 回滚

关闭插件即可停止标题覆盖，数据库绑定会保留。需要回滚到 `1.0.0` 时，先停止 MoviePilot，用 `title_bindings.sqlite3.before-source-id-v2.bak` 替换当前数据库，再安装旧版插件；该操作不会移动或删除任何媒体文件。
