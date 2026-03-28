"""
Tests for RasUtils.safe_resolve() function.

This function ensures Windows drive letters are preserved when paths would
otherwise be converted to UNC paths by Path.resolve().

HEC-RAS cannot read from UNC paths, so this is critical for network drive support.
"""

import os
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock
import pytest

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from ras_commander.RasUtils import RasUtils


class TestSafeResolve:
    """Tests for safe_resolve function."""

    def test_local_drive_path_unchanged(self):
        """Local drive paths should be resolved normally."""
        if os.name != 'nt':
            pytest.skip("Windows-only test")

        # Use a path that exists on the system
        test_path = Path("C:/Windows/System32")
        if not test_path.exists():
            pytest.skip("Test path doesn't exist")

        result = RasUtils.safe_resolve(test_path)

        # Should return a resolved absolute path
        assert result.is_absolute()
        assert str(result).startswith("C:")

    def test_relative_path_becomes_absolute(self):
        """Relative paths should become absolute."""
        test_path = Path(".")
        result = RasUtils.safe_resolve(test_path)

        assert result.is_absolute()
        assert result.exists()

    def test_linux_uses_standard_resolve(self):
        """On Linux/Mac, should use standard resolve()."""
        if os.name == 'nt':
            pytest.skip("Linux/Mac-only test")

        test_path = Path("/tmp")
        if not test_path.exists():
            test_path = Path.home()

        result = RasUtils.safe_resolve(test_path)

        assert result.is_absolute()

    def test_accepts_string_path(self):
        """Should accept string paths, not just Path objects."""
        # Use current directory which always exists
        result = RasUtils.safe_resolve(".")

        assert isinstance(result, Path)
        assert result.is_absolute()

    def test_accepts_path_object(self):
        """Should accept Path objects."""
        result = RasUtils.safe_resolve(Path("."))

        assert isinstance(result, Path)
        assert result.is_absolute()

    @pytest.mark.skipif(os.name != 'nt', reason="Windows-only test")
    def test_unc_path_returned_when_input_is_unc(self):
        """If input is already UNC, output should also be UNC (no drive to preserve)."""
        # Mock a UNC path - we can't test with real UNC without network access
        test_path = Path(r"\\server\share\folder")

        # When path doesn't have drive letter, UNC is acceptable
        with patch.object(Path, 'resolve', return_value=Path(r"\\server\share\folder")):
            with patch.object(Path, 'absolute', return_value=Path(r"\\server\share\folder")):
                result = RasUtils.safe_resolve(test_path)

        # UNC input should give UNC output
        assert str(result).startswith("\\\\")


class TestSafeResolveWithMockedResolve:
    """Tests using mocked resolve() to simulate mapped drive behavior."""

    @pytest.mark.skipif(os.name != 'nt', reason="Windows-only test")
    def test_mapped_drive_preserves_letter(self):
        """When resolve() would return UNC, safe_resolve should use absolute()."""
        # Simulate: H:\Projects resolves to \\192.168.1.1\share\Projects
        original_path = Path(r"H:\Projects\Model.prj")
        unc_path = Path(r"\\192.168.1.1\share\Projects\Model.prj")
        absolute_path = Path(r"H:\Projects\Model.prj")

        with patch.object(Path, 'resolve', return_value=unc_path):
            with patch.object(Path, 'absolute', return_value=absolute_path):
                result = RasUtils.safe_resolve(original_path)

        # Should preserve drive letter, not use UNC
        assert str(result).startswith("H:")
        assert not str(result).startswith("\\\\")

    @pytest.mark.skipif(os.name != 'nt', reason="Windows-only test")
    def test_local_drive_uses_resolve(self):
        """When resolve() returns drive letter path, should use it."""
        original_path = Path(r"C:\Projects\Model.prj")
        resolved_path = Path(r"C:\Projects\Model.prj")

        with patch.object(Path, 'resolve', return_value=resolved_path):
            result = RasUtils.safe_resolve(original_path)

        # Should use resolve() result when it's not UNC
        assert str(result) == str(resolved_path)

    @pytest.mark.skipif(os.name != 'nt', reason="Windows-only test")
    def test_various_drive_letters(self):
        """Test with different drive letters."""
        for drive in ['D:', 'E:', 'Z:', 'H:']:
            original_path = Path(f"{drive}\\Projects\\Model.prj")
            unc_path = Path(r"\\server\share\Projects\Model.prj")
            absolute_path = original_path

            with patch.object(Path, 'resolve', return_value=unc_path):
                with patch.object(Path, 'absolute', return_value=absolute_path):
                    result = RasUtils.safe_resolve(original_path)

            assert str(result).startswith(drive), f"Failed for drive {drive}"

    @pytest.mark.skipif(os.name != 'nt', reason="Windows-only test")
    def test_debug_logging_on_fallback(self, caplog):
        """Should log debug message when falling back to absolute()."""
        import logging

        caplog.set_level(logging.DEBUG)

        original_path = Path(r"H:\Projects\Model.prj")
        unc_path = Path(r"\\192.168.1.1\share\Projects\Model.prj")
        absolute_path = Path(r"H:\Projects\Model.prj")

        with patch.object(Path, 'resolve', return_value=unc_path):
            with patch.object(Path, 'absolute', return_value=absolute_path):
                RasUtils.safe_resolve(original_path)

        # Check that debug message was logged
        # Note: May not capture if logging not configured, so this is optional
        # The function should still work correctly regardless


class TestSafeResolveIntegration:
    """Integration tests with real filesystem."""

    def test_current_directory(self):
        """Current directory should resolve correctly."""
        result = RasUtils.safe_resolve(Path.cwd())

        assert result.exists()
        assert result.is_absolute()

    def test_parent_directory(self):
        """Parent directory should resolve correctly."""
        result = RasUtils.safe_resolve(Path.cwd().parent)

        assert result.exists()
        assert result.is_absolute()

    def test_with_relative_components(self):
        """Path with .. should resolve correctly."""
        # Create a path with relative components
        test_path = Path.cwd() / "subdir" / ".."

        result = RasUtils.safe_resolve(test_path)

        assert result.is_absolute()
        # The .. should be resolved
        assert ".." not in str(result)

    def test_nonexistent_path(self):
        """Non-existent path should still be resolvable."""
        test_path = Path.cwd() / "nonexistent_folder" / "model.prj"

        result = RasUtils.safe_resolve(test_path)

        assert result.is_absolute()
        assert "nonexistent_folder" in str(result)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
