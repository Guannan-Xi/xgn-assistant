# 很有脑子的小猪理

这是一个独立合并工程，源目录不被修改：

- `D:\Quanlan\Codes\Python\视频号\科研进展小猪理`
- `D:\Quanlan\Codes\Python\著作解读`

## 统一工作台

双击 `run_windows.bat` 会打开“很有脑子的小猪理”的融合 UI。左侧切换模式，右侧只展示当前模式需要的功能：

- 科研助手：每日研究速递、检索天数、文章数量、期刊、图片 API 跳过、邮件发送。
- 文史小秘：书籍 PDF、输出目录、续跑目录、起始阶段、复用开关、生图/后处理/拆分素材开关、绘图测试。

`run_research_gui.bat` 和 `run_culture_gui.bat` 也会打开同一个融合 UI，只是预选对应模式。

## CLI

```bat
python AutoMediaProducer.py --mode research --cli -- --daily-research-digest
python AutoMediaProducer.py --mode culture --cli -- --book "D:\path\book.pdf"
```

## 图片测试

文史小秘里的绘图测试仍走 `images.generate`，模型默认 `gpt-image-2`，尺寸 `720x1280`。测试调用使用 `timeout=240` 和 `max_retries=0`，避免 30 秒超时加 SDK 自动重试造成误判。

## 目录结构

- `quanlan_dual_assistant/`：统一 UI、模式切换、运行分发、日志汇总。
- `modes/research/`：科研助手运行内核。
- `modes/culture/`：文史小秘运行内核。
- `tools/python_cmd.bat`：优先选择本机可用 Python，避开 Windows Store 占位程序。
