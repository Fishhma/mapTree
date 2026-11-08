"""Версия файла в адресе статики: /static/genealogy/tree.css?v=3f2a9c1b04.

Браузер держит CSS и JS в кэше и после обычного F5 может показать старый вид.
Версия — начало хеша содержимого файла: файл изменился → изменился адрес →
браузер скачивает свежий. Подключается в settings.STORAGES["staticfiles"],
так что все {% static %} в шаблонах получают версию сами.
"""
from __future__ import annotations

import hashlib
import os

from django.contrib.staticfiles import finders
from django.contrib.staticfiles.storage import StaticFilesStorage

_cache: dict[str, tuple[float, str]] = {}      # путь → (время изменения, версия)


def file_version(path: str) -> str:
    """Первые 10 знаков md5 содержимого; пересчитывается, только если файл менялся."""
    mtime = os.path.getmtime(path)
    cached = _cache.get(path)
    if cached and cached[0] == mtime:
        return cached[1]
    with open(path, "rb") as f:
        version = hashlib.md5(f.read(), usedforsecurity=False).hexdigest()[:10]
    _cache[path] = (mtime, version)
    return version


class VersionedStaticFilesStorage(StaticFilesStorage):
    def url(self, name):
        url = super().url(name)
        path = finders.find(name)
        if not path and self.exists(name):           # после collectstatic
            path = self.path(name)
        return f"{url}?v={file_version(path)}" if path else url
