# 全澜脑科学 AutoMedia Producer｜科学经典单任务精简版

本版本已锁定为“科学经典解读”：单任务队列运行，只生成科学经典解读脚本与分镜，不再提供其它内容风格入口。

关键约束：
- 章节介绍前必须先有生活化科学钩子疑问，第 2 句过渡到本章科学问题，第 3 句为 A2 首页章节提要。
- 台词开头书名使用中文简名；作者使用第一作者简名，合著书为“XXX 等人合著”。
- 固定生成 A1 微信封面 3:4、A2 微信首页 9:16、A01 B站封面 4:3、A02 B站首页 16:9。
- A1/A2/A01/A02 复用同一张整章内容总结无字背景，公共文字与 full_canvas 全屏蒙版由后处理统一叠加。

# QuanLan AutoMediaProducer - integrated postprocess spec v2026.05.23

本包是两个上传版本的完整集成版：保留主功能链路，并补齐/同步后处理规范。

## 集成口径

- 运行入口只加载 `quanlan_automedia/source_modules/`，不再保留旧 `source_parts` / `backup` 兜底。
- `AutoMediaProducer.py` 是轻量启动器；Windows 双击和 `python -m quanlan_automedia` 都走同一套模块化加载逻辑。
- 保留主功能链路：PDF 目录提取、章节切分、本地逐章解析、脚本/LRC、配图、图片后处理、提示词配置和章节完成后压缩/邮件发送。

## 运行

```bash
pip install -r requirements.txt
python AutoMediaProducer.py
```

Windows 可双击：

```text
run_windows.bat
```

## Key 放置位置

Key 文件放在项目根目录，与 `AutoMediaProducer.py` 同级：

```text
openai_api_key.txt
gemini_api_key.txt
xai_api_key.txt
chatshare_api_key.txt
deepseek_api_key.txt
```

## 模型调用方案

- 国外文本/生图模型默认通过 OpenAI-compatible 中转站访问：`https://greatwalllink.top/v1`。可用环境变量 `NEWAPI_BASE_URL` 或 `FOREIGN_MODEL_BASE_URL` 覆盖。
- 台词润色/全文终审默认使用 DeepSeek 官方接口：`https://api.deepseek.com`。可用环境变量 `DEEPSEEK_BASE_URL` 覆盖。
- 默认方案：脚本初稿 `GPT-5.5`，全文终审 `DeepSeek Chat（官方润色）`，配图 `GPT Image 2`。

## 每日研究速递

新增“每日研究速递”短视频素材生成：

- 自动从 PubMed / NCBI E-utilities 检索神经科学顶刊最新论文摘要。
- 默认期刊包括 `Nature Neuroscience`、`Neuron`、`Nature`、`Science`、`Cell`、`Brain`、`Journal of Neuroscience` 等。
- DeepSeek 官方生成中文栏目口播、目录和每篇论文的研究问题、核心发现、意义说明；表达易懂但保持科研严谨。
- GPT Image 2 / image2 生成无字 Cell 风格文献图片摘要。
- 本地输出卡片播放式素材：首页、目录页、每篇论文卡、全澜品牌页、口播台词、LRC、文献信息 JSON、图片提示词。

GUI：左侧“工具”区点击 `每日速递`。

CLI 示例：

```bash
python AutoMediaProducer.py --daily-research-digest
python AutoMediaProducer.py --daily-research-digest --daily-days 30 --daily-max-articles 5
python AutoMediaProducer.py --daily-research-digest --daily-skip-image-api
```

可选环境变量：

```text
NCBI_EMAIL=your_email@example.com
NCBI_API_KEY=your_ncbi_api_key
```

默认输出：

```text
chapter_pdf_direct_output/每日研究速递/YYYY-MM-DD/
  00_文献信息.json
  01_栏目素材.json
  02_口播台词.txt
  03_口播分页.lrc
  04_图片摘要提示词.txt
  cards/
  visual_summaries/
```

## 本地 PDF 逐章解析

- 默认流程：先按目录切出章节 PDF，再用 PyMuPDF4LLM 本地解析该章节为 Markdown，保存为 `parsed_content.md`，脚本生成直接使用该 Markdown。
- 不再解析整本书，也不在本地解析成功时上传章节 PDF 附件。
- 如果 PyMuPDF4LLM 未安装或解析失败，会回退 pypdf；仍无文本时才回退旧 PDF 附件直传。
- 安装依赖：`pip install pymupdf4llm pymupdf`，或直接运行 `pip install -r requirements.txt`。

## 后处理已集成的关键点

- A1 封面、A2 首页、C 结尾页：AI 只生成无文字背景图，文字、品牌、遮罩、字号、位置由 Pillow 后处理确定性渲染。
- A1/A2/C 使用 `GLOBAL SCRIPT THEME / 全章主题锚点` 生成整章主题图，不再使用泛泛神经元/DNA 装饰背景。
- B 系列内容页：按对应台词生成，最终绘图提示词带 `PAIRED VOICEOVER / 文案语义锁`，避免图像和文案脱节。
- 配图完成或断点续跑后，对图片目录执行幂等后处理；已存在图片也会从 `_raw/` 原图重新盖章，避免重复叠加。
- 内容页统一裁切画幅、柔和蒙版、英文品牌、底部字幕参考线。

## 重新合并单文件

```bash
python tools/rebuild_single_file.py
```

会生成：

```text
AutoMediaProducer_rebuilt.py
```

## 本轮后处理规范同步

- `quanlan_default_prompt_templates.json` 已写入完整 `postprocess_requirements`。
- `postprocess_requirements_integrated.json` 是同一规范的独立副本，便于核对。
- 源码内置 `DEFAULT_POSTPROCESS_REQUIREMENTS` 和 `POSTPROCESS_STABLE_SPEC` 已同步，删除外部默认模板时也不会丢失本轮规范。

## 2026-05-25 新增：章节完成后邮件发送

- 左侧顶部现在先显示“提示词风格”，风格选择和“提示词与后处理”入口都在最上方。
- 每个任务页面都有独立的“完成后邮件”设置：可保存本任务页的收件邮箱，并在每章完成后把该章节目录完整压缩为 ZIP。
- ZIP 默认保存到输出目录下的 `99_章节压缩包/`。
- 如需自动发送附件，请填写项目根目录下的 `quanlan_email_settings.json`，或设置环境变量：`QUANLAN_SMTP_HOST`、`QUANLAN_SMTP_PORT`、`QUANLAN_SMTP_USER`、`QUANLAN_SMTP_PASSWORD`、`QUANLAN_SMTP_FROM`、`QUANLAN_SMTP_SSL`、`QUANLAN_SMTP_TLS`。
- 如果 SMTP 未配置，程序不会中断任务；会保留本地 ZIP 并在日志中提示未发送原因。


## PNG Logo Postprocess Contract

当前工程的后处理品牌 logo 已升级为 PNG-only：

- 英文 `QuanLan BrainScience®` 使用 `assets/logos/en/logo_en_tight.png`
- 中文 `全澜脑科学®` 使用 `assets/logos/zh/logo_zh_tight.png`
- 封面、首页、内容页和科学结尾页均通过图片缩放与坐标放置实现 logo
- 不再通过字体、字符排版、字距或文本绘制来重建这两个 logo
- 自检脚本：`python tools/validate_png_logo_postprocess.py`

## 精简优化版说明

本包已删除历史备份、旧分片兜底、开发工具、示例输出、变更日志和本地 Key 文件；运行时只加载 `quanlan_automedia/source_modules/`。详细见 `OPTIMIZATION_REPORT.md`。

### v4：A系列/C图全章视觉摘要锁

A1/A2/A01/A02 和 C 图现在会先生成本地 `0_全章视觉摘要_A系列C图依据.txt`，并把该摘要注入最终绘图提示词。A 系列只生成一张全章总结 Master Background，其他平台图裁切复用；C 图必须回扣本章主线并保守承接下一章，禁止泛化医学背景或空品牌氛围图。
