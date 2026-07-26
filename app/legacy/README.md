# 旧 PyQt 平台

本目录保留学校提供的界面源码、UI、资源和原始 EXE。正式复现入口是项目根目录的命令行工具。

- `A_chedaoyuce0.py`：平台主逻辑。
- `A_app0.py` / `A_app0.ui`：界面代码和 Qt Designer 文件。
- `daojulogo.py` / `daojulogo.qrc`：Qt 资源。
- `A_chedaoyuce0.exe`：学校提供的历史构建产物，不作为当前环境的受支持入口。

平台运行时通过文件对话框选择模型 JSON/H5。集中模型位于项目根目录的 `artifacts`。
