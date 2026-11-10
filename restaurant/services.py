"""业务服务，调用方在同一数据库事务中完成权限校验和业务操作。"""

import logging
from decimal import Decimal

from restaurant.domain import (require, positive_int, text, money, total_amount,
                               payment_change, pagination)
from restaurant.security import PasswordHasher

logger = logging.getLogger(__name__)
EMPLOYEE_PUBLIC = "employee_id,username,name,role,phone,create_time,enabled"


class AuthService:
    def __init__(self, db):
        self.db = db
        self.password_hasher = PasswordHasher()
        self._dummy = self.password_hasher.hash("unavailable-account")

    def login(self, username, password):
        username = text(username, "账号", 20)
        require(isinstance(password, str) and 1 <= len(password) <= 128, 400, "密码长度无效")
        employee = self.db.query("SELECT * FROM employee WHERE username=%s", (username,), one=True)
        valid = self.password_hasher.verify(password, employee["password"] if employee else self._dummy)
        require(valid and employee and employee["enabled"], 401, "账号或密码错误，或账号已停用")
        return {key: employee[key] for key in ("employee_id", "name", "role")}

    def require_role(self, session, roles):
        require(session.get("employee_id"), 401, "请先登录")
        employee = self.db.query("SELECT employee_id,name,role,enabled FROM employee WHERE employee_id=%s",
                                 (session["employee_id"],), one=True)
        require(employee and employee["enabled"], 401, "账号已停用，请重新登录")
        require(employee["role"] in roles, 403, "当前角色无权执行此操作")
        return employee


class OrderService:
    def __init__(self, db):
        self.db = db

    def list_tables(self):
        return {"tables": self.db.query("SELECT * FROM dining_table ORDER BY table_id")}

    def _table(self, table_id):
        table_id = positive_int(table_id, "桌台编号")
        table = self.db.query("SELECT * FROM dining_table WHERE table_id=%s FOR UPDATE", (table_id,), one=True)
        require(table, 404, "桌台不存在")
        return table

    def lock_order(self, order_id):
        order_id = positive_int(order_id, "订单编号")
        order = self.db.query("SELECT * FROM orders WHERE order_id=%s FOR UPDATE", (order_id,), one=True)
        require(order, 404, "订单不存在")
        return order

    def items(self, order_id):
        rows = self.db.query("SELECT i.*,d.dish_name FROM order_item i JOIN dish d ON d.dish_id=i.dish_id "
                             "WHERE i.order_id=%s ORDER BY i.item_id", (order_id,))
        for row in rows:
            row["subtotal"] = row["price"] * row["quantity"]
        return rows

    def detail(self, order_id):
        order = self.db.query("SELECT * FROM orders WHERE order_id=%s", (order_id,), one=True)
        require(order, 404, "订单不存在")
        order["order_items"] = self.items(order_id)
        return order

    def open_table(self, table_id):
        table = self._table(table_id)
        require(table["status"] == "空闲", 409, "该桌已经开台，请刷新")
        self.db.execute("UPDATE dining_table SET status='占用' WHERE table_id=%s", (table_id,))
        table["status"] = "占用"
        return table

    def clear_table(self, table_id):
        table = self._table(table_id)
        require(table["status"] == "占用", 409, "桌台已经空闲")
        if table["current_order_id"]:
            order = self.lock_order(table["current_order_id"])
            require(order["table_id"] == table_id, 409, "订单与桌台关联异常")
            require(order["status"] == "已结账", 409, "请先完成结账再清台")
        self.db.execute("UPDATE dining_table SET status='空闲',current_order_id=NULL WHERE table_id=%s", (table_id,))
        table.update(status="空闲", current_order_id=None)
        return table

    def create(self, table_id):
        table = self._table(table_id)
        require(table["status"] == "占用" and table["current_order_id"] is None, 409, "桌台未开台或已有订单")
        return {"table_id": table_id, "items": []}

    def _priced_item(self, item):
        require(isinstance(item, dict), 400, "菜品明细须为对象")
        dish_id = positive_int(item.get("dish_id"), "菜品编号")
        quantity = positive_int(item.get("quantity"), "数量")
        dish = self.db.query("SELECT dish_id,price,status FROM dish WHERE dish_id=%s FOR SHARE", (dish_id,), one=True)
        require(dish, 404, "菜品不存在")
        require(dish["status"] == "在售", 409, "菜品已下架，请重新选择")
        return {"dish_id": dish_id, "quantity": quantity, "price": dish["price"]}

    def submit(self, table_id, items, waiter_id):
        self.create(table_id)
        require(isinstance(items, list) and 1 <= len(items) <= 100, 400, "订单须包含1～100条菜品")
        # 菜品按编号读取，避免不同终端反向获取菜品锁。
        for item in items:
            require(isinstance(item, dict), 400, "菜品明细须为对象")
            positive_int(item.get("dish_id"), "菜品编号")
        priced = [self._priced_item(item) for item in sorted(items, key=lambda x: x["dish_id"])]
        total = total_amount(priced)
        order_id = self.db.execute("INSERT INTO orders(table_id,waiter_id,total_price) VALUES(%s,%s,%s)",
                                   (table_id, waiter_id, total))
        for item in priced:
            self.db.execute("INSERT INTO order_item(order_id,dish_id,quantity,price) VALUES(%s,%s,%s,%s)",
                            (order_id, item["dish_id"], item["quantity"], item["price"]))
        self.db.execute("UPDATE dining_table SET current_order_id=%s WHERE table_id=%s", (order_id, table_id))
        return self.detail(order_id)

    def _recalculate(self, order_id):
        total = total_amount(self.items(order_id))
        self.db.execute("UPDATE orders SET total_price=%s,version=version+1 WHERE order_id=%s", (total, order_id))
        return self.detail(order_id)

    def add_item(self, order_id, item):
        order = self.lock_order(order_id)
        require(order["status"] != "已结账", 409, "已结账订单不能加菜")
        priced = self._priced_item(item)
        self.db.execute("INSERT INTO order_item(order_id,dish_id,quantity,price) VALUES(%s,%s,%s,%s)",
                        (order_id, priced["dish_id"], priced["quantity"], priced["price"]))
        return self._recalculate(order_id)

    def remove_item(self, order_id, item_id, reason):
        order = self.lock_order(order_id)
        positive_int(item_id, "明细编号")
        text(reason, "退菜原因", 200)
        require(order["status"] != "已结账", 409, "已结账订单不能退菜")
        items = self.items(order_id)
        item = next((i for i in items if i["item_id"] == item_id), None)
        require(item, 404, "明细不属于该订单")
        require(item["status"] == "待制作", 409, "仅待制作菜品可以退菜")
        require(len(items) > 1, 409, "订单至少保留一条明细")
        self.db.execute("DELETE FROM order_item WHERE item_id=%s", (item_id,))
        # 原因作为单独字段记录，换行转义以避免日志伪造。
        logger.info("remove_item order_id=%s item_id=%s reason=%r", order_id, item_id, reason)
        return self._recalculate(order_id)


class KitchenService:
    def __init__(self, db, orders):
        self.db = db
        self.orders = orders

    def list_pending(self, filters):
        size, offset = pagination(filters)
        count = self.db.query("SELECT COUNT(*) total FROM orders WHERE status<>'已结账'", one=True)["total"]
        orders = self.db.query("SELECT o.*,t.table_no FROM orders o JOIN dining_table t ON t.table_id=o.table_id "
                               "WHERE o.status<>'已结账' ORDER BY o.order_id LIMIT %s OFFSET %s", (size, offset))
        for order in orders:
            order["items"] = self.orders.items(order["order_id"])
        return {"orders": orders, "total": count}

    def accept(self, order_id):
        order = self.orders.lock_order(order_id)
        require(order["status"] == "已提交", 409, "订单已接单或已结账")
        self.db.execute("UPDATE orders SET status='已接单',version=version+1 WHERE order_id=%s", (order_id,))
        return {"order_id": order_id, "status": "已接单"}

    def _transition(self, order_id, item_id, previous, target):
        order = self.orders.lock_order(order_id)
        positive_int(item_id, "明细编号")
        require(order["status"] == "已接单", 409, "请先接单，已结账订单不可修改")
        item = self.db.query("SELECT * FROM order_item WHERE item_id=%s AND order_id=%s", (item_id, order_id), one=True)
        require(item, 404, "明细不存在或不属于该订单")
        require(item["status"] == previous, 409, "明细状态已变化，请刷新")
        self.db.execute("UPDATE order_item SET status=%s WHERE item_id=%s", (target, item_id))
        self.db.execute("UPDATE orders SET version=version+1 WHERE order_id=%s", (order_id,))
        return {"order_id": order_id, "item_id": item_id, "status": target}

    def start(self, order_id, item_id):
        return self._transition(order_id, item_id, "待制作", "制作中")

    def serve(self, order_id, item_id):
        return self._transition(order_id, item_id, "制作中", "已出菜")


class BillingService:
    def __init__(self, db, orders):
        self.db = db
        self.orders = orders

    def preview(self, order_id):
        positive_int(order_id, "订单编号")
        order = self.orders.detail(order_id)
        require(order["status"] != "已结账", 409, "该订单已经结账，请查询账单")
        return {"order_id": order_id, "items": order["order_items"],
                "total_amount": total_amount(order["order_items"]), "quote_version": order["version"]}

    def settle(self, order_id, version, amount, method, cashier_id):
        positive_int(version, "报价版本")
        paid = money(amount, "实收金额")
        order = self.orders.lock_order(order_id)
        require(order["status"] == "已接单", 409, "订单未接单或已经结账，请查询状态")
        items = self.orders.items(order_id)
        require(items and all(i["status"] == "已出菜" for i in items), 409, "尚有菜品未出菜")
        require(order["version"] == version, 409, "报价已过期，请重新预览并核对收款")
        total = total_amount(items)
        change = payment_change(total, paid, method)
        bill_id = self.db.execute("INSERT INTO bill(order_id,cashier_id,total_amount,paid_amount,pay_method) "
                                  "VALUES(%s,%s,%s,%s,%s)", (order_id, cashier_id, total, paid, method))
        self.db.execute("UPDATE orders SET status='已结账',total_price=%s,version=version+1 WHERE order_id=%s",
                        (total, order_id))
        bill = self.db.query("SELECT * FROM bill WHERE bill_id=%s", (bill_id,), one=True)
        bill["change_amount"] = change
        return bill

    def status(self, order_id, include_bill=False):
        positive_int(order_id, "订单编号")
        order = self.orders.detail(order_id)
        order["items"] = order.pop("order_items")
        if include_bill:
            bill = self.db.query("SELECT * FROM bill WHERE order_id=%s", (order_id,), one=True)
            if bill:
                bill["change_amount"] = bill["paid_amount"] - bill["total_amount"]
            order["bill"] = bill
        return order


class MenuService:
    def __init__(self, db):
        self.db = db

    def search(self, filters):
        size, offset = pagination(filters)
        conditions = ["1=1"]
        values = []
        if filters.get("keyword"):
            conditions.append("dish_name LIKE %s")
            values.append("%" + text(filters["keyword"], "关键字", 50) + "%")
        if filters.get("category_id") is not None:
            conditions.append("category_id=%s")
            values.append(positive_int(filters["category_id"], "分类编号"))
        where = " AND ".join(conditions)
        total = self.db.query("SELECT COUNT(*) total FROM dish WHERE " + where, values, one=True)["total"]
        items = self.db.query("SELECT * FROM dish WHERE " + where + " ORDER BY dish_id LIMIT %s OFFSET %s",
                              values + [size, offset])
        return {"items": items, "total": total, "categories": self.db.query("SELECT * FROM dish_category ORDER BY category_id")}

    def manage_dish(self, action, dish_id, fields, filters):
        if action == "list":
            return self.search(filters)
        clean = {}
        allowed = {"dish_name", "category_id", "price", "status", "description"}
        require(isinstance(fields, dict) and set(fields) <= allowed, 400, "菜品字段不合法")
        if "dish_name" in fields:
            clean["dish_name"] = text(fields["dish_name"], "菜名", 50)
        if "category_id" in fields:
            clean["category_id"] = positive_int(fields["category_id"], "分类编号")
        if "price" in fields:
            clean["price"] = money(fields["price"], "菜价")
        if "status" in fields:
            require(fields["status"] in ("在售", "下架"), 400, "菜品状态无效")
            clean["status"] = fields["status"]
        if "description" in fields:
            clean["description"] = text(fields["description"], "菜品说明", 200, 0)
        return manage_record(self.db, "dish", "dish_id", action, dish_id, clean,
                             {"dish_name", "category_id", "price"})

    def manage_category(self, action, category_id, fields, filters):
        require(isinstance(fields, dict) and set(fields) <= {"category_name"}, 400, "分类字段不合法")
        clean = {"category_name": text(fields["category_name"], "分类名称", 20)} if "category_name" in fields else {}
        return manage_record(self.db, "dish_category", "category_id", action, category_id, clean,
                             {"category_name"}, filters)


class EmployeeService:
    def __init__(self, db):
        self.db = db
        self.password_hasher = PasswordHasher()

    def manage(self, action, employee_id, fields, filters, actor_id):
        allowed = {"username", "password", "name", "role", "phone", "enabled"}
        require(isinstance(fields, dict) and set(fields) <= allowed, 400, "员工字段不合法")
        clean = {}
        for key in ("username", "name", "phone"):
            if key in fields:
                clean[key] = text(fields[key], key, 20, 0 if key == "phone" else 1)
        if "password" in fields:
            password = fields["password"]
            require(isinstance(password, str) and 8 <= len(password) <= 128, 400, "密码须为8～128个字符")
            clean["password"] = self.password_hasher.hash(password)
        if "role" in fields:
            require(fields["role"] in ("管理员", "服务员", "后厨", "收银员"), 400, "角色无效")
            clean["role"] = fields["role"]
        if "enabled" in fields:
            require(type(fields["enabled"]) is bool, 400, "enabled须为布尔值")
            clean["enabled"] = fields["enabled"]
        # 保留一个可登录的管理入口，禁止当前管理员自行删除、停用或降权。
        if employee_id == actor_id:
            require(action != "delete" and clean.get("enabled", True) and
                    clean.get("role", "管理员") == "管理员", 409, "不能删除、停用或降低当前管理员的权限")
        return manage_record(self.db, "employee", "employee_id", action, employee_id, clean,
                             {"username", "password", "name", "role"}, filters, EMPLOYEE_PUBLIC)


def manage_record(db, table, id_field, action, record_id, fields, required, filters=None, projection="*"):
    """表名与列名均来自程序内部白名单，所有用户值通过占位符传入。"""
    require(action in ("list", "create", "update", "delete"), 400, "管理操作无效")
    if action == "list":
        size, offset = pagination(filters or {})
        return {"items": db.query(f"SELECT {projection} FROM {table} ORDER BY {id_field} LIMIT %s OFFSET %s", (size, offset)),
                "total": db.query(f"SELECT COUNT(*) total FROM {table}", one=True)["total"]}
    if action == "create":
        require(required <= fields.keys(), 400, "缺少必填字段")
        columns = ",".join(fields)
        placeholders = ",".join(["%s"] * len(fields))
        record_id = db.execute(f"INSERT INTO {table}({columns}) VALUES({placeholders})", tuple(fields.values()))
    else:
        positive_int(record_id, "记录编号")
        require(db.query(f"SELECT {id_field} FROM {table} WHERE {id_field}=%s FOR UPDATE", (record_id,), one=True),
                404, "记录不存在")
        if action == "delete":
            db.execute(f"DELETE FROM {table} WHERE {id_field}=%s", (record_id,))
            return {id_field: record_id, "deleted": True}
        require(fields, 400, "没有需要修改的字段")
        assignment = ",".join(key + "=%s" for key in fields)
        db.execute(f"UPDATE {table} SET {assignment} WHERE {id_field}=%s", tuple(fields.values()) + (record_id,))
    return db.query(f"SELECT {projection} FROM {table} WHERE {id_field}=%s", (record_id,), one=True)
