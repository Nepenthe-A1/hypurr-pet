# Hypurr 桌宠 🐱

**Hyperliquid 社区猫 Hypurr** 的桌面宠物素材包 —— 白猫、橄榄绿连帽外套、懂行情。

基于开源插件 [`PC2005-cloud/dsh-pet`](https://github.com/PC2005-cloud/dsh-pet)（MIT）二次创作。
本仓库是**素材包 + 工具链 + 配方文档**，不是独立程序。

---

## 快速开始

### 方式一：装进 DSH（推荐）

前提：你已经装好 [DSH](https://github.com/deepseek-ai) 和 `dsh-pet` 插件。

```bash
# 1. 把插件装进 DSH 的 desktop profile
dsh plugin install dsh-pet

# 2. 把本仓库的素材包拷进去
cp -r pet/hypurr-config.json   ~/.dsh/dsh-pet/pet/
cp -r pet/hypurr-animation     ~/.dsh/dsh-pet/pet/hypurr-animation
```

Windows 上 `~/.dsh` 即 `C:\Users\<你>\.dsh`。

### 方式二：便携版（不需要 DSH）

到 [Releases](../../releases) 下载 `HypurrPet-Portable-*.zip`，解压后双击「启动 Hypurr.vbs」。

> ⚠️ 便携版内含 Electron 运行时，约 **330 MB**（压缩后约 150 MB），所以放在 Releases 而不是仓库里。

---

## 内容一览

| 目录 | 内容 |
|---|---|
| `pet/hypurr-animation/` | **18 条** 640×360 VP9-alpha webm 动画（15.09 MB） |
| `pet/hypurr-config.json` | 种类配置：动画池、权重、六档文案、行情开关 |
| `tools/` | 素材链工具：抠像 / 归一化 / 编码 / 校验 / 补丁 |
| `docs/PROMPTS-*.md` | AI 生成动画用的提示词配方 |

### 17 个动作（第 18 条见下方说明）

| 用途 | 动作 |
|---|---|
| 待机（3） | `待机呼吸休闲` / `待机-伸懒腰打哈欠` / `待机-舔爪洗脸` |
| 点击回应（2） | `点击回应-开心跃动` / `点击回应-被吓一跳` |
| 拖拽（1） | `被鼠标拖拽悬空反馈` |
| 转向（2） | `原地转身回头` / `原地坐下张望` |
| 工作状态（6） | `工作状态-思考冒泡` / `工作状态-忙碌点按` / `工作状态-清点归档` / `工作状态-原地踱步张望` / `工作状态-雀跃庆祝` / `工作状态-垂头叹气冒汗` |
| 随机动作（3） | `原地小憩沉眠` / `轻快摇摆舞` / `吃Token` |

> `凭空扑蝴蝶.webm` 在包里但**配置未引用**，属于暂不启用的素材（右键菜单里不会出现）。保留在仓库里供后续启用。

---

## 素材链

从 AI 生成的视频到插件能播的 webm：

```
AI 生成的品红底视频（1280×720 / 24fps）
  → tools/key_green.py      抠像（品红预设 + 补斑 + 可选去碎屑/去水印）
  → tools/normalize.py      归一化：站立 900px、脚底 y=1115、画布 2160×1215、24fps
  → tools/encode_playback.py 640×360 VP9-alpha（提锐 + CRF30）
  → 复制进 pet/hypurr-animation/
```

```bash
python tools/key_green.py <源.mp4> <输出.webm> --no-fix-debris
python tools/normalize.py --in video/step02 --out video/step03
python tools/encode_playback.py --in video/step03 --out video/step04
```

**依赖 ffmpeg**：脚本按 `环境变量 FFMPEG` → `PATH` → 常见安装位置 的顺序自动查找，
找不到会给出可操作的提示。也可以显式指定：

```bash
set FFMPEG=D:\ffmpeg\bin\ffmpeg.exe
set FFPROBE=D:\ffmpeg\bin\ffprobe.exe
```

### 规格（换算到 640×360）

| 项 | 值 |
|---|---|
| 站立高 | 266.7 px |
| 脚底 y | 330.4 px |
| 中心 x | 320 px |

`tools/fit_playback.py` 可把任意带 alpha 的素材**一次重采样**贴合到该规格并交叉校验。

---

## 四个补丁

插件本身不提供这些行为，需要给 `node_modules/dsh-pet/` 打补丁
（**插件升级会覆盖 `lib/` 与 `runtime/`**，升级后重跑即可，脚本幂等且有备份）：

| 补丁 | 目标文件 | 工具 |
|---|---|---|
| 动作冷却（网页） | `lib/client.js` | `patch_pet_cooldown.py` |
| 动作冷却（桌面） | `runtime/electron-helper/sprite.js` | `patch_pet_cooldown_desktop.py` |
| 菜单隐藏碎碎念 + HYPE 行情 | `lib/index.js` + `lib/client.js` | `patch_pet_market.py` |
| 文字不镜像 | `sprite.js` 的 `playOnce` + 配置 | `patch_pet_nomirror.py` |

**为什么需要"文字不镜像"**：宠物朝右时整帧会 `scaleX(-1)`，问号等字形会左右反掉。
内置豁免只看 `categories[].noMirror`，而宿主推送的 workStatus 动作拿不到豁免。
补丁让它读 `animations.noMirrorNames`，配置里加名字即可扩展。

---

## 工具清单

| 脚本 | 作用 |
|---|---|
| `ffmpeg_path.py` | 定位 ffmpeg/ffprobe（所有脚本共用） |
| `key_green.py` | 品红/绿幕抠像（主力工具） |
| `key_from_black.py` | 从黑底不透明素材还原 alpha |
| `matte_util.py` | HSV / 连通域 / 形态学基础函数 |
| `normalize.py` | 归一化到统一站立高度与画布 |
| `fit_playback.py` | 一步贴合到播放规格（避免二次重采样） |
| `encode_playback.py` | 640×360 播放变体（提锐 + CRF） |
| `despill_edge.py` | 边缘品红溢色清理（含透明侧颜色外渗） |
| `specks.py` | 清除角落水印残留 |
| `find_watermark.py` | 检测静止水印残留 |
| `check_clip.py` | 源素材 QA（构图/漂移/安全区/水印/真实帧率） |
| `make_reference.py` | 生成合规参考图（可指定底色） |
| `verify_dsh_config.py` | 校验配置：权重合计、引用文件是否存在 |
| `market_link.py` | 行情联动（外部脚本版，调试用） |
| `batch_user_keyed.py` | 批量处理用户自抠素材 |
| `patch_pet_*.py` | 四个补丁（见上表） |

---

## 行情联动

轮询 Hyperliquid 公开行情，按阈值驱动宠物（无需 API key）：

| 规则 | 动画 | 气泡 |
|---|---|---|
| 涨 ≥ +1.5% | `工作状态-雀跃庆祝` | `HYPE +1.92% 喵！冲` |
| 跌 ≤ −1.5% | `工作状态-垂头叹气冒汗` | `HYPE -2.15% …猫粮缩水` |

> ⚠️ **实际轮询间隔以代码为准**：宿主侧内嵌版为 **60 分钟**（`MARKET_POLL_MS`），
> 同事件冷却 60 分钟。阈值/币种在 `patch_pet_market.py` 顶部，或直接改 `lib/index.js`。

---

## 制作中的坑（都实测过，供后来者参考）

- **VP9 的 alpha 在独立平面**：`ffprobe` 常报 `yuv420p`；读 RGBA **必须** `-c:v libvpx-vp9`，
  否则 alpha 全读成 255 → 误判"没有透明通道"。判断有无 alpha 要**解帧实测**（四角应为 0）。
- **容器有 alpha ≠ 透明**：四角 alpha 是否为 0 才是判据，别靠播放器肉眼判断
  （VLC / Windows 播放器都不显示 alpha）。
- **品红溢色**：贴着 alpha 边界的像素色相落在 285–310° 即为污染。干净基线 ≈0–4%，
  出问题的素材 20–44%。修的时候**必须同时做透明侧颜色外渗**，否则 VP9 的 4:2:0
  色度下采样会把透明像素的品红平均回来。推荐 `--ring 5 --bleed 3`。
- **清角落残留要同时跑品红和绿色两个判据**：绿幕时代素材的水印残留是**绿色**（~135°）。
  但**不能全包盲清** —— 彩纸 / 问号光晕 / 青币发光边会被误删。逐条先 `--dry` 再落盘。
- **素材源头的蒙版质量决定上限**：抠像边缘毛糙是颜色规则救不了的，只能重导。
  导出前自检：四角 alpha 是否为 0、预览背景是否为干净棋盘格、角色周围有没有黑块/毛刺。
- **归一化按首末帧站立高度算缩放**：所以每条动作的**首末帧都必须回到标准站立**，
  否则切换动画时宠物会突然变大/变小。

---

## 许可与致谢

本仓库基于 [`PC2005-cloud/dsh-pet`](https://github.com/PC2005-cloud/dsh-pet)（**MIT**，v0.3.7）二次创作。

- 插件本体版权归 **PC2005-cloud** 所有，依 MIT 许可使用
- Hypurr 素材、工具链与补丁由 **Nepenthe-A1** 制作，同样以 **MIT** 发布

上游的版权声明与许可全文见 [`NOTICE.md`](NOTICE.md)。
再分发本仓库内容时，请一并保留这些声明。

**免责声明**：Hypurr 是 Hyperliquid 社区的形象，本项目是非官方粉丝创作，
与 Hyperliquid Labs 及 dsh-pet 作者均无隶属或背书关系。行情数据来自 Hyperliquid 公开接口，
仅供娱乐，**不构成任何投资建议**。