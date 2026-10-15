from datetime import date, timedelta
from dataclasses import replace
from itertools import combinations
import math
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PySide6.QtCore import QAbstractAnimation, QDate, QEvent, QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QPushButton

from src.database.db import Database
from src.database.models import AppUsage, ManualNote
from src.memory_star_map import build_memory_atlas
from src.memory_space import SpaceCamera, camera_between, constellation_positions
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


class MemorySpaceTests(unittest.TestCase):
    def test_camera_flight_turns_the_short_way_and_eases_its_full_pose(self):
        start = SpaceCamera(target=(200, -80, 40), distance=300, yaw=math.radians(179), pitch=-0.6)
        end = SpaceCamera(target=(0, 0, 0), distance=1200, yaw=math.radians(-179), pitch=0.18)
        first = camera_between(start, end, 0)
        last = camera_between(start, end, 1)
        self.assertEqual(first.target, start.target)
        self.assertAlmostEqual(first.distance, start.distance)
        self.assertEqual(last.target, end.target)
        self.assertAlmostEqual(last.distance, end.distance)
        self.assertAlmostEqual(math.remainder(last.yaw - end.yaw, math.tau), 0)
        middle = camera_between(start, end, 0.5)
        self.assertAlmostEqual(middle.yaw, math.pi)
        self.assertAlmostEqual(middle.distance, 600)
        self.assertAlmostEqual(middle.pitch, (start.pitch + end.pitch) / 2)
        # Similar-sized end intervals travel much less than a middle interval.
        at = lambda t: camera_between(start, end, t).target[0]
        self.assertLess(abs(at(0.01) - at(0)), abs(at(0.51) - at(0.50)) / 100)
        self.assertLess(abs(at(1) - at(0.99)), abs(at(0.51) - at(0.50)) / 100)

    def test_perspective_depth_and_behind_camera_clipping(self):
        camera = SpaceCamera(distance=1000, yaw=0, pitch=0)
        near = camera.project((100, 0, 500), 1000, 700)
        far = camera.project((100, 0, -500), 1000, 700)
        self.assertGreater(near[0] - 500, far[0] - 500)
        self.assertIsNone(camera.project((0, 0, 1100), 1000, 700))
        self.assertEqual(camera.project((0, 0, 0), 1000, 700)[:2], (500, 350))

    def test_orbit_exposes_depth_without_changing_memory_geometry(self):
        atlas = build_memory_atlas([activity(1), activity(2, day="2026-10-13")], [])
        positions = constellation_positions(atlas)
        self.assertEqual(positions, constellation_positions(atlas))
        self.assertGreater(len({p[2] for p in positions.values()}), 1)
        camera = SpaceCamera()
        before = {key: camera.project(p, 1000, 700) for key, p in positions.items()}
        camera.orbit(100, 40)
        self.assertNotEqual(before, {key: camera.project(p, 1000, 700) for key, p in positions.items()})
        camera.orbit(0, 100000)
        self.assertLess(abs(camera.pitch), math.pi / 2)
        self.assertEqual(set(positions), {star.key for star in atlas.stars})


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
        pos = self.page.view.project_star(star.key).toPoint()
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
        distance = view.camera.distance
        view.zoom_by(2)
        self.assertLess(view.camera.distance, distance)
        before = view.camera.yaw
        QTest.mousePress(view.viewport(), Qt.MouseButton.LeftButton, pos=QPoint(12, 12))
        QTest.mouseMove(view.viewport(), QPoint(80, 40))
        QTest.mouseRelease(view.viewport(), Qt.MouseButton.LeftButton, pos=QPoint(80, 40))
        self.assertNotEqual(view.camera.yaw, before)
        target = view.camera.target
        QTest.mousePress(view, Qt.MouseButton.RightButton, pos=QPoint(25, 25))
        QTest.mouseMove(view, QPoint(100, 60))
        QTest.mouseRelease(view, Qt.MouseButton.RightButton, pos=QPoint(100, 60))
        self.assertNotEqual(view.camera.target, target)
        key = self.page._selected_key
        QTest.keyClick(view, Qt.Key.Key_Right)
        self.assertNotEqual(self.page._selected_key, key)
        view.fit_all()
        self.assertAlmostEqual(view.camera.distance, distance, places=2)

    def test_canvas_fills_page_and_details_do_not_resize_it_or_reopen_on_refresh(self):
        self.assertEqual(self.page.view.geometry(), self.page.rect())
        self.assertFalse(self.page.detail_panel.isVisible())
        self.assertFalse(self.page.controls.isVisible())
        star = next(star for star in self.page._atlas.stars if star.kind == "note")
        self.page.view.select_star(star.key, reveal=True)
        self.qt_app.processEvents()
        self.assertTrue(self.page.detail_panel.isVisible())
        self.assertEqual(self.page.view.geometry(), self.page.rect())
        # Focus lands in the unobstructed part of the sky, not under its card.
        point = self.page.view.project_star(star.key).toPoint()
        self.assertFalse(self.page.detail_panel.geometry().contains(point))
        self.assertGreater(point.y(), self.page.heading.geometry().bottom())
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

    def test_filters_and_immersive_mode_keep_escape_and_selection_accessible(self):
        self.page.filter_button.click()
        self.assertTrue(self.page.controls.isVisible())
        self.assertTrue(self.page.search_input.hasFocus())
        QTest.keyClick(self.page.search_input, Qt.Key.Key_Escape)
        self.assertFalse(self.page.controls.isVisible())
        self.page.immerse_button.click()
        self.assertFalse(self.page.heading.isVisible())
        self.assertFalse(self.page.back_button.isVisible())
        self.assertTrue(self.page.tools.isVisible())
        QTest.keyClick(self.page.view, Qt.Key.Key_Escape)
        self.assertTrue(self.page.heading.isVisible())
        self.assertTrue(self.page.back_button.isVisible())

    def test_entry_approaches_remembered_view_and_reveals_controls_without_losing_refresh(self):
        view = self.page.view
        destination = replace(view.camera)
        positions = dict(view.world_positions)
        with patch("src.ui.pages.star_map_page.reduced_motion_enabled", return_value=False), \
             patch("src.ui.pages.star_map_canvas.reduced_motion_enabled", return_value=False):
            self.page.enter()
            self.qt_app.processEvents()
            self.assertTrue(view._entry_active)
            self.assertTrue(self.page._chrome_intro.active)
            self.assertFalse(self.page.tools.isVisible())
            self.assertGreater(view.camera.distance, destination.distance)
            self.page.refresh()  # Unchanged recording refreshes must not cut the arrival short.
            self.assertEqual(view._flight.state(), QAbstractAnimation.State.Running)
            view._flight.setCurrentTime(view._flight.duration() // 2)
            self.assertGreater(view.camera.distance, destination.distance)
            self.assertLess(view.camera.distance, destination.distance * 1.27)
            self.assertGreater(self.page._chrome_intro._progress, 0)
            view._flight.setCurrentTime(view._flight.duration())
            self.assertFalse(view._entry_active)
            self.assertFalse(self.page._chrome_intro.active)
            self.assertTrue(self.page.tools.isVisible())
            self.assertTrue(self.page.heading.isVisible())
            self.assertEqual(view.world_positions, positions)
            self.assertAlmostEqual(view.camera.distance, destination.distance)
            self.assertAlmostEqual(view.camera.yaw, destination.yaw)
            self.assertEqual(view.camera.target, destination.target)

    def test_entry_can_be_taken_over_and_hide_or_lock_cannot_restart_it(self):
        view = self.page.view
        with patch("src.ui.pages.star_map_page.reduced_motion_enabled", return_value=False), \
             patch("src.ui.pages.star_map_canvas.reduced_motion_enabled", return_value=False):
            self.page.enter()
            self.qt_app.processEvents()
            view.zoom_by(1.1)
            self.assertFalse(view._entry_active)
            self.assertFalse(self.page._chrome_intro.active)
            self.assertTrue(self.page.tools.isVisible())
            self.page.enter()
            self.qt_app.processEvents()
            self.page.hide()
            self.qt_app.processEvents()
            self.assertFalse(view._entry_active)
            self.assertFalse(self.page._chrome_intro.active)
            self.assertEqual(view._flight.state(), QAbstractAnimation.State.Stopped)
            self.page.show()
            self.qt_app.processEvents()
            self.page.enter()
            self.qt_app.processEvents()
            self.assertTrue(self.page._chrome_intro.active)
            self.page.clear_private_content()
            self.assertFalse(self.page._chrome_intro.active)
            self.assertFalse(view._entry_active)
            self.page.refresh()
            self.page.enter()  # Lock before the deferred entrance gets its turn.
            self.page.clear_private_content()
            self.qt_app.processEvents()
            self.assertFalse(self.page._entrance_timer.isActive())
            self.assertFalse(self.page._chrome_intro.active)
            self.assertFalse(view._entry_active)
            self.assertEqual(view.world_positions, {})

    def test_entry_respects_reduced_motion(self):
        destination = replace(self.page.view.camera)
        self.page.enter()
        self.qt_app.processEvents()
        self.assertEqual(self.page.view.camera, destination)
        self.assertFalse(self.page._chrome_intro.active)
        self.assertEqual(self.page.view._flight.state(), QAbstractAnimation.State.Stopped)
        self.assertTrue(self.page.tools.isVisible())

    def test_home_button_glides_from_current_pose_and_can_be_interrupted(self):
        view = self.page.view
        destination = view._overview_camera()
        view.camera.orbit(140, 50)
        view.camera.pan(130, -80, view.height())
        view.zoom_by(2)
        start = replace(view.camera)
        home = next(button for button in self.page.tools.findChildren(QPushButton)
                    if button.accessibleName() == "回到星图全景")
        with patch("src.ui.pages.star_map_canvas.reduced_motion_enabled", return_value=False):
            home.click()
            self.assertEqual(view._flight.state(), QAbstractAnimation.State.Running)
            self.assertEqual(view.camera, start)  # The click itself never jumps.
            view._flight.setCurrentTime(view._flight.duration() // 2)
            middle = replace(view.camera)
            self.assertGreater(middle.distance, start.distance)
            self.assertLess(middle.distance, destination.distance)
            self.assertNotEqual(middle.target, start.target)
            self.assertNotEqual(middle.yaw, start.yaw)
            self.assertNotEqual(middle.pitch, start.pitch)
            # Dragging takes control at the current frame, not at an endpoint.
            QTest.mousePress(view, Qt.MouseButton.LeftButton, pos=QPoint(12, 12))
            self.assertEqual(view._flight.state(), QAbstractAnimation.State.Stopped)
            self.assertEqual(view.camera, middle)
            QTest.mouseMove(view, QPoint(50, 35))
            QTest.mouseRelease(view, Qt.MouseButton.LeftButton, pos=QPoint(50, 35))
            interrupted = replace(view.camera)
            home.click()
            self.assertEqual(view.camera, interrupted)
            view._flight.setCurrentTime(view._flight.duration())
            self.assertEqual(view.camera.target, destination.target)
            self.assertAlmostEqual(view.camera.distance, destination.distance)
            self.assertAlmostEqual(math.remainder(view.camera.yaw - destination.yaw, math.tau), 0)
            self.assertAlmostEqual(view.camera.pitch, destination.pitch)
            self.assertTrue(view._overview)

    def test_home_key_glides_but_reduced_motion_returns_immediately(self):
        view = self.page.view
        view.camera.orbit(90, -30)
        start = replace(view.camera)
        with patch("src.ui.pages.star_map_canvas.reduced_motion_enabled", return_value=False):
            QTest.keyClick(view, Qt.Key.Key_Home)
            self.assertEqual(view._flight.state(), QAbstractAnimation.State.Running)
            self.assertEqual(view.camera, start)
        self.page._fit_all()  # setUp requests reduced motion.
        self.assertEqual(view._flight.state(), QAbstractAnimation.State.Stopped)
        self.assertEqual(view.camera.target, view._overview_camera().target)
        self.assertAlmostEqual(view.camera.distance, view._fit_distance)
        self.assertTrue(view._overview)

    def test_drift_stops_on_selection_hide_and_lock_and_respects_reduced_motion(self):
        view = self.page.view
        self.assertFalse(view._drift.isActive())
        with patch("src.ui.pages.star_map_canvas.reduced_motion_enabled", return_value=False):
            view.set_roaming(True)
            self.assertTrue(view._drift.isActive())
            view.select_star(next(iter(view.world_positions)))
            self.assertFalse(view._drift.isActive())
            view.focus_star(view.selected_key())
            self.assertEqual(view._flight.state(), QAbstractAnimation.State.Running)
            self.page.hide()
            self.assertEqual(view._flight.state(), QAbstractAnimation.State.Stopped)
            self.assertFalse(view._drift.isActive())
        self.page.clear_private_content()
        self.assertEqual(view.world_positions, {})
        self.assertEqual(view.selected_key(), "")

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
        self.assertEqual(self.page.view.world_positions, {})
        self.assertEqual(self.page.view.atlas.stars, ())
        self.assertEqual(self.page.star_picker.count(), 0)
        self.assertEqual(self.page.detail_title.text(), "")
        self.assertFalse(self.page.detail_panel.isVisible())
        self.assertEqual(self.page.status_label.toolTip(), "")
        self.assertEqual(self.page.status_label.accessibleDescription(), "")
        self.assertFalse(self.page._search_timer.isActive())


if __name__ == "__main__":
    unittest.main()
