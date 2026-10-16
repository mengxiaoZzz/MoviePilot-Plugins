# MoviePilot 媒体标题固定

整理标题与分类固定插件，兼容 MoviePilot V2，并按 V3 3.1.5 的接口完成分类适配。它按“媒体来源 + 来源内 ID”保存固定标题和分类，避免元数据变化后，同一媒体被整理到多个不同目录。

## 工作方式

1. 自动下载任务建立前查询已有绑定；分类仍在 MP 当前配置中时才覆盖下载分类。分类被删除、改名或配置读取失败时，保留传入的识别分类并同步到下载参数，不改变已有绑定，也不取消任务。
2. 整理路径渲染前查询标题绑定；存在绑定时覆盖 `title`、`year` 和 `title_year`。
3. 仅在 MoviePilot 发出“整理完成”事件后，才把首次成功整理使用的标题、年份和分类写入数据库；预览或整理失败不会建立绑定。

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
2. 后续整理会自动记录并复用首次成功整理的标题和分类；其他元数据仍由 MoviePilot 正常更新。

## 人工维护

插件提供以下 Bearer Token 鉴权接口：

- `GET /api/v1/plugin/MediaTitleLock/config`
- `POST /api/v1/plugin/MediaTitleLock/config`
- `GET /api/v1/plugin/MediaTitleLock/categories`
- `GET /api/v1/plugin/MediaTitleLock/diagnostics`
- `GET /api/v1/plugin/MediaTitleLock/bindings`
- `POST /api/v1/plugin/MediaTitleLock/bindings`
- `POST /api/v1/plugin/MediaTitleLock/bindings/delete`

插件不再提供独立设置页。主页面集中展示运行设置、筛选和绑定列表；点击“新增绑定”或列表行内“编辑”后打开维护弹窗，删除仅保留在列表行内。人工新增或修改时，分类为必填项，选项来自 MoviePilot 当前分类配置；列表支持按 TMDB ID 和标题筛选，分页显示当前页、总页数与可点击页码。

列表现在使用后端分页：`GET .../bindings?page=1&page_size=25&tmdbid=&title=`。`page_size` 限制为 1–100，返回 `items`、`total`、`page`、`page_size`、`page_count` 和 `category_error`。筛选在全库执行，超出末页时自动纠正页码，空结果为第 1 / 1 页；旧的 `limit` 参数不再用于此接口。按更新时间倒序、同秒按内部行号升序，复用现有索引并保证顺序确定；不提供仅对当前页排序的表头操作。

每条记录附带 `category_status`：`valid`（有效）、`invalid`（失效）、`missing`（未填写）、`unknown`（配置暂不可读）。分类配置读取失败不会阻止列表查询。

V2 使用原分类接口；V3 使用宿主目录路由的只读分类解析器，选项是启用的安全分类路径（如 `剧集/日韩剧`），不是分类显示名称。下载校验按媒体类型执行；禁用、删除、路径变更或类型不匹配的绑定分类不再覆盖识别结果。分类选项读取或人工保存校验失败时返回明确提示，不写入绑定。

## 运行诊断

- 点击“运行诊断”展开，默认收起。仅保存本次运行最近 100 条记录，重载后清空，不额外写数据库。
- `GET .../config` 增加 `backend_version` 和 `ui_revision`；新版前端对比自身版本与构建标识，不一致或后端缺少信息时持续提示。已缓存的旧前端本身不具备此检测能力，仍需更新和强制刷新。
- `GET .../diagnostics` 返回版本、`items`、`last_applied_at`、`emby_status: "not_checked"`、`category_scope: "new_downloads_only"`。
- 诊断记录结构：`timestamp`、`stage`、`status`、`message`、`media_source`、`media_id`、`original_title`、`effective_title`、`original_category`、`effective_category`。时间统一为 `yyyy-MM-dd HH:mm:ss`。
- 区分下载分类应用／回退、标题渲染、文件整理成功／失败，显示缺少身份、标题、分类等未自动记录原因。最近应用时间取最近 100 条记录，可能来自预览或尚未完成的下载，不等同于入库时间。
- 本插件不查询 Emby，不把“文件整理成功”显示为“Emby 已识别”。

新增或修改绑定示例：

```json
{
  "media_source": "themoviedb",
  "media_id": "330150",
  "canonical_title": "死灵法师！我即是天灾",
  "canonical_year": "2026",
  "media_category": "国产剧"
}
```

## 数据与限制

- 数据库位置：MoviePilot 插件数据目录下的 `MediaTitleLock/title_bindings.sqlite3`。
- 从 `1.0.0` 升级时会把旧主键自动迁移为“媒体来源 + 来源内 ID”，并在同目录生成 `title_bindings.sqlite3.before-source-id-v2.bak`。旧库存在同来源同 ID 的电影、剧集记录时保留更新时间较新的记录。
- 从 `1.0.2` 升级时会新增分类字段，并在同目录生成 `title_bindings.sqlite3.before-category-v3.bak`。旧绑定的分类为空，编辑时需从 MoviePilot 分类中补选。
- 固定分类在 MoviePilot 创建自动下载任务时生效；已加入下载器的旧任务和手动整理任务不会被追溯修改分类。
- 失效分类回退也仅覆盖新下载任务；不改历史下载记录、不补改生成后的文件路径、不改 MP 本体。识别分类为空时也不注入失效分类，交由 MP 原流程处理；插件不取消任务，但不能绕过 MP 自身的分类或目录要求。
- 本轮未迁移身份键，仍为“来源 + ID”，电影／剧集身份区分暂缓。
- 尚无绑定的媒体会先使用 MoviePilot 自动识别分类，并在首次整理成功后补充绑定；识别不到分类时不会建立不完整绑定。
- 升级不会删除旧版本已经保存的标题绑定。
- 依赖 `ResourceDownload`、`TransferRenameBuild` 与 `TransferComplete` 事件。V3 兼容 `media_source` 主身份字段；固定分类时同步 `classification.effective` 与兼容分类字段，保留自动推荐、标签和策略修订号。绑定仍以路径保存，不新增分类 ID 或媒体类型字段，不做本轮数据迁移。
- 分类读取失败或失效时，不改 V3 的识别分类快照、不覆盖现有绑定、不设置任务取消标志。仍仅覆盖新下载任务；不能替 MP 绕过存储权限、目录配置或其他整理错误。
- V3 已使用 3.1.5 官方源码的分类模型和路径解析器完成合同测试；尚需在实际部署中验证完整下载、整理链路。分类路径读取尚未包含在 V3 稳定 SDK 中，当前适配依赖 `app.application.classification.reference` 的只读接口。

## 验证

```bash
cd plugins.v2/mediatitlelock && npm install --no-package-lock && npm run build
python3 -m unittest discover -s tests/mediatitlelock -v
python3 -m compileall plugins.v2/mediatitlelock
```

测试覆盖 626 条记录逐页访问无遗漏／重复、越界和空结果、失效分类与配置异常回退、标题固定保持生效、诊断容量和版本、翻页失败与乱序响应。页面每次只保存当前页（最多 100 条），不再受接口默认 500 条截断；后端计数和深页 OFFSET 仍随数据量增长，原有绑定缓存不变，诊断内存固定最多 100 条。

可选 V3 合同测试（在本仓库根目录运行，使用已有 Pydantic 2 环境；不启动 MP，不访问真实媒体或用户数据库）：

```bash
MOVIEPILOT_V3_SOURCE=/path/to/MoviePilot-3.1.5 python3 -m unittest discover -s tests/mediatitlelock -v
```

该测试在独立进程加载 MP 真实分类模型和路径解析器，覆盖有效路径、禁用、删除、改路径、媒体类型不匹配及读取异常回退，并验证绑定记录保持不变。未提供源码目录时只跳过此项，其余测试正常运行。

## 回滚

关闭插件即可停止标题和分类覆盖，数据库绑定会保留。需要回滚到 `1.0.2` 时，先停止 MoviePilot，用 `title_bindings.sqlite3.before-category-v3.bak` 替换当前数据库，再安装旧版插件；该操作不会移动或删除任何媒体文件。

1.0.7 的分页、分类回退和诊断改动不新增迁移；从已安装的 1.0.6 升级无需改变表结构。回滚只需恢复同套旧前后端文件并重启 MP，无需恢复数据库。

1.0.8 的 V2/V3 兼容修复同样不改变插件数据目录或数据库结构。本版前端入口为 `dist/v1.0.8/assets`，发布包包含该版本的完整前端资源。回滚只需恢复修复前的同套插件前后端代码，保留原数据目录；不需要恢复或重建绑定库。插件代码回滚与 MP 主版本降级是两回事。
