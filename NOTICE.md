# 来源与署名

NativeVNC 最初在 [noVNC](https://github.com/novnc/noVNC) 源码目录内开发，基于该项目的 VNC 客户端工作进行原生桌面客户端开发，现将 Python / PySide6 客户端整理为独立仓库。它不是 noVNC 官方发布的客户端。

本仓库运行时不加载 noVNC 的 JavaScript、HTML、CSS 或浏览器组件，也未包含上游网页资源、字体、图标或打包产物。原生客户端的协议实现、窗口界面及设置管理保留在本仓库中。

## noVNC

- 上游项目：https://github.com/novnc/noVNC
- 保留的上游版权声明：`noVNC is Copyright (C) 2022 The noVNC authors`。
- 上游作者列表原文：[licenses/noVNC/AUTHORS](licenses/noVNC/AUTHORS)。
- 上游许可证说明原文：[licenses/noVNC/LICENSE.txt](licenses/noVNC/LICENSE.txt)。其中的路径描述对应上游仓库，并不表示这些文件也包含在本仓库中。
- MPL 2.0 全文：[LICENSE](LICENSE)。本仓库源码沿用 MPL-2.0，保留上游来源和署名。

本次整理来源于本地 noVNC 工作目录；该目录没有 Git 历史，因此没有标注无法核实的上游版本或提交号。

## Python 依赖

PySide6、PyCryptodome 和 websocket-client 通过 `requirements.txt` 安装，分别保留各自项目的许可证，不因本仓库采用 MPL-2.0 而改变。本仓库不内置这些依赖的二进制文件。
