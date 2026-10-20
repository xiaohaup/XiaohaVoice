# 固定版本

此公开仓库以全新的Git历史导入两个平台的保留版源码，不复制原私有仓库的提交历史或个人资料。公开标签对应公开镜像提交；原私有提交、标签及附件保持原样。日期相同不代表Mac和Windows使用同一版本号。

源码运行逻辑与保留版一致；公开副本仅整理许可、说明、校验清单与必要的忽略规则。Release运行Windows安装包保持原字节，Mac公开副本仅清理开发路径及更新本地签名，SHA256如下。

## macOS · 0.3.8 / build 12

- 冻结日期：2026-10-21。
- 标签：`macos-v0.3.8-build12`。
- 保留分支：`codex/baseline-macos-0.3.8`。
- 对应当前安装的原生程序、运行组件和维护源码，不包含任何个人 Data。
- 干净安装包：公开下载文件名 `XiaohaVoice-0.3.8-macOS-arm64-build12-public.zip`。原私有基线包保留不变；公开副本仅将两个开发路径改为中性路径、更新本地签名和包内校验清单。
- 公开ZIP SHA256：`a40afd52a6ed7a2ccd07df7d7e9751731b84c7273266e3d5445c8ffe75ac5bcf`。原私有ZIP SHA256：`a34cce31fe93469d9b70505486a8fb1bf45c7492eab7b47befae80874f330386`。
- 原私有基线包含65个可与原安装对应的程序／组件／维护源码文件。公开副本已核对去除签名后的原生程序完全相同、识别组件与维护源码完全相同；Data仅空占位。
- 原私有基线程序与组件逐文件指纹：`versions/macos-0.3.8-build12/installed-manifest.json`；公开包装差异见同目录`public-package-verification.json`。

## Windows

- 冻结日期：2026-10-21；版本 **0.4.0-preview.1 / winfix6**，Windows x64。
- 标签：`windows-v0.4.0-preview.1-winfix6-20261021`。
- 保留分支：`codex/baseline-windows-20261021`。
- 原始源码来自已保留的Windows winfix6树；[使用与构建说明](https://github.com/xiaohaup/XiaohaVoice/blob/windows-v0.4.0-preview.1-winfix6-20261021/windows/README.md)。
- [安装包与源码附件](https://github.com/xiaohaup/XiaohaVoice/releases/tag/windows-v0.4.0-preview.1-winfix6-20261021)：
  - 运行工具包 `XiaohaVoice-0.4.0-preview.1-winfix6-baseline-20261021.zip`，289,973,286 字节，SHA256 `083c6978e5ea93651b1cc3a615c2491a11da77604b6c6777d54c0bd0a3c05d00`。
  - 源码包 `XiaohaVoice-Windows-source-v0.4.0-preview.1-winfix6-baseline-20261021.zip`，627,477 字节，SHA256 `950df03cd2e6b8e890ad5871000d1e37fba914eecc60e25769c0b8d48aaaf686`。
- 已核对 GitHub 附件 SHA256、分支与标签；本端下载源码包再算哈希相同，含嵌套归档共121文件，未发现个人 Data／身份／凭证／日志目录。
- Windows 执行端已核对当前安装的 EXE，源码运行逻辑未变；仅整理说明、依赖锁及源码包装。当前代码验证为76通过、1跳过，共同组件33通过；本人真实讲话与服务识别仍需后续实测。
- Windows 个人完整备份只留 Windows 本机，执行端已试还原校验；不作为 Release 附件。

## 后续开发规则

从选定基线创建新的 `codex/` 分支；新功能使用新版本号与新标签。不要移动或覆盖本页已有标签，不将个人 Data 加入源码提交或干净安装包。发布修复版也使用新标签。
