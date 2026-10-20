# 第三方来源与许可

| 组件 | 用途与许可 | 来源 |
| --- | --- | --- |
| missuo/koe协议参考 | 豆包输入法兼容协议；MIT，Vincent Yang | https://github.com/missuo/koe/tree/b73e038e91b3ca314429e776054abf06870a0af0 |
| Opus | 音频编码；BSD，按包附COPYING | https://opus-codec.org/ |
| Python与Python依赖 | 本机工作台与运行组件，分别保留原许可 | 锁定版本及LICENSES目录 |
| Qt for Python / PySide6 | Windows原生窗口、音频、托盘、WebEngine；依Qt相应开源或商业条款 | https://doc.qt.io/qtforpython-6/licenses.html |
| PyInstaller | 构建工具；GPLv2含应用分发例外 | https://pyinstaller.org/en/stable/license.html |

项目自有源码的MIT许可不覆盖第三方组件的原许可证，也不授予第三方语音服务访问权。协议参考不代表服务方提供第三方支持或长期稳定承诺。

koe原许可见LICENSES/koe-MIT.txt及ime-channel-test/UPSTREAM-LICENSE-MIT.txt。分发包已有组件许可与署名，Qt补充原文和源码入口见LICENSES/Qt/README.md。重新分发应保留实际组件的许可、通知及对应源代码获取条件。

`desktop/assets/api-check.pcm`是内置一秒“语音测试”合成样本，不含用户声音；只在本人明确发起识别测速时使用。没有复制iCopy或闪电说的专有代码、品牌或个人资料。
