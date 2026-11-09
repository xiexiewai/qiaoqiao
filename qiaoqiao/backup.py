"""Portable, versioned backups of daily aggregates, without device preferences."""

import hashlib
import hmac
import json
import os
import re
import tempfile
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

from . import __version__
from .core import Counts

FORMAT = "qiaoqiao-backup"
FORMAT_VERSION = 1
MAX_FILE_BYTES = 64 * 1024 * 1024
MAX_COUNT = 2**63 - 1
MIN_DAY = date(1900, 1, 1)
KEY_PATTERN = re.compile(r"(?:e[01]_)?[0-7][0-9a-f]")


@dataclass(frozen=True)
class Backup:
    start: date
    end: date
    counts: Counts
    app_version: str
    exported_at: str

    def select(self, start: date, end: date) -> Counts:
        if not self.start <= start <= end <= self.end:
            raise ValueError("导入日期必须位于备份文件的范围内。")
        return select_counts(self.counts, start, end)


def select_counts(counts: Counts, start: date, end: date) -> Counts:
    lower, upper = start.isoformat(), end.isoformat()
    return {key: value for key, value in counts.items() if lower <= key[0] <= upper}


def _day(value: object) -> date:
    if not isinstance(value, str):
        raise ValueError("日期必须使用 YYYY-MM-DD 格式。")
    try:
        result = date.fromisoformat(value)
    except ValueError as error:
        raise ValueError("备份包含无效日期。") from error
    if value != result.isoformat() or result < MIN_DAY:
        raise ValueError("日期必须使用 YYYY-MM-DD 格式，且不早于 1900-01-01。")
    return result


def _canonical(payload: dict) -> bytes:
    return json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False,
    ).encode("utf-8")


def _checksum(payload: dict) -> str:
    return hashlib.sha256(_canonical(payload)).hexdigest()


def _unique_object(pairs: list) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("备份包含重复字段。")
        result[key] = value
    return result


def _parse(payload: object) -> Backup:
    if not isinstance(payload, dict) or payload.get("format") != FORMAT:
        raise ValueError("这不是敲敲备份文件。")
    if type(payload.get("format_version")) is not int or payload["format_version"] != FORMAT_VERSION:
        raise ValueError("不支持此备份格式版本，请使用兼容版本的敲敲。")
    required = {"format", "format_version", "app_version", "exported_at", "date_range", "daily_counts", "checksum"}
    if set(payload) != required:
        raise ValueError("备份字段不完整或包含当前格式不支持的字段。")
    span = payload["date_range"]
    if not isinstance(span, dict) or set(span) != {"start", "end"}:
        raise ValueError("备份必须明确声明起止日期。")
    start, end = _day(span["start"]), _day(span["end"])
    if start > end:
        raise ValueError("备份起始日期不能晚于结束日期。")
    version, stamp = payload["app_version"], payload["exported_at"]
    if not isinstance(version, str) or not version or len(version) > 64:
        raise ValueError("备份的应用版本无效。")
    try:
        if not isinstance(stamp, str) or len(stamp) > 64:
            raise ValueError()
        if datetime.fromisoformat(stamp).utcoffset() is None:
            raise ValueError()
    except ValueError as error:
        raise ValueError("备份导出时间必须包含时区。") from error
    rows = payload["daily_counts"]
    if not isinstance(rows, list):
        raise ValueError("备份统计记录必须是数组。")
    counts: Counts = {}
    for row in rows:
        if not isinstance(row, dict) or set(row) != {"day", "key_id", "count"}:
            raise ValueError("备份中的统计记录格式无效。")
        day = _day(row["day"])
        key_id, count = row["key_id"], row["count"]
        if not start <= day <= end:
            raise ValueError("备份记录超出了声明的日期范围。")
        # Accept physical scan IDs outside the displayed layouts as well.
        if not isinstance(key_id, str) or KEY_PATTERN.fullmatch(key_id) is None:
            raise ValueError("备份包含无效的物理键标识。")
        if type(count) is not int or not 0 <= count <= MAX_COUNT:
            raise ValueError("敲击次数必须是 SQLite 可保存的非负整数。")
        identity = (row["day"], key_id)
        if identity in counts:
            raise ValueError("备份包含重复的日期与物理键记录。")
        counts[identity] = count
    checksum = payload["checksum"]
    if (not isinstance(checksum, dict) or set(checksum) != {"algorithm", "value"}
            or checksum["algorithm"] != "sha256"
            or not isinstance(checksum["value"], str)
            or re.fullmatch(r"[0-9a-f]{64}", checksum["value"]) is None):
        raise ValueError("备份缺少有效的 SHA-256 校验和。")
    content = {key: value for key, value in payload.items() if key != "checksum"}
    if not hmac.compare_digest(checksum["value"], _checksum(content)):
        raise ValueError("备份校验失败，文件可能已损坏或被修改。")
    return Backup(start, end, counts, version, stamp)


def read_backup(path: Path) -> Backup:
    with Path(path).open("rb") as stream:
        raw = stream.read(MAX_FILE_BYTES + 1)
    if len(raw) > MAX_FILE_BYTES:
        raise ValueError("备份文件超过 64 MiB，请按更小日期范围导出。")
    try:
        payload = json.loads(raw.decode("utf-8-sig"), object_pairs_hook=_unique_object)
        return _parse(payload)
    except (UnicodeError, json.JSONDecodeError, RecursionError) as error:
        raise ValueError("无法读取备份，请选择有效的 UTF-8 JSON 文件。") from error


def write_backup(path: Path, counts: Counts, start: date, end: date) -> Path:
    """Called in the persistence worker with a detached in-memory snapshot."""
    payload = {
        "format": FORMAT,
        "format_version": FORMAT_VERSION,
        "app_version": __version__,
        "exported_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "date_range": {"start": start.isoformat(), "end": end.isoformat()},
        "daily_counts": [
            {"day": day, "key_id": key, "count": count}
            for (day, key), count in sorted(select_counts(counts, start, end).items())
        ],
    }
    payload["checksum"] = {"algorithm": "sha256", "value": _checksum(payload)}
    _parse(payload)
    raw = (json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8")
    if len(raw) > MAX_FILE_BYTES:
        raise ValueError("备份文件超过 64 MiB，请按更小日期范围导出。")
    path = Path(path)
    temporary = None
    try:
        # Same-directory replacement leaves an existing backup intact on failure.
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".qiaoqiao-", suffix=".tmp", delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return path
