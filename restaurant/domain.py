"""领域金额、参数校验和状态对象，共享规则集中在此。"""

import re
from dataclasses import dataclass, field
from decimal import Decimal


class BusinessError(Exception):
    """可返回给客户端的业务错误，code 与详细设计一致。"""

    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def require(condition, code, message):
    if not condition:
        raise BusinessError(code, message)


def positive_int(value, name):
    require(type(value) is int and 0 < value <= 2147483647, 400, f"{name}必须是正整数")
    return value


def text(value, name, maximum, minimum=1):
    require(isinstance(value, str) and minimum <= len(value.strip()) <= maximum,
            400, f"{name}长度应为{minimum}～{maximum}个字符")
    return value.strip()


def money(value, name="金额"):
    require(isinstance(value, str) and re.fullmatch(r"\d{1,6}\.\d{2}", value),
            400, f"{name}须为两位小数字符串，范围0.00～999999.99")
    return Decimal(value)


def total_amount(items):
    total = sum((Decimal(item["price"]) * item["quantity"] for item in items), Decimal("0.00"))
    require(Decimal("0") <= total <= Decimal("999999.99"), 400, "订单金额超出允许范围")
    return total.quantize(Decimal("0.01"))


def payment_change(total, paid, method):
    require(method in ("现金", "扫码", "刷卡"), 400, "支付方式无效")
    require(paid >= total, 400, "实收金额不足")
    require(method == "现金" or paid == total, 400, "扫码或刷卡金额须等于应收")
    return paid - total


def pagination(data):
    page = positive_int(data.get("page", 1), "页码")
    size = positive_int(data.get("page_size", 20), "每页数量")
    require(size <= 100, 400, "每页最多100条")
    return size, (page - 1) * size


@dataclass
class OrderItem:
    dish_id: int
    price: Decimal
    quantity: int
    status: str = "待制作"

    def subtotal(self):
        return self.price * self.quantity

    def can_cancel(self):
        return self.status == "待制作"


@dataclass
class Order:
    status: str = "已提交"
    items: list = field(default_factory=list)

    def calculate_total(self):
        return sum((item.subtotal() for item in self.items), Decimal("0.00"))


@dataclass
class Bill:
    order_id: int
    total_amount: Decimal
    paid_amount: Decimal
    pay_method: str

    def calculate_change(self):
        return payment_change(self.total_amount, self.paid_amount, self.pay_method)
