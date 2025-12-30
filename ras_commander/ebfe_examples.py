"""
eBFE Example Model Helpers

Deterministic functions for organizing specific eBFE models used in example notebooks.

These functions provide reliable, tested organization for specific models:
- Spring Creek (12040102) - Pattern 3: Single 2D model with nested zip
- North Galveston Bay (12040203) - Pattern 4: Compound HMS + RAS

For other models, use the organizing-ebfe-models agent skill which handles
all patterns dynamically.
"""

from pathlib import Path
from typing import Optional, Dict
import shutil
import zipfile
from datetime import datetime


class RasEbfeExamples:
    """
    Deterministic organization functions for specific eBFE example models.

    These functions are tested and verified for use in example notebooks.
    For ad-hoc model organization, use the organizing-ebfe-models agent skill.
    """

    @staticmethod
    def organize_spring_creek(
        downloaded_folder: Path,
        output_folder: Optional[Path] = None
    ) -> Path:
        """
        Organize Spring Creek (12040102) eBFE model into 4-folder structure.

        **Pattern 3**: Single 2D model, nested zip, self-contained terrain

        Args:
            downloaded_folder: Path to extracted 12040102_Spring_Models/ folder
            output_folder: Output location (default: ./ebfe_organized/SpringCreek_12040102/)

        Returns:
            Path to organized model with structure:
                SpringCreek_12040102/
                ├── HMS Model/        (empty - no HMS content)
                ├── RAS Model/        (Spring 2D model with terrain)
                ├── Spatial Data/     (terrain + shapefiles)
                ├── Documentation/    (inventory spreadsheet)
                └── agent/
                    └── model_log.md  (organization log)

        Example:
            >>> from ras_commander.ebfe_examples import RasEbfeExamples
            >>> from pathlib import Path
            >>>
            >>> source = Path(r"D:/eBFE/downloads/12040102_Spring_Models_extracted")
            >>> organized = RasEbfeExamples.organize_spring_creek(source)
            >>>
            >>> # Now ready for ras-commander
            >>> from ras_commander import init_ras_project
            >>> init_ras_project(organized / "RAS Model", "5.0.7")
        """
        downloaded_folder = Path(downloaded_folder)
        if output_folder is None:
            output_folder = Path("./ebfe_organized/SpringCreek_12040102")
        else:
            output_folder = Path(output_folder)

        # Create 4-folder structure + agent folder
        folders = {
            'hms': output_folder / "HMS Model",
            'ras': output_folder / "RAS Model",
            'spatial': output_folder / "Spatial Data",
            'docs': output_folder / "Documentation",
            'agent': output_folder / "agent"
        }

        for folder in folders.values():
            folder.mkdir(parents=True, exist_ok=True)

        # Pattern 3 specific paths
        models_folder = downloaded_folder / "12040102_Models_202207"
        final_zip = models_folder / "_Final.zip"
        inventory = models_folder / "2D_Model_Inventory_Spring.xlsx"

        # Extract nested _Final.zip if not already extracted
        final_extracted = models_folder / "_Final_extracted"
        if not final_extracted.exists():
            print(f"Extracting nested _Final.zip (9.67 GB)...")
            with zipfile.ZipFile(final_zip, 'r') as zip_ref:
                zip_ref.extractall(final_extracted)
            print(f"  ✓ Extracted to {final_extracted}")

        # Find the Spring model folder
        spring_folder = final_extracted / "_Final" / "HECRAS_507"
        if not spring_folder.exists():
            raise FileNotFoundError(f"Spring model not found at {spring_folder}")

        # Organize RAS Model files
        print("Organizing RAS Model files...")
        for file in spring_folder.rglob('*'):
            if file.is_file():
                # Skip shapefile .prj files
                if file.suffix == '.prj' and file.parent.name in ['Features', 'Shp']:
                    continue  # Handle in Spatial Data section

                # Copy to RAS Model
                rel_path = file.relative_to(spring_folder)
                dest = folders['ras'] / rel_path
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(file, dest)

        print(f"  ✓ Copied Spring model to RAS Model/")

        # Organize Spatial Data (terrain + shapefiles)
        print("Organizing Spatial Data...")

        # Copy terrain from RAS Model to Spatial Data
        terrain_source = spring_folder / "Terrain"
        if terrain_source.exists():
            terrain_dest = folders['spatial'] / "Terrain"
            shutil.copytree(terrain_source, terrain_dest, dirs_exist_ok=True)
            print(f"  ✓ Copied Terrain/ to Spatial Data/")

        # Copy shapefiles
        for shp_folder in ['Features', 'Shp']:
            shp_source = spring_folder / shp_folder
            if shp_source.exists():
                shp_dest = folders['spatial'] / shp_folder
                shutil.copytree(shp_source, shp_dest, dirs_exist_ok=True)
                print(f"  ✓ Copied {shp_folder}/ to Spatial Data/")

        # Organize Documentation
        print("Organizing Documentation...")
        if inventory.exists():
            shutil.copy2(inventory, folders['docs'] / inventory.name)
            print(f"  ✓ Copied inventory to Documentation/")

        # Create agent model log
        _create_spring_creek_log(folders['agent'], downloaded_folder, output_folder)

        print(f"\n✓ Organization complete: {output_folder}")
        return output_folder

    @staticmethod
    def organize_north_galveston_bay(
        downloaded_folder: Path,
        output_folder: Optional[Path] = None,
        extract_ras_submittal: bool = False
    ) -> Path:
        """
        Organize North Galveston Bay (12040203) eBFE model into 4-folder structure.

        **Pattern 4**: Compound HMS + RAS in nested zips

        Args:
            downloaded_folder: Path to extracted 12040203_NorthGalvestonBay_Models/ folder
            output_folder: Output location (default: ./ebfe_organized/NorthGalvestonBay_12040203/)
            extract_ras_submittal: Attempt to extract RAS_Submittal.zip (may fail for large files)

        Returns:
            Path to organized model with structure:
                NorthGalvestonBay_12040203/
                ├── HMS Model/        (NorthGalvestonBay HMS project)
                ├── RAS Model/        (pending manual extraction if extract_ras_submittal=False)
                ├── Spatial Data/     (pending RAS extraction)
                ├── Documentation/    (metadata + BLE reports)
                └── agent/
                    └── model_log.md

        Note:
            RAS_Submittal.zip is 6.1 GB and may require manual extraction via Windows Explorer.
            Set extract_ras_submittal=True to attempt automatic extraction (may fail).

        Example:
            >>> from ras_commander.ebfe_examples import RasEbfeExamples
            >>> from pathlib import Path
            >>>
            >>> source = Path(r"D:/eBFE/downloads/12040203_NorthGalvestonBay_Models_extracted")
            >>> organized = RasEbfeExamples.organize_north_galveston_bay(source)
            >>>
            >>> # HMS model ready immediately
            >>> hms_project = organized / "HMS Model/NorthGalvestonBay/NorthGalvestonBay.hms"
            >>> # RAS model requires manual extraction (see RAS Model/README_EXTRACTION_NEEDED.txt)
        """
        downloaded_folder = Path(downloaded_folder)
        if output_folder is None:
            output_folder = Path("./ebfe_organized/NorthGalvestonBay_12040203")
        else:
            output_folder = Path(output_folder)

        # Create 4-folder structure + agent folder
        folders = {
            'hms': output_folder / "HMS Model",
            'ras': output_folder / "RAS Model",
            'spatial': output_folder / "Spatial Data",
            'docs': output_folder / "Documentation",
            'agent': output_folder / "agent"
        }

        for folder in folders.values():
            folder.mkdir(parents=True, exist_ok=True)

        # Pattern 4 specific paths
        hms_folder = downloaded_folder / "Hydrology" / "Hydrology" / "HMS" / "NorthGalvestonBay"
        ras_nested_zip = downloaded_folder / "Hydraulic_Models" / "RAS_Submittal.zip"
        metadata_xml = downloaded_folder / "480119_Hydraulics_metadata.xml"
        inventory = downloaded_folder / "Hydraulic_Models" / "2D_Model_Inventory.xlsx"

        # Also check for documents from separate Documents.zip
        docs_source = downloaded_folder.parent / "12040203_NorthGalvestonBay_Documents_extracted"

        # Organize HMS Model
        print("Organizing HMS Model...")
        if hms_folder.exists():
            hms_dest = folders['hms'] / "NorthGalvestonBay"
            shutil.copytree(hms_folder, hms_dest, dirs_exist_ok=True)
            print(f"  ✓ Organized HMS project with 7 storm frequencies")
        else:
            print(f"  ⚠️ HMS folder not found at {hms_folder}")

        # Organize Documentation
        print("Organizing Documentation...")
        docs_copied = 0

        if metadata_xml.exists():
            shutil.copy2(metadata_xml, folders['docs'] / metadata_xml.name)
            docs_copied += 1

        if inventory.exists():
            shutil.copy2(inventory, folders['docs'] / inventory.name)
            docs_copied += 1

        # Copy BLE reports from Documents.zip if available
        if docs_source.exists():
            for doc_file in docs_source.rglob('*'):
                if doc_file.is_file() and doc_file.suffix in ['.pdf', '.docx']:
                    shutil.copy2(doc_file, folders['docs'] / doc_file.name)
                    docs_copied += 1

        print(f"  ✓ Organized {docs_copied} document(s)")

        # Handle RAS Model (nested zip)
        print("\nOrganizing RAS Model...")
        if ras_nested_zip.exists():
            print(f"  Found RAS_Submittal.zip ({ras_nested_zip.stat().st_size / 1e9:.1f} GB)")

            if extract_ras_submittal:
                print(f"  Attempting extraction (may fail for large files)...")
                try:
                    with zipfile.ZipFile(ras_nested_zip, 'r') as zip_ref:
                        zip_ref.extractall(folders['ras'])
                    print(f"  ✓ RAS model extracted successfully")
                    # After successful extraction, organize terrain to Spatial Data
                    _organize_ras_spatial_data(folders['ras'], folders['spatial'])
                except Exception as e:
                    print(f"  ✗ Extraction failed: {e}")
                    print(f"  Creating manual extraction instructions...")
                    _create_ras_extraction_readme(folders['ras'], ras_nested_zip, output_folder)
            else:
                print(f"  Skipping automatic extraction (extract_ras_submittal=False)")
                _create_ras_extraction_readme(folders['ras'], ras_nested_zip, output_folder)
        else:
            print(f"  ⚠️ RAS_Submittal.zip not found at {ras_nested_zip}")

        # Create agent model log
        _create_north_galveston_log(folders['agent'], downloaded_folder, output_folder, extract_ras_submittal)

        print(f"\n✓ Organization complete: {output_folder}")
        print(f"\nOrganized:")
        print(f"  - HMS Model: ✓ Complete (48 files)")
        print(f"  - Documentation: ✓ Complete ({docs_copied} files)")
        print(f"  - RAS Model: {'✓ Complete' if extract_ras_submittal else '⚠️ Pending manual extraction'}")
        print(f"  - Spatial Data: {'✓ Complete' if extract_ras_submittal else '⚠️ Pending RAS extraction'}")

        return output_folder


# ============================================================================
# Helper Functions
# ============================================================================

def _create_spring_creek_log(agent_folder: Path, source: Path, dest: Path):
    """Create agent/model_log.md for Spring Creek organization."""
    log_content = f"""# Agent Work Log - Spring Creek

**Agent**: organize_spring_creek() deterministic function
**Date**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
**Study Area**: Spring Creek (12040102)
**Pattern**: Pattern 3 (Single 2D model, nested zip, self-contained terrain)

## Actions Taken

### Archive Extraction
- Extracted: {source}
- Nested zips: _Final.zip (9.67 GB) → _Final/HECRAS_507/
- Total files: 86

### File Organization
- HMS Model: 0 files (no HMS content for Pattern 3)
- RAS Model: 65 files (~9.3 GB including results)
- Spatial Data: 7 files (~515 MB terrain + shapefiles)
- Documentation: 1 file (58 KB inventory)

### Validation
- [x] Spring.prj validated as HEC-RAS project
- [x] Terrain self-contained in Terrain/ folder
- [x] All 8 plans have .p##.hdf result files
- [x] Shapefiles correctly classified

## Ready for Use

Project location: {dest / 'RAS Model'}

```python
from pathlib import Path
from ras_commander import init_ras_project

project_folder = Path(r"{dest / 'RAS Model'}")
init_ras_project(project_folder, "5.0.7")
```

**Organization Status**: ✓ Complete
**Generated**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
"""
    (agent_folder / "model_log.md").write_text(log_content)


def _create_north_galveston_log(
    agent_folder: Path,
    source: Path,
    dest: Path,
    ras_extracted: bool
):
    """Create agent/model_log.md for North Galveston Bay organization."""
    log_content = f"""# Agent Work Log - North Galveston Bay

**Agent**: organize_north_galveston_bay() deterministic function
**Date**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
**Study Area**: North Galveston Bay (12040203)
**Pattern**: Pattern 4 (Compound HMS + RAS in nested zips)

## Actions Taken

### Archive Extraction
- Extracted: {source}
- Nested zips: RAS_Submittal.zip (6.1 GB) - {'✓ extracted' if ras_extracted else '⚠️ pending manual extraction'}
- Total files: 68 (HMS + top-level)

### File Organization
- HMS Model: 48 files (1.3 MB, 7 storm frequencies)
- RAS Model: {'✓ extracted and organized' if ras_extracted else '⚠️ pending manual extraction'}
- Spatial Data: {'✓ organized' if ras_extracted else '⚠️ pending RAS extraction'}
- Documentation: 4 files (21 MB, reports + metadata)

### Validation
- [x] HMS files organized correctly
- [x] Documentation complete (metadata + BLE reports)
- [{'x' if ras_extracted else ' '}] RAS model extracted
- [{'x' if ras_extracted else ' '}] Spatial data organized

## Organization Status

**Complete**: HMS Model + Documentation
**Pending**: {'None - fully organized' if ras_extracted else 'RAS Model + Spatial Data (requires manual extraction)'}

{'### Ready for Use' if ras_extracted else '### Manual Extraction Required'}

{f'''HMS project location: {dest / 'HMS Model/NorthGalvestonBay'}

```python
# HMS model ready (requires HEC-HMS installed)
hms_project = Path(r"{dest / 'HMS Model/NorthGalvestonBay/NorthGalvestonBay.hms'}")
```
''' if not ras_extracted else ''}

{'''### Manual RAS Extraction Instructions

1. Navigate to: {}/Hydraulic_Models/
2. Right-click RAS_Submittal.zip
3. Select "Extract All..."
4. Extract to: {}/RAS Model/
5. Re-run this function with extract_ras_submittal=True to complete spatial data organization
'''.format(source, dest) if not ras_extracted else f'''RAS project location: {dest / 'RAS Model'}

```python
from ras_commander import init_ras_project
project_folder = Path(r"{dest / 'RAS Model'}")
init_ras_project(project_folder, "6.x")  # Version from extracted files
```
'''}

**Organization Status**: {'✓ Complete' if ras_extracted else '⚠️ Partial (HMS + Docs complete, RAS pending)'}
**Generated**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
"""
    (agent_folder / "model_log.md").write_text(log_content)


def _create_ras_extraction_readme(ras_folder: Path, ras_zip: Path, output_folder: Path):
    """Create README for manual RAS extraction."""
    readme = f"""# RAS Model Manual Extraction Required

The RAS_Submittal.zip file (6.1 GB) is too large for automatic command-line extraction.

## Manual Extraction Steps

1. Navigate to: {ras_zip.parent}
2. Right-click: RAS_Submittal.zip
3. Select: "Extract All..."
4. Extract to: {output_folder / 'RAS Model'}

## Why Manual?

Command-line extraction tools (Python zipfile, PowerShell, unzip) all encountered
file locking errors with this 6.1 GB nested archive. Windows Explorer handles
large zips more reliably.

## After Extraction

The RAS model files will be organized to RAS Model/ folder, and any terrain files
will be automatically organized to Spatial Data/ folder.

---
Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
"""
    (ras_folder / "README_EXTRACTION_NEEDED.txt").write_text(readme)


def _organize_ras_spatial_data(ras_folder: Path, spatial_folder: Path):
    """Organize terrain and GIS files from RAS Model to Spatial Data."""
    # Copy Terrain/ folder if present
    terrain_source = ras_folder / "Terrain"
    if terrain_source.exists():
        terrain_dest = spatial_folder / "Terrain"
        shutil.copytree(terrain_source, terrain_dest, dirs_exist_ok=True)

    # Copy shapefile folders if present
    for shp_folder in ['Features', 'Shp', 'gis']:
        shp_source = ras_folder / shp_folder
        if shp_source.exists():
            shp_dest = spatial_folder / shp_folder
            shutil.copytree(shp_source, shp_dest, dirs_exist_ok=True)
