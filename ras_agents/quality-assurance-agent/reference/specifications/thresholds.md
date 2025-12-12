# Threshold Constants Specification

## Overview

This document specifies all validation threshold constants used by RasCheck. These thresholds are based on FEMA guidelines, HEC-RAS documentation, and standard hydraulic engineering practice as implemented in cHECk-RAS.

## Implementation

### thresholds.py

```python
"""
Validation threshold constants for RasCheck.

All threshold values used for validation are defined here for easy
modification and project-specific customization.

Based on:
- FEMA Guidelines and Specifications for Flood Hazard Mapping Partners
- HEC-RAS Hydraulic Reference Manual
- cHECk-RAS validation methodology
"""

from dataclasses import dataclass, field
from typing import Dict, Optional, Any
from enum import Enum


# ============================================================================
# Threshold Data Classes
# ============================================================================

@dataclass
class ManningsNThresholds:
    """
    Thresholds for Manning's n roughness coefficients.

    Based on:
    - Open Channel Hydraulics (Chow, 1959)
    - HEC-RAS Hydraulic Reference Manual
    - FEMA guidelines for typical floodplain conditions
    """
    # Overbank (Left and Right) - higher roughness typical for floodplains
    overbank_min: float = 0.030  # Smooth pasture, lawns
    overbank_max: float = 0.200  # Dense brush, heavy timber

    # Channel - lower roughness typical for main channels
    channel_min: float = 0.025  # Clean, straight, no rifts
    channel_max: float = 0.100  # Heavy brush, timber, debris

    # Warning thresholds (stricter than error thresholds)
    overbank_warn_min: float = 0.040
    overbank_warn_max: float = 0.180
    channel_warn_min: float = 0.030
    channel_warn_max: float = 0.080


@dataclass
class TransitionCoefficientThresholds:
    """
    Thresholds for contraction/expansion coefficients.

    Based on:
    - HEC-RAS Hydraulic Reference Manual (Table 3-1)
    - Standard hydraulic practice for gradually varied flow
    """
    # Non-structure cross sections (gradual transitions)
    regular_contraction_max: float = 0.1  # Typical for gradual contraction
    regular_expansion_max: float = 0.3    # Typical for gradual expansion

    # Structure sections (abrupt transitions)
    structure_contraction_max: float = 0.3  # More aggressive for structures
    structure_expansion_max: float = 0.5    # More aggressive for structures

    # Bridge-specific transitions
    bridge_contraction_typical: float = 0.3
    bridge_expansion_typical: float = 0.5

    # Culvert-specific transitions (may be higher for entrance/exit losses)
    culvert_contraction_typical: float = 0.3
    culvert_expansion_typical: float = 0.5


@dataclass
class ReachLengthThresholds:
    """
    Thresholds for cross section spacing (reach lengths).

    Based on:
    - FEMA guidelines for adequate model resolution
    - HEC-RAS modeling best practices
    - Backwater effect distance considerations
    """
    # Ratio of consecutive reach lengths (LOB, Chan, ROB)
    length_ratio_max: float = 2.0  # Max ratio between consecutive lengths

    # Minimum reach length (prevents near-zero spacing)
    min_length_ft: float = 10.0   # Minimum allowable reach length

    # Maximum reach length (ensures adequate resolution)
    max_length_ft: float = 5000.0  # Maximum before warning

    # Cross section density (sections per mile)
    min_sections_per_mile: float = 2.0


@dataclass
class StructureThresholds:
    """
    Thresholds for bridge and culvert validation.

    Based on:
    - HEC-RAS Hydraulic Reference Manual
    - Bridge and culvert hydraulics guidelines
    """
    # Section spacing for bridges
    bridge_section_spacing_min_ft: float = 50.0    # Min distance between sections
    bridge_section_spacing_max_ft: float = 500.0   # Max distance between sections

    # Culvert entrance/exit coefficients
    culvert_entrance_coef_min: float = 0.2   # Minimum entrance coefficient
    culvert_entrance_coef_max: float = 1.0   # Maximum entrance coefficient
    culvert_exit_coef_typical: float = 1.0   # Standard exit coefficient

    # Weir coefficients
    weir_coefficient_min: float = 2.5   # Minimum Cd (conservative)
    weir_coefficient_max: float = 3.1   # Maximum Cd (sharp-crested ideal)
    weir_coefficient_typical: float = 2.6  # Typical for broad-crested weirs

    # Bridge high chord clearance (should have freeboard)
    min_high_chord_clearance_ft: float = 1.0

    # Ineffective flow requirements at structures
    structure_ineffective_required: bool = True


@dataclass
class FloodwayThresholds:
    """
    Thresholds for floodway analysis validation.

    Based on:
    - FEMA NFIP regulations (44 CFR 60.3)
    - State-specific surcharge requirements
    """
    # Standard FEMA surcharge limit (feet)
    surcharge_max_ft: float = 1.0

    # State-specific surcharge limits (can be more restrictive)
    surcharge_limits_by_state: Dict[str, float] = field(default_factory=lambda: {
        'default': 1.0,
        'AL': 1.0,
        'AK': 1.0,
        'AZ': 1.0,
        'AR': 1.0,
        'CA': 1.0,
        'CO': 1.0,
        'CT': 1.0,
        'DE': 1.0,
        'FL': 1.0,
        'GA': 1.0,
        'HI': 1.0,
        'ID': 1.0,
        'IL': 0.1,  # Illinois - 0.1 ft
        'IN': 1.0,
        'IA': 1.0,
        'KS': 1.0,
        'KY': 1.0,
        'LA': 1.0,
        'ME': 1.0,
        'MD': 1.0,
        'MA': 1.0,
        'MI': 1.0,
        'MN': 0.5,  # Minnesota - 0.5 ft
        'MS': 1.0,
        'MO': 1.0,
        'MT': 1.0,
        'NE': 1.0,
        'NV': 1.0,
        'NH': 1.0,
        'NJ': 0.2,  # New Jersey - 0.2 ft
        'NM': 1.0,
        'NY': 1.0,
        'NC': 1.0,
        'ND': 1.0,
        'OH': 1.0,
        'OK': 1.0,
        'OR': 1.0,
        'PA': 1.0,
        'RI': 1.0,
        'SC': 1.0,
        'SD': 1.0,
        'TN': 1.0,
        'TX': 1.0,
        'UT': 1.0,
        'VT': 1.0,
        'VA': 1.0,
        'WA': 1.0,
        'WV': 1.0,
        'WI': 0.01,  # Wisconsin - 0.01 ft (essentially zero rise)
        'WY': 1.0,
    })

    # Warning threshold (percentage of max surcharge)
    surcharge_warning_percent: float = 0.9  # Warn at 90% of max

    # Acceptable encroachment methods (Method 1 is manual, less preferred)
    acceptable_encroachment_methods: list = field(default_factory=lambda: [2, 3, 4, 5])

    # Discharge tolerance between profiles (percent)
    discharge_tolerance_percent: float = 5.0

    # Minimum floodway width (feet)
    min_floodway_width_ft: float = 10.0


@dataclass
class ProfileThresholds:
    """
    Thresholds for multiple profile comparison validation.

    Based on:
    - Expected physical relationships between flood profiles
    - Quality control requirements for flood studies
    """
    # WSE ordering tolerance (allows for minor numerical differences)
    wse_order_tolerance_ft: float = 0.01

    # Flow regime consistency expectations
    require_subcritical: bool = True  # Typically require subcritical flow

    # Top width relationship (larger floods = wider)
    topwidth_order_check: bool = True

    # Velocity reasonableness
    velocity_max_fps: float = 25.0  # Maximum reasonable velocity
    velocity_min_fps: float = 0.1   # Minimum (very slow flow warning)

    # Froude number limits
    froude_subcritical_max: float = 1.0
    froude_supercritical_min: float = 1.0
    froude_supercritical_max: float = 3.0


@dataclass
class GeometryThresholds:
    """
    Thresholds for geometry validation.

    Based on:
    - HEC-RAS modeling requirements
    - Physical reasonableness checks
    """
    # Ineffective flow areas
    ineffective_elevation_tolerance_ft: float = 0.1

    # Levee positioning
    levee_position_tolerance_ft: float = 1.0

    # Blocked obstruction elevation tolerance
    blocked_elevation_tolerance_ft: float = 0.1

    # Bank station requirements
    bank_station_check: bool = True
    min_channel_width_ft: float = 1.0

    # Cross section point limits
    max_xs_points: int = 500  # HEC-RAS limit
    warn_xs_points: int = 450  # Warn before hitting limit


# ============================================================================
# Default Threshold Instance
# ============================================================================

@dataclass
class ValidationThresholds:
    """
    Complete set of validation thresholds.

    Provides default values that can be overridden for specific projects.
    """
    mannings_n: ManningsNThresholds = field(default_factory=ManningsNThresholds)
    transitions: TransitionCoefficientThresholds = field(default_factory=TransitionCoefficientThresholds)
    reach_length: ReachLengthThresholds = field(default_factory=ReachLengthThresholds)
    structures: StructureThresholds = field(default_factory=StructureThresholds)
    floodway: FloodwayThresholds = field(default_factory=FloodwayThresholds)
    profiles: ProfileThresholds = field(default_factory=ProfileThresholds)
    geometry: GeometryThresholds = field(default_factory=GeometryThresholds)


# Global default thresholds instance
DEFAULT_THRESHOLDS = ValidationThresholds()


# ============================================================================
# Threshold Access Functions
# ============================================================================

def get_default_thresholds() -> ValidationThresholds:
    """
    Get default validation thresholds.

    Returns:
        ValidationThresholds instance with default values

    Example:
        >>> thresholds = get_default_thresholds()
        >>> thresholds.mannings_n.overbank_max
        0.200
    """
    return ValidationThresholds()


def get_state_surcharge_limit(state_code: str) -> float:
    """
    Get state-specific surcharge limit.

    Args:
        state_code: Two-letter state code (e.g., 'IL', 'WI')

    Returns:
        Maximum allowable surcharge in feet

    Example:
        >>> get_state_surcharge_limit('IL')
        0.1
        >>> get_state_surcharge_limit('TX')
        1.0
    """
    thresholds = get_default_thresholds()
    state_limits = thresholds.floodway.surcharge_limits_by_state
    return state_limits.get(state_code.upper(), state_limits['default'])


def create_custom_thresholds(overrides: Dict[str, Any]) -> ValidationThresholds:
    """
    Create custom thresholds with specific overrides.

    Args:
        overrides: Dictionary of threshold overrides
            Format: {'category.field': value}
            Example: {'mannings_n.overbank_max': 0.150}

    Returns:
        ValidationThresholds instance with overrides applied

    Example:
        >>> custom = create_custom_thresholds({
        ...     'mannings_n.overbank_max': 0.150,
        ...     'floodway.surcharge_max_ft': 0.5
        ... })
        >>> custom.mannings_n.overbank_max
        0.150
    """
    thresholds = get_default_thresholds()

    for key, value in overrides.items():
        parts = key.split('.')
        if len(parts) == 2:
            category, field = parts
            if hasattr(thresholds, category):
                category_obj = getattr(thresholds, category)
                if hasattr(category_obj, field):
                    setattr(category_obj, field, value)

    return thresholds


# ============================================================================
# Threshold Documentation
# ============================================================================

THRESHOLD_DOCUMENTATION = {
    'mannings_n': {
        'description': "Manning's roughness coefficient thresholds",
        'source': "Chow (1959), HEC-RAS Reference Manual",
        'fields': {
            'overbank_min': "Minimum n for overbank areas (smooth pasture)",
            'overbank_max': "Maximum n for overbank areas (dense timber)",
            'channel_min': "Minimum n for channel (clean, straight)",
            'channel_max': "Maximum n for channel (heavy brush/debris)"
        }
    },
    'transitions': {
        'description': "Contraction/expansion coefficient thresholds",
        'source': "HEC-RAS Reference Manual Table 3-1",
        'fields': {
            'regular_contraction_max': "Max contraction for gradual transitions",
            'regular_expansion_max': "Max expansion for gradual transitions",
            'structure_contraction_max': "Max contraction at structures",
            'structure_expansion_max': "Max expansion at structures"
        }
    },
    'reach_length': {
        'description': "Cross section spacing thresholds",
        'source': "FEMA modeling guidelines",
        'fields': {
            'length_ratio_max': "Maximum ratio of consecutive reach lengths",
            'min_length_ft': "Minimum allowable reach length",
            'max_length_ft': "Maximum reach length before warning"
        }
    },
    'structures': {
        'description': "Bridge and culvert thresholds",
        'source': "HEC-RAS Hydraulic Reference Manual",
        'fields': {
            'bridge_section_spacing_min_ft': "Minimum bridge section spacing",
            'bridge_section_spacing_max_ft': "Maximum bridge section spacing",
            'weir_coefficient_min': "Minimum weir discharge coefficient",
            'weir_coefficient_max': "Maximum weir discharge coefficient"
        }
    },
    'floodway': {
        'description': "Floodway analysis thresholds",
        'source': "44 CFR 60.3 (NFIP regulations)",
        'fields': {
            'surcharge_max_ft': "Maximum allowable surcharge (federal)",
            'surcharge_limits_by_state': "State-specific surcharge limits",
            'acceptable_encroachment_methods': "Valid encroachment methods"
        }
    },
    'profiles': {
        'description': "Multiple profile comparison thresholds",
        'source': "Physical hydraulic relationships",
        'fields': {
            'wse_order_tolerance_ft': "Tolerance for WSE ordering check",
            'velocity_max_fps': "Maximum reasonable velocity",
            'froude_subcritical_max': "Maximum Froude for subcritical flow"
        }
    }
}


def get_threshold_documentation(category: Optional[str] = None) -> Dict:
    """
    Get documentation for thresholds.

    Args:
        category: Optional category name to get specific docs

    Returns:
        Documentation dictionary

    Example:
        >>> docs = get_threshold_documentation('mannings_n')
        >>> docs['description']
        "Manning's roughness coefficient thresholds"
    """
    if category:
        return THRESHOLD_DOCUMENTATION.get(category, {})
    return THRESHOLD_DOCUMENTATION


# ============================================================================
# Threshold Validation
# ============================================================================

def validate_thresholds(thresholds: ValidationThresholds) -> list:
    """
    Validate threshold values for consistency.

    Checks:
    - Min values less than max values
    - Positive values where required
    - Consistent relationships

    Args:
        thresholds: ValidationThresholds to validate

    Returns:
        List of validation error messages (empty if valid)

    Example:
        >>> thresholds = get_default_thresholds()
        >>> errors = validate_thresholds(thresholds)
        >>> len(errors)
        0
    """
    errors = []

    # Manning's n checks
    n = thresholds.mannings_n
    if n.overbank_min >= n.overbank_max:
        errors.append("overbank_min must be less than overbank_max")
    if n.channel_min >= n.channel_max:
        errors.append("channel_min must be less than channel_max")
    if n.overbank_min <= 0 or n.channel_min <= 0:
        errors.append("Manning's n values must be positive")

    # Transition checks
    t = thresholds.transitions
    if t.regular_contraction_max <= 0 or t.regular_expansion_max <= 0:
        errors.append("Transition coefficients must be positive")
    if t.regular_contraction_max > t.structure_contraction_max:
        errors.append("Structure contraction should be >= regular contraction")

    # Reach length checks
    r = thresholds.reach_length
    if r.length_ratio_max <= 1.0:
        errors.append("length_ratio_max should be greater than 1.0")
    if r.min_length_ft <= 0:
        errors.append("min_length_ft must be positive")
    if r.min_length_ft >= r.max_length_ft:
        errors.append("min_length_ft must be less than max_length_ft")

    # Structure checks
    s = thresholds.structures
    if s.weir_coefficient_min >= s.weir_coefficient_max:
        errors.append("weir_coefficient_min must be less than max")

    # Floodway checks
    f = thresholds.floodway
    if f.surcharge_max_ft <= 0:
        errors.append("surcharge_max_ft must be positive")
    if not f.acceptable_encroachment_methods:
        errors.append("Must have at least one acceptable encroachment method")

    # Profile checks
    p = thresholds.profiles
    if p.velocity_max_fps <= p.velocity_min_fps:
        errors.append("velocity_max must be greater than velocity_min")

    return errors
```

## Threshold Reference Tables

### Manning's n Values

| Surface Type | Minimum | Maximum | Typical |
|--------------|---------|---------|---------|
| **Overbank Areas** |
| Pasture, no brush | 0.025 | 0.035 | 0.030 |
| Pasture, some brush | 0.035 | 0.050 | 0.040 |
| Heavy brush | 0.050 | 0.070 | 0.060 |
| Trees | 0.100 | 0.160 | 0.120 |
| Dense timber | 0.150 | 0.200 | 0.180 |
| **Channels** |
| Clean, straight | 0.025 | 0.033 | 0.030 |
| Clean, winding | 0.033 | 0.045 | 0.040 |
| Sluggish, weedy | 0.050 | 0.080 | 0.065 |
| Sluggish, brush | 0.075 | 0.150 | 0.100 |

Source: Chow, V.T. (1959), Open-Channel Hydraulics

### Transition Coefficients

| Transition Type | Contraction | Expansion |
|-----------------|-------------|-----------|
| Gradual transition | 0.1 | 0.3 |
| Typical bridge | 0.3 | 0.5 |
| Abrupt transition | 0.4 | 0.8 |
| Severe (structures) | 0.6 | 1.0 |

Source: HEC-RAS Hydraulic Reference Manual, Table 3-1

### Weir Coefficients

| Weir Type | Cd Minimum | Cd Maximum | Typical |
|-----------|------------|------------|---------|
| Sharp-crested | 3.0 | 3.3 | 3.1 |
| Broad-crested | 2.5 | 3.0 | 2.6 |
| Ogee spillway | 3.8 | 4.1 | 3.9 |
| Roadway embankment | 2.5 | 3.0 | 2.6 |

Source: HEC-RAS Hydraulic Reference Manual

### State-Specific Surcharge Limits

| State | Max Surcharge (ft) | Notes |
|-------|-------------------|-------|
| Federal (default) | 1.0 | FEMA standard |
| Illinois | 0.1 | Very restrictive |
| Minnesota | 0.5 | Moderate |
| New Jersey | 0.2 | Restrictive |
| Wisconsin | 0.01 | Essentially zero-rise |
| All others | 1.0 | Federal standard |

Source: State floodplain management regulations

### Flow Regime Criteria

| Froude Number | Flow Regime | Stability |
|---------------|-------------|-----------|
| Fr < 0.8 | Subcritical | Stable |
| 0.8 ≤ Fr < 1.0 | Near-critical | Watch |
| Fr = 1.0 | Critical | Unstable |
| 1.0 < Fr ≤ 1.5 | Supercritical | May be OK |
| Fr > 1.5 | High supercritical | Warning |
| Fr > 3.0 | Extreme | Error |

## Usage Examples

### Using Default Thresholds

```python
from ras_commander.check.thresholds import get_default_thresholds

thresholds = get_default_thresholds()

# Check a Manning's n value
n_value = 0.250
if n_value > thresholds.mannings_n.overbank_max:
    print(f"ERROR: n={n_value} exceeds maximum {thresholds.mannings_n.overbank_max}")
```

### Using State-Specific Surcharge

```python
from ras_commander.check.thresholds import get_state_surcharge_limit

# Illinois project
surcharge = 0.15
limit = get_state_surcharge_limit('IL')  # Returns 0.1

if surcharge > limit:
    print(f"ERROR: Surcharge {surcharge} ft exceeds IL limit of {limit} ft")
```

### Creating Custom Thresholds

```python
from ras_commander.check.thresholds import create_custom_thresholds

# Project with stricter requirements
custom = create_custom_thresholds({
    'mannings_n.overbank_max': 0.150,  # More restrictive
    'floodway.surcharge_max_ft': 0.5,  # State requirement
    'structures.weir_coefficient_max': 2.8  # Conservative
})

# Use custom thresholds in validation
results = RasCheck.run_all(
    hdf_path,
    geometry_hdf_path,
    thresholds=custom
)
```

### Validating Custom Thresholds

```python
from ras_commander.check.thresholds import (
    create_custom_thresholds,
    validate_thresholds
)

# Create potentially invalid thresholds
custom = create_custom_thresholds({
    'mannings_n.overbank_min': 0.300,  # Invalid: min > max
    'mannings_n.overbank_max': 0.200
})

errors = validate_thresholds(custom)
if errors:
    print("Threshold validation errors:")
    for error in errors:
        print(f"  - {error}")
```

## Integration with Check Functions

Each check function accepts an optional `thresholds` parameter:

```python
@staticmethod
@log_call
def check_nt(
    hdf_path: Path,
    geometry_hdf_path: Path,
    thresholds: Optional[ValidationThresholds] = None,
    ...
) -> CheckResults:
    """Check Manning's n and transition coefficients."""
    if thresholds is None:
        thresholds = get_default_thresholds()

    # Use thresholds in validation
    n_limits = thresholds.mannings_n
    if n_value > n_limits.overbank_max:
        messages.append(CheckMessage(
            message_id="NT_RC_01L",
            severity=Severity.ERROR,
            message=f"Manning's n ({n_value}) exceeds max ({n_limits.overbank_max})",
            threshold=n_limits.overbank_max,
            value=n_value
        ))
```

## Threshold Categories Summary

| Category | Purpose | Key Thresholds |
|----------|---------|----------------|
| `mannings_n` | Roughness validation | overbank: 0.030-0.200, channel: 0.025-0.100 |
| `transitions` | Contraction/expansion | regular: 0.1/0.3, structure: 0.3/0.5 |
| `reach_length` | XS spacing | ratio_max: 2.0, min: 10 ft, max: 5000 ft |
| `structures` | Bridge/culvert | spacing: 50-500 ft, weir Cd: 2.5-3.1 |
| `floodway` | Encroachment | surcharge: 1.0 ft (federal), state-specific |
| `profiles` | Multi-profile | WSE tolerance: 0.01 ft, velocity max: 25 fps |
| `geometry` | General geometry | ineffective tolerance: 0.1 ft |

## Original cHECk-RAS Threshold Comparison

| Check | cHECk-RAS | RasCheck | Notes |
|-------|-----------|----------|-------|
| LOB/ROB n max | 0.20 | 0.200 | Same |
| Channel n max | 0.10 | 0.100 | Same |
| LOB/ROB n min | 0.03 | 0.030 | Same |
| Channel n min | 0.025 | 0.025 | Same |
| Reach length ratio | 2.0 | 2.0 | Same |
| Regular contraction | 0.1 | 0.1 | Same |
| Regular expansion | 0.3 | 0.3 | Same |
| Structure contraction | 0.3 | 0.3 | Same |
| Structure expansion | 0.5 | 0.5 | Same |
| Weir Cd min | 2.5 | 2.5 | Same |
| Weir Cd max | 3.1 | 3.1 | Same |
| Surcharge (federal) | 1.0 ft | 1.0 ft | Same |

All thresholds have been preserved from the original cHECk-RAS implementation to ensure consistent validation results.
