# QuanLan Prompt Fragments

这里放所有可单独优化的提示词片段。运行时优先读取本目录文件；修改后重启程序即可生效。

主要文件：

- `chapter_title_translation.md`：章节名翻译。
- `book_title_translation.md`：书名翻译。
- `short_video_summary.md`：短视频总结。
- `next_chapter_local_context.md`：下一章本地 Markdown 摘录。
- `next_chapter_guidance.md`：下一章结尾预告事实校验。


- `script_generation.md`：脚本初稿主提示词。
- `voiceover_polish.md`：最终台词润色提示词，默认配合豆包 Ark 使用。
- `contract_opening_no_repeat.md`：开头钩子和正文去重规则。
- `contract_script_style_undergrad.md`：本科生水平、通俗自然、去 AI 味规则。
- `voiceover_polish_extra_rules.md`：最终润色附加规则。
- `pdf_local_only.md`：PDF 只允许本地解析的安全规则。
- `postprocess_requirements.json`：后处理参数。

注意：不要把 API Key 写进任何提示词文件。
