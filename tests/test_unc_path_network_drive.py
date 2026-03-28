"""
Test UNC path fix with real network drive operations.

This test validates that the safe_resolve() function properly preserves
Windows drive letters (H:\) instead of converting to UNC paths (\\server\share).

These tests require the H: drive to be available and writable.
"""

import os
import sys
import shutil
from pathlib import Path
from datetime import datetime
import pytest

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from ras_commander import RasExamples, init_ras_project, ras
from ras_commander.RasUtils import RasUtils


# Test directory on network drive
NETWORK_TEST_DIR = Path("H:/Test_Folder/UNC_Path_Test")


def is_network_drive_available():
    """Check if network drive is available for testing."""
    return Path("H:/Test_Folder").exists()


@pytest.fixture(scope="module")
def setup_network_test_dir():
    """Setup test directory on network drive."""
    if not is_network_drive_available():
        pytest.skip("Network drive H: not available")

    # Clean up any previous test artifacts
    if NETWORK_TEST_DIR.exists():
        shutil.rmtree(NETWORK_TEST_DIR)

    NETWORK_TEST_DIR.mkdir(parents=True, exist_ok=True)

    yield NETWORK_TEST_DIR

    # Optional: clean up after tests (leave for inspection)
    # shutil.rmtree(NETWORK_TEST_DIR, ignore_errors=True)


class TestSafeResolveNetworkDrive:
    """Test safe_resolve() with actual network drive paths."""

    @pytest.mark.skipif(not is_network_drive_available(), reason="Network drive not available")
    def test_safe_resolve_preserves_drive_letter(self, setup_network_test_dir):
        """safe_resolve() should preserve H: drive letter."""
        test_path = setup_network_test_dir / "test_file.txt"

        # Write a test file
        test_path.write_text("test content")

        resolved = RasUtils.safe_resolve(test_path)
        resolved_str = str(resolved)

        # Should start with H:, not UNC path
        assert resolved_str.startswith("H:"), \
            f"Expected H: drive letter, got: {resolved_str}"
        assert not resolved_str.startswith("\\\\"), \
            f"Got UNC path: {resolved_str}"

        print(f"[PASS] safe_resolve preserved drive letter: {resolved_str}")

    @pytest.mark.skipif(not is_network_drive_available(), reason="Network drive not available")
    def test_relative_path_on_network_drive(self, setup_network_test_dir):
        """
        Relative paths on network drive may resolve to UNC.

        This is expected behavior - safe_resolve() only preserves drive letters
        when the ORIGINAL path has a drive letter. For relative paths, it returns
        what resolve() returns.

        In practice, ras-commander always constructs paths from project_folder
        (which has a drive letter), so relative paths are not passed directly.
        """
        # Save current directory
        original_cwd = Path.cwd()

        try:
            # Change to network directory
            os.chdir(setup_network_test_dir)

            # Create a relative path
            relative_path = Path("subdir/file.txt")
            (setup_network_test_dir / "subdir").mkdir(exist_ok=True)
            (setup_network_test_dir / "subdir/file.txt").write_text("test")

            resolved = RasUtils.safe_resolve(relative_path)
            resolved_str = str(resolved)

            # Relative path will resolve to absolute, but may be UNC
            # This is expected - the key thing is that absolute paths with
            # drive letters preserve the drive letter
            assert resolved.is_absolute(), \
                f"Should resolve to absolute path: {resolved_str}"

            print(f"[INFO] Relative path resolved to: {resolved_str}")

            # Now test that if we construct the path with drive letter, it works
            absolute_path = setup_network_test_dir / "subdir" / "file.txt"
            resolved_absolute = RasUtils.safe_resolve(absolute_path)
            resolved_absolute_str = str(resolved_absolute)

            assert resolved_absolute_str.startswith("H:"), \
                f"Absolute path should preserve drive letter: {resolved_absolute_str}"

            print(f"[PASS] Absolute path preserved drive letter: {resolved_absolute_str}")
        finally:
            os.chdir(original_cwd)

    @pytest.mark.skipif(not is_network_drive_available(), reason="Network drive not available")
    def test_compare_resolve_vs_safe_resolve(self, setup_network_test_dir):
        """Demonstrate the difference between resolve() and safe_resolve()."""
        test_path = setup_network_test_dir / "compare_test.txt"
        test_path.write_text("test")

        # Standard resolve - may convert to UNC
        standard_resolved = test_path.resolve()

        # Safe resolve - preserves drive letter
        safe_resolved = RasUtils.safe_resolve(test_path)

        print(f"Standard resolve: {standard_resolved}")
        print(f"Safe resolve: {safe_resolved}")

        # safe_resolve should always have drive letter
        assert str(safe_resolved).startswith("H:"), \
            f"safe_resolve should preserve H: drive: {safe_resolved}"

        # Log if standard resolve converted to UNC (expected behavior on mapped drives)
        if str(standard_resolved).startswith("\\\\"):
            print("[INFO] Standard resolve() converted to UNC path (expected on mapped drive)")
            print("[PASS] safe_resolve() correctly preserved drive letter")
        else:
            print("[INFO] Standard resolve() preserved drive letter (local path or OS behavior)")


class TestRasExamplesOnNetworkDrive:
    """Test RasExamples extraction to network drive."""

    @pytest.mark.skipif(not is_network_drive_available(), reason="Network drive not available")
    def test_extract_muncie_to_network_drive(self, setup_network_test_dir):
        """Extract Muncie project to network drive and verify paths."""
        output_path = setup_network_test_dir / "muncie_test"

        # Extract project
        project_path = RasExamples.extract_project(
            "Muncie",
            output_path=output_path
        )

        # Verify project was extracted
        assert project_path.exists(), f"Project not extracted: {project_path}"

        # Check that path uses drive letter
        project_str = str(project_path)
        assert project_str.startswith("H:"), \
            f"Expected H: drive letter, got: {project_str}"

        print(f"[PASS] Muncie extracted to: {project_path}")

        # Verify .prj file exists
        prj_files = list(project_path.glob("*.prj"))
        assert len(prj_files) > 0, "No .prj file found"
        print(f"[PASS] Found .prj file: {prj_files[0]}")

    @pytest.mark.skipif(not is_network_drive_available(), reason="Network drive not available")
    def test_extract_baldagle_to_network_drive(self, setup_network_test_dir):
        """Extract BaldEagleCrkMulti2D project to network drive."""
        output_path = setup_network_test_dir / "baldagle_test"

        project_path = RasExamples.extract_project(
            "BaldEagleCrkMulti2D",
            output_path=output_path
        )

        assert project_path.exists(), f"Project not extracted: {project_path}"
        assert str(project_path).startswith("H:"), \
            f"Expected H: drive: {project_path}"

        print(f"[PASS] BaldEagleCrkMulti2D extracted to: {project_path}")


class TestInitRasProjectOnNetworkDrive:
    """Test init_ras_project with network drive paths."""

    @pytest.mark.skipif(not is_network_drive_available(), reason="Network drive not available")
    def test_init_project_preserves_drive_letter(self, setup_network_test_dir):
        """init_ras_project should preserve H: drive letter in all paths."""
        output_path = setup_network_test_dir / "init_test"

        # Extract project first
        project_path = RasExamples.extract_project(
            "Muncie",
            output_path=output_path
        )

        # Initialize project
        init_ras_project(project_path, "6.6")

        # Check prj_file path
        prj_file_str = str(ras.prj_file)
        assert prj_file_str.startswith("H:"), \
            f"prj_file should use H: drive: {prj_file_str}"
        assert not prj_file_str.startswith("\\\\"), \
            f"prj_file should not be UNC path: {prj_file_str}"

        print(f"[PASS] ras.prj_file: {prj_file_str}")

        # Check project_folder path
        folder_str = str(ras.project_folder)
        assert folder_str.startswith("H:"), \
            f"project_folder should use H: drive: {folder_str}"

        print(f"[PASS] ras.project_folder: {folder_str}")

        # Check plan_df paths
        if len(ras.plan_df) > 0:
            # Check a plan file path
            plan_path = ras.plan_df.iloc[0].get('plan_path') or ras.plan_df.iloc[0].get('Full Path')
            if plan_path:
                plan_str = str(plan_path)
                assert plan_str.startswith("H:") or not plan_str.startswith("\\\\"), \
                    f"Plan path should not be UNC: {plan_str}"
                print(f"[PASS] Plan path: {plan_str}")

    @pytest.mark.skipif(not is_network_drive_available(), reason="Network drive not available")
    def test_dataframes_use_drive_letters(self, setup_network_test_dir):
        """DataFrames should use H: drive letter in file paths."""
        output_path = setup_network_test_dir / "df_test"

        project_path = RasExamples.extract_project(
            "BaldEagleCrkMulti2D",
            output_path=output_path
        )

        init_ras_project(project_path, "6.6")

        # Check all file paths in DataFrames
        path_columns = ['Full Path', 'file_path', 'hdf_path', 'HDF_Results_Path',
                       'plan_path', 'geom_path', 'flow_path']

        issues = []

        for df_name in ['plan_df', 'geom_df']:
            df = getattr(ras, df_name, None)
            if df is None or df.empty:
                continue

            for col in path_columns:
                if col not in df.columns:
                    continue

                for idx, val in df[col].items():
                    if val is not None and str(val).strip():
                        val_str = str(val)
                        if val_str.startswith("\\\\"):
                            issues.append(f"{df_name}[{idx}][{col}] = {val_str}")

        if issues:
            print("[FAIL] Found UNC paths in DataFrames:")
            for issue in issues:
                print(f"  - {issue}")
            pytest.fail(f"Found {len(issues)} UNC paths in DataFrames")
        else:
            print(f"[PASS] All paths in DataFrames use drive letters")


class TestEdgeCases:
    """Test edge cases for UNC path handling."""

    @pytest.mark.skipif(not is_network_drive_available(), reason="Network drive not available")
    def test_deeply_nested_path(self, setup_network_test_dir):
        """Test deeply nested paths on network drive."""
        deep_path = setup_network_test_dir / "a" / "b" / "c" / "d" / "e" / "file.txt"
        deep_path.parent.mkdir(parents=True, exist_ok=True)
        deep_path.write_text("deep test")

        resolved = RasUtils.safe_resolve(deep_path)

        assert str(resolved).startswith("H:"), \
            f"Deep path should preserve H: drive: {resolved}"

        print(f"[PASS] Deeply nested path: {resolved}")

    @pytest.mark.skipif(not is_network_drive_available(), reason="Network drive not available")
    def test_path_with_spaces(self, setup_network_test_dir):
        """Test paths with spaces on network drive."""
        space_path = setup_network_test_dir / "folder with spaces" / "file name.txt"
        space_path.parent.mkdir(parents=True, exist_ok=True)
        space_path.write_text("space test")

        resolved = RasUtils.safe_resolve(space_path)

        assert str(resolved).startswith("H:"), \
            f"Space path should preserve H: drive: {resolved}"
        assert "folder with spaces" in str(resolved), \
            "Spaces should be preserved in path"

        print(f"[PASS] Path with spaces: {resolved}")

    @pytest.mark.skipif(not is_network_drive_available(), reason="Network drive not available")
    def test_path_with_special_characters(self, setup_network_test_dir):
        """Test paths with special characters on network drive."""
        special_path = setup_network_test_dir / "folder-with_chars(1)" / "file-1.txt"
        special_path.parent.mkdir(parents=True, exist_ok=True)
        special_path.write_text("special test")

        resolved = RasUtils.safe_resolve(special_path)

        assert str(resolved).startswith("H:"), \
            f"Special chars path should preserve H: drive: {resolved}"

        print(f"[PASS] Path with special chars: {resolved}")


def run_manual_tests():
    """Run tests manually without pytest for quick verification."""
    print("=" * 70)
    print("UNC Path Fix - Manual Test Suite")
    print(f"Test Time: {datetime.now().isoformat()}")
    print("=" * 70)

    if not is_network_drive_available():
        print("[SKIP] Network drive H: not available")
        return

    # Setup
    if NETWORK_TEST_DIR.exists():
        shutil.rmtree(NETWORK_TEST_DIR)
    NETWORK_TEST_DIR.mkdir(parents=True)

    tests = TestSafeResolveNetworkDrive()
    test_methods = [
        ("safe_resolve preserves drive letter", tests.test_safe_resolve_preserves_drive_letter),
        ("compare resolve vs safe_resolve", tests.test_compare_resolve_vs_safe_resolve),
    ]

    for name, test_fn in test_methods:
        print(f"\n--- {name} ---")
        try:
            test_fn(NETWORK_TEST_DIR)
        except Exception as e:
            print(f"[FAIL] {e}")

    # Test RasExamples
    print("\n--- RasExamples extraction ---")
    try:
        tests2 = TestRasExamplesOnNetworkDrive()
        tests2.test_extract_muncie_to_network_drive(NETWORK_TEST_DIR)
    except Exception as e:
        print(f"[FAIL] {e}")

    # Test init_ras_project
    print("\n--- init_ras_project ---")
    try:
        tests3 = TestInitRasProjectOnNetworkDrive()
        tests3.test_init_project_preserves_drive_letter(NETWORK_TEST_DIR)
    except Exception as e:
        print(f"[FAIL] {e}")

    print("\n" + "=" * 70)
    print("Manual tests complete")
    print("=" * 70)


if __name__ == "__main__":
    run_manual_tests()
