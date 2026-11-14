# NativeVNC

独立 Windows 桌面客户端，使用 Python / PySide6，不依赖浏览器或 WebView。

项目最初基于 [noVNC](https://github.com/novnc/noVNC) 开发，现将原生客户端单独整理为源码仓库；运行时不依赖 noVNC 网页前端。来源、署名和许可证说明见 [NOTICE.md](NOTICE.md)。本项目不是 noVNC 官方客户端。

## 启动

在项目根目录执行：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m native_vnc
```

需要 Python 3.10 或更高版本。也可运行根目录的 `run_native.py` 或 `run-native.ps1`。启动脚本只运行源代码，不执行打包。

### VS Code 运行和调试

用 VS Code 打开项目根目录 `NativeVNC`，选择 `.venv\Scripts\python.exe` 解释器，然后按 F5，选择 `Native VNC`。项目的 `.vscode/launch.json` 使用模块方式启动，相当于 `python -m native_vnc`。

使用编辑器右上角的“运行 Python 文件”时，请打开根目录的 `run_native.py` 再运行。不要直接运行 `native_vnc/__main__.py`：它使用包内相对导入，作为独立文件运行会出现 `attempted relative import with no known parent package`。

## 打包 Windows 程序

双击项目根目录的 `build.bat` 即可。脚本自动创建或复用 `.venv`、安装依赖并打包成单个可执行文件，成功或失败后都会保留窗口显示结果。此脚本由用户自行运行。

以下命令由用户在项目根目录的 PowerShell 中自行执行。建议使用独立虚拟环境，避免把其他项目的依赖一起收集：

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt pyinstaller
.\.venv\Scripts\python.exe -m PyInstaller --noconfirm --clean NativeVNC.spec
```

输出为 `dist\NativeVNC.exe`，发送到其他电脑时复制这一个文件即可。

当前 `NativeVNC.spec` 使用单文件模式，启动时需要解压依赖。若以后调整为目录分发，需要修改打包配置，并复制整个输出目录及其依赖；仅复制目录版 exe 会缺少 Python DLL。

`run_native.py` 是打包入口；不要直接把包含包内相对导入的 `native_vnc\__main__.py` 当作脚本入口。配置仍保存在当前用户的 `%APPDATA%\NativeVNC\settings.json`，不包含在分发文件中。

## 交互

- Mac 自带屏幕共享：填写地址、Mac 账户短名称和账户登录密码，按回车连接。用户名不是 Apple ID，也不是账户显示名称。
- 普通 VNC：将用户名留空，填写 VNC 密码；免密连接可将密码留空。
- 地址支持 `192.168.1.10:5900`、`[::1]:5900`、`vnc://host:5900`、`ws://host:6080/websockify`、`wss://host/path?token=...`。
- 地址需要是实际 VNC 或 WebSocket 入口，不能直接填写 noVNC 的 HTTP 网页链接。
- 界面采用灰色简洁样式，保留微软雅黑和原有字号，深浅色跟随系统实时切换；标题栏、最小化、最大化/还原、关闭及窗口边框由 Windows 提供。
- 默认使用英语。点击登录页标题右侧的 Settings / 设置，可切换 English / 简体中文，保存后立即生效并记住选择；连接状态、验证错误和断线提示也随语言切换。
- 设置中的“记忆上次窗口大小”默认开启。关闭后不保存普通窗口的尺寸和位置，下次使用默认宽度并按远端屏幕比例调整；最大化和全屏状态仍按原有规则记忆。
- 登录页以 360 × 330 的客户区居中打开，不记忆登录页的位置、大小或最大化状态。表单靠上排列，连接状态和错误显示在按钮下方；较长信息自动增加高度，不移动或压缩输入框。
- 断开或退出时记忆共享屏幕窗口的位置、尺寸、Windows 最大化和 F11 全屏状态，点击关闭时立即保存。登录页仍以普通窗口打开，连接成功后恢复上次最大化或全屏状态；普通窗口收到首帧后，以记忆的窗口宽度为起点，重新按远端画面比例调整客户区，避免旧尺寸产生空白边，并计入 Windows 标题栏和边框，适应当前显示器的可用区域。远端分辨率变化或退出全屏回到普通窗口时也会重新调整。
- 拖动 Windows 标准窗口边缘或四角调整大小；拖动系统标题栏移动窗口，双击标题栏最大化或还原。画面等比适应，不改变远端分辨率。黑边不向远端发送点击。
- 鼠标使用本地系统光标，支持远端光标形状、左右键、中键、拖拽和横纵滚轮。未收到远端光标时使用系统箭头。
- 键鼠输入独立发送，不等待图像接收超时；鼠标移动按需合并，空闲时不启动移动定时器。界面忙时直接显示最新完整画面，避免旧帧排队积累延迟。优先使用 CopyRect 在画面缓冲区内复制滚动区域，减少临时内存分配，并向支持的服务端请求低压缩等级，以减少编码开销。
- 连接成功后不显示应用内的信息或按钮栏，远程画面区域填满客户区，四周没有额外留白。F11 切换全屏，全屏时隐藏系统标题栏。其他常规键盘输入发给远端。
- 失去焦点时释放远端按键和鼠标按钮。断线保留最后画面，点击“重新连接”重试；使用系统关闭按钮结束连接并退出。
- 自动保存上次地址、用户名。勾选“记住密码”后，仅在成功认证后保存密码。编辑地址或用户名时清空密码输入，切换身份后清除旧身份保存的密码。

配置位于 `%APPDATA%\NativeVNC\settings.json`，语言和窗口记忆选项也保存在此处；密码使用当前 Windows 用户的 DPAPI 加密。取消“记住密码”并连接或退出即可清除保存的密码。带令牌的 WebSocket 地址会作为地址保存到本机配置文件。

## 第一版范围

- RFB 3.3 / 3.7 / 3.8；Mac 账户认证（Apple DH / security type 30）、免密和传统 VNC 密码认证。
- 识别 Mac 自带屏幕共享的 3.888 / 3.889 协议版本，连接后请求共享控制模式。Mac 建立会话后的约两秒内可能忽略按键，客户端会暂存最初的键盘事件后按顺序发送。
- Raw、CopyRect、Hextile、Zlib 图像编码；Cursor、DesktopSize、LastRect 扩展。
- WSS 使用正常证书校验，不跳过无效证书。TCP VNC 和 WS 本身不加密。
- 网页登录 Cookie、企业认证、VeNCrypt、文件传输、剪贴板同步、多会话、托盘不包含在此版本中。
- 系统保留组合键仍可能由本机 Windows 处理；当前界面不提供向远端发送 Ctrl+Alt+Del 的按钮。
- 中文输入法提交的文字通过 Unicode keysym 发送，实际支持取决于 VNC 服务端。

### Mac 锁屏

填写用户名时，通过 Apple DH 使用 Mac 账户密码认证，不降级为单独的 VNC 共享密码。该账户必须具有屏幕共享控制权限。用户名留空时仍使用传统 VNC 共享密码。

账户认证与屏幕解锁由 Mac 分别决定；账户认证成功不保证跳过所有锁屏、FileVault 或会话选择。客户端不模拟输入登录密码，也不修改远端锁屏设置。

## 项目结构

```text
NativeVNC/
├── native_vnc/            # 原生客户端源码
├── .vscode/launch.json    # VS Code 模块启动配置
├── licenses/noVNC/       # 上游原始署名和许可证说明
├── requirements.txt      # 运行依赖
├── run_native.py          # 脚本入口
├── run-native.ps1         # PowerShell 启动脚本
├── build.bat              # 用户自行执行的打包脚本
├── NativeVNC.spec         # PyInstaller 单文件配置
├── LICENSE                # MPL-2.0 全文
└── NOTICE.md              # 来源与署名
```

## 上传源码

将整个项目作为独立 Git 仓库管理。`.gitignore` 已排除虚拟环境、缓存、构建目录、可执行文件、个人设置、常见密钥及临时文件。提交源码、依赖说明、构建配置及许可证文件即可；不要把旧 noVNC 仓库的网页资源或本机的 `%APPDATA%\NativeVNC` 配置复制进来。

本项目沿用 MPL-2.0，见 [LICENSE](LICENSE)，并保留 [noVNC 来源说明](NOTICE.md)。后续发布版本时，将对应源码与发布版本关联，方便使用者找到对应实现。
