"""Переводы интерфейса (русский — исходный язык, английский и чешский — в locale/).

Строки в коде пишутся по-русски и оборачиваются для перевода:
  Python:    from django.utils.translation import gettext as _   →  _("Сохранить")
  шаблоны:   {% load i18n %} {% translate "Сохранить" %}, {% blocktranslate trimmed %}…{% endblocktranslate %}
  JS:        gettext("Сохранить"), interpolate(gettext("…%(n)s…"), {n}, true), ngettext(…)

Инструменты GNU gettext (makemessages, msgfmt) не нужны — их заменяет этот модуль:
  python manage.py translations   собрать строки из кода, дописать новые в .po
                                  (с пустым переводом) и скомпилировать .mo
.po — то, что правится руками и лежит в git; .mo собираются сами при запуске
(GenealogyConfig.ready), если .po новее. Тест не даёт оставить строку без перевода.
"""
from __future__ import annotations

import ast
import re
import struct
from dataclasses import dataclass, field
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
LOCALE_DIR = BASE_DIR / "locale"
LANGS = ("en", "cs", "ru")         # ru — только для множественного числа (у ru три формы)

PLURAL_FORMS = {
    "en": "nplurals=2; plural=(n != 1);",
    "cs": "nplurals=3; plural=(n==1) ? 0 : (n>=2 && n<=4) ? 1 : 2;",
    "ru": ("nplurals=3; plural=(n%10==1 && n%100!=11 ? 0 : n%10>=2 && n%10<=4 && "
           "(n%100<12 || n%100>14) ? 1 : 2);"),
}
# Где искать строки: (папка, шаблон файлов, домен). djangojs — строки для браузера.
SOURCES = (
    ("genealogy", "**/*.py", "django"),
    ("tree_engine", "**/*.py", "django"),
    ("maptree", "**/*.py", "django"),
    ("templates", "**/*.html", "django"),
    ("static/genealogy", "**/*.js", "djangojs"),
)
SKIP = ("migrations", "tests.py", "test_", "i18n.py")
PY_FUNCS = {"_", "gettext", "gettext_lazy", "gettext_noop", "ngettext", "ngettext_lazy"}


@dataclass
class Message:
    msgid: str
    plural: str | None = None
    refs: list[str] = field(default_factory=list)
    msgstr: list[str] = field(default_factory=list)   # [строка] или формы мн. числа

    @property
    def key(self):
        return (self.msgid, self.plural)

    def translated(self, lang: str) -> bool:
        return bool(self.msgstr) and all(self.msgstr)


# ---------- сбор строк из кода ----------

def _py_messages(text: str):
    for node in ast.walk(ast.parse(text)):
        if not isinstance(node, ast.Call):
            continue
        name = getattr(node.func, "id", None) or getattr(node.func, "attr", None)
        if name not in PY_FUNCS or not node.args:
            continue
        args = [a.value if isinstance(a, ast.Constant) and isinstance(a.value, str) else None
                for a in node.args[:2]]
        if args[0] is None:
            continue
        plural = args[1] if name.startswith("ngettext") and len(args) > 1 else None
        yield node.lineno, args[0], plural


_TPL_SIMPLE = re.compile(r"""\{%\s*(?:translate|trans)\s+(?:"((?:[^"\\]|\\.)*)"|'((?:[^'\\]|\\.)*)')""")
_TPL_BLOCK = re.compile(r"\{%\s*blocktrans(?:late)?\b([^%]*)%\}(.*?)\{%\s*endblocktrans(?:late)?\s*%\}", re.S)
_TPL_FILTER = re.compile(r"""_\(\s*"((?:[^"\\]|\\.)*)"\s*\)""")
_TPL_VAR = re.compile(r"\{\{\s*([\w.]+)\s*\}\}")


def _block_text(text: str, trimmed: bool) -> str:
    from django.utils.translation import trim_whitespace
    text = _TPL_VAR.sub(lambda m: f"%({m.group(1)})s", text.replace("%", "%%"))
    return trim_whitespace(text) if trimmed else text


def _template_messages(text: str):
    line = lambda pos: text.count("\n", 0, pos) + 1  # noqa: E731
    for m in _TPL_SIMPLE.finditer(text):
        yield line(m.start()), (m.group(1) if m.group(1) is not None else m.group(2)), None
    for m in _TPL_FILTER.finditer(text):
        yield line(m.start()), m.group(1), None
    for m in _TPL_BLOCK.finditer(text):
        trimmed = "trimmed" in m.group(1).split()
        parts = re.split(r"\{%\s*plural\s*%\}", m.group(2))
        singular = _block_text(parts[0], trimmed)
        plural = _block_text(parts[1], trimmed) if len(parts) > 1 else None
        yield line(m.start()), singular, plural


_JS_CALL = re.compile(r"""\b(n?gettext)\(\s*"((?:[^"\\]|\\.)*)"(?:\s*,\s*"((?:[^"\\]|\\.)*)")?""")


def _js_unescape(s: str | None) -> str | None:
    escapes = {"n": "\n", "t": "\t"}
    return s and re.sub(r"\\(.)", lambda e: escapes.get(e.group(1), e.group(1)), s)


def _js_messages(text: str):
    unescape = _js_unescape
    for m in _JS_CALL.finditer(text):
        plural = unescape(m.group(3)) if m.group(1) == "ngettext" else None
        yield text.count("\n", 0, m.start()) + 1, unescape(m.group(2)), plural


def extract(base: Path = BASE_DIR) -> dict[str, dict[tuple, Message]]:
    """Все строки для перевода: {домен: {(msgid, plural): Message}} в порядке появления в коде."""
    found: dict[str, dict[tuple, Message]] = {"django": {}, "djangojs": {}}
    for folder, pattern, domain in SOURCES:
        for path in sorted((base / folder).glob(pattern)):
            rel = path.relative_to(base).as_posix()
            if any(s in rel for s in SKIP):
                continue
            text = path.read_text(encoding="utf-8")
            reader = (_py_messages if path.suffix == ".py" else
                      _js_messages if path.suffix == ".js" else _template_messages)
            for lineno, msgid, plural in reader(text):
                if not msgid.strip():
                    continue
                msg = found[domain].setdefault((msgid, plural), Message(msgid, plural))
                msg.refs.append(f"{rel}:{lineno}")
    return found


# ---------- .po: чтение и запись ----------

def _unquote(s: str) -> str:
    s = s.strip()
    assert s.startswith('"') and s.endswith('"'), s
    out, i, body = [], 0, s[1:-1]
    escapes = {"n": "\n", "t": "\t", '"': '"', "\\": "\\"}
    while i < len(body):
        if body[i] == "\\" and i + 1 < len(body):
            out.append(escapes.get(body[i + 1], body[i + 1]))
            i += 2
        else:
            out.append(body[i])
            i += 1
    return "".join(out)


def _quote(s: str) -> str:
    s = s.replace("\\", "\\\\").replace('"', '\\"').replace("\t", "\\t")
    if "\n" not in s:
        return f'"{s}"'
    lines = s.split("\n")
    parts = [line + "\\n" for line in lines[:-1]] + ([lines[-1]] if lines[-1] else [])
    return '""\n' + "\n".join(f'"{p}"' for p in parts)


def read_po(path: Path) -> tuple[str, dict[tuple, Message]]:
    """→ (заголовок msgstr, {(msgid, plural): Message}). Строки «#~» (устаревшие) пропускаются."""
    header, messages = "", {}
    if not path.exists():
        return header, messages
    entries, current, key = [], None, None
    for raw in path.read_text(encoding="utf-8").splitlines() + [""]:
        line = raw.strip()
        if not line or line.startswith("#"):
            if current and not line:
                entries.append(current)
                current = None
            continue
        if current is None:
            current = {"msgid": "", "msgid_plural": None, "msgstr": {}}
        m = re.match(r"(msgid_plural|msgid|msgstr(?:\[(\d+)\])?)\s+(.*)", line)
        if m:
            key = (m.group(1), m.group(2))
            value = _unquote(m.group(3))
        else:
            value = _unquote(line)
        name, index = key
        if name == "msgid":
            current["msgid"] += value
        elif name == "msgid_plural":
            current["msgid_plural"] = (current["msgid_plural"] or "") + value
        else:
            idx = int(index or 0)
            current["msgstr"][idx] = current["msgstr"].get(idx, "") + value
    for e in entries:
        strs = [e["msgstr"][i] for i in sorted(e["msgstr"])]
        if e["msgid"] == "":
            header = strs[0] if strs else ""
            continue
        msg = Message(e["msgid"], e["msgid_plural"], msgstr=strs)
        messages[msg.key] = msg
    return header, messages


def _header(lang: str, domain: str) -> str:
    return (f"Project-Id-Version: mapTree\n"
            f"Language: {lang}\n"
            f"MIME-Version: 1.0\n"
            f"Content-Type: text/plain; charset=UTF-8\n"
            f"Content-Transfer-Encoding: 8bit\n"
            f"Plural-Forms: {PLURAL_FORMS[lang]}\n")


def write_po(path: Path, lang: str, domain: str, messages: list[Message], obsolete: list[Message]):
    nplurals = int(re.search(r"nplurals=(\d)", PLURAL_FORMS[lang]).group(1))
    out = [f"# Переводы mapTree: {lang}, домен {domain}.",
           "# Новые строки дописывает «python manage.py translations»; переводить — в msgstr.",
           'msgid ""', "msgstr " + _quote(_header(lang, domain)), ""]
    for msg in messages:
        out += [f"#: {ref}" for ref in msg.refs[:5]]
        out.append("msgid " + _quote(msg.msgid))
        if msg.plural is not None:
            out.append("msgid_plural " + _quote(msg.plural))
            forms = (msg.msgstr + [""] * nplurals)[:nplurals]
            out += [f"msgstr[{i}] " + _quote(s) for i, s in enumerate(forms)]
        else:
            out.append("msgstr " + _quote(msg.msgstr[0] if msg.msgstr else ""))
        out.append("")
    for msg in obsolete:
        out.append("#~ msgid " + _quote(msg.msgid).replace("\n", "\n#~ "))
        out.append("#~ msgstr " + _quote(msg.msgstr[0] if msg.msgstr else "").replace("\n", "\n#~ "))
        out.append("")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(out), encoding="utf-8", newline="\n")


def po_path(lang: str, domain: str) -> Path:
    return LOCALE_DIR / lang / "LC_MESSAGES" / f"{domain}.po"


def needs_translation(lang: str, msg: Message) -> bool:
    """В русском (исходном) нужен перевод только для мн. числа: в msgid всего две формы."""
    return lang != "ru" or msg.plural is not None


def update_po_files() -> dict[str, list[str]]:
    """Дописать новые строки во все .po, устаревшие пометить «#~». → {файл: [непереведённые]}."""
    found = extract()
    missing = {}
    for lang in LANGS:
        for domain, current in found.items():
            path = po_path(lang, domain)
            _, old = read_po(path)
            wanted = [m for m in current.values() if needs_translation(lang, m)]
            for msg in wanted:
                if msg.key in old:
                    msg.msgstr = old[msg.key].msgstr
                else:
                    msg.msgstr = []
            keys = {m.key for m in wanted}
            obsolete = [m for k, m in old.items() if k not in keys and m.plural is None and any(m.msgstr)]
            if wanted or obsolete or path.exists():
                write_po(path, lang, domain, wanted, obsolete)
            untranslated = [m.msgid for m in wanted if not m.translated(lang)]
            if untranslated:
                missing[str(path.relative_to(BASE_DIR))] = untranslated
            for m in wanted:      # следующий язык начинает с чистого листа
                m.msgstr = []
    return missing


# ---------- .po → .mo ----------

def compile_mo(path: Path) -> bytes:
    """Двоичный каталог gettext (как msgfmt). Непереведённые строки в него не попадают."""
    header, messages = read_po(path)
    lang = path.parent.parent.name
    catalog = {"": header or _header(lang, path.stem)}
    for msg in messages.values():
        if not msg.msgstr or not all(msg.msgstr):
            continue
        key = msg.msgid if msg.plural is None else f"{msg.msgid}\0{msg.plural}"
        catalog[key] = "\0".join(msg.msgstr)
    keys = sorted(catalog, key=lambda k: k.encode())
    ids = [k.encode() for k in keys]
    strs = [catalog[k].encode() for k in keys]
    n = len(keys)
    orig_start = 28
    trans_start = orig_start + 8 * n
    data_start = trans_start + 8 * n
    offsets, blob = [], b""
    for s in ids + strs:
        offsets.append((len(s), data_start + len(blob)))
        blob += s + b"\0"
    out = struct.pack("<7I", 0x950412DE, 0, n, orig_start, trans_start, 0, data_start)
    for length, offset in offsets:
        out += struct.pack("<2I", length, offset)
    return out + blob


def compile_all(force: bool = False) -> list[Path]:
    """Собрать .mo там, где .po новее (или .mo нет). → список пересобранных."""
    done = []
    for po in sorted(LOCALE_DIR.glob("*/LC_MESSAGES/*.po")):
        mo = po.with_suffix(".mo")
        if force or not mo.exists() or mo.stat().st_mtime < po.stat().st_mtime:
            data = compile_mo(po)
            if not mo.exists() or mo.read_bytes() != data:
                mo.write_bytes(data)
                done.append(mo)
            else:
                mo.touch()            # содержимое то же — только время, чтобы не пересобирать
    return done
