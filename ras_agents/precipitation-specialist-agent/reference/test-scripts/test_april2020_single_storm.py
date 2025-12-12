"""
Test PrecipAORC: Single Storm Event (April 30, 2020)

Step-by-step walkthrough of PrecipAorc functionality with pause for HEC-RAS inspection.
"""

import sys
from pathlib import Path

# Add ras-commander to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

# ============================================================================
# STEP 1: Setup and Project Extraction
# ============================================================================
print("=" * 70)
print("STEP 1: Setup and Project Extraction")
print("=" * 70)

from ras_commander import init_ras_project, RasExamples

# Extract example project
project_path = RasExamples.extract_project("BaldEagleCrkMulti2D")
print(f"Project extracted to: {project_path}")

# Initialize project
ras = init_ras_project(project_path, "6.6")
print(f"\nProject: {ras.project_name}")
print(f"Plans: {len(ras.plan_df)}")

# Verify template plan 06 exists
template_plan = "06"
plan_06 = ras.plan_df[ras.plan_df['plan_number'] == template_plan]
if len(plan_06) > 0:
    print(f"\nTemplate Plan {template_plan}: {plan_06.iloc[0]['Plan Title']}")
else:
    raise ValueError(f"Template plan {template_plan} not found!")

print("\n" + "=" * 70)
input("Press Enter to continue to Step 2 (Generate Storm Catalog)...")
