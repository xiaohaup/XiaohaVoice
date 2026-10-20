<p align="center"><img src=".github/assets/cover.svg" alt="小哈语音 Xiaoha Voice" width="780"></p>

<p align="center">按一下说话，再按一下，把话留在光标处。</p>
<p align="center">
<a href="LICENSE"><img alt="MIT" src="https://img.shields.io/badge/license-MIT-80694e"></a>
<img alt="macOS Apple Silicon" src="https://img.shields.io/badge/macOS-Apple_Silicon-d9cfbd">
<img alt="Windows x64" src="https://img.shields.io/badge/Windows-x64-dce5ed">
<img alt="Chinese" src="https://img.shields.io/badge/language-简体中文-e2e8dd">
</p>

<p align="center"><a href="#下载体验">下载体验</a> · <a href="#这一版能做什么">功能</a> · <a href="docs/GETTING_STARTED.md">首次使用</a> · <a href="docs/FAQ.md">常见问题</a> · <a href="CONTRIBUTING.md">参与贡献</a></p>

**小哈语音（Xiaoha Voice）** 是一个轻量桌面语音输入工具。一次按键开始，实时看到转写，再按同一个键结束，结果自动送到当前输入框；期间正常使用鼠标、切换窗口也不会结束录音。

面向想保留简单语音输入、词库纠正和本机历史的人。当前为体验版；不把自动检查通过当成所有电脑、网络和输入框都已兼容。

## 下载体验

| 平台 | 基础功能保留版 | 下载 |
| --- | --- | --- |
| macOS | **0.3.8 · build 12** · Apple Silicon，macOS 14+ | [完整工具包](https://github.com/xiaohaup/XiaohaVoice/releases/tag/macos-v0.3.8-build12) |
| Windows | **0.4.0-preview.1 · winfix6** · Windows x64，已在Windows 11构建检查 | [完整工具包](https://github.com/xiaohaup/XiaohaVoice/releases/tag/windows-v0.4.0-preview.1-winfix6-20261021) |

- 下载Release里的完整ZIP；GitHub自动生成的Source code压缩包是源码，需要自行构建。
- **完整解压，保留整个工具包文件夹**，双击其中的App或EXE。Runtime、Components和Data也是程序的一部分，不要只复制启动图标。
- 先按[首次使用](docs/GETTING_STARTED.md)配置自己的识别通道和系统权限。干净安装包不带作者账号、历史、录音、API密钥或识别身份。
- Mac当前为本地签名，尚未完成Developer ID签名／公证；Windows为未签名体验包。系统可能要求额外确认；请先核对同页SHA256。Intel Mac、Linux暂未验证。
- Windows录音通道的本人真实讲话和服务识别仍需实测，构建、模拟测试与界面检查不替代这一步。请使用短测试句验证后再日常使用。

## 这一版能做什么

| 能力 | 使用方式 |
| --- | --- |
| 流式语音输入 | 同键启停、实时文字、Esc取消；快捷键与鼠标侧键可配置 |
| 自动粘贴或只复制 | 粘贴到当前输入框，不按回车发送；可保留新转写或恢复原剪贴板 |
| 本机历史与统计 | 搜索、日历、导出、字数／时长／次数、活动图、应用与关键词排行 |
| 词库纠正 | 按明确规则在本地纠正，例如Cloud → Claude；编辑草稿自动保存 |
| 两种识别通道 | 输入法兼容通道、火山引擎API；配置与测试结果分别保留 |
| 日常使用 | 菜单栏／托盘待命、开机自启、静默启动、主题与浮窗独立配色 |
| 资料保护 | 完整工具包备份、保留原资料的恢复、闪电说历史显式导入、待恢复录音管理 |
| 网络与排错 | 本工具代理设置、可关闭的运行元数据日志 |

本地界面、统计与备份不需要登录云账号。Windows各项限制以[Windows说明](https://github.com/xiaohaup/XiaohaVoice/blob/windows-v0.4.0-preview.1-winfix6-20261021/windows/README.md)为准。

## 识别通道说明

**豆包输入法兼容通道**参考开源MIT项目[missuo/koe](https://github.com/missuo/koe)，独立连接语音服务；无需安装官方输入法，也不使用豆包网页／桌面账号。新设备须在设置中明确初始化自己的身份，再测试。

这条通道是兼容协议，没有官方开放API的稳定性承诺，不保证永久免费或无限用。遇到认证拒绝会停止，不循环注册或轮换身份。项目并非豆包或火山引擎官方产品。

**火山引擎正式API**使用自己的服务账号与API凭证，按自己的服务条款和额度使用。设置页提供开通、创建凭证、接口说明入口及手动测试；API密钥保存在操作系统安全存储。识别测速使用内置合成短句，可能消耗自己的服务额度。

## 数据留在哪里

历史全文、词库、设置和待恢复音频保存在自己的工具包Data；成功录音只保留文字及统计字段。运行日志不记录口述全文或凭证。自己的完整备份含个人资料，**不要贴到公开Issue或作为分发包上传**。

仓库已准备可部署账号服务和五端网页入口，但当前没有提供托管云服务。未登录并主动开启前，不进行后台云同步；移动网页不等同于原生手机输入法或锁屏后台剪贴板。

[数据与恢复](docs/数据与恢复说明.md) · [隐私与网络行为](docs/PRIVACY.md) · [同步范围](docs/SYNC.md)

## 版本与后续路线

这是独立公开副本，使用全新的提交历史。两端运行源码与已保留版本一致，Windows安装包保持原字节，Mac公开副本仅清理开发路径及更新本地签名；仅整理开源说明、许可和发布校验。原私有归档继续保留。

Mac与Windows分别保留基础版本的独立标签，新功能不添加到这两个基线。后续bug修复使用新修订／标签，保留旧附件；后续功能计划另开0.5版本。

**剪贴板历史、常用语与快捷面板目前处于方案阶段，尚未包含在上述安装包里。** 计划Mac和Windows同步推进，见[路线图](docs/ROADMAP.md)。

[固定版本与校验清单](VERSIONS.md) · [所有版本](https://github.com/xiaohaup/XiaohaVoice/releases)

## 从源码构建

- Mac：[构建说明](docs/BUILD_MACOS.md)。Swift原生宿主 + Python运行组件，提供独立干净工具包构建脚本。
- Windows：[构建说明](https://github.com/xiaohaup/XiaohaVoice/blob/windows-v0.4.0-preview.1-winfix6-20261021/windows/README.md)，Python／PySide6原生宿主 + Win32适配。
- 共用工作台：`sync-suite/`；两个ASR适配：`ime-channel-test/`。目录名保留，不需要另装“输入法语音测试”应用。

[技术结构](docs/ARCHITECTURE.md) · [参与贡献](CONTRIBUTING.md) · [反馈问题](https://github.com/xiaohaup/XiaohaVoice/issues/new/choose)

## 开源与致谢

自有源码采用[MIT](LICENSE)许可。感谢[missuo/koe](https://github.com/missuo/koe)的协议参考；保留其Vincent Yang署名和MIT原文。Python、Opus、Qt/PySide及其他依赖遵循各自许可证，见[第三方声明](docs/THIRD_PARTY.md)和分发包LICENSES。

识别服务由所选服务方处理音频；开源源码的使用许可不等于服务方承诺或接口授权。请自行评估使用场景，欢迎用合成短句复现问题与贡献改进。
