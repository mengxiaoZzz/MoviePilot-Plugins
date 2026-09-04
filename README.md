# MoviePilot-Plugins

个人 MoviePilot V2 插件市场仓库。仓库根目录遵循 MoviePilot GitHub 插件市场结构，可在同一仓库中持续添加多个插件。

## 仓库结构

```text
MoviePilot-Plugins/
├── package.v2.json
├── icons/
├── plugins.v2/
│   └── mediatitlelock/
└── tests/
    └── mediatitlelock/
```

新增插件时：

1. 在 `plugins.v2/<插件 ID 小写>/` 新建插件源码目录。
2. 将图标放入 `icons/`。
3. 在根目录 `package.v2.json` 增加插件元数据，保留已有插件条目。
4. 在 `tests/<插件 ID 小写>/` 放置对应测试。

## 已有插件

| 插件 | ID | 说明 |
| --- | --- | --- |
| [媒体标题固定](plugins.v2/mediatitlelock/README.md) | `MediaTitleLock` | 固定首次入库标题，避免同一媒体生成多个名称不同的目录。 |

## 接入 MoviePilot

发布到 GitHub 后，在 MoviePilot V2 的 `PLUGIN_MARKET` 中追加仓库地址：

```text
https://github.com/<GitHub 用户名>/MoviePilot-Plugins
```

本地仓库方式则将 `PLUGIN_LOCAL_REPO_PATHS` 指向包含 `package.v2.json` 的当前仓库根目录。

## 验证

```bash
python3 -m unittest discover -s tests/mediatitlelock -v
python3 -m compileall plugins.v2/mediatitlelock
python3 -m json.tool package.v2.json
```
