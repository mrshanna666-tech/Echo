"""Open an isolated synthetic atlas, or render QA captures without recording."""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta
import os
from pathlib import Path
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--interactive", action="store_true")
    parser.add_argument("--start-home", action="store_true", help="Start the interactive demo on Home to try the atlas entrance")
    parser.add_argument("--native-capture", action="store_true", help="Capture the native OpenGL window instead of headless painter output")
    parser.add_argument("--output", type=Path, default=ROOT / "screenshots" / "memory-atlas.png")
    args = parser.parse_args()
    if args.start_home and not args.interactive:
        parser.error("--start-home requires --interactive")
    scratch = ROOT / "build" / "atlas-preview"
    scratch.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=scratch) as directory:
        os.environ["ECHO_DATA_DIR"] = directory
        os.environ["ECHO_DEMO_MODE"] = "1"
        os.environ["ECHO_LANGUAGE"] = "zh-CN"
        if not args.interactive:
            os.environ["ECHO_REDUCE_MOTION"] = "1"
        if not args.interactive and not args.native_capture:
            os.environ["QT_QPA_PLATFORM"] = "offscreen"

        from PySide6.QtCore import QEvent
        from PySide6.QtGui import QFont, QFontDatabase
        from PySide6.QtWidgets import QApplication
        from src.database.db import Database
        from src.ui.today_window import TodayWindow
        from src.utils.time_utils import to_db_datetime

        app = QApplication([])
        # The offscreen Qt platform has no Windows font database. Register
        # installed fonts explicitly so the QA render matches the real window.
        if not args.interactive:
            for filename in ("msyh.ttc", "msyhbd.ttc", "segoeui.ttf"):
                path = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts" / filename
                if path.exists():
                    QFontDatabase.addApplicationFont(str(path))
        app.setFont(QFont("Microsoft YaHei", 10))
        database = Database(Path(directory) / "atlas.db")
        database.initialize()
        titles = (
            ("VS Code", "Echo · 记忆星图的交互设计"),
            ("Browser", "阅读本地应用与个人记忆的资料"),
            ("Design Studio", "Echo · 星群的颜色和形状"),
            ("Writer", "写下这个星期想完成的事情"),
            ("Music Player", "午后的轻音乐"),
        )
        today = datetime.now().replace(hour=9, minute=0, second=0, microsecond=0)
        for offset in range(9):
            for index, (name, title) in enumerate(titles):
                if (offset + index) % 4 == 0:
                    continue
                start = today - timedelta(days=offset) + timedelta(hours=index)
                end = start + timedelta(minutes=35 + index * 3)
                identifier = database.create_app_usage(date=start.strftime("%Y-%m-%d"), app_name=name,
                                                       window_title=title, start_time=to_db_datetime(start),
                                                       created_at=to_db_datetime(start))
                database.finish_app_usage(identifier, end_time=to_db_datetime(end), duration_seconds=int((end - start).total_seconds()))
                if index == 2 and offset in (0, 2, 5, 8):
                    moment = end + timedelta(minutes=5)
                    database.add_manual_note(date=moment.strftime("%Y-%m-%d"),
                                             content=("今天想到：每个星点都应该能回到真实的记录。" if offset == 0 else
                                                      "把零散的日子连起来，才发现这个想法已经走了这么远。"),
                                             created_at=to_db_datetime(moment))
        independent = today.replace(hour=21)
        database.add_manual_note(date=independent.strftime("%Y-%m-%d"), content="晚饭后散步，看见了很好看的月亮。",
                                 created_at=to_db_datetime(independent))

        window = TodayWindow(database)
        window.resize(1440, 900)
        window._switch_page("today" if args.start_home else "star_map")
        window.sidebar.local_status.setText("示例数据")
        window.star_map_page.heading.layout().itemAt(0).widget().setText("ECHO  /  MEMORY UNIVERSE  /  示例数据")
        window.setWindowTitle("Echo - 记忆星图入场体验（示例数据）" if args.start_home else "Echo - 3D 记忆星图（示例数据）")
        window.show()
        app.processEvents()
        app.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        if args.interactive:
            app.exec()
        else:
            if args.native_capture:
                from PySide6.QtTest import QTest
                QTest.qWait(1000)
            surface = window.star_map_page.view._gl
            print("Renderer:", "OpenGL" if surface and surface.ready else "3D painter fallback")
            args.output.parent.mkdir(parents=True, exist_ok=True)
            if not window.grab().save(str(args.output)):
                raise RuntimeError("Could not save atlas preview")
            window.resize(980, 660)
            app.processEvents()
            if args.native_capture:
                QTest.qWait(150)
            compact = args.output.with_name(args.output.stem + "-compact.png")
            if not window.grab().save(str(compact)):
                raise RuntimeError("Could not save compact preview")
            print(args.output)
            print(compact)
            page = window.star_map_page
            # The second angle makes the depth/parallax inspectable in QA.
            page.view.camera.orbit(90, -20)
            page.view._render()
            app.processEvents()
            if args.native_capture:
                QTest.qWait(100)
            orbit = args.output.with_name(args.output.stem + "-orbit.png")
            if not window.grab().save(str(orbit)):
                raise RuntimeError("Could not save orbit preview")
            print(orbit)
            page.view.fit_all()
            page.immerse_button.click()
            app.processEvents()
            if args.native_capture:
                QTest.qWait(100)
            immersive = args.output.with_name(args.output.stem + "-immersive.png")
            if not window.grab().save(str(immersive)):
                raise RuntimeError("Could not save immersive preview")
            print(immersive)
            page.immerse_button.click()
            if args.native_capture:
                page.fullscreen_button.click()
                QTest.qWait(100)
                assert window.isFullScreen()
                page.fullscreen_button.click()
                QTest.qWait(100)
                assert not window.isFullScreen()
            # Inspect the compact floating detail without sacrificing canvas
            # space, then verify both routes back to Echo restore navigation.
            note = next(star for star in page._atlas.stars if star.kind == "note")
            page.view.select_star(note.key, reveal=True)
            app.processEvents()
            if args.native_capture:
                QTest.qWait(150)
            detail = args.output.with_name(args.output.stem + "-detail.png")
            if not window.grab().save(str(detail)):
                raise RuntimeError("Could not save detail preview")
            print(detail)
            assert window.sidebar.isHidden()
            assert page.view.size() == window.size()
            page.replay_requested.emit(note.sources[0].date, note.sources[0].timestamp)
            app.processEvents()
            assert not window.sidebar.isHidden()
            assert window.stack.currentIndex() == window._page_indexes["memory"]
            window._switch_page("star_map")
            page.back_button.click()
            app.processEvents()
            assert not window.sidebar.isHidden()
            assert window.stack.currentIndex() == window._page_indexes["today"]
        window.close()
        window.deleteLater()
        app.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        database.close()


if __name__ == "__main__":
    main()
