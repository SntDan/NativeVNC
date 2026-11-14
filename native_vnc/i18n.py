# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""UI translations, applied at the display boundary rather than in the decoder."""

import re
from string import Formatter


LANGUAGES = (("English", "en"), ("简体中文", "zh_CN"))

ENGLISH = {
    "设置": "Settings",
    "语言": "Language",
    "记忆上次窗口大小": "Remember last window size",
    "仅影响普通窗口的尺寸和位置，仍会记忆最大化和全屏状态。":
        "Only affects normal window size and position. Maximized and fullscreen modes are still remembered.",
    "保存": "Save",
    "取消": "Cancel",
    "无法保存设置：{error}": "Could not save settings: {error}",
    "服务器地址": "Server address",
    "用户名": "Username",
    "密码": "Password",
    "记住密码": "Remember password",
    "连接": "Connect",
    "重新连接": "Reconnect",
    "192.168.1.10:5900 或 wss://…": "192.168.1.10:5900 or wss://…",
    "Mac 账户短名称；普通 VNC 留空": "Mac account name; leave blank for VNC",
    "Mac 登录密码，或 VNC 密码": "Mac login password or VNC password",
    "配置暂时无法保存，仍可连接。": "Could not save settings. You can still connect.",
    "连接已取消。": "Connection cancelled.",
    "正在断开…": "Disconnecting…",
    "正在连接服务器…": "Connecting to server…",
    "正在协商连接…": "Negotiating connection…",
    "正在验证 Mac 账户…": "Authenticating Mac account…",
    "正在验证密码…": "Authenticating…",
    "正在接收画面…": "Waiting for the remote desktop…",
    "远程桌面": "Remote desktop",
    "连接超时，请检查地址和网络。": "Connection timed out. Check the address and network.",
    "连接失败，请检查服务器、端口及证书。": "Connection failed. Check the server, port and certificate.",
    "连接失败，请检查服务器、端口及证书。（{error}）":
        "Connection failed. Check the server, port and certificate. ({error})",
    "请输入服务器地址。": "Enter a server address.",
    "请输入主机:端口，或 ws://、wss:// 连接地址。": "Enter host:port or a ws:// or wss:// address.",
    "地址中请只填写主机，密码填在下方。": "Enter only the host in the address field. Use the password field below.",
    "端口必须在 1–65535 之间。": "The port must be between 1 and 65535.",
    "VNC 直连地址应为主机:端口。IPv6 地址请使用 [地址]:端口。":
        "Use host:port for direct VNC connections, or [address]:port for IPv6.",
    "请填写实际 WebSocket 地址，不是 noVNC 网页地址。":
        "Enter the actual WebSocket endpoint, rather than a noVNC page URL.",
    "网关返回了文本，请使用二进制 RFB WebSocket 入口。":
        "The gateway returned text. Use a binary RFB WebSocket endpoint.",
    "传统 VNC 密码需使用 Latin-1 字符。": "Standard VNC passwords must use Latin-1 characters.",
    "连接发送失败，请重新连接。": "Could not send data. Reconnect to the server.",
    "服务器响应超时，请检查地址和连接方式。": "The server timed out. Check the address and connection type.",
    "连接已断开。": "Connection lost.",
    "服务器返回的信息过长。": "The server message is too long.",
    "服务器剪贴板内容过长。": "The server clipboard content is too large.",
    "暂不支持服务器消息 {kind}。": "Unsupported server message {kind}.",
    "此地址不是 VNC 服务，请检查端口或 WebSocket 路径。":
        "This endpoint is not a VNC server. Check the port or WebSocket path.",
    "服务器返回了无效的 VNC 版本。": "The server returned an invalid VNC version.",
    "暂不支持此 VNC 协议版本。": "This VNC protocol version is not supported.",
    "服务器拒绝连接：": "The server refused the connection: ",
    "认证失败：": "Authentication failed: ",
    "密码错误或连接被拒绝。": "Incorrect password or connection refused.",
    "此服务器不支持 Mac 账户登录。普通 VNC 连接请将用户名留空。":
        "This server does not support Mac account login. Leave the username blank for standard VNC.",
    "此 Mac 需要账户登录，请填写 Mac 用户名和登录密码。":
        "This Mac requires account login. Enter the Mac username and login password.",
    "此服务器要求的认证暂不支持。": "The server requires an unsupported authentication method.",
    "Mac 账户登录需要支持 Apple 认证的服务端。": "Mac account login requires a server with Apple authentication.",
    "当前仅支持免密和传统 VNC 密码认证。": "Only no-authentication and standard VNC password login are supported here.",
    "Mac 拒绝登录，请检查账户短名称、登录密码及屏幕共享权限。":
        "Mac login was rejected. Check the account name, password and Screen Sharing permissions.",
    "Mac 用户名和密码不能包含空字符，且各自的 UTF-8 长度不能超过 63 字节。":
        "Mac credentials cannot contain null characters or exceed 63 UTF-8 bytes each.",
    "Mac 返回了不支持的认证密钥长度。": "The Mac returned an unsupported authentication key length.",
    "Mac 返回了无效的认证参数。": "The Mac returned invalid authentication parameters.",
    "Mac 认证密钥协商失败。": "Mac authentication key negotiation failed.",
    "远程画面尺寸无效或过大。": "The remote desktop size is invalid or too large.",
    "服务器返回了超出画面范围的图像。": "The server returned a rectangle outside the remote desktop.",
    "图像数据长度不正确。": "The image data has an invalid length.",
    "Hextile 子矩形超出范围。": "A Hextile subrectangle is out of bounds.",
    "远程光标尺寸过大。": "The remote cursor is too large.",
    "远程光标热点超出范围。": "The remote cursor hotspot is out of bounds.",
    "压缩图像过大。": "The compressed image is too large.",
    "服务器使用了未协商的图像编码 {encoding}。": "The server used an unnegotiated image encoding: {encoding}.",
    "记住密码仅在 Windows 上可用。": "Saving passwords is only supported on Windows.",
}


def _template_pattern(source):
    parts = []
    for literal, field, _, _ in Formatter().parse(source):
        parts.append(re.escape(literal))
        if field:
            parts.append(f"(?P<{field}>.*?)")
    return re.compile("".join(parts), re.DOTALL)


_TEMPLATES = tuple((_template_pattern(source), target)
                   for source, target in ENGLISH.items() if "{" in source)
_PREFIXES = ("服务器拒绝连接：", "认证失败：")


def translate(message, language="en"):
    if language == "zh_CN":
        return message
    if message in ENGLISH:
        return ENGLISH[message]
    for prefix in _PREFIXES:
        if message.startswith(prefix):
            return ENGLISH[prefix] + translate(message[len(prefix):], language)
    for pattern, target in _TEMPLATES:
        match = pattern.fullmatch(message)
        if match:
            return target.format(**match.groupdict())
    return message  # Preserve names and messages supplied by the remote server.
