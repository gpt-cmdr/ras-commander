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

    # Bridge pressure flow coefficients (sluice gate discharge coefficient)
    # Based on HEC-RAS Hydraulic Reference Manual
    pressure_flow_coef_min: float = 0.8    # Minimum typical Cd for pressure flow
    pressure_flow_coef_max: float = 1.0    # Maximum typical Cd for pressure flow

    # Bridge submergence ratio threshold for orifice flow transition
    # When tailwater depth / headwater depth above deck > this ratio, orifice flow occurs
    orifice_flow_submergence_ratio: float = 0.8

    # Tailwater control threshold (fraction of deck elevation approach)
    # When TW is within this fraction of deck elevation, tailwater controls
    tailwater_control_tolerance_ft: float = 0.5


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

    # Starting WSE thresholds for FW_SW_* checks
    starting_wse_diff_threshold_ft: float = 0.5  # Max difference between base and floodway starting WSE
    starting_wse_computed_diff_ft: float = 1.0   # Max difference between specified and computed starting WSE
    starting_wse_above_bank_warning: bool = True  # Warn when starting WSE exceeds bank elevation


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
            category, field_name = parts
            if hasattr(thresholds, category):
                category_obj = getattr(thresholds, category)
                if hasattr(category_obj, field_name):
                    setattr(category_obj, field_name, value)

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
