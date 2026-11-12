"""Load and save plain text with Notepad encodings and line endings.

The editor keeps ``\\n`` internally. Saving writes the chosen ending and
encoding, including a BOM for UTF-8 with BOM and both UTF-16 encodings.
"""

from __future__ import annotations

import locale
import sys
from dataclasses import dataclass

ENCODING_UTF8 = "utf-8"
ENCODING_UTF8_BOM = "utf-8-bom"
ENCODING_UTF16_LE = "utf-16-le"
ENCODING_UTF16_BE = "utf-16-be"
ENCODING_ANSI = "ansi"

ENCODINGS: tuple[tuple[str, str], ...] = (
    (ENCODING_UTF8, "UTF-8"),
    (ENCODING_UTF8_BOM, "UTF-8 with BOM"),
    (ENCODING_UTF16_LE, "UTF-16 LE"),
    (ENCODING_UTF16_BE, "UTF-16 BE"),
    (ENCODING_ANSI, "ANSI"),
)

NEWLINE_CRLF = "CRLF"
NEWLINE_LF = "LF"
NEWLINE_CR = "CR"

NEWLINES: tuple[tuple[str, str], ...] = (
    (NEWLINE_CRLF, "CRLF"),
    (NEWLINE_LF, "LF"),
    (NEWLINE_CR, "CR"),
)

_ENCODING_IDS = {key for key, _label in ENCODINGS}
_NEWLINE_IDS = {key for key, _label in NEWLINES}

_UTF8_BOM = b"\xef\xbb\xbf"
_UTF16_LE_BOM = b"\xff\xfe"
_UTF16_BE_BOM = b"\xfe\xff"

_NEWLINE_CHARS = {
    NEWLINE_CRLF: "\r\n",
    NEWLINE_LF: "\n",
    NEWLINE_CR: "\r",
}


@dataclass(frozen=True)
class LoadedText:
    text: str
    encoding: str
    newline: str
    binary: bool


def encoding_label(encoding: str) -> str:
    for key, label in ENCODINGS:
        if key == encoding:
            return label
    return "UTF-8"


def newline_label(newline: str) -> str:
    for key, label in NEWLINES:
        if key == newline:
            return label
    return "CRLF"


def normalize_encoding(encoding: str | None) -> str:
    if encoding in _ENCODING_IDS:
        return str(encoding)
    return ENCODING_UTF8


def normalize_newline_name(newline: str | None) -> str:
    if newline in _NEWLINE_IDS:
        return str(newline)
    return NEWLINE_CRLF


def ansi_codec_name() -> str:
    """Windows ANSI code page. Elsewhere, the locale preferred encoding."""
    if sys.platform == "win32":
        return "mbcs"
    preferred = locale.getpreferredencoding(False)
    return preferred or "cp1252"


def normalize_newlines(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")


def apply_newlines(text: str, newline: str) -> str:
    ending = _NEWLINE_CHARS[normalize_newline_name(newline)]
    return normalize_newlines(text).replace("\n", ending)


def detect_newline(text: str) -> str:
    crlf = text.count("\r\n")
    stripped = text.replace("\r\n", "")
    lf = stripped.count("\n")
    cr = stripped.count("\r")
    if crlf == 0 and lf == 0 and cr == 0:
        return NEWLINE_CRLF
    ranking = {
        NEWLINE_CRLF: (crlf, 3),
        NEWLINE_LF: (lf, 2),
        NEWLINE_CR: (cr, 1),
    }
    return max(ranking, key=lambda name: ranking[name])


def _null_ratio(data: bytes, offset: int) -> float:
    sample = data[offset::2]
    if not sample:
        return 0.0
    return sum(byte == 0 for byte in sample) / len(sample)


def detect_encoding(data: bytes) -> str:
    if data.startswith(_UTF16_LE_BOM):
        return ENCODING_UTF16_LE
    if data.startswith(_UTF16_BE_BOM):
        return ENCODING_UTF16_BE
    if data.startswith(_UTF8_BOM):
        return ENCODING_UTF8_BOM
    if len(data) >= 4 and len(data) % 2 == 0 and b"\x00" in data:
        le_ratio = _null_ratio(data, 1)
        be_ratio = _null_ratio(data, 0)
        if le_ratio > 0.5 and le_ratio >= be_ratio:
            try:
                data.decode("utf-16-le")
            except UnicodeDecodeError:
                pass
            else:
                return ENCODING_UTF16_LE
        if be_ratio > 0.5 and be_ratio > le_ratio:
            try:
                data.decode("utf-16-be")
            except UnicodeDecodeError:
                pass
            else:
                return ENCODING_UTF16_BE
    try:
        data.decode("utf-8")
    except UnicodeDecodeError:
        return ENCODING_ANSI
    return ENCODING_UTF8


def _payload(data: bytes, encoding: str) -> tuple[bytes, str]:
    if encoding == ENCODING_UTF8_BOM:
        raw = data[len(_UTF8_BOM) :] if data.startswith(_UTF8_BOM) else data
        return raw, "utf-8"
    if encoding == ENCODING_UTF16_LE:
        raw = data[len(_UTF16_LE_BOM) :] if data.startswith(_UTF16_LE_BOM) else data
        return raw, "utf-16-le"
    if encoding == ENCODING_UTF16_BE:
        raw = data[len(_UTF16_BE_BOM) :] if data.startswith(_UTF16_BE_BOM) else data
        return raw, "utf-16-be"
    if encoding == ENCODING_ANSI:
        return data, ansi_codec_name()
    return data, "utf-8"


def decode_bytes(data: bytes, encoding: str) -> str:
    raw, codec = _payload(data, normalize_encoding(encoding))
    errors = "replace" if encoding == ENCODING_ANSI else "strict"
    return raw.decode(codec, errors=errors)


def load_bytes(data: bytes) -> LoadedText:
    encoding = detect_encoding(data)
    try:
        decoded = decode_bytes(data, encoding)
    except UnicodeDecodeError:
        encoding = ENCODING_ANSI
        decoded = decode_bytes(data, encoding)
    binary = b"\x00" in data and not encoding.startswith("utf-16")
    return LoadedText(
        text=normalize_newlines(decoded),
        encoding=encoding,
        newline=detect_newline(decoded),
        binary=binary,
    )


def encode_text(text: str, encoding: str, newline: str) -> bytes:
    encoding = normalize_encoding(encoding)
    payload = apply_newlines(text, newline)
    if encoding == ENCODING_UTF8:
        return payload.encode("utf-8")
    if encoding == ENCODING_UTF8_BOM:
        return _UTF8_BOM + payload.encode("utf-8")
    if encoding == ENCODING_UTF16_LE:
        return _UTF16_LE_BOM + payload.encode("utf-16-le")
    if encoding == ENCODING_UTF16_BE:
        return _UTF16_BE_BOM + payload.encode("utf-16-be")
    return payload.encode(ansi_codec_name(), errors="strict")
