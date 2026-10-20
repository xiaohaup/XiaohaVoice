# Qt与Windows分发补充说明

Windows基础工具包使用PySide6 6.12.0和独立的Qt动态库，没有修改Qt源码。项目自有源码采用MIT，第三方Qt/PySide组件不因此改成MIT。

- Qt for Python授权说明：https://doc.qt.io/qtforpython-6/licenses.html
- 开源／商业授权入口：https://doc.qt.io/qtforpython-6/commercial/index.html
- PySide源码入口：https://code.qt.io/cgit/pyside/pyside-setup.git/
- Qt源码入口：https://code.qt.io/cgit/qt/ ，源码下载：https://download.qt.io/official_releases/qt/
- 构建所用依赖版本见相应Windows源码的requirements-windows.txt和dependencies.lock.json；使用／分发时按确切版本获取对应源代码及其原许可证。

本目录补充GNU GPLv2、GPLv3、LGPLv3原文，与原工具包已有第三方声明共同阅读；不是替代或撤销Qt自身的授权条件。原Windows包中的Qt／PySide动态库保持可替换；不禁止为调试库的修改而进行的必要分析。重新分发者还应保留与其实际使用模块对应的版权和许可证，并按相应条款提供或指向对应源代码。

基础保留程序和二进制ZIP未变更，本补充是公开发布文档，不给旧版增加功能。
