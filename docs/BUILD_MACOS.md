# 构建 Mac 基线

目标为 Apple Silicon、macOS 14+。这一版原生程序是本地 ad-hoc 签名；代码签名和系统权限不适合通过复制另一台电脑的登记来解决。

## 环境

- macOS Apple Silicon，Xcode Command Line Tools（含 swiftc、iconutil、codesign）。
- Python 3.11+，建议使用与锁文件验证环境一致的 Python 版本。原基线运行环境为 Python 3.14；二进制不是跨系统可用的 Python 虚拟环境。
- Opus 动态库；原构建通过 Homebrew 的 opus 获得。

安装 Python 依赖：

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r sync-suite/requirements-lock.txt
```

依赖文件原样保留自当前维护版本。其他 Python／系统组合可能需要新的依赖验证，不能把本机锁定结果当作所有版本的保证。

## 生成完整干净工具包

```sh
.venv/bin/python scripts/build_macos.py --output dist/小哈语音工具包
```

构建脚本生成隔离的原生 App、Python Runtime、剪贴板辅助程序、Opus 和组件，并打本地签名；不启动 App、不开麦、不访问真实剪贴板、不初始化识别身份、不复制本机 Data。必须指定尚不存在的输出文件夹，避免覆盖已有个人工具包。Opus 不在标准 Homebrew 路径时传入 `--opus /absolute/path/libopus.0.dylib`。

`mac-prototype/build.py` 是原生源文件的原始构建入口，原样保留；新增包装脚本负责完整工具包的相对目录构建，不改变原录音、粘贴或识别代码。

## 离线检查

```sh
PYTHONPATH=sync-suite:ime-channel-test .venv/bin/python -m pytest sync-suite/tests ime-channel-test/tests
python3 scripts/verify_snapshot.py
```

Python 回归仅用合成数据、假凭证和模拟网络，不打开真人麦克风或调用付费 API。新 Mac 上的真实权限、快捷键、录音、显示和目标输入框仍需逐项实测。

## 版本恢复

```sh
git switch --detach macos-v0.3.8-build12
```

需要原封不动的旧二进制时直接下载该标签的 Release 安装包并校验 SHA256。重新编译可能因编译器、路径、签名或依赖不同产生不同二进制哈希；源码指纹与构建结果指纹分开记录，不承诺可重复构建的字节一致性。
