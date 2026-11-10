"""Qt 真实窗口与后台 TLS 请求联调，可用 offscreen 平台在测试环境运行。"""

import os
from pathlib import Path
import threading
import time

import pytest
from PyQt5.QtWidgets import QApplication, QMessageBox
from PyQt5.QtGui import QFontDatabase

from restaurant.gui import ClientWindow, RecordDialog, STYLE
from restaurant.server import RestaurantServer


@pytest.mark.integration
def test_four_role_windows_and_waiter_ui(system, mysql_environment, monkeypatch):
    app = QApplication.instance() or QApplication([])
    if os.environ.get("QT_QPA_PLATFORM") == "offscreen":
        QFontDatabase.addApplicationFont("C:/Windows/Fonts/msyh.ttc")
    app.setStyleSheet(STYLE)
    _, _, router, _ = system
    config = dict(mysql_environment[0])
    server = RestaurantServer(config, router)
    config["port"] = server.address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    windows, messages = [], []
    monkeypatch.setattr(QMessageBox, "warning", lambda parent, title, message: messages.append(message))
    monkeypatch.setattr(QMessageBox, "information", lambda parent, title, message: messages.append(message))
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.Yes)
    def wait(window):
        deadline = time.monotonic() + 15
        while window.worker and time.monotonic() < deadline:
            app.processEvents()
            time.sleep(0.01)
        app.processEvents()
        assert window.worker is None
        assert not messages, messages
    def capture(window, name):
        if os.environ.get("RESTAURANT_QA_DIR"):
            path = Path(os.environ["RESTAURANT_QA_DIR"])
            path.mkdir(parents=True, exist_ok=True)
            window.grab().save(str(path / (name + ".png")))
    try:
        for username in ("waiter", "kitchen", "cashier", "admin"):
            window = ClientWindow(config, username)
            windows.append(window)
            window.show()
            window.password.setText("Demo@12345")
            window.login()
            wait(window)
            assert window.actor["role"] in window.windowTitle()
        waiter, kitchen, cashier, admin = windows
        waiter.tables.selectRow(0)
        waiter.table_action("open_table")
        wait(waiter)
        waiter.tables.selectRow(0)
        waiter.menu.selectRow(0)
        waiter.quantity.setValue(2)
        waiter.add_draft()
        assert len(waiter.draft) == 1
        waiter.submit_draft()
        wait(waiter)
        assert waiter.order_items.rowCount() == 1
        capture(waiter, "waiter")
        kitchen.refresh_kitchen()
        wait(kitchen)
        kitchen.kitchen_orders.selectRow(0)
        kitchen.kitchen_action("accept_order")
        wait(kitchen)
        kitchen.kitchen_orders.selectRow(0)
        kitchen.kitchen_items.selectRow(0)
        kitchen.kitchen_action("start_item")
        wait(kitchen)
        kitchen.kitchen_orders.selectRow(0)
        kitchen.kitchen_items.selectRow(0)
        kitchen.kitchen_action("mark_served")
        wait(kitchen)
        kitchen.kitchen_orders.selectRow(0)
        capture(kitchen, "kitchen")
        cashier.bill_order_id.setValue(waiter.order_id.value())
        cashier.preview()
        wait(cashier)
        cashier.paid.setValue(100)
        cashier.settle()
        wait(cashier)
        assert "结账成功" in cashier.bill_result.text()
        capture(cashier, "cashier")
        capture(admin, "admin")
        waiter.refresh_tables()
        wait(waiter)
        waiter.tables.selectRow(0)
        waiter.table_action("clear_table")
        wait(waiter)
        assert waiter.tables.rows[0]["status"] == "空闲"
        dialog = RecordDialog("employee", {"employee_id": 2, "username": "waiter", "enabled": True}, admin)
        assert "password" not in dialog.values()
    finally:
        for window in windows:
            if window.worker:
                wait(window)
            window.close()
        server.close()
        thread.join(timeout=2)
