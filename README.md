# Subtitle Extractor

从本地视频或音频中提取带时间轴的原文字幕。这个仓库只负责语音识别，不负责翻译。

默认使用本地 `whisper-large-v3`、Transformers FP16 和 ROCm GPU。程序启动时递归扫描媒体目录一次，过滤已经成功提取且输入与配置均未变化的视频，处理完后退出。FastAPI 作为可选的单文件调用方式保留。

## 接口边界

输入是本机媒体文件的绝对路径。输出是 subtitle-document/v1 JSON，其中每个片段都有 id、start、end、text。翻译服务直接接受这份 JSON，因此两个服务可分别部署和升级。

## 安装

    python3 -m venv .venv
    source .venv/bin/activate
    # 先安装与你的 ROCm 版本匹配的 PyTorch
    pip install -e '.[asr,dev]'
    cp .env.example .env

项目不会声明通用 PyTorch 依赖，以免覆盖已经配置好的 ROCm 构建。运行前确认 `torch.cuda.is_available()` 为 `True`，并确保系统能够执行 `ffmpeg`。

## 使用方法

1. 将视频放入 `/home/simon/modeling-video` 或其任意层级的子目录。默认支持 `.mp4`、`.mkv`、`.mov`、`.webm`、`.m4v` 和 `.avi`。
2. 在 WSL 中启动项目环境并运行任务：

   ```bash
   cd ~/ai/subtitle-translator/subtitle-extractor
   source .venv/bin/activate
   subtitle-extractor
   ```

   也可以使用 `python -m subtitle_extractor` 或显式执行 `subtitle-extractor scan`。

3. 程序递归扫描一次、顺序处理待提取视频，然后自动退出。运行汇总示例：

   ```json
   {
     "status": "complete",
     "discovered": 10,
     "completed": 3,
     "skipped": 7,
     "failed": 0,
     "busy": 0,
     "deferred": 0
   }
   ```

原文字幕和状态保存在 `/home/simon/subtitle-output/jobs/<分片>/<job_id>/`：

```text
extract.state.json
source.subtitle.json
```

提取端不会修改视频或向媒体目录写字幕。最终同名中文字幕 SRT 由翻译端生成。重复运行时，文件大小、修改时间和处理配置均未变化的成功任务会自动跳过。

`failed` 大于零时退出码为 1；修复问题后重新运行即可按状态重试。`deferred` 表示文件修改时间不足默认的 60 秒稳定期，等待后重新启动。扫描本身无法启动时退出码为 2。查看详细日志：

```bash
subtitle-extractor --log-level DEBUG
```

## 配置

首次使用可执行 `cp .env.example .env`，再修改 `.env`。常用配置如下：

```env
SUBTITLE_EXTRACTOR_INPUT_DIR=/home/simon/modeling-video
SUBTITLE_EXTRACTOR_DATA_DIR=/home/simon/subtitle-output
SUBTITLE_EXTRACTOR_MODEL=/home/simon/models/whisper-large-v3
SUBTITLE_EXTRACTOR_LANGUAGE=english
SUBTITLE_EXTRACTOR_FILE_SETTLE_SECONDS=60
```

修改模型、语言、分段方式等输出相关配置后，已有视频会重新提取。仅改变日志级别不会使任务失效。

## 可选 API

    subtitle-extractor api

服务默认监听 http://127.0.0.1:8011，API 文档位于 `/docs`。API 只允许读取 `SUBTITLE_EXTRACTOR_INPUT_DIR` 内的文件。

## 示例

    curl -X POST http://127.0.0.1:8011/v1/transcriptions \
      -H 'Content-Type: application/json' \
      -d '{"media_path":"/absolute/path/demo.mp4","language":"auto"}'

测试时可设置 `SUBTITLE_EXTRACTOR_BACKEND=mock`，无需加载模型或占用 GPU。
