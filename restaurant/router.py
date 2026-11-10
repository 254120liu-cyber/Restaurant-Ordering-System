"""统一身份授权、事务边界、业务分发和异常响应。"""

import logging
import pymysql

from restaurant.domain import BusinessError, require
from restaurant.services import AuthService, MenuService, OrderService, KitchenService, BillingService, EmployeeService

logger = logging.getLogger(__name__)


class RequestRouter:
    def __init__(self, db):
        self.db = db
        self.auth = AuthService(db)
        self.menu = MenuService(db)
        self.orders = OrderService(db)
        self.kitchen = KitchenService(db, self.orders)
        self.billing = BillingService(db, self.orders)
        self.employees = EmployeeService(db)
        self.role_rules = {}
        for role, names in {
            "服务员": ("list_tables", "open_table", "clear_table", "list_dishes", "create_order", "submit_order", "add_item", "remove_item", "get_order_status"),
            "后厨": ("list_kitchen_orders", "accept_order", "start_item", "mark_served"),
            "收银员": ("preview_bill", "settle_bill", "get_order_status"),
            "管理员": ("manage_dish", "manage_category", "manage_employee"),
        }.items():
            for name in names:
                self.role_rules.setdefault(name, set()).add(role)

    def _handle(self, action, data, actor):
        order_id, table_id = data.get("order_id"), data.get("table_id")
        handlers = {
            "list_tables": lambda: self.orders.list_tables(),
            "open_table": lambda: self.orders.open_table(table_id),
            "clear_table": lambda: self.orders.clear_table(table_id),
            "create_order": lambda: self.orders.create(table_id),
            "list_dishes": lambda: self.menu.search(data),
            "submit_order": lambda: self.orders.submit(table_id, data.get("items"), actor["employee_id"]),
            "add_item": lambda: self.orders.add_item(order_id, data),
            "remove_item": lambda: self.orders.remove_item(order_id, data.get("item_id"), data.get("reason")),
            "list_kitchen_orders": lambda: self.kitchen.list_pending(data),
            "accept_order": lambda: self.kitchen.accept(order_id),
            "start_item": lambda: self.kitchen.start(order_id, data.get("item_id")),
            "mark_served": lambda: self.kitchen.serve(order_id, data.get("item_id")),
            "preview_bill": lambda: self.billing.preview(order_id),
            "settle_bill": lambda: self.billing.settle(order_id, data.get("quote_version"), data.get("paid_amount"),
                                                       data.get("pay_method"), actor["employee_id"]),
            "get_order_status": lambda: self.billing.status(order_id, actor["role"] == "收银员"),
            "manage_dish": lambda: self.menu.manage_dish(data.get("action"), data.get("dish_id"), data.get("fields", {}), data),
            "manage_category": lambda: self.menu.manage_category(data.get("action"), data.get("category_id"), data.get("fields", {}), data),
            "manage_employee": lambda: self.employees.manage(data.get("action"), data.get("employee_id"), data.get("fields", {}), data, actor["employee_id"]),
        }
        return handlers[action]()

    def dispatch(self, session, request):
        request_id, action, code = None, None, 0
        try:
            require(isinstance(request, dict), 400, "请求须为对象")
            request_id = request.get("request_id")
            require(isinstance(request_id, str) and 1 <= len(request_id) <= 64 and
                    all(c.isalnum() or c in "-_." for c in request_id), 400, "请求编号须为1～64位字母、数字或-_.")
            action, data = request.get("type"), request.get("data")
            require(isinstance(action, str) and len(action) <= 40 and isinstance(data, dict), 400, "type或data格式错误")
            if action == "logout":
                session.clear()
                result = {}
            elif action == "login":
                session.clear()
                result = self.db.transaction(lambda c: self.auth.login(data.get("username"), data.get("password")))
                session["employee_id"] = result["employee_id"]
            else:
                require(action in self.role_rules, 400, "未知业务请求")
                def work(connection):
                    actor = self.auth.require_role(session, self.role_rules[action])
                    return self._handle(action, data, actor)
                result = self.db.transaction(work, readonly=action in ("preview_bill", "get_order_status"))
            return {"request_id": request_id, "code": 0, "msg": "成功", "data": result}
        except BusinessError as exc:
            code, message = exc.code, str(exc)
        except pymysql.IntegrityError as exc:
            code, message = 409, "记录重复或被其他数据引用，请检查后重试"
            logger.warning("constraint request_id=%r sql_error=%s", request_id, exc.args[0])
        except (pymysql.OperationalError, pymysql.InterfaceError):
            code, message = 503, "数据库暂时不可用，请查询状态后再操作"
            logger.exception("database_unavailable request_id=%r", request_id)
        except Exception:
            code, message = 500, "服务暂时异常，请保留请求编号并联系管理员"
            logger.exception("request_failed request_id=%r", request_id)
        finally:
            logger.info("request request_id=%r employee_id=%s action=%r code=%s",
                        request_id if isinstance(request_id, str) else None, session.get("employee_id"), action, code)
        return {"request_id": request_id if isinstance(request_id, str) and len(request_id) <= 64 else None,
                "code": code, "msg": message, "data": {}}
