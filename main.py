"""命令行与打包程序入口。默认启动单机演示。"""

import argparse
import json
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
import sys
import threading

from restaurant.bootstrap import DemoEnvironment, load_config
from restaurant.database import DatabaseHelper
from restaurant.router import RequestRouter
from restaurant.server import RestaurantServer


def configure_logging(config):
    path = Path(config["log_file"])
    path.parent.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(path, maxBytes=2_000_000, backupCount=3, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s:%(lineno)d %(message)s"))
    logging.getLogger().addHandler(handler)
    logging.getLogger().setLevel(logging.INFO)


def main():
    parser = argparse.ArgumentParser(description="餐馆点菜系统")
    parser.add_argument("mode", nargs="?", choices=["demo", "server", "client"], default="demo")
    parser.add_argument("--config", default="config.local.json")
    parser.add_argument("--home", help="单机演示数据目录")
    parser.add_argument("--check", action="store_true", help="检查单机演示环境并退出")
    args = parser.parse_args()
    environment = server = database = None
    try:
        if args.mode == "demo":
            environment = DemoEnvironment(args.home)
            config = environment.start()
        else:
            config = load_config(args.config)
        if args.mode in ("demo", "server"):
            configure_logging(config)
            database = DatabaseHelper(config)
            server = RestaurantServer(config, RequestRouter(database))
            if args.mode == "server":
                server.serve_forever()
                return 0
            threading.Thread(target=server.serve_forever, daemon=True, name="listener").start()
        if args.check:
            from restaurant.client import TcpClient
            client = TcpClient(config)
            try:
                actor = client.request("login", {"username": "waiter", "password": "Demo@12345"})
                tables = client.request("list_tables", {})
                output = {"ok": True, "role": actor["role"], "tables": len(tables["tables"])}
                if sys.stdout:
                    print(json.dumps(output, ensure_ascii=False))
                Path(config["log_file"]).with_name("check-result.json").write_text(json.dumps(output, ensure_ascii=False), encoding="utf-8")
            finally:
                client.close()
            return 0
        from PyQt5.QtWidgets import QApplication
        from restaurant.gui import STYLE, DemoLauncher, ClientWindow
        app = QApplication(sys.argv[:1])
        app.setStyleSheet(STYLE)
        window = DemoLauncher(config) if args.mode == "demo" else ClientWindow(config)
        window.show()
        return app.exec_()
    except KeyboardInterrupt:
        return 0
    except Exception as exc:
        logging.exception("startup_failed")
        if sys.stderr:
            print(f"启动失败：{exc}", file=sys.stderr)
        if getattr(sys, "frozen", False) and not args.check:
            from restaurant.qt_runtime import configure_qt
            configure_qt()
            from PyQt5.QtWidgets import QApplication, QMessageBox
            app = QApplication.instance() or QApplication(sys.argv[:1])
            QMessageBox.critical(None, "启动失败", str(exc))
        return 1
    finally:
        if server:
            server.close()
        if database:
            database.close()
        if environment:
            environment.close()


if __name__ == "__main__":
    sys.exit(main())
