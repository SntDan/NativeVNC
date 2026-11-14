# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Small atomic settings file; saved passwords are protected by Windows DPAPI."""

import base64
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import tempfile


class Blob(ctypes.Structure):
    _fields_ = [("size", wintypes.DWORD), ("data", ctypes.POINTER(ctypes.c_ubyte))]


def _dpapi(data, decrypt=False):
    if os.name != "nt":
        raise OSError("记住密码仅在 Windows 上可用。")
    buffer = ctypes.create_string_buffer(data)
    source = Blob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)))
    target = Blob()
    crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    function = crypt32.CryptUnprotectData if decrypt else crypt32.CryptProtectData
    function.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.c_void_p,
                         ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
    function.restype = wintypes.BOOL
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p
    if not function(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(target)):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        return ctypes.string_at(target.data, target.size)
    finally:
        kernel32.LocalFree(target.data)


class Settings:
    def __init__(self, path=None):
        self.path = Path(path) if path else Path(os.environ.get("APPDATA", Path.home())) / "NativeVNC" / "settings.json"
        try:
            self.values = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(self.values, dict):
                self.values = {}
        except (OSError, ValueError):
            self.values = {}
        # Legacy window records included the login page; only restore desktop_window.
        self.values.pop("window", None)
        self.values.pop("maximized", None)

    @property
    def language(self):
        language = self.values.get("language", "en")
        return language if language in ("en", "zh_CN") else "en"

    @property
    def remember_window_size(self):
        value = self.values.get("remember_window_size", True)
        return value if isinstance(value, bool) else True

    def set_preferences(self, language, remember_window_size):
        previous = self.values
        updated = {**previous, "language": language, "remember_window_size": remember_window_size}
        if not remember_window_size and isinstance(updated.get("desktop_window"), dict):
            updated["desktop_window"] = dict(updated["desktop_window"])
            updated["desktop_window"].pop("geometry", None)
        self.values = updated
        try:
            self.save()
        except OSError:
            self.values = previous
            raise

    def password(self):
        if self.values.get("remember_password") is not True:
            return ""
        try:
            return _dpapi(base64.b64decode(self.values.get("password", "")), decrypt=True).decode("utf-8")
        except (OSError, ValueError, TypeError):
            return ""

    def remember(self, address, remember_password, username=""):
        if (address != self.values.get("address") or
                username != self.values.get("username", "") or not remember_password):
            self.values.pop("password", None)
        self.values.update(address=address, username=username, remember_password=remember_password)
        self.save()

    def authenticated(self, password):
        if self.values.get("remember_password") and password:
            self.values["password"] = base64.b64encode(_dpapi(password.encode("utf-8"))).decode("ascii")
        else:
            self.values.pop("password", None)
        self.save()

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=self.path.parent,
                                             prefix="settings-", suffix=".tmp", delete=False) as file:
                temporary = file.name
                json.dump(self.values, file, ensure_ascii=False, indent=2)
            os.replace(temporary, self.path)
        finally:
            if temporary and os.path.exists(temporary):
                os.unlink(temporary)
