# 最终文件清单与迁移记录

## 数据

| 内容 | 数量 | 最终位置 | 来源 | 校验 |
|---|---:|---|---|---|
| 合格图像 | 98 | `data/images/qualified` | `yuan/Qualified` | 98/98 SHA-256 一致 |
| 不合格图像 | 82 | `data/images/unqualified` | `yuan/Unqualified` | 82/82 SHA-256 一致 |
| 合格掩码 | 98 | `data/masks/qualified` | `chedao/mask0/qualifiled` | 98/98 SHA-256 一致 |
| 不合格掩码 | 82 | `data/masks/unqualified` | `chedao/mask0/unqualified` | 82/82 SHA-256 一致 |
| Labelme JSON | 82 | `data/annotations/labelme_json` | `chedao/labelme_json` | 82/82 SHA-256 一致 |
| 数据清单 | 180 行 | `data/manifests/dataset.csv` | 整理后生成 | 115 训练、29 验证、36 测试 |

清单按类别分别以固定随机种子 1 做分层划分：先保留20%测试集，再从剩余数据中取20%作为验证集，最终为115/29/36。合格与不合格图像存在同名文件，因此 `sample_id` 包含类别；只有不合格样本允许绑定 JSON，避免跨类别标注泄漏。合格掩码原有双扩展名被保留，配对逻辑兼容 `a.png.png`、`a.jpg.png` 和同 stem 的 `.png`。

## 权重

| 最终文件 | SHA-256 |
|---|---|
| `artifacts/classification/model.json` | `350CCFAA431067A2023E2086310432B872FD6B5384AA722DABF3652C9574BEFA` |
| `artifacts/classification/weights.h5` | `2887AA69ABEAB8CFCD1A16E167D32A2AC06DBFBCB087D2A828AFB5C9ECA35E76` |
| `artifacts/multitask/model.json` | `377A1CECE0DC45BD15407356EC2B624AC25072A9A91DDEBAEC5C51A508005F50` |
| `artifacts/multitask/weights.h5` | `63DE0DFBB93F3B64264E774C73109D50D110DEFEB9A63DA411DA00425890AD63` |

软件目录中的四个同名 JSON/H5 与上述文件完全重复，因此没有再次保留。

## 保留的三份模型和组件

| 文件 | 用途 | 原始依据 |
|---|---|---|
| `models/classifier.py` | 分类重新训练 | `chedao/fenlei/yuanxingchedao_xcbam.py` |
| `models/multitask.py` | 默认分类—分割重新训练 | `chedao/fenge/yuanxingchedao_cs.py`、学校说明文档 |
| `models/multitask_agsfpn_reference.py` | AG+FPN 参考 | `分割/yuanxingchedao_cs_agsfpn-loss.py` |
| `models/xception.py` | 自定义 Xception 骨干 | `chedao/fenge/Xception_0.py` |
| `models/cbam.py` | CBAM 组件 | `yuanxingchedao_cbam.py` 的重复副本 |
| `models/attention_gate.py` | AG+FPN 唯一实际使用的注意力门 | `yuanxingchedao_attentiongate.py` |
| `models/generator.py` | 同步图像/掩码增强 | `yuanxingchedao_generator.py` |

已删除未使用的 `attention`、自定义 focal/dice/mixed loss、SA、外部 mIoU 等缺失模块导入。`attentiongate_gai.py` 和 `attentiongate_gai0.py` 未被最终模型调用，没有保留。

## 文档和平台

- 5 份根目录文档原样迁移到 `docs/reference`，逐文件 SHA-256 一致。
- PyQt 源码、UI、资源、账户文件和原始 EXE 保留在 `app/legacy`。
- 平台主源码改为相对自身定位账户文件、项目数据和中央 `artifacts`；`daojulogo` 副作用导入保留。
- 原始 EXE 仅作历史产物，不是正式复现入口。

## 删除的冗余内容

- `分割` 中的 FCN、PSPNet、UNet++、DeepLab、FPN、AGS、MobileNetV2、ResNet50 和 AttentionGate 改进消融版本。
- `分类` 中的 `d1`、`d2` 和重复的 XCBAM/CBAM 文件。
- `chedao`、`软件` 中迁移后重复的数据、代码和权重副本。
- `yuan` 中迁移后重复的原始图像副本。
- Python 缓存、失败安装遗留的 `UNKNOWN.egg-info` 和临时测试日志。

压缩包始终留在资料根目录，未移动、未改名、未删除。

## 压缩包基准 SHA-256

| 文件 | SHA-256 |
|---|---|
| `chedao.zip` | `CEFFB240610B2A9112CDB48F7B176D15F3C724BF06B41D3D9B98AC4D18B8FBEF` |
| `yuan.rar` | `D16D7E8D20579309EBEF7886C2C788F967A9C7188E8377FF84162984806828E3` |
| `分割.rar` | `E77E50135802E7309D26A4869C2070EE960B797199E4498C342C2BED86BEE3FE` |
| `分类.rar` | `43963D0D854E9D9D9DE502EE79852BBEAE5CE70C9A72A73FC69BAA10E3898AD2` |
| `软件.rar` | `08FE3FC1C0370C36873B768247A02B8EF44BD8511229F9225BACFD7CCC54EF12` |
