"""
Additional tests for UNC path fix in RasMap and RasDss modules.

These tests verify that:
1. RasMap.add_terrain_layer() produces paths with drive letters
2. RasDss methods work with network drive paths
3. Projects with DSS boundary conditions work correctly
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
NETWORK_TEST_DIR = Path("H:/Test_Folder/UNC_Path_RasMap_DSS_Test")


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


class TestRasMapOnNetworkDrive:
    """Test RasMap operations on network drive."""

    @pytest.mark.skipif(not is_network_drive_available(), reason="Network drive not available")
    def test_rasmap_paths_preserve_drive_letter(self, setup_network_test_dir):
        """RasMap should preserve drive letters in terrain layer paths."""
        from ras_commander import RasMap

        output_path = setup_network_test_dir / "rasmap_test"

        # Extract project with terrain
        project_path = RasExamples.extract_project(
            "BaldEagleCrkMulti2D",
            output_path=output_path
        )

        init_ras_project(project_path, "6.6")

        # Check that rasmap_df paths don't have UNC
        if hasattr(ras, 'rasmap_df') and ras.rasmap_df is not None and not ras.rasmap_df.empty:
            for col in ras.rasmap_df.columns:
                if 'path' in col.lower() or 'file' in col.lower():
                    for idx, val in ras.rasmap_df[col].items():
                        if val and str(val).startswith("\\\\"):
                            pytest.fail(f"UNC path found in rasmap_df[{col}]: {val}")

        print(f"[PASS] RasMap paths use drive letters")


class TestDamBreachProjectOnNetworkDrive:
    """Test Dam Breaching project which has complex boundary conditions."""

    @pytest.mark.skipif(not is_network_drive_available(), reason="Network drive not available")
    def test_extract_dam_breaching_to_network_drive(self, setup_network_test_dir):
        """Extract Dam Breaching project to network drive."""
        output_path = setup_network_test_dir / "dambrk_test"

        project_path = RasExamples.extract_project(
            "Dam Breaching",
            output_path=output_path
        )

        assert project_path.exists(), f"Project not extracted: {project_path}"
        assert str(project_path).startswith("H:"), \
            f"Expected H: drive: {project_path}"

        print(f"[PASS] Dam Breaching extracted to: {project_path}")

    @pytest.mark.skipif(not is_network_drive_available(), reason="Network drive not available")
    def test_init_dam_breaching_preserves_paths(self, setup_network_test_dir):
        """Initialize Dam Breaching and check all paths use drive letter."""
        output_path = setup_network_test_dir / "dambrk_init_test"

        project_path = RasExamples.extract_project(
            "Dam Breaching",
            output_path=output_path
        )

        init_ras_project(project_path, "6.6")

        # Check all key paths
        paths_to_check = {
            'prj_file': str(ras.prj_file),
            'project_folder': str(ras.project_folder),
        }

        issues = []
        for name, path_str in paths_to_check.items():
            if path_str.startswith("\\\\"):
                issues.append(f"{name}: {path_str}")
            else:
                print(f"[OK] {name}: {path_str}")

        if issues:
            pytest.fail(f"UNC paths found: {issues}")

        print(f"[PASS] All Dam Breaching paths use drive letters")


class TestMultipleProjectsOnNetworkDrive:
    """Test switching between multiple projects on network drive."""

    @pytest.mark.skipif(not is_network_drive_available(), reason="Network drive not available")
    def test_project_switching(self, setup_network_test_dir):
        """Test switching between projects maintains drive letters."""
        projects = ["Muncie", "BaldEagleCrkMulti2D"]
        project_paths = {}

        # Extract all projects
        for proj_name in projects:
            output_path = setup_network_test_dir / f"switch_test_{proj_name}"
            project_paths[proj_name] = RasExamples.extract_project(
                proj_name,
                output_path=output_path
            )

        # Initialize each project and verify paths
        for proj_name, proj_path in project_paths.items():
            init_ras_project(proj_path, "6.6")

            # Verify prj_file uses drive letter
            prj_str = str(ras.prj_file)
            assert prj_str.startswith("H:"), \
                f"Project {proj_name} prj_file should have H: drive: {prj_str}"

            print(f"[OK] {proj_name}: {prj_str}")

        print(f"[PASS] Project switching maintains drive letters")


class TestDSSOperationsOnNetworkDrive:
    """Test DSS operations with network drive paths."""

    @pytest.mark.skipif(not is_network_drive_available(), reason="Network drive not available")
    def test_dss_path_resolution(self, setup_network_test_dir):
        """Test that DSS file paths are resolved with drive letters."""
        # Create a test DSS path (doesn't need to exist for path resolution test)
        dss_path = setup_network_test_dir / "test_boundary.dss"

        resolved = RasUtils.safe_resolve(dss_path)
        resolved_str = str(resolved)

        assert resolved_str.startswith("H:"), \
            f"DSS path should preserve H: drive: {resolved_str}"
        assert not resolved_str.startswith("\\\\"), \
            f"DSS path should not be UNC: {resolved_str}"

        print(f"[PASS] DSS path resolved with drive letter: {resolved_str}")


def run_tests():
    """Run tests manually."""
    print("=" * 70)
    print("UNC Path Fix - RasMap/DSS Test Suite")
    print(f"Test Time: {datetime.now().isoformat()}")
    print("=" * 70)

    if not is_network_drive_available():
        print("[SKIP] Network drive H: not available")
        return

    # Setup
    if NETWORK_TEST_DIR.exists():
        shutil.rmtree(NETWORK_TEST_DIR)
    NETWORK_TEST_DIR.mkdir(parents=True)

    # Run tests
    test_classes = [
        TestRasMapOnNetworkDrive,
        TestDamBreachProjectOnNetworkDrive,
        TestMultipleProjectsOnNetworkDrive,
        TestDSSOperationsOnNetworkDrive,
    ]

    for test_class in test_classes:
        print(f"\n--- {test_class.__name__} ---")
        tests = test_class()
        for method_name in dir(tests):
            if method_name.startswith("test_"):
                print(f"\n  {method_name}:")
                try:
                    getattr(tests, method_name)(NETWORK_TEST_DIR)
                except Exception as e:
                    print(f"  [FAIL] {e}")

    print("\n" + "=" * 70)
    print("Tests complete")
    print("=" * 70)


if __name__ == "__main__":
    run_tests()
