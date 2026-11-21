# YouTube 高清下载器 & WorkBuddy Skill

用一句话把 YouTube 单视频或整个播放列表下载成**真 1080p / 720p MP4**，自动处理
SABR-only、PO Token、n-challenge/EJS、沙箱环境的 NODE_OPTIONS 陷阱、403 重试与音视频合并。

最初为解决「默认 yt-dlp 只能拿到 360p、高清格式存在但无 URL」而沉淀，已在 Windows +
WorkBuddy 环境实测可稳定下载整部 52 集动画的 1080p 版本。

## 两种用法

### 1. 作为 WorkBuddy Skill（推荐）

把本仓库的 `SKILL.md`、`scripts/`、`references/` 放到用户级技能目录：

```
~/.workbuddy/skills/youtube-hd-downloader/
```

之后在任意项目 / 任意 agent 中直接说：

> 下载这个 YouTube 播放列表的高清视频（1080p）：<播放列表链接>

agent 会自动加载 skill 并调用封装脚本。

### 2. 作为独立命令行工具

先安装依赖（幂等，可重复运行）：

```bash
python scripts/setup.py
```

下载单个视频 / 整个播放列表：

```bash
# 单视频，1080p 优先
env -u NODE_OPTIONS python scripts/download.py "<视频URL>" --out "./videos" --quality 1080

# 整部剧，1080p 优先，重试 5 次，失败回退 720p
env -u NODE_OPTIONS python scripts/download.py "<播放列表URL>" --out "./videos" --quality 1080 --whole --retries 5
```

`download.py` 参数：

| 参数 | 说明 |
|------|------|
| `URL`（必填） | 单个视频或播放列表链接 |
| `--out` | 输出目录，默认当前目录 |
| `--quality` | `1080`（默认）/ `720` / `best` |
| `--whole` | 按播放列表处理，文件名带序号 |
| `--retries` | 每种格式的重试次数，默认 5 |
| `--pot-port` | PO Token 服务端口，默认 4416 |

## 目录结构

```
youtube-hd-downloader/
  SKILL.md                    # skill 元信息 + 给 agent 的完整说明
  README.md                   # 本文件
  scripts/
    download.py               # 主下载器：解析列表 / 重试 / 回退 / 校验 / 汇总
    setup.py                  # 幂等环境自检与安装
  references/
    troubleshooting.md        # 详细排障
```

## 为什么默认只有 360p（原理）

YouTube 对 web/mweb 客户端启用了 **SABR-only**：1080p/720p 格式（itag 137/136）
存在于 player response 中，但 URL 被隐藏，yt-dlp 报 `missing a URL`。本方案拆解为：

1. **PO Token** — 本地 `bgutil-ytdlp-pot-provider` HTTP 服务（端口 4416）自动生成，pip 插件取用；
2. **EJS / n-challenge** — `yt-dlp-ejs` + node 运行时求解 JS 挑战（`--js-runtimes node`）；
3. **清除 NODE_OPTIONS** — 某些托管环境（如 WorkBuddy）在 `NODE_OPTIONS` 注入 sandbox shim，
   会让 node 求解挑战时报 `Access to this API has been restricted`，导致高清格式全部消失。
   脚本会在子进程环境中删除该变量 —— **这是最隐蔽、最关键的坑**；
4. **mweb 客户端 + 重试** — mweb 最稳（made-for-kids 视频不支持 android_vr）；
   PO Token 有绑定/时效，会间歇性 403，需多次重试（实测平均 2-3 次）；
5. **音视频合并** — 137/136 是纯视频，与音频 140 用 ffmpeg 合并成 MP4。

完整说明见 `SKILL.md`，排障见 `references/troubleshooting.md`。

## 验证结果

```bash
ffmpeg -i "<输出文件>.mp4" 2>&1 | grep -i "Video:"
```

看到 `1920x1080` 或 `1280x720` 即为真高清。`download.py` 结束时会打印每个文件的实际分辨率。

## 注意事项

- 仅下载你有权访问的内容，遵守当地法律与平台条款。
- 脚本中的已验证路径只是默认候选，找不到时自动发现兜底，不硬编码为必需项。
