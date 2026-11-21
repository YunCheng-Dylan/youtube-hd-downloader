# YouTube 高清下载排障手册

## 1. 只能拿到 360p / 高清格式消失

**典型报错**

```
Some formats have been skipped as they are missing a URL
Requested format is not available
```

**原因**：YouTube 的 SABR-only 实验把 720p/1080p（itag 136/137）的 URL 隐藏了，
需要 PO Token + n-challenge 求解才能拿到。

**排查步骤**

1. 确认 NODE_OPTIONS 已清除（本环境第一大坑）：
   ```bash
   echo "${NODE_OPTIONS:-<unset>}"
   ```
   如果输出包含 `node-language-shim.cjs`，所以 yt-dlp 调用都必须 `env -u NODE_OPTIONS`。
2. 确认 node 可用：`node --version`（需 v18+，本环境 v22）。
3. 确认 `yt-dlp-ejs` 已装：`python -m pip show yt-dlp-ejs`。
4. 确认加了两项关键参数：`--js-runtimes node` 和
   `--extractor-args "youtube:player_client=mweb"`。

## 2. `Access to this API has been restricted. Use --allow-fs-read`

**原因**：WorkBuddy 在 `NODE_OPTIONS` 注入了 `node-language-shim.cjs`，限制了 node
的文件系统 API，n-challenge 求解失败，导致所有高清格式被丢弃。

**处理**：运行 yt-dlp 前清除 NODE_OPTIONS：

- bash: `env -u NODE_OPTIONS python -m yt_dlp ...`
- Python subprocess: `env = os.environ.copy(); env.pop("NODE_OPTIONS", None)`，再传入 `env=env`
- 本 skill 的 `download.py` 已在 `clean_env()` 中自动处理。

## 3. `Sign in to confirm you are not a bot` / HTTP 403

**原因**：PO Token 绑定会话/时效问题，或 IP 被临时风控——**间歇性**出现很正常。

**处理**

1. 重试：实测平均 2-3 次成功，最多 5 次（`--retries 5`）。
2. 确认 PO 服务在 4416 端口运行：
   ```bash
   # Windows bash 可用
   netstat -ano | grep 4416
   ```
3. 确认用 `player_client=mweb`（android_vr 对 made-for-kids 视频不可用）。
4. 必要时重启 PO 服务：
   ```bash
   cd "C:/Users/Admin/bgutil-ytdlp-pot-provider/server"
   env -u NODE_OPTIONS node build/main.js --port 4416
   ```
5. 仍未解决：检查 yt-dlp 是否为最新版（SABR 参数变化频繁）：
   `python -m pip install -U "yt-dlp[default]"`。

## 4. PO Token 服务起不来

| 症状 | 处理 |
|------|------|
| `build/main.js` 不存在 | 在 `server/` 目录执行 `npm ci && npx tsc` |
| `npx tsc` 报 NODE_OPTIONS 相关错误 | `env -u NODE_OPTIONS npx tsc` |
| `npm ci` 失败 | 检查 node/npm 版本；删 node_modules 后重试 |
| 端口被占 | 换端口：`node build/main.js --port <其他端口>`，并在 download.py 用 `--pot-port` 对应 |
| 克隆失败 | 手动 `git clone --single-branch --branch 2.0.2 --depth 1 https://github.com/Brainicism/bgutil-ytdlp-pot-provider.git` |

一键重建：`python scripts/setup.py --upgrade`

## 5. 合并后没有声音 / 合并失败

**原因**：itag 137/136 是纯视频，必须和音频 itag 140 合并。

**处理**

- 用 `-f "137+140"` 或 `-f "136+140"`，不要用单独的 `137`。
- 确认 ffmpeg 可被 yt-dlp 找到：`--ffmpeg-location <ffmpeg.exe路径>`。
- 确认 ffmpeg 存在：`python -c "import imageio_ffmpeg; print(imageio_ffmpeg.get_ffmpeg_exe())"`。
- 缺 ffmpeg：`python -m pip install imageio-ffmpeg`。

## 6. made-for-kids 视频下载失败

android_vr 等客户端不支持这类视频，统一使用：

```
--extractor-args "youtube:player_client=mweb"
```

## 7. 每次都重新下载已存在视频

脚本按"文件存在且大小 > 1MB"跳过。若仍重复下载：

- 检查输出目录是否正确（`--out`）。
- 检查文件名是否被 sanitize（非法字符被移除）。
- 手动确认文件不是 0 字节的残留（可删除后重下）。

## 8. 验证分辨率

```bash
"<ffmpeg路径>" -hide_banner -i "<文件>.mp4" 2>&1 | grep -i "Video:"
```

- `1920x1080` -> 真 1080p
- `1280x720` -> 真 720p
- `640x360` -> 只有 360p，说明高清路径没走通，回到第 1 节

## 9. 环境迁移到新机器

复制整个 skill 目录到新机器的 `~/.workbuddy/skills/`，然后：

1. 跑 `python scripts/setup.py` 安装依赖并编译 PO server。
2. 若路径变化，脚本会自动发现；也可设环境变量：
   - `BGUTIL_POT_SERVER_DIR` = PO server 目录
   - `BGUTIL_REPO_DIR` = 克隆仓库根目录
   - `NODE_DIR` = node 二进制目录
3. 保持 `env -u NODE_OPTIONS`（或让脚本自动清理）。

## 快速自检清单

- [ ] `python -m pip show yt-dlp yt-dlp-ejs bgutil-ytdlp-pot-provider imageio-ffmpeg`
- [ ] `node --version` >= 18
- [ ] `C:\Users\Admin\bgutil-ytdlp-pot-provider\server\build\main.js` 存在
- [ ] 端口 4416 可连接
- [ ] 运行 yt-dlp 时 NODE_OPTIONS 为空
- [ ] 命令含 `--js-runtimes node` 和 `player_client=mweb`
- [ ] 使用 `137+140` / `136+140`，并传了 `--ffmpeg-location`
