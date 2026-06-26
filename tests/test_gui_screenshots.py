"""Unit coverage for Win32 screenshot crop helpers."""

from ras_commander.gui.screenshots import RasScreenshot


def test_visible_frame_crop_box_trims_invisible_window_border():
    crop_box = RasScreenshot._visible_frame_crop_box(
        window_rect=(100, 50, 1100, 850),
        visible_frame_rect=(108, 51, 1098, 839),
        image_size=(1000, 800),
    )

    assert crop_box == (8, 1, 998, 789)


def test_visible_frame_crop_box_returns_none_when_no_crop_needed():
    crop_box = RasScreenshot._visible_frame_crop_box(
        window_rect=(100, 50, 1100, 850),
        visible_frame_rect=(100, 50, 1100, 850),
        image_size=(1000, 800),
    )

    assert crop_box is None


def test_visible_frame_crop_box_rejects_implausibly_small_bounds():
    crop_box = RasScreenshot._visible_frame_crop_box(
        window_rect=(100, 50, 1100, 850),
        visible_frame_rect=(200, 150, 300, 250),
        image_size=(1000, 800),
    )

    assert crop_box is None
