# 许可与归属声明（NOTICE）

本项目是 [`PC2005-cloud/dsh-pet`](https://github.com/PC2005-cloud/dsh-pet) 的**二次创作（fork 素材包）**。
本文件说明哪些部分是上游的、哪些是本项目新增的，以及再分发时的义务。

- 本仓库的 [`LICENSE`](LICENSE)（MIT，Copyright (c) 2026 Nepenthe-A1）覆盖**本项目的原创部分**
- 上游 [`LICENSE-UPSTREAM-dsh-pet`](LICENSE-UPSTREAM-dsh-pet)
  （MIT，Copyright (c) 2026 PC2005-cloud）覆盖**插件本体**
- 两者适用范围不同，不要把 `LICENSE` 当成对整个衍生包的授权声明

---

## 一、上游项目

| 项 | 内容 |
|---|---|
| 项目 | dsh-pet |
| 作者 | **PC2005-cloud**（GitHub，提交署名 `pc2005`） |
| 仓库 | https://github.com/PC2005-cloud/dsh-pet |
| 许可 | **MIT License** |
| 本项目基于的版本 | **v0.3.7** |

`dsh-pet` 以 MIT 许可发布。MIT 允许使用、复制、修改、合并、发布、分发、再许可和/或销售
本软件的副本，**前提是保留上述版权声明和本许可声明**。

上游的版权声明与 MIT 许可全文见：

- [`LICENSE-UPSTREAM-dsh-pet`](LICENSE-UPSTREAM-dsh-pet) —— 随本仓库提供副本
- https://github.com/PC2005-cloud/dsh-pet/blob/main/LICENSE —— 上游原始文件

---

## 二、本项目的原创部分

以下内容由 **Nepenthe-A1** 制作，以 MIT 许可发布：

| 内容 | 说明 |
|---|---|
| `pet/hypurr-animation/*.webm` | 18 条 Hypurr 动画（AI 生成 + 后期处理） |
| `pet/hypurr-config.json` | 种类配置（动画池、权重、六档文案） |
| `tools/*.py` | 素材链工具与补丁脚本 |
| `docs/PROMPTS-*.md` | 提示词配方 |
| 便携版打包层 | `build_portable*.py`、启动器、更新通道 |

---

## 三、修改上游代码的部分（四个补丁）

以下补丁**修改了上游 dsh-pet 的源代码**。它们以独立脚本形式提供于 `tools/`，
不直接分发修改后的上游源码：

| 补丁 | 修改位置 | 工具 | marker |
|---|---|---|---|
| 动作冷却（网页） | `lib/client.js` | `patch_pet_cooldown.py` | `dsh-pet-cooldown-patch` |
| 动作冷却（桌面） | `runtime/electron-helper/sprite.js` | `patch_pet_cooldown_desktop.py` | `dsh-pet-cooldown-desktop` |
| 菜单隐藏碎碎念 + HYPE 行情 | `lib/index.js`、`lib/client.js` | `patch_pet_market.py` | `dsh-pet-market-patch` |
| 文字不镜像 | `sprite.js` 的 `playOnce` + 配置 | `patch_pet_nomirror.py` | `dsh-pet-nomirror-patch` |

依据 MIT 许可，这些是对上游代码的合法修改。
**再分发便携版**（内含打过补丁的 `app/`）时，必须同时附带：

1. 上游的 MIT 许可全文
2. 上游版权声明「Copyright (c) PC2005-cloud」
3. 本文件的补丁说明

---

## 四、再分发检查清单

如果你要基于本项目再发布（尤其是打包便携版）：

- [ ] 保留 `LICENSE`（本项目）与 `LICENSE-UPSTREAM-dsh-pet`（上游）
- [ ] 保留本 `NOTICE.md`
- [ ] 便携包内 `app/` 目录必须含上游 MIT 许可全文
- [ ] 不得声称上游代码为你原创
- [ ] 不得使用 "dsh-pet" 名义为你的衍生版背书（MIT 不授予商标权）

---

## 五、第三方组件

便携版内含以下第三方软件，各自适用其自身许可：

| 组件 | 许可 |
|---|---|
| Electron | MIT |
| Chromium | BSD-3-Clause 等（见 `LICENSES.chromium.html`） |
| Node.js 依赖（`@electron/get` 等） | 各自 MIT / ISC |

---

## 六、免责声明

- **非官方粉丝创作**：Hypurr 是 Hyperliquid 社区形象，本项目与 Hyperliquid Labs
  及 dsh-pet 作者均无隶属、赞助或背书关系。
- **行情数据**：来自 Hyperliquid 公开接口，仅供娱乐展示，**不构成投资建议**。
- **动画素材**：由 AI 生成并经人工后期处理，不含任何第三方版权素材。
- **按原样提供**：依 MIT 许可，作者不对使用后果提供任何担保。