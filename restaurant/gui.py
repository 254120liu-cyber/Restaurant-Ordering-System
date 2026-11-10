"""四角色桌面界面，所有网络请求在后台线程串行执行。"""

from PyQt5.QtCore import Qt, QThread, pyqtSignal
from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QTableWidget,
    QTableWidgetItem, QHeaderView, QMessageBox, QFormLayout, QDialog, QDialogButtonBox,
    QSplitter, QGroupBox, QAbstractItemView)

from restaurant.client import TcpClient
from restaurant.domain import BusinessError
from restaurant.qt_runtime import configure_qt

configure_qt()

STYLE = """
QWidget { font-family: 'Microsoft YaHei'; font-size: 13px; color: #203442; }
QMainWindow, QDialog { background: #f3f6f8; }
QLabel#title { font-size: 24px; font-weight: bold; color: #124f5c; padding: 8px 0; }
QPushButton { background: #176b78; color: white; border: none; border-radius: 5px;
              padding: 8px 14px; min-height: 18px; }
QPushButton:hover { background: #218493; }
QPushButton:disabled { background: #9eacb1; color: #e7eded; }
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox { background: white; padding: 6px;
              border: 1px solid #c4d2d8; border-radius: 4px; }
QTableWidget { background: white; alternate-background-color: #edf4f5; border: 1px solid #c4d2d8;
               selection-background-color: #c5e4e8; selection-color: #102f36; }
QHeaderView::section { background: #e0ebef; padding: 7px; border: none; font-weight: bold; }
QGroupBox { border: 1px solid #c4d2d8; border-radius: 6px; margin-top: 14px; padding-top: 15px; }
QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 4px; }
"""


class RequestWorker(QThread):
    succeeded = pyqtSignal(object)
    failed = pyqtSignal(int, str)

    def __init__(self, client, action, data, parent):
        super().__init__(parent)
        self.client, self.action, self.data = client, action, data

    def run(self):
        try:
            self.succeeded.emit(self.client.request(self.action, self.data))
        except BusinessError as exc:
            self.failed.emit(exc.code, str(exc))
        except Exception:
            self.failed.emit(0, "连接中断或请求超时。请重新登录，先查询订单或账单状态再决定是否重试。")


def button(label, callback):
    result = QPushButton(label)
    result.clicked.connect(callback)
    return result


def horizontal(*widgets):
    box = QHBoxLayout()
    for widget in widgets:
        box.addWidget(widget)
    return box


def table():
    result = QTableWidget()
    result.setSelectionBehavior(QAbstractItemView.SelectRows)
    result.setSelectionMode(QAbstractItemView.SingleSelection)
    result.setEditTriggers(QAbstractItemView.NoEditTriggers)
    result.setAlternatingRowColors(True)
    result.verticalHeader().hide()
    result.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
    return result


def populate(widget, rows, columns):
    widget.clearSelection()
    widget.setCurrentCell(-1, -1)
    widget.rows = rows
    widget.setColumnCount(len(columns))
    widget.setHorizontalHeaderLabels([label for _, label in columns])
    widget.setRowCount(len(rows))
    for row_index, row in enumerate(rows):
        for col_index, (key, _) in enumerate(columns):
            value = row.get(key)
            widget.setItem(row_index, col_index, QTableWidgetItem("—" if value is None else str(value)))


def selected(widget):
    index = widget.currentRow()
    if index < 0 or index >= len(getattr(widget, "rows", [])):
        QMessageBox.information(widget, "请选择", "请先在表格中选择一行。")
        return None
    return widget.rows[index]


ITEM_COLUMNS = [("item_id", "明细号"), ("dish_name", "菜名"), ("quantity", "数量"),
                ("price", "单价"), ("subtotal", "小计"), ("status", "状态")]


class ClientWindow(QMainWindow):
    def __init__(self, config, username=""):
        super().__init__()
        self.client = TcpClient(config)
        self.worker = None
        self.draft = []
        self.quote = None
        self.setWindowTitle("餐馆点菜系统")
        self.resize(1150, 790)
        self._show_login(username)

    def _base(self, title):
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(22, 16, 22, 20)
        label = QLabel(title)
        label.setObjectName("title")
        layout.addWidget(label)
        self.setCentralWidget(panel)
        return layout

    def request(self, action, data, callback):
        if self.worker is not None:
            return
        self.centralWidget().setEnabled(False)
        self.statusBar().showMessage("正在处理，请稍候…")
        worker = RequestWorker(self.client, action, data, self)
        self.worker = worker
        self._pending = None
        worker.succeeded.connect(lambda result: setattr(self, "_pending", (True, result)))
        worker.failed.connect(lambda code, msg: setattr(self, "_pending", (False, (code, msg))))
        def finished():
            self.worker = None
            self.centralWidget().setEnabled(True)
            worker.deleteLater()
            success, result = self._pending
            if success:
                self.statusBar().showMessage("操作完成", 8000)
                callback(result)
            else:
                code, message = result
                self.statusBar().showMessage(message)
                QMessageBox.warning(self, "操作提示", message)
                if code in (0, 401):
                    self._show_login()
        worker.finished.connect(finished)
        worker.start()

    def _show_login(self, username=""):
        self.draft, self.quote = [], None
        layout = self._base("餐馆点菜系统 · 员工登录")
        layout.addWidget(QLabel("使用分配的员工账号登录，系统按角色提供操作界面。"))
        layout.addStretch()
        form = QFormLayout()
        self.username, self.password = QLineEdit(username), QLineEdit()
        self.password.setEchoMode(QLineEdit.Password)
        form.addRow("员工账号", self.username)
        form.addRow("登录密码", self.password)
        layout.addLayout(form)
        layout.addWidget(button("登录", self.login))
        self.password.returnPressed.connect(self.login)
        layout.addStretch(2)

    def login(self):
        self.request("login", {"username": self.username.text(), "password": self.password.text()}, self._logged_in)

    def _logged_in(self, actor):
        self.actor = actor
        self.setWindowTitle(f"餐馆点菜系统 · {actor['role']} · {actor['name']}")
        layout = self._base(f"{actor['role']}工作台")
        layout.addLayout(horizontal(QLabel(f"当前员工  {actor['name']}"),
                         button("退出登录", lambda: self.request("logout", {}, lambda r: self._show_login()))))
        {"服务员": self._waiter, "后厨": self._kitchen, "收银员": self._cashier, "管理员": self._admin}[actor["role"]](layout)

    def _waiter(self, layout):
        self.tables, self.menu, self.draft_table, self.order_items = table(), table(), table(), table()
        self.order_id = QSpinBox()
        self.order_id.setRange(1, 2147483647)
        self.quantity = QSpinBox()
        self.quantity.setRange(1, 999)
        self.keyword, self.category = QLineEdit(), QComboBox()
        self.keyword.setPlaceholderText("按菜名搜索")
        self.category.addItem("全部分类", None)
        self.menu_page = QSpinBox()
        self.menu_page.setRange(1, 999999)
        self.menu_count = QLabel()
        splitter = QSplitter(Qt.Horizontal)
        left, right = QWidget(), QWidget()
        a, b = QVBoxLayout(left), QVBoxLayout(right)
        a.addWidget(QLabel("餐桌状态"))
        a.addWidget(self.tables)
        a.addLayout(horizontal(button("刷新桌台", self.refresh_tables), button("开台", lambda: self.table_action("open_table")),
                               button("清台", lambda: self.table_action("clear_table"))))
        a.addWidget(QLabel("当前草稿 · 选择桌台后加入菜品"))
        a.addWidget(self.draft_table)
        self.draft_label = QLabel("草稿为空")
        a.addWidget(self.draft_label)
        a.addLayout(horizontal(button("移除草稿行", self.remove_draft), button("提交订单", self.submit_draft)))
        b.addLayout(horizontal(self.keyword, self.category, QLabel("页"), self.menu_page, button("查询", self.refresh_menu)))
        b.addWidget(self.menu_count)
        b.addWidget(self.menu)
        b.addLayout(horizontal(QLabel("数量"), self.quantity, button("加入草稿", self.add_draft), button("追加到订单", self.add_to_order)))
        b.addLayout(horizontal(QLabel("订单号"), self.order_id, button("查询订单", self.refresh_order)))
        b.addWidget(self.order_items)
        self.reason = QLineEdit()
        self.reason.setPlaceholderText("退菜原因（仅待制作明细可整行退菜）")
        b.addLayout(horizontal(self.reason, button("退选中菜品", self.remove_order_item)))
        self.order_label = QLabel("选择桌台可读取当前订单号")
        b.addWidget(self.order_label)
        splitter.addWidget(left)
        splitter.addWidget(right)
        splitter.setSizes([440, 650])
        layout.addWidget(splitter)
        self.tables.itemSelectionChanged.connect(self._table_selected)
        self.refresh_tables(after=self.refresh_menu)

    def _table_selected(self):
        index = self.tables.currentRow()
        if 0 <= index < len(getattr(self.tables, "rows", [])):
            row = self.tables.rows[index]
            if row["current_order_id"]:
                self.order_id.setValue(row["current_order_id"])

    def refresh_tables(self, checked=False, after=None):
        def done(result):
            populate(self.tables, result["tables"], [("table_no", "桌号"), ("seats", "座位"), ("status", "状态"), ("current_order_id", "当前订单")])
            if after:
                after()
        self.request("list_tables", {}, done)

    def table_action(self, action):
        row = selected(self.tables)
        if row:
            self.request(action, {"table_id": row["table_id"]}, lambda r: self.refresh_tables())

    def refresh_menu(self):
        data = {"keyword": self.keyword.text(), "page": self.menu_page.value(), "page_size": 20}
        category = self.category.currentData()
        if category:
            data["category_id"] = category
        def done(result):
            populate(self.menu, result["items"], [("dish_name", "菜名"), ("price", "单价"), ("status", "状态")])
            self.menu_count.setText(f"共 {result['total']} 道菜 · 第 {self.menu_page.value()} 页，每页20条")
            self.category.clear()
            self.category.addItem("全部分类", None)
            for row in result["categories"]:
                self.category.addItem(row["category_name"], row["category_id"])
            self.category.setCurrentIndex(max(0, self.category.findData(category)))
        self.request("list_dishes", data, done)

    def add_draft(self):
        row, dining = selected(self.menu), selected(self.tables)
        if not row or not dining:
            return
        if self.draft and self.draft_table_id != dining["table_id"]:
            QMessageBox.warning(self, "草稿提示", "当前草稿属于另一张桌，请先提交或移除全部草稿行。")
            return
        if dining["status"] != "占用" or dining["current_order_id"]:
            QMessageBox.warning(self, "桌台提示", "请先开台，已有订单请使用追加到订单。")
            return
        if row["status"] != "在售":
            QMessageBox.warning(self, "菜品提示", "该菜品已下架。")
            return
        self.draft_table_id, self.draft_table_no = dining["table_id"], dining["table_no"]
        self.draft.append({"dish_id": row["dish_id"], "dish_name": row["dish_name"], "quantity": self.quantity.value(), "price": row["price"]})
        self.show_draft()

    def show_draft(self):
        populate(self.draft_table, self.draft, [("dish_name", "菜名"), ("quantity", "数量"), ("price", "参考单价")])
        self.draft_label.setText(f"{self.draft_table_no} 桌 · {len(self.draft)}条 · 提交时按服务器价格计价" if self.draft else "草稿为空")

    def remove_draft(self):
        if selected(self.draft_table):
            self.draft.pop(self.draft_table.currentRow())
            self.show_draft()

    def submit_draft(self):
        if not self.draft:
            QMessageBox.information(self, "草稿提示", "请先加入菜品。")
            return
        data = {"table_id": self.draft_table_id, "items": [{"dish_id": i["dish_id"], "quantity": i["quantity"]} for i in self.draft]}
        def done(result):
            self.draft = []
            self.show_draft()
            self.order_id.setValue(result["order_id"])
            self.show_order(result)
            self.refresh_tables()
        self.request("submit_order", data, done)

    def show_order(self, result):
        populate(self.order_items, result.get("items", result.get("order_items", [])), ITEM_COLUMNS)
        self.order_label.setText(f"订单 {result['order_id']} · {result['status']} · 应收 ¥{result['total_price']}")

    def refresh_order(self):
        self.request("get_order_status", {"order_id": self.order_id.value()}, self.show_order)

    def add_to_order(self):
        row = selected(self.menu)
        if row:
            self.request("add_item", {"order_id": self.order_id.value(), "dish_id": row["dish_id"], "quantity": self.quantity.value()}, self.show_order)

    def remove_order_item(self):
        row = selected(self.order_items)
        if row:
            self.request("remove_item", {"order_id": self.order_id.value(), "item_id": row["item_id"], "reason": self.reason.text()}, self.show_order)

    def _kitchen(self, layout):
        self.kitchen_page = QSpinBox()
        self.kitchen_page.setRange(1, 999999)
        self.kitchen_label = QLabel("按订单接单，再逐项开始制作和标记出菜")
        layout.addLayout(horizontal(QLabel("页码"), self.kitchen_page, button("刷新订单", self.refresh_kitchen), self.kitchen_label))
        self.kitchen_orders, self.kitchen_items = table(), table()
        layout.addWidget(self.kitchen_orders)
        layout.addWidget(button("接选中订单", lambda: self.kitchen_action("accept_order")))
        layout.addWidget(self.kitchen_items)
        layout.addLayout(horizontal(button("开始制作", lambda: self.kitchen_action("start_item")),
                                   button("标记出菜", lambda: self.kitchen_action("mark_served"))))
        self.kitchen_orders.itemSelectionChanged.connect(self.show_kitchen_items)
        self.refresh_kitchen()

    def refresh_kitchen(self):
        def done(result):
            populate(self.kitchen_orders, result["orders"], [("order_id", "订单号"), ("table_no", "桌号"), ("status", "状态"), ("order_time", "下单时间")])
            populate(self.kitchen_items, [], ITEM_COLUMNS)
            self.kitchen_label.setText(f"共 {result['total']} 个未结账订单，每页10个")
        self.request("list_kitchen_orders", {"page": self.kitchen_page.value(), "page_size": 10}, done)

    def show_kitchen_items(self):
        i = self.kitchen_orders.currentRow()
        if 0 <= i < len(getattr(self.kitchen_orders, "rows", [])):
            populate(self.kitchen_items, self.kitchen_orders.rows[i]["items"], ITEM_COLUMNS)

    def kitchen_action(self, action):
        order = selected(self.kitchen_orders)
        if not order:
            return
        data = {"order_id": order["order_id"]}
        if action != "accept_order":
            item = selected(self.kitchen_items)
            if not item:
                return
            data["item_id"] = item["item_id"]
        self.request(action, data, lambda r: self.refresh_kitchen())

    def _cashier(self, layout):
        self.bill_order_id = QSpinBox()
        self.bill_order_id.setRange(1, 2147483647)
        layout.addLayout(horizontal(QLabel("订单号"), self.bill_order_id, button("预览账单", self.preview), button("查询订单与收款结果", self.bill_status)))
        layout.addWidget(QLabel("先核对明细与应收，再确认现场已收款。扫码和刷卡在本系统中登记收款结果。"))
        self.bill_items = table()
        layout.addWidget(self.bill_items)
        self.bill_total = QLabel("请先预览账单")
        self.bill_total.setObjectName("title")
        layout.addWidget(self.bill_total)
        self.pay_method, self.paid = QComboBox(), QDoubleSpinBox()
        self.pay_method.addItems(["现金", "扫码", "刷卡"])
        self.paid.setRange(0, 999999.99)
        self.paid.setDecimals(2)
        layout.addLayout(horizontal(QLabel("支付方式"), self.pay_method, QLabel("实际收款"), self.paid,
                                   button("确认已收款并结账", self.settle)))
        self.bill_result = QLabel("超时或重复提示时，先查询收款结果。")
        self.bill_result.setWordWrap(True)
        layout.addWidget(self.bill_result)
        self.bill_order_id.valueChanged.connect(lambda: setattr(self, "quote", None))

    def preview(self):
        def done(result):
            self.quote = result
            populate(self.bill_items, result["items"], ITEM_COLUMNS)
            self.bill_total.setText(f"订单 {result['order_id']} · 应收 ¥{result['total_amount']}")
            self.paid.setValue(float(result["total_amount"]))
            self.bill_result.setText(f"当前报价版本 {result['quote_version']}，请核对现场收款。")
        self.request("preview_bill", {"order_id": self.bill_order_id.value()}, done)

    def settle(self):
        if not self.quote:
            QMessageBox.information(self, "请先核对", "请先预览当前订单账单。")
            return
        if QMessageBox.question(self, "确认收款", f"确认已收到 {self.paid.value():.2f} 元？") != QMessageBox.Yes:
            return
        data = {"order_id": self.quote["order_id"], "quote_version": self.quote["quote_version"],
                "paid_amount": f"{self.paid.value():.2f}", "pay_method": self.pay_method.currentText()}
        self.request("settle_bill", data, self.show_bill)

    def show_bill(self, bill):
        self.quote = None
        self.bill_result.setText(f"结账成功 · 账单 {bill['bill_id']} · 订单 {bill['order_id']}\n"
                                f"应收 ¥{bill['total_amount']}  实收 ¥{bill['paid_amount']}  找零 ¥{bill['change_amount']}\n"
                                f"支付方式 {bill['pay_method']}  时间 {bill['pay_time']}")

    def bill_status(self):
        def done(result):
            populate(self.bill_items, result["items"], ITEM_COLUMNS)
            self.bill_total.setText(f"订单 {result['order_id']} · {result['status']} · ¥{result['total_price']}")
            if result.get("bill"):
                self.show_bill(result["bill"])
            else:
                self.bill_result.setText("尚无已提交账单，请核对现场收款后重新预览。")
        self.request("get_order_status", {"order_id": self.bill_order_id.value()}, done)

    def _admin(self, layout):
        self.entity = QComboBox()
        for label, value in [("菜品", "dish"), ("分类", "category"), ("员工", "employee")]:
            self.entity.addItem(label, value)
        self.admin_page = QSpinBox()
        self.admin_page.setRange(1, 999999)
        self.admin_label = QLabel()
        layout.addLayout(horizontal(self.entity, QLabel("页"), self.admin_page, button("刷新", self.refresh_admin), self.admin_label))
        self.admin_table = table()
        layout.addWidget(self.admin_table)
        layout.addLayout(horizontal(button("新增", lambda: self.edit_record(False)), button("修改选中项", lambda: self.edit_record(True)),
                                   button("删除选中项", self.delete_record)))
        layout.addWidget(QLabel("被历史记录引用的菜品和员工可改为下架或停用。员工密码仅在新建或重设时输入。"))
        self.entity.currentIndexChanged.connect(lambda: (self.admin_page.setValue(1), self.refresh_admin()))
        self.refresh_admin()

    def refresh_admin(self):
        entity = self.entity.currentData()
        columns = {
            "dish": [("dish_id", "编号"), ("dish_name", "菜名"), ("category_id", "分类号"), ("price", "单价"), ("status", "状态"), ("description", "说明")],
            "category": [("category_id", "编号"), ("category_name", "分类名称")],
            "employee": [("employee_id", "编号"), ("username", "账号"), ("name", "姓名"), ("role", "角色"), ("phone", "电话"), ("enabled", "启用")],
        }
        def done(result):
            populate(self.admin_table, result["items"], columns[entity])
            self.admin_label.setText(f"共 {result['total']} 条，每页20条")
        self.request("manage_" + entity, {"action": "list", "page": self.admin_page.value(), "page_size": 20}, done)

    def edit_record(self, editing):
        entity = self.entity.currentData()
        record = selected(self.admin_table) if editing else {}
        if record is None:
            return
        dialog = RecordDialog(entity, record, self)
        if dialog.exec_() == QDialog.Accepted:
            data = {"action": "update" if editing else "create", "fields": dialog.values()}
            if editing:
                data[entity + "_id"] = record[entity + "_id"]
            self.request("manage_" + entity, data, lambda r: self.refresh_admin())

    def delete_record(self):
        record = selected(self.admin_table)
        if record and QMessageBox.question(self, "确认删除", "确认删除选中的记录？被引用的记录会保留。") == QMessageBox.Yes:
            entity = self.entity.currentData()
            self.request("manage_" + entity, {"action": "delete", entity + "_id": record[entity + "_id"]}, lambda r: self.refresh_admin())

    def closeEvent(self, event):
        if self.worker:
            QMessageBox.information(self, "正在处理", "当前操作尚未返回，请稍候再关闭。")
            event.ignore()
            return
        self.client.close()
        event.accept()


class RecordDialog(QDialog):
    def __init__(self, entity, record, parent):
        super().__init__(parent)
        self.setWindowTitle("维护资料")
        self.setMinimumWidth(430)
        self.entity, self.record, self.inputs = entity, record, {}
        form = QFormLayout(self)
        specs = {
            "dish": [("dish_name", "菜名", None), ("category_id", "分类编号", "int"), ("price", "单价", "money"),
                     ("status", "状态", ["在售", "下架"]), ("description", "说明", None)],
            "category": [("category_name", "分类名称", None)],
            "employee": [("username", "账号", None), ("name", "姓名", None), ("password", "密码（修改时留空保留）", "password"),
                         ("role", "角色", ["服务员", "后厨", "收银员", "管理员"]), ("phone", "电话", None), ("enabled", "是否启用", ["启用", "停用"])],
        }
        for key, label, kind in specs[entity]:
            value = record.get(key)
            if isinstance(kind, list):
                widget = QComboBox()
                widget.addItems(kind)
                if key == "enabled":
                    widget.setCurrentIndex(0 if value is None or value else 1)
                elif value:
                    widget.setCurrentText(str(value))
            elif kind == "int":
                widget = QSpinBox()
                widget.setRange(1, 2147483647)
                widget.setValue(value or 1)
            elif kind == "money":
                widget = QDoubleSpinBox()
                widget.setRange(0, 999999.99)
                widget.setValue(float(value or 0))
            else:
                widget = QLineEdit(str(value or ""))
                if kind == "password":
                    widget.setEchoMode(QLineEdit.Password)
            form.addRow(label, widget)
            self.inputs[key] = widget
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def values(self):
        values = {}
        for key, widget in self.inputs.items():
            if isinstance(widget, QComboBox):
                values[key] = widget.currentText() if key != "enabled" else widget.currentIndex() == 0
            elif isinstance(widget, QDoubleSpinBox):
                values[key] = f"{widget.value():.2f}"
            elif isinstance(widget, QSpinBox):
                values[key] = widget.value()
            else:
                values[key] = widget.text()
        if self.record and values.get("password") == "":
            values.pop("password")
        return values


class DemoLauncher(QMainWindow):
    def __init__(self, config):
        super().__init__()
        self.config, self.windows = config, []
        self.setWindowTitle("餐馆点菜系统 · 单机演示")
        self.resize(650, 430)
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(30, 24, 30, 24)
        title = QLabel("餐馆点菜系统")
        title.setObjectName("title")
        layout.addWidget(title)
        layout.addWidget(QLabel("单机演示服务已就绪 · MySQL 8.0 · TCP/TLS"))
        layout.addWidget(QLabel("依次演示开台点菜 → 后厨接单出菜 → 收银结账 → 服务员清台"))
        for label, username in [("服务员工作台", "waiter"), ("后厨工作台", "kitchen"), ("收银工作台", "cashier"), ("管理工作台", "admin")]:
            layout.addWidget(button(label, lambda checked=False, name=username: self.open_client(name)))
        layout.addWidget(QLabel("演示账号与按钮对应，初始密码均为 Demo@12345\n关闭本窗口会停止本次演示服务，数据库内容保留。"))
        self.setCentralWidget(panel)

    def open_client(self, username):
        window = ClientWindow(self.config, username)
        self.windows.append(window)
        window.show()

    def closeEvent(self, event):
        if any(window.worker for window in self.windows):
            QMessageBox.information(self, "正在处理", "请等待客户端当前操作完成后退出。")
            event.ignore()
            return
        for window in self.windows:
            window.close()
        event.accept()
