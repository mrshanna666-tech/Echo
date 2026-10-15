from datetime import date, timedelta
from itertools import combinations
import math
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PySide6.QtCore import QDate, QEvent, QPoint, QPointF, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QPushButton

from src.database.db import Database
from src.database.models import AppUsage, ManualNote
from src.memory_star_map import build_memory_atlas
from src.ui.pages.memory_page import MemoryPage
from src.ui.pages.star_map_page import StarMapPage


def activity(identifier, app="Code", day="2026-10-14", start="10:00", end="11:00", title="Echo workspace"):
    return AppUsage(identifier, day, app, title, f"{day} {start}:00",
                    f"{day} {end}:00", 3600, f"{day} {start}:00")


class MemoryAtlasTests(unittest.TestCase):
    def test_daily_stars_preserve_sources_and_join_days_without_double_counting(self):
        rows = [activity(1), activity(2, app="code", start="12:00", end="13:00"),
                activity(3, day="2026-10-13")]
        atlas = build_memory_atlas(rows, [])
        self.assertEqual((atlas.app_count, atlas.source_count, atlas.day_count), (1, 3, 2))
        daily = [star for star in atlas.stars if star.kind == "day"]
        self.assertEqual([len(star.sources) for star in daily], [1, 2])
        self.assertEqual(sum(source.duration_seconds for star in daily for source in star.sources), 10_800)
        self.assertEqual(len([link for link in atlas.links if link.kind == "chronology"]), 1)

    def test_notes_link_to_nearest_interval_and_distant_or_other_day_notes_stay_independent(self):
        rows = [activity(1), activity(2, app="Browser", start="11:10", end="11:15")]
        notes = [ManualNote(1, "2026-10-14", "An idea during writing", "2026-10-14 10:40:00"),
                 ManualNote(2, "2026-10-14", "Continue reading", "2026-10-14 11:16:00"),
                 ManualNote(3, "2026-10-14", "An evening thought", "2026-10-14 19:00:00"),
                 ManualNote(4, "2026-10-15", "Tomorrow", "2026-10-15 10:00:00")]
        atlas = build_memory_atlas(rows, notes)
        nearby = {link.source: link.target for link in atlas.links if link.kind == "nearby"}
        self.assertEqual(nearby, {"note:1": "day:code:2026-10-14", "note:2": "day:browser:2026-10-14"})
        self.assertEqual(len([star for star in atlas.stars if star.kind == "note"]), 4)

    def test_notes_only_history_needs_no_activity_or_fabricated_links(self):
        atlas = build_memory_atlas([], [ManualNote(7, "2026-10-14", "A quiet day", "2026-10-14 20:00:00")])
        self.assertEqual((atlas.source_count, atlas.day_count, atlas.app_count), (1, 1, 0))
        self.assertEqual(atlas.links, ())

    def test_layout_and_note_tie_breaking_are_stable_when_input_order_changes(self):
        rows = [activity(1), activity(2, app="Browser"), activity(3, day="2026-10-13")]
        notes = [ManualNote(1, "2026-10-14", "Remember this", "2026-10-14 11:00:00")]
        self.assertEqual(build_memory_atlas(rows, notes), build_memory_atlas(list(reversed(rows)), notes))

    def test_bounded_overview_can_expand_one_app_and_search_older_notes(self):
        rows = [activity(i + 1, day=(date(2026, 10, 14) - timedelta(days=i)).isoformat()) for i in range(20)]
        notes = [ManualNote(i, "2026-10-14", f"idea {i}", f"2026-10-14 12:{i:02}:00") for i in range(45)]
        overview = build_memory_atlas(rows, notes)
        self.assertEqual((overview.hidden_days, overview.hidden_notes), (8, 5))
        expanded = build_memory_atlas(rows, [], app_filter="Code")
        self.assertEqual((expanded.day_count, expanded.hidden_days), (20, 0))
        searched = build_memory_atlas(rows, notes, query="idea 0")
        self.assertEqual([star.key for star in searched.stars], ["note:0"])

    def test_query_and_app_filter_do_not_create_sources_that_did_not_match(self):
        rows = [activity(1, title="Echo"), activity(2, app="Browser", title="Other task")]
        notes = [ManualNote(1, "2026-10-14", "Echo plan", "2026-10-14 10:30:00")]
        filtered = build_memory_atlas(rows, notes, query="echo", app_filter="code")
        self.assertEqual({source.record_id for star in filtered.stars for source in star.sources if source.kind == "activity"}, {1})
        self.assertEqual(filtered.source_count, 2)

    def test_dense_overview_keeps_stars_separate_in_a_stable_landscape(self):
        rows = [activity(app * 12 + day, app=f"App {app}",
                         day=(date(2026, 10, 14) - timedelta(days=day)).isoformat())
                for app in range(8) for day in range(12)]
        # Stress the case where every note attaches to the same visible day.
        notes = [ManualNote(i, "2026-10-14", f"Idea {i}", f"2026-10-14 10:{i:02}:00")
                 for i in range(40)]
        atlas = build_memory_atlas(rows, notes)
        self.assertEqual(atlas, build_memory_atlas(rows[::-1], notes[::-1]))
        self.assertEqual(len(atlas.stars), 8 + 8 * 12 + 40)
        self.assertGreater(min(math.dist(a.position, b.position)
                               for a, b in combinations(atlas.stars, 2)), 42)
        xs, ys = zip(*(star.position for star in atlas.stars))
        self.assertGreaterEqual((max(xs) - min(xs)) / (max(ys) - min(ys)), 1.6)

    def test_expanded_app_distributes_all_ninety_days_around_its_hub(self):
        rows = [activity(i, day=(date(2026, 10, 14) - timedelta(days=i)).isoformat())
                for i in range(90)]
        atlas = build_memory_atlas(rows, [], app_filter="Code")
        hub = next(star for star in atlas.stars if star.kind == "app")
        daily = [star for star in atlas.stars if star.kind == "day"]
        self.assertEqual(len(daily), 90)
        self.assertGreater(min(math.dist(a.position, b.position)
                               for a, b in combinations(atlas.stars, 2)), 42)
        self.assertTrue(any(star.position[1] < hub.position[1] for star in daily))
        self.assertTrue(any(star.position[1] > hub.position[1] for star in daily))


class MemoryAtlasDatabaseTests(unittest.TestCase):
    def test_inclusive_period_and_loading_limit_include_note_only_days(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Database(Path(directory) / "atlas.db")
            database.initialize()
            try:
                for day in ("2026-10-11", "2026-10-12", "2026-10-13", "2026-10-14"):
                    database.create_app_usage(date=day, app_name="Code", window_title="Echo",
                                              start_time=f"{day} 10:00:00", created_at=f"{day} 10:00:00")
                database.add_manual_note(date="2026-10-15", content="No app today", created_at="2026-10-15 10:00:00")
                rows, notes, truncated = database.get_star_map_records("2026-10-12", "2026-10-15")
                self.assertEqual([row.date for row in rows], ["2026-10-12", "2026-10-13", "2026-10-14"])
                self.assertEqual([note.date for note in notes], ["2026-10-15"])
                self.assertFalse(truncated)
                rows, _, truncated = database.get_star_map_records("2026-10-12", "2026-10-15", limit=2)
                self.assertEqual([row.date for row in rows], ["2026-10-13", "2026-10-14"])
                self.assertTrue(truncated)
                database.close()
                self.assertEqual(database.get_star_map_records("2026-10-12", "2026-10-15"), ([], [], False))
            finally:
                database.close()


class MemoryAtlasInteractionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with patch.dict(os.environ, {"QT_QPA_PLATFORM": "offscreen", "ECHO_LANGUAGE": "zh-CN"}):
            cls.qt_app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.language = patch.dict(os.environ, {"ECHO_LANGUAGE": "zh-CN", "ECHO_REDUCE_MOTION": "1"})
        self.language.start()
        self.directory = tempfile.TemporaryDirectory()
        self.database = Database(Path(self.directory.name) / "atlas.db")
        self.database.initialize()
        self.day = QDate.currentDate().toString("yyyy-MM-dd")
        identifier = self.database.create_app_usage(date=self.day, app_name="Code", window_title="Echo source",
                                                    start_time=f"{self.day} 10:00:00", created_at=f"{self.day} 10:00:00")
        self.database.finish_app_usage(identifier, end_time=f"{self.day} 11:00:00", duration_seconds=3600)
        self.database.add_manual_note(date=self.day, content="Remember the orange star", created_at=f"{self.day} 11:05:00")
        self.page = StarMapPage(self.database)
        self.page.resize(1000, 740)
        self.page.show()
        self.qt_app.processEvents()

    def tearDown(self):
        self.page.close()
        self.page.deleteLater()
        self.qt_app.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.database.close()
        self.directory.cleanup()
        self.language.stop()

    def test_canvas_click_and_source_button_open_the_actual_memory_moment(self):
        star = next(star for star in self.page._atlas.stars if star.kind == "note")
        pos = self.page.view.mapFromScene(QPointF(*star.position))
        QTest.mouseClick(self.page.view.viewport(), Qt.MouseButton.LeftButton, pos=pos)
        self.qt_app.processEvents()
        self.assertEqual(self.page._selected_key, star.key)
        self.assertEqual(self.page.star_picker.currentData(), star.key)
        memory = MemoryPage(self.database)
        self.page.replay_requested.connect(memory.focus_moment)
        button = next(button for button in self.page.sources_scroll.findChildren(QPushButton)
                      if button.objectName() == "atlasReplay" and not button.isHidden())
        button.click()
        self.assertEqual(memory.date_edit.date().toString("yyyy-MM-dd"), self.day)
        self.assertEqual(memory.time_edit.time().toString("HH:mm"), "11:05")
        self.assertEqual(memory.replay_timeline._time.toString("HH:mm"), "11:05")
        memory.deleteLater()

    def test_zoom_pan_and_keyboard_selection_work(self):
        view = self.page.view
        scale = view.transform().m11()
        view.zoom_by(2)
        self.assertGreater(view.transform().m11(), scale)
        before = view.mapToScene(QPoint(0, 0))
        QTest.mousePress(view.viewport(), Qt.MouseButton.LeftButton, pos=QPoint(12, 12))
        QTest.mouseMove(view.viewport(), QPoint(80, 40))
        QTest.mouseRelease(view.viewport(), Qt.MouseButton.LeftButton, pos=QPoint(80, 40))
        self.assertNotEqual(view.mapToScene(QPoint(0, 0)), before)
        key = self.page._selected_key
        QTest.keyClick(view, Qt.Key.Key_Right)
        self.assertNotEqual(self.page._selected_key, key)
        view.fit_all()
        self.assertAlmostEqual(view.transform().m11(), scale, places=2)

    def test_canvas_fills_page_and_details_do_not_resize_it_or_reopen_on_refresh(self):
        self.assertEqual(self.page.view.geometry(), self.page.rect())
        self.assertFalse(self.page.detail_panel.isVisible())
        star = next(star for star in self.page._atlas.stars if star.kind == "note")
        self.page.view.select_star(star.key, reveal=True)
        self.qt_app.processEvents()
        self.assertTrue(self.page.detail_panel.isVisible())
        self.assertEqual(self.page.view.geometry(), self.page.rect())
        # Focus lands in the unobstructed part of the sky, not under its card.
        point = self.page.view.mapFromScene(QPointF(*star.position))
        self.assertFalse(self.page.detail_panel.geometry().contains(point))
        self.assertGreater(point.y(), self.page.controls.geometry().bottom())
        self.page.close_detail_button.click()
        self.page.refresh()
        self.assertFalse(self.page.detail_panel.isVisible())
        self.assertEqual(self.page.view.geometry(), self.page.rect())

    def test_list_and_escape_leave_a_keyboard_route_back_to_echo(self):
        exits = []
        self.page.exit_requested.connect(lambda: exits.append(True))
        self.page.list_button.click()
        self.assertTrue(self.page.detail_panel.isVisible())
        self.assertTrue(self.page.star_picker.hasFocus())
        QTest.keyClick(self.page.star_picker, Qt.Key.Key_Escape)
        self.qt_app.processEvents()
        self.assertFalse(self.page.detail_panel.isVisible())
        self.assertEqual(exits, [])
        QTest.keyClick(self.page.view, Qt.Key.Key_Escape)
        self.qt_app.processEvents()
        self.assertEqual(exits, [True])
        self.page.back_button.click()
        self.assertEqual(exits, [True, True])

    def test_filter_search_empty_state_and_lock_clear_private_records(self):
        self.page.app_combo.setCurrentIndex(1)
        self.assertTrue(all(star.kind == "note" for star in self.page._atlas.stars))
        self.page.search_input.setText("missing record")
        self.page._redraw()
        self.assertEqual(self.page._atlas.stars, ())
        self.page.search_input.clear()
        self.page.refresh()
        self.assertTrue(self.page._atlas.stars)
        self.page.clear_private_content()
        self.qt_app.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.assertEqual(self.page._usage, [])
        self.assertEqual(self.page._notes, [])
        self.assertEqual(self.page.view.scene().items(), [])
        self.assertEqual(self.page.star_picker.count(), 0)
        self.assertEqual(self.page.detail_title.text(), "")
        self.assertFalse(self.page.detail_panel.isVisible())
        self.assertEqual(self.page.status_label.toolTip(), "")
        self.assertEqual(self.page.status_label.accessibleDescription(), "")
        self.assertFalse(self.page._search_timer.isActive())


if __name__ == "__main__":
    unittest.main()
