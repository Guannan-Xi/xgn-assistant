# 固定 LOGO 使用说明

已将用户提供的“知识慢炖”LOGO 固定写入工程：

```text
automedia_core/assets/knowledge_slow_stew_logo.png
```

规则：

1. C 片尾页必须使用这个固定 PNG，不再使用程序临时绘制的假 logo。
2. C 片尾页品牌区只展示固定 logo 和 slogan，避免重复出现多个“知识慢炖”。
3. 如果该 logo 文件缺失，Playwright 后处理会直接报错，避免静默生成错误品牌图。
4. A 系列图仍按用户要求只保留：书名、作者、章节序号、章节名称、集数、本集小标题，不加 logo。
5. 生图提示词继续要求 AI 不生成任何 logo、文字、水印；品牌 logo 只在后处理阶段由程序统一叠加。

当前固定 slogan：

```text
让经典不再高冷，让智慧人人可用
```
