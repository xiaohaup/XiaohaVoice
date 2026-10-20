# 第三方组件与来源

本公开副本的自有源码采用根目录MIT许可。第三方组件保留原许可，Qt补充原文和对应源码入口见 ../LICENSES/Qt/README.md。

- Qt for Python / PySide6 6.12.0：原生窗口、音频、托盘与 WebEngine。遵循其 LGPLv3/GPLv3/商业授权选项；本构建使用官方社区分发，保持独立动态库与通知，不修改 Qt。成品中原始许可证随依赖元数据收集，使用者可以替换相应动态库。参阅 [官方授权说明](https://doc.qt.io/qtforpython-6/licenses.html)。
- PyInstaller 6.22.3：构建工具；GPLv2 带分发应用的例外。参阅 [官方许可证](https://pyinstaller.org/en/stable/license.html)。
- Opus 1.6.1：从 conda-forge 的 Windows x64 包取出单一 DLL；包 SHA-256 固定在 dependencies.lock.json。BSD 许可证原文 `COPYING` 随成品保存为 `LICENSES/Opus-COPYING.txt`。[来源](https://anaconda.org/conda-forge/libopus)。
- ASR 兼容协议参考代码的 MIT 许可证：保留于 `Components/engine/UPSTREAM-LICENSE-MIT.txt`。沿用原有引用，不代表服务方授权或稳定性承诺。
- FastAPI、Uvicorn、HTTPX、Requests、Websockets、Cryptography、Keyring、Jieba 等：版本在 requirements-windows.txt；成品收集构建环境各分发包的许可证和依赖清单。API 密钥由 Keyring 的 Windows 后端保存。

打包不附带用户录音、转写历史、凭证和其他应用的安装包。不代表识别服务已经正式开放第三方接入。
