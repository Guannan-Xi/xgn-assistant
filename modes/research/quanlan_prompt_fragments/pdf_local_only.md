【PDF 本地解析安全规则】
- PDF 文件只允许在本机用 PyMuPDF4LLM / pypdf 解析。
- 任何文本模型，包括豆包、OpenAI、Gemini、Grok、ChatShare，都只能接收本地解析后的文本或 Markdown。
- 如果本地解析失败，停止对应文本生成，不上传 PDF，不让模型猜测原文内容。
