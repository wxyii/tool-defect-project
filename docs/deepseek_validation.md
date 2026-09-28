# DeepSeek 刀片缺陷识别验证

本功能是独立验证入口，不会改变现有 `tool-defect predict` 的 TensorFlow 推理逻辑。

## 本地运行

先安装依赖并设置环境变量。真实密钥不要写入代码、配置、命令行参数、日志或 Git：

```powershell
\.venv\Scripts\python.exe -m pip install -r requirements-deepseek.txt
$env:DEEPSEEK_API_KEY = "新生成的密钥"
```

调用批量脚本：

```powershell
\.venv\Scripts\python.exe tools/run_deepseek_comparison.py `
  --input "图片目录" `
  --output outputs/deepseek_validation `
  --baseline-predictions "现有算法父图 predictions.csv" `
  --detail original `
  --thinking disabled
```

结果包括：

- `deepseek_predictions.csv`：逐图结构化结果和候选分流；
- `deepseek_raw.jsonl`：逐图原始 JSON 响应和耗时；
- `summary.json`：请求成功率、候选分流、标签指标和与现有算法的冲突数；
- `REPORT.md`：简要报告。

重复使用同一个输出目录不会覆盖历史结果。每次运行会自动生成唯一 `run_id`：

- `deepseek_predictions.csv` 追加本次每张图片一行，并记录运行编号、时间、模型、响应编号和真值标签；
- `deepseek_raw.jsonl` 追加本次每张图片的原始 JSON；
- `summary.json` 累计保存运行次数、图片数、成功/失败数、候选分流和每次运行记录；
- `REPORT.md` 追加本次运行报告和累计统计。

同一个输出目录不建议让多个并发进程同时写入；连续运行或串行运行是安全的。

如果有质检标签，可额外传入 `--labels-csv`。CSV 至少包含 `image_path,label`，标签支持 `qualified/unqualified`、`合格/不合格` 或 `0/1`。

现有算法应先用原有入口生成父图级 `predictions.csv`，再通过 `--baseline-predictions` 传入。八分块必须传入已经聚合到父图的结果，不能把子图 CSV 当作基线。

## 服务器运行

服务器环境中同样只设置会话级环境变量，建议使用权限受控的密钥管理系统注入，不要写入项目目录：

```bash
export DEEPSEEK_API_KEY='新生成的密钥'
source .venv/bin/activate
python tools/run_deepseek_comparison.py \
  --input /path/to/images \
  --output outputs/deepseek_validation \
  --baseline-predictions /path/to/parent_predictions.csv
```

生产部署时，建议由 systemd、容器编排平台或公司密钥服务注入 `DEEPSEEK_API_KEY`，并限制读取权限、定期轮换、避免把密钥放入进程参数和备份日志。若设备图片不允许外发，应使用公司内网模型或本地模型，不调用公网 API。训练服务器的 TensorFlow 环境不要安装这个依赖，单独创建 DeepSeek 环境。

## 公司服务器已部署模型

可以复用本项目的客户端，前提是服务器提供 OpenAI 兼容的 Chat Completions 接口，并且支持视觉输入。把 `--base-url` 改为公司网关地址，`--model` 改为服务注册的模型名；如果内部网关不校验密钥，可在客户端使用网关要求的占位令牌，但仍建议由网关统一鉴权：

```bash
export DEEPSEEK_API_KEY='由公司网关分配的令牌'
python tools/run_deepseek_comparison.py \
  --base-url 'http://公司模型服务地址/v1' \
  --model '公司服务中的模型名' \
  --input /path/to/images \
  --output outputs/deepseek_internal_validation
```

如果内部服务不是 OpenAI 兼容协议，则只需替换 `src/tool_defect/deepseek/client.py` 中的请求适配层，批量、JSON 校验和结果对比逻辑可以继续复用。上线前还需要确认内部服务的图片留存、权限、审计和并发限制。
