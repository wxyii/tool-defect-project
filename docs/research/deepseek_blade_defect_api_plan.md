# DeepSeek-V4.1-Flash 刀片缺陷识别验证方案

## 结论

DeepSeek-V4.1-Flash 通过 API 做刀片图像的零样本识别在技术上可行，适合先做小规模验证和人工复检辅助；在没有刀片级质检真值、没有稳定的像素级缺陷标注前，不建议直接替换当前监督模型或直接用于自动放行。

## 官方接口事实

- API 模型名使用 `deepseek-flash`，当前对应 DeepSeek-V4.1-Flash；不要把 `deepseek-v4.1-flash` 作为请求中的模型名。
- OpenAI 兼容接口为 `https://api.deepseek.com`，本地图片可使用 base64 data URL，也可先通过 Files API 上传后使用 `file_id`。
- 支持 JPEG、PNG、GIF、WebP。单张 base64/URL 图片上限为 32 MiB，单次内联请求体上限为 48 MiB；图片最多按每张约 1024 图像 token 计费，并会自动缩放。
- `detail=original`/`high` 保留原始图像处理方式，`low` 会缩放到 512×512。微小缺陷验证应优先比较 `original` 和 `high`，不能只用 `low`。
- 可设置 `response_format={"type":"json_object"}`，但提示词中仍必须明确要求输出 JSON，并设置合理的 `max_tokens`。
- JSON 输出保证 JSON 语法，不保证字段内容是真实的；代码仍须校验枚举值、缺陷列表、图像质量和完整性。

## 项目落地边界

当前项目已有原图定位、边界归一化、八分块推理和可视化链路，但目标边界归一化权重当前主要在服务器；DeepSeek 验证可以独立于 TensorFlow 先在本地进行。首期应新增独立的 DeepSeek 验证入口，不改写现有 `tool-defect predict`，避免混淆基线。

建议输入对比三种情况：

1. 原始显微图；
2. 自动定位后的刀片区域裁剪图；
3. 原图与刀片裁剪图一并发送。

如果原图外侧有图案，不能只依赖提示词要求模型忽略背景；应通过裁剪或遮罩验证背景是否影响结果。不要把极坐标展开图直接当作大模型的唯一输入，优先提供原始刀片图或几何校正后的刀片裁剪图。

## 推荐输出

不要只返回“是/否”。接口层应要求 JSON，至少包含：

```json
{
  "has_defect": "yes | no | uncertain",
  "image_quality": "usable | unclear",
  "defects": [
    {
      "type": "edge_damage | pit | crack | other",
      "location": "clock_position_or_sector_and_radial_zone",
      "evidence": "short description"
    }
  ],
  "certainty": "high | medium | low"
}
```

`uncertain`、`unclear` 或接口异常都必须进入人工复检，不能自动放行。模型给出的 certainty 不是经过校准的概率，不能直接当作现有算法的 `P(不合格)` 使用。

## 验证顺序

1. 用 5–10 张已知样例做 API 连通性和 JSON 解析测试。
2. 在同一批父图上分别测试原图、裁剪图和双图输入，固定提示词、模型名、图像 detail 和输出格式。
3. 使用现有 27 张验证父图调提示词和分流规则；使用共同的 34 张测试父图做最终对比，不用测试集反复改提示词。
4. 对每张图片至少重复调用 3 次，记录结果一致性、耗时、输入/输出 token 和失败率。
5. 与当前边界归一化整图、八分块模型比较：分类准确率、不合格召回率、不合格误放数量、人工复检率；缺陷位置另行按扇区或人工框进行评价。

## 建议的生产候选架构

第一阶段采用 DeepSeek 作为独立的第二意见或人工复检模型：

`原图 → 图像质量检查/自动定位 → DeepSeek 视觉判断 → JSON 校验 → 三段式决策`

- 明确识别为缺陷：进入不合格候选；
- 明确无缺陷、图像清晰、定位成功且与本地模型不冲突：进入合格候选；
- 不确定、定位失败、图像模糊、API 错误、两模型冲突：人工复检；
- 只有经过真实样本验证后，才把候选规则固化为自动放行/自动拦截。

## 数据与合规注意

显微图像会上传到 DeepSeek API。正式使用前必须确认设备图片、产品信息和项目数据是否允许外发，并确认组织对服务器所在地、保存周期和数据使用条款的接受程度。若不能接受，应优先采用本地模型或仅在脱敏样本上做验证。

## 官方资料

- [DeepSeek Vision](https://api-docs.deepseek.com/guides/vision/)
- [Chat Completions API](https://api-docs.deepseek.com/api/create-chat-completion/)
- [JSON Output](https://api-docs.deepseek.com/guides/json_mode/)
- [Models & Pricing](https://api-docs.deepseek.com/quick_start/pricing/)
- [Files API](https://api-docs.deepseek.com/guides/files_api/)
- [DeepSeek Privacy Policy](https://cdn.deepseek.com/policies/en-US/deepseek-privacy-policy.html)
