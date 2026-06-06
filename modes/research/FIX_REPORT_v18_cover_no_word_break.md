# v18 封面/首页字幕不拆词修复

- 封面/首页换行逻辑改为英文按完整单词折行，中文按自然字符折行。
- 英文单词、数字、连字符词作为不可拆单元，避免一个词被拆到两行或被 max_lines 截断。
- 英文章节名允许最多 3 行，并优先缩小字号来完整显示。
- 更新 `postprocess_requirements.json`，记录 `no_word_break` 与 `shrink_font_before_truncation` 规则。
