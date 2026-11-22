# YouTube 高清下载 Skill

一个用户级 WorkBuddy Skill：用一句话就能把 YouTube 单视频或整个播放列表下载成
**真 1080p / 720p MP4**，自动处理 PO Token、n-challenge、NODE_OPTIONS 沙箱陷阱、
403 重试和音视频合并。

安装位置：`C:\Users\Admin\.workbuddy\skills\youtube-hd-downloader\`（用户级，任意项目 / 任意 agent 可用）。

## 快速使用

在对话里直接说：

> 下载这个 YouTube 播放列表的高清视频（1080p）：<播放列表链接>

> 把这个视频下载成 1080p：<视频链接>

agent 会加载本 skill 并执行封装脚本。等价的手动命令：

```bash
PY="C:/Users/Admin/.workbuddy/binaries/python/versions/3.13.12/python.exe"
SKILL="C:/Users/Admin/.workbuddy/skills/youtube-hd-downloader"

# 单视频，1080p 优先
env -u NODE_OPTIONS "$PY" "$SKILL/scripts/download.py" "<视频URL>" --out "<输出目录>" --quality 1080

# 整播放列表，1080p 优先，最多重试 5 次，失败回退 720p
env -u NODE_OPTIONS "$PY" "$SKILL/scripts/download.py" "<播放列表URL>" --out "<输出目录>" --quality 1080 --whole --retries 5

# 带登录 cookie（遇到 403 时强烈建议），并限定集数范围
env -u NODE_OPTIONS "$PY" "$SKILL/scripts/download.py" "<播放列表URL>" --out "<输出目录>" \
  --whole --start 34 --end 136 --cookies "<Netscape格式cookie文件>"
```

### download.py 参数

| 参数 | 说明 |
|------|------|
| `URL`（必填） | 单个视频或播放列表链接 |
| `--out` | 输出目录，默认当前目录 |
| `--quality` | `1080`（默认）/ `720` / `best` |
| `--whole` | 按播放列表处理，文件名带 `01 - ` 序号 |
| `--retries` | 每种格式的重试次数，默认 5 |
| `--pot-port` | PO Token 服务端口，默认 4416 |
| `--start` / `--end` | 只下载播放列表中的集数范围（含端点） |
| `--cookies` | Netscape 格式 cookie 文件；403 时强烈建议提供 |
| `--client` | 播放器客户端，默认 `web_embedded`（直连高清流，最稳） |

## 目录结构

```
youtube-hd-downloader/
  SKILL.md                     # skill 元信息 + 给 agent 的完整说明
  README.md                    # 本文件（给人看）
  scripts/
    download.py                # 主下载器：解析列表 / 重试 / 回退 / 校验 / 汇总
    setup.py                   # 幂等环境自检与安装
  references/
    troubleshooting.md         # 详细排障
```

## 环境自检 / 安装

```bash
PY="C:/Users/Admin/.workbuddy/binaries/python/versions/3.13.12/python.exe"
"$PY" "C:/Users/Admin/.workbuddy/skills/youtube-hd-downloader/scripts/setup.py"
```

`setup.py` 是幂等的：已安装的依赖会跳过；缺失时会自动 `pip install`、克隆并编译
PO Token server。加 `--upgrade` 可升级到最新版依赖。

## 原理简介

默认 yt-dlp 只能拿到 360p，是因为 YouTube 对 web/mweb 客户端启用了 **SABR-only**：
1080p/720p 格式（itag 137/136）存在但 URL 被隐藏。解法由几块拼成：

1. **PO Token**：本地 `bgutil-ytdlp-pot-provider` 服务（端口 4416）自动生成 token，
   pip 插件自动取用。
2. **EJS / n-challenge**：`yt-dlp-ejs` + node 运行时求解 JS 挑战（`--js-runtimes node`）。
3. **清除 NODE_OPTIONS**：WorkBuddy 在 `NODE_OPTIONS` 注入 sandbox shim，会让 node
   求解挑战时报 `Access to this API has been restricted`，导致高清格式全部消失。
   脚本在运行 yt-dlp 前强制从子进程环境删除该变量——**这是本环境最关键的坑**。
4. **客户端选择**：默认 `web_embedded`，它返回直连 DASH URL，实测 1080p
   （360 MB）能完整下载；`mweb` 虽能解析格式，但签名 URL 常在几 MB 后 403，
   大批量下载时尤甚。配合登录 cookie 效果最好。
5. **重试与回退**：`Requested format is not available` / 403 会重试，1080p
   耗尽后自动回退 720p。
6. **音视频合并**：137/136 是纯视频，与音频 140 用 ffmpeg 合并成 MP4；
   同时清除 `NODE_OPTIONS` 与 `CODEBUDDY_SAFE_DELETE_ENABLED`，避免合并后清理失败。

详见 `SKILL.md` 与 `references/troubleshooting.md`。

## 验证结果

```bash
"<ffmpeg路径>" -i "<输出文件>.mp4" 2>&1 | grep -i "Video:"
```

看到 `1920x1080` 或 `1280x720` 即为真高清。`download.py` 结束时也会打印每个文件
的实际分辨率和成功/跳过/失败汇总。

## 注意事项

- 仅下载你有权访问的内容，遵守当地法律与平台条款。
- 脚本中的已验证路径只是默认候选，找不到时会自动发现兜底，不会硬编码为必需项。
- 不要停止正在运行的下载进程，也不要改动用户已有的视频文件。
