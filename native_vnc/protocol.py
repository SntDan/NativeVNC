# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""RFB 3.3/3.7/3.8 over TCP or binary WebSocket, without a browser."""

from dataclasses import dataclass
import hashlib
import queue
import secrets
import socket
import struct
import threading
import time
from urllib.parse import urlsplit
import zlib


MAX_PIXELS = 32 * 1024 * 1024
MAX_TEXT = 1024 * 1024
APPLE_KEY_GUARD_SECONDS = 2.1


class ProtocolError(Exception):
    pass


class Cancelled(Exception):
    pass


@dataclass(frozen=True)
class Endpoint:
    scheme: str
    host: str
    port: int
    url: str = ""

    @classmethod
    def parse(cls, address):
        address = address.strip()
        if not address:
            raise ValueError("请输入服务器地址。")
        try:
            url = urlsplit(address if "://" in address else "vnc://" + address)
            if url.scheme not in ("vnc", "tcp", "ws", "wss"):
                raise ValueError("请输入主机:端口，或 ws://、wss:// 连接地址。")
            if not url.hostname or url.username is not None or url.password is not None:
                raise ValueError("地址中请只填写主机，密码填在下方。")
            port = url.port if url.port is not None else {"vnc": 5900, "tcp": 5900, "ws": 80, "wss": 443}[url.scheme]
            if not 1 <= port <= 65535:
                raise ValueError("端口必须在 1–65535 之间。")
            if url.scheme in ("tcp", "vnc") and (url.path not in ("", "/") or url.query or url.fragment):
                raise ValueError("VNC 直连地址应为主机:端口。IPv6 地址请使用 [地址]:端口。")
            if url.fragment:
                raise ValueError("请填写实际 WebSocket 地址，不是 noVNC 网页地址。")
            return cls(url.scheme, url.hostname, port, address)
        except ValueError as exc:
            raise ValueError(str(exc)) from None


class Transport:
    def __init__(self, endpoint):
        self.endpoint = endpoint
        self.connection = None
        self.is_websocket = endpoint.scheme in ("ws", "wss")
        self.send_lock = threading.Lock()

    def open(self):
        if self.is_websocket:
            import websocket
            self.connection = websocket.create_connection(
                self.endpoint.url, timeout=5, subprotocols=["binary"],
                sockopt=((socket.IPPROTO_TCP, socket.TCP_NODELAY, 1),),
            )
        else:
            self.connection = socket.create_connection((self.endpoint.host, self.endpoint.port), timeout=5)
            self.connection.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        self.connection.settimeout(0.05)

    def recv(self):
        if self.is_websocket:
            import websocket
            try:
                data = self.connection.recv()
            except websocket.WebSocketTimeoutException:
                raise socket.timeout from None
            if isinstance(data, str):
                raise ProtocolError("网关返回了文本，请使用二进制 RFB WebSocket 入口。")
            return data
        return self.connection.recv(65536)

    def send(self, data):
        # Requests and input share one ordered byte stream, even across sendall calls.
        with self.send_lock:
            if self.is_websocket:
                self.connection.send_binary(data)
            else:
                self.connection.sendall(data)

    def close(self):
        if self.connection is not None:
            if self.is_websocket:
                self.connection.shutdown()
            else:
                self.connection.close()
            self.connection = None


def challenge_response(password, challenge):
    from Crypto.Cipher import DES
    try:
        key = password.encode("latin-1")[:8].ljust(8, b"\0")
    except UnicodeEncodeError:
        raise ProtocolError("传统 VNC 密码需使用 Latin-1 字符。") from None
    reversed_key = bytes(int(f"{byte:08b}"[::-1], 2) for byte in key)
    return DES.new(reversed_key, DES.MODE_ECB).encrypt(challenge)


class Session:
    """Receive/decode frames separately from the event-driven input sender."""

    def __init__(self, endpoint, password="", *, username="", status=lambda text: None,
                 connected=lambda name: None, frame=lambda w, h, pixels: None,
                 cursor=lambda w, h, x, y, pixels: None, transport=None):
        self.transport = transport or Transport(endpoint)
        self.password = password
        self.username = username
        self.status = status
        self.connected = connected
        self.frame = frame
        self.cursor = cursor
        self.stopped = threading.Event()
        self.ready = threading.Event()
        self.outgoing = queue.SimpleQueue()
        self.sender = None
        self.send_error = None
        self.is_apple = False
        self.keys_allowed_at = 0.0
        self.buffer = bytearray()
        self.width = self.height = 0
        self.pixels = bytearray()
        self.inflator = zlib.decompressobj()
        self.deadline = None

    def stop(self):
        self.ready.clear()
        self.stopped.set()

    def enqueue(self, data):
        if self.ready.is_set() and not self.stopped.is_set():
            self.outgoing.put(data)

    def key(self, keysym, down):
        self.enqueue(struct.pack("!BBHI", 4, bool(down), 0, keysym))

    def pointer(self, x, y, buttons):
        self.enqueue(struct.pack("!BBHH", 5, buttons, x, y))

    def _send_input(self):
        try:
            while True:
                data = self.outgoing.get()
                if data is None:
                    return
                if self.keys_allowed_at and data[:2] == b"\x04\x01":
                    # Apple's agent briefly rejects key-down events after session setup.
                    # Preserve input order without blocking the UI or framebuffer receiver.
                    delay = self.keys_allowed_at - time.monotonic()
                    if delay > 0:
                        self.stopped.wait(delay)
                    self.keys_allowed_at = 0.0
                self.transport.send(data)
        except Exception as exc:
            self.send_error = exc

    def _read(self, count):
        while True:
            if self.stopped.is_set():
                raise Cancelled()
            if self.send_error is not None:
                raise ProtocolError("连接发送失败，请重新连接。") from self.send_error
            if len(self.buffer) >= count:
                result = bytes(memoryview(self.buffer)[:count])
                del self.buffer[:count]
                return result
            if self.deadline and time.monotonic() > self.deadline:
                raise ProtocolError("服务器响应超时，请检查地址和连接方式。")
            try:
                data = self.transport.recv()
            except socket.timeout:
                continue
            if not data:
                raise ProtocolError("连接已断开。")
            self.buffer.extend(data)

    def _unpack(self, fmt):
        return struct.unpack(fmt, self._read(struct.calcsize(fmt)))

    def _reason(self):
        size, = self._unpack("!I")
        if size > MAX_TEXT:
            raise ProtocolError("服务器返回的信息过长。")
        return self._read(size).decode("utf-8", "replace")

    def run(self):
        try:
            self.status("正在连接服务器…")
            self.transport.open()
            if self.stopped.is_set():
                raise Cancelled()
            self.deadline = time.monotonic() + 15
            self._handshake()
            self.deadline = None
            self.sender = threading.Thread(target=self._send_input, name="vnc-input")
            self.sender.start()
            while not self.stopped.is_set():
                kind = self._read(1)[0]
                if kind == 0:
                    changed = self._update()
                    # Let the server prepare the next update while we publish this snapshot.
                    self._request(True)
                    if changed:
                        self.frame(self.width, self.height, bytes(self.pixels))
                elif kind == 1:  # SetColorMapEntries (true-colour clients do not use it)
                    _, _, count = self._unpack("!BHH")
                    self._read(count * 6)
                elif kind == 2:  # Bell
                    pass
                elif kind == 3:  # Clipboard is deliberately not exposed in this version.
                    self._read(3)
                    size, = self._unpack("!I")
                    if size > MAX_TEXT:
                        raise ProtocolError("服务器剪贴板内容过长。")
                    self._read(size)
                else:
                    raise ProtocolError(f"暂不支持服务器消息 {kind}。")
        finally:
            self.ready.clear()
            self.password = ""
            if self.sender is not None:
                # Drain releases briefly, then close blocked I/O before waiting
                # for the sender. Joining first could keep the process alive forever.
                self.outgoing.put(None)
                self.sender.join(timeout=0.2)
            self.transport.close()
            if self.sender is not None:
                self.sender.join()

    def _handshake(self):
        self.status("正在协商连接…")
        banner = self._read(12)
        self.is_apple = banner in (b"RFB 003.888\n", b"RFB 003.889\n")
        if not banner.startswith(b"RFB ") or banner[7:8] != b".":
            raise ProtocolError("此地址不是 VNC 服务，请检查端口或 WebSocket 路径。")
        try:
            major, minor = int(banner[4:7]), int(banner[8:11])
        except ValueError:
            raise ProtocolError("服务器返回了无效的 VNC 版本。") from None
        if major != 3 or minor < 3:
            raise ProtocolError("暂不支持此 VNC 协议版本。")
        version = 8 if minor >= 8 else 7 if minor >= 7 else 3
        self.transport.send(f"RFB 003.{version:03d}\n".encode("ascii"))
        if version == 3:
            security, = self._unpack("!I")
            if security == 0:
                raise ProtocolError("服务器拒绝连接：" + self._reason())
        else:
            count = self._read(1)[0]
            if not count:
                raise ProtocolError("服务器拒绝连接：" + self._reason())
            offered = self._read(count)
            if self.username:
                if 30 not in offered:
                    raise ProtocolError("此服务器不支持 Mac 账户登录。普通 VNC 连接请将用户名留空。")
                security = 30
            else:
                security = 2 if 2 in offered else 1 if 1 in offered else 0
            if not security:
                if 30 in offered:
                    raise ProtocolError("此 Mac 需要账户登录，请填写 Mac 用户名和登录密码。")
                raise ProtocolError("此服务器要求的认证暂不支持。")
            self.transport.send(bytes([security]))
        if self.username and security != 30:
            raise ProtocolError("Mac 账户登录需要支持 Apple 认证的服务端。")
        if security == 30:
            self.is_apple = True
            self.status("正在验证 Mac 账户…")
            self._authenticate_apple()
        elif security == 2:
            self.status("正在验证密码…")
            self.transport.send(challenge_response(self.password, self._read(16)))
        elif security != 1:
            raise ProtocolError("当前仅支持免密和传统 VNC 密码认证。")
        if security in (2, 30) or version == 8:
            result, = self._unpack("!I")
            if result:
                if security == 30:
                    raise ProtocolError("Mac 拒绝登录，请检查账户短名称、登录密码及屏幕共享权限。")
                reason = self._reason() if version == 8 else "密码错误或连接被拒绝。"
                raise ProtocolError("认证失败：" + reason)
        self.password = ""
        self.transport.send(b"\x01")  # Shared session: do not evict another client.
        width, height = self._unpack("!HH")
        self._read(16)  # Server's pixel format; SetPixelFormat below replaces it.
        name = self._reason()
        self._resize(width, height)
        # 32-bit little-endian BGRX, compatible with QImage.Format_RGB32.
        self.transport.send(struct.pack("!BBBBBBBBHHHBBBxxx", 0, 0, 0, 0,
                                        32, 24, 0, 1, 255, 255, 255, 16, 8, 0))
        # Copy scrolling regions when possible; ask for fast, low-level compression.
        encodings = (1, 6, 5, 0, -239, -223, -224, -255)
        self.transport.send(struct.pack("!BBH", 2, 0, len(encodings)) +
                            struct.pack("!" + "i" * len(encodings), *encodings))
        if self.is_apple:
            # Apple starts a viewer in observe mode; ordinary RFB input alone is ignored.
            # SetMode: type 10, one padding byte, u16 control mode 1 (shared control).
            self.transport.send(struct.pack("!BBH", 10, 0, 1))
            self.keys_allowed_at = time.monotonic() + APPLE_KEY_GUARD_SECONDS
        self.ready.set()
        self.connected(name or "远程桌面")
        self.status("正在接收画面…")
        self._request(False)

    def _authenticate_apple(self):
        """Security type 30: DH, MD5 of fixed-width secret, AES-ECB credentials."""
        from Crypto.Cipher import AES
        username = self.username.encode("utf-8")
        password = self.password.encode("utf-8")
        if any(len(value) > 63 or b"\0" in value for value in (username, password)):
            raise ProtocolError("Mac 用户名和密码不能包含空字符，且各自的 UTF-8 长度不能超过 63 字节。")
        generator, length = self._unpack("!HH")
        if not 16 <= length <= 512:
            raise ProtocolError("Mac 返回了不支持的认证密钥长度。")
        prime = int.from_bytes(self._read(length), "big")
        server_key = int.from_bytes(self._read(length), "big")
        if prime < 5 or prime % 2 == 0 or not 1 < generator < prime - 1 or not 1 < server_key < prime - 1:
            raise ProtocolError("Mac 返回了无效的认证参数。")
        private_key = secrets.randbelow(prime - 3) + 2
        public_key = pow(generator, private_key, prime).to_bytes(length, "big")
        shared = pow(server_key, private_key, prime).to_bytes(length, "big")
        if int.from_bytes(shared, "big") <= 1:
            raise ProtocolError("Mac 认证密钥协商失败。")
        credentials = bytearray(secrets.token_bytes(128))
        credentials[:len(username) + 1] = username + b"\0"
        credentials[64:65 + len(password)] = password + b"\0"
        key = hashlib.md5(shared).digest()  # Required by Apple's legacy ARD protocol.
        encrypted = AES.new(key, AES.MODE_ECB).encrypt(credentials)
        self.transport.send(encrypted + public_key)

    def _request(self, incremental):
        self.transport.send(struct.pack("!BBHHHH", 3, incremental, 0, 0, self.width, self.height))

    def _resize(self, width, height):
        if not width or not height or width * height > MAX_PIXELS:
            raise ProtocolError("远程画面尺寸无效或过大。")
        self.width, self.height = width, height
        self.pixels = bytearray(width * height * 4)

    def _bounds(self, x, y, width, height):
        if not width or not height or x + width > self.width or y + height > self.height:
            raise ProtocolError("服务器返回了超出画面范围的图像。")

    def _blit(self, x, y, width, height, pixels):
        self._bounds(x, y, width, height)
        if len(pixels) != width * height * 4:
            raise ProtocolError("图像数据长度不正确。")
        target = memoryview(self.pixels)
        stride = width * 4
        if width == self.width or height == 1:
            start = (y * self.width + x) * 4
            target[start:start + len(pixels)] = pixels
            return
        source = memoryview(pixels)
        for row in range(height):
            start = ((y + row) * self.width + x) * 4
            target[start:start + stride] = source[row * stride:(row + 1) * stride]

    def _copy_rect(self, x, y, width, height, sx, sy):
        self._bounds(sx, sy, width, height)
        pixels = memoryview(self.pixels)
        stride = self.width * 4
        size = width * 4
        if width == self.width or height == 1:
            source = (sy * self.width + sx) * 4
            target = (y * self.width + x) * 4
            size *= height
            pixels[target:target + size] = pixels[source:source + size]
            return
        # Contiguous view assignments handle horizontal overlap; copy bottom-up
        # when moving down so later rows still read their original source pixels.
        rows = range(height - 1, -1, -1) if y > sy else range(height)
        for row in rows:
            source = ((sy + row) * self.width + sx) * 4
            target = ((y + row) * self.width + x) * 4
            pixels[target:target + size] = pixels[source:source + size]

    def _hextile(self, x, y, width, height):
        background = foreground = b"\0" * 4
        for top in range(y, y + height, 16):
            th = min(16, y + height - top)
            for left in range(x, x + width, 16):
                tw = min(16, x + width - left)
                flags = self._read(1)[0]
                if flags & 1:
                    self._blit(left, top, tw, th, self._read(tw * th * 4))
                    continue
                if flags & 2:
                    background = self._read(4)
                if flags & 4:
                    foreground = self._read(4)
                self._blit(left, top, tw, th, background * (tw * th))
                if flags & 8:
                    for _ in range(self._read(1)[0]):
                        color = self._read(4) if flags & 16 else foreground
                        xy, wh = self._read(2)
                        sx, sy = xy >> 4, xy & 15
                        sw, sh = (wh >> 4) + 1, (wh & 15) + 1
                        if sx + sw > tw or sy + sh > th:
                            raise ProtocolError("Hextile 子矩形超出范围。")
                        self._blit(left + sx, top + sy, sw, sh, color * (sw * sh))

    def _cursor(self, hot_x, hot_y, width, height):
        if width > 512 or height > 512:
            raise ProtocolError("远程光标尺寸过大。")
        bgr = self._read(width * height * 4)
        stride = (width + 7) // 8
        mask = self._read(stride * height)
        rgba = bytearray(len(bgr))
        for y in range(height):
            for x in range(width):
                offset = (y * width + x) * 4
                rgba[offset:offset + 3] = bgr[offset:offset + 3][::-1]
                rgba[offset + 3] = 255 if mask[y * stride + x // 8] & (128 >> (x % 8)) else 0
        if width and height and (hot_x >= width or hot_y >= height):
            raise ProtocolError("远程光标热点超出范围。")
        self.cursor(width, height, hot_x, hot_y, bytes(rgba))

    def _update(self):
        _, count = self._unpack("!BH")
        changed = False
        for _ in range(count):
            x, y, width, height, encoding = self._unpack("!HHHHi")
            if encoding == -224:
                break
            if encoding == -239:
                self._cursor(x, y, width, height)
                continue
            if encoding == -223:
                self._resize(width, height)
                changed = True
                continue
            self._bounds(x, y, width, height)
            if encoding == 0:
                self._blit(x, y, width, height, self._read(width * height * 4))
            elif encoding == 1:
                sx, sy = self._unpack("!HH")
                self._copy_rect(x, y, width, height, sx, sy)
            elif encoding == 5:
                self._hextile(x, y, width, height)
            elif encoding == 6:
                size, = self._unpack("!I")
                if size > MAX_PIXELS * 4:
                    raise ProtocolError("压缩图像过大。")
                raw = self.inflator.decompress(self._read(size), width * height * 4 + 1)
                self._blit(x, y, width, height, raw)
            else:
                raise ProtocolError(f"服务器使用了未协商的图像编码 {encoding}。")
            changed = True
        return changed
