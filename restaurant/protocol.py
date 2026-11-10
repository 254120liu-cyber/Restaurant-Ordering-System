"""TLS 上的 UTF-8 JSON 行协议，每帧最多64 KiB（含换行）。"""

import json
from datetime import datetime, timezone, timedelta
from decimal import Decimal

from restaurant.domain import BusinessError

MAX_FRAME = 65536


def json_value(value):
    if isinstance(value, Decimal):
        return format(value, ".2f")
    if isinstance(value, datetime):
        return value.replace(tzinfo=timezone(timedelta(hours=8))).isoformat()
    raise TypeError(f"Cannot serialize {type(value).__name__}")


def encode_frame(payload):
    encoded = (json.dumps(payload, ensure_ascii=False, default=json_value, allow_nan=False) + "\n").encode("utf-8")
    if len(encoded) > MAX_FRAME:
        raise BusinessError(400, "消息过长，请减少查询数量或提交条目")
    return encoded


def decode_frame(frame):
    try:
        if not frame.endswith(b"\n") or len(frame) > MAX_FRAME:
            raise ValueError("invalid frame")
        return json.loads(frame.decode("utf-8"), parse_constant=lambda x: (_ for _ in ()).throw(ValueError(x)))
    except (ValueError, UnicodeDecodeError, RecursionError) as exc:
        raise BusinessError(400, "JSON消息格式不正确") from exc


def read_frame(stream):
    frame = stream.readline(MAX_FRAME + 1)
    if not frame:
        return None
    if len(frame) > MAX_FRAME or not frame.endswith(b"\n"):
        raise BusinessError(400, "帧超过64 KiB或未完整结束，连接已关闭")
    return frame
