"""独立单元测试，覆盖金额、边界、领域对象、密码和协议。"""

from decimal import Decimal
from datetime import datetime
from io import BytesIO
import pytest

from restaurant.domain import (BusinessError, money, positive_int, total_amount,
                               payment_change, pagination, Order, OrderItem, Bill, text)
from restaurant.security import PasswordHasher
from restaurant.protocol import encode_frame, decode_frame, read_frame, MAX_FRAME


@pytest.mark.parametrize("value", ["-1.00", "1.001", "NaN", "Infinity", "1000000.00", "1", 1.0, None, True])
def test_money_rejects_invalid(value):
    with pytest.raises(BusinessError):
        money(value)


@pytest.mark.parametrize("value", ["0.00", "0.01", "999999.99"])
def test_money_boundaries(value):
    assert money(value) == Decimal(value)


@pytest.mark.parametrize("value", [0, -1, True, None, "1", 2.5, 2147483648])
def test_id_rejects_invalid(value):
    with pytest.raises(BusinessError):
        positive_int(value, "编号")


def test_decimal_arithmetic_and_snapshots():
    assert total_amount([{"price": Decimal("0.10"), "quantity": 3}]) == Decimal("0.30")
    with pytest.raises(BusinessError):
        total_amount([{"price": Decimal("999999.99"), "quantity": 2}])
    item = OrderItem(1, Decimal("12.50"), 2)
    assert item.subtotal() == Decimal("25.00")
    assert item.can_cancel()
    item.status = "制作中"
    assert not item.can_cancel()
    assert Order(items=[item]).calculate_total() == Decimal("25.00")


@pytest.mark.parametrize("paid,method", [("9.00", "现金"), ("11.00", "扫码"), ("11.00", "刷卡"), ("10.00", "未知")])
def test_payment_invalid(paid, method):
    with pytest.raises(BusinessError):
        payment_change(Decimal("10.00"), Decimal(paid), method)


def test_payment_change():
    assert Bill(1, Decimal("10.00"), Decimal("20.00"), "现金").calculate_change() == 10
    assert payment_change(Decimal("10.00"), Decimal("10.00"), "刷卡") == 0


def test_pagination_and_text():
    assert pagination({"page": 2, "page_size": 10}) == (10, 10)
    assert pagination({}) == (20, 0)
    with pytest.raises(BusinessError):
        pagination({"page_size": 101})
    assert text(" 分类 ", "分类", 20) == "分类"
    with pytest.raises(BusinessError):
        text(" ", "分类", 20)


def test_salted_passwords():
    h = PasswordHasher()
    first, second = h.hash("password123"), h.hash("password123")
    assert first != second and len(first) <= 128
    assert h.verify("password123", first)
    assert not h.verify("wrong", first)
    assert not h.verify("password123", "invalid")
    assert not h.verify("password123", first.replace("16384", "2"))


def test_protocol_unicode_decimal_datetime_and_multiple_frames():
    frame = encode_frame({"name": "宫保鸡丁", "price": Decimal("28.00"), "time": datetime(2026, 11, 10)})
    stream = BytesIO(frame * 2)
    data = decode_frame(read_frame(stream))
    assert data["price"] == "28.00" and data["time"].endswith("+08:00")
    assert decode_frame(read_frame(stream)) == data
    assert read_frame(stream) is None


@pytest.mark.parametrize("frame", [b'{"x":NaN}\n', b'bad\n', b'{}', b'\xff\n'])
def test_protocol_invalid(frame):
    with pytest.raises(BusinessError):
        decode_frame(frame)


def test_protocol_size_limit():
    with pytest.raises(BusinessError):
        encode_frame({"data": "中" * MAX_FRAME})
    with pytest.raises(BusinessError):
        read_frame(BytesIO(b"x" * (MAX_FRAME + 1)))
    with pytest.raises(BusinessError):
        read_frame(BytesIO(b"unfinished"))
