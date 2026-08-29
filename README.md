# Subtitle Extractor

从本地视频或音频中提取带时间轴的原文字幕。这个仓库只负责语音识别，不负责翻译。

当前提交提供可启动的 FastAPI 服务、统一字幕 JSON 契约和 mock ASR 后端。针对 AMD Radeon RX 7900 XTX 的 ROCm Whisper 后端将在下一阶段接入，外部 API 无需随模型实现变化。

## 接口边界

输入是本机媒体文件的绝对路径。输出是 subtitle-document/v1 JSON，其中每个片段都有 id、start、end、text。翻译服务直接接受这份 JSON，因此两个服务可分别部署和升级。

## 本地启动

    python3 -m venv .venv
    source .venv/bin/activate
    pip install -e '.[dev]'
    cp .env.example .env
    subtitle-extractor

服务默认监听 http://127.0.0.1:8011，API 文档位于 /docs。

## 示例

    curl -X POST http://127.0.0.1:8011/v1/transcriptions \
      -H 'Content-Type: application/json' \
      -d '{"media_path":"/absolute/path/demo.mp4","language":"auto"}'

现在的 mock 后端不会读取媒体内容，只用于先打通接口。正式后端会通过 AsrBackend 协议接入。

