# 配置说明

本目录用于把“可调参数”从程序中解耦出来。

- `文案风格配置.json`：控制分集开头、结尾、关注语、摘要长度等文案风格。
- `后处理风格覆盖.json`：覆盖 `prompts/05_后处理规范.json` 中的排版、字体、颜色、装饰开关。
- `运行开关.json`：控制是否启用配置覆盖、是否启用高保真装饰等开关。

优先级：程序默认值 < `prompts/05_后处理规范.json` < `config/后处理风格覆盖.json`。

后续要换文案风格、换封面风格、改品牌信息，优先改这里和 `prompts/`，不需要改 Python 程序。

## 后处理渲染引擎

现在支持两种后处理渲染方式：

- `playwright_html`：推荐。适合做更强视觉冲击的短视频封面。
- `pillow`：兼容旧版，作为兜底回退方案。

你可以在 `config/运行开关.json` 中修改：

```json
{
  "postprocess": {
    "render_engine": "playwright_html"
  }
}
```

如果你要临时回退旧版渲染，改成：

```json
{
  "postprocess": {
    "render_engine": "pillow"
  }
}
```

