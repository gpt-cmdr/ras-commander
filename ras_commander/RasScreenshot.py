"""
RasScreenshot - Backward compatibility shim.

This module has been migrated to ras_commander.gui.screenshots.
All functionality is preserved. Import from ras_commander.gui for new code.
"""

from .gui.screenshots import RasScreenshot, DEFAULT_SCREENSHOT_FOLDER

__all__ = ['RasScreenshot', 'DEFAULT_SCREENSHOT_FOLDER']
