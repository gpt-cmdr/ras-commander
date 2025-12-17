"""
Validation Framework - Base Classes

Provides core validation infrastructure for ras-commander validation systems.
This module defines the base classes used throughout ras-commander for validation:
- ValidationSeverity: Enumeration of severity levels (INFO, WARNING, ERROR, CRITICAL)
- ValidationResult: Single validation check result with severity and context
- ValidationReport: Comprehensive validation report aggregating multiple results

This module follows the ras-commander static class pattern and integrates with the
centralized logging system.

Example:
    >>> from ras_commander.validation_base import ValidationSeverity, ValidationResult
    >>> result = ValidationResult(
    ...     check_name="format_check",
    ...     severity=ValidationSeverity.ERROR,
    ...     passed=False,
    ...     message="Invalid format detected",
    ...     details={"expected": "DSS", "found": "HDF"}
    ... )
    >>> print(result)
    [ERROR] [FAIL] format_check: Invalid format detected

See Also:
    - ras_commander.dss.RasDss: DSS validation methods
    - ras_commander.RasMap: Map layer validation methods
    - .claude/rules/documentation/hierarchical-knowledge-best-practices.md
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Dict, Any, List, Optional
from collections import Counter

__all__ = [
    'ValidationSeverity',
    'ValidationResult',
    'ValidationReport',
]


class ValidationSeverity(Enum):
    """
    Validation result severity levels.

    Defines four severity levels for validation results, ordered from least to most severe.
    Supports comparison operations (INFO < WARNING < ERROR < CRITICAL).

    Attributes:
        INFO: Informational message (e.g., "File size: 2.5 GB")
        WARNING: Non-critical issue that doesn't prevent operation (e.g., "Large file may be slow")
        ERROR: Critical issue that prevents operation (e.g., "File not found")
        CRITICAL: Blocking issue requiring immediate attention (e.g., "Corrupt file format")

    Example:
        >>> from ras_commander.validation_base import ValidationSeverity
        >>> severity = ValidationSeverity.ERROR
        >>> if severity >= ValidationSeverity.WARNING:
        ...     print("Action required")
        Action required

        >>> # Comparison operations
        >>> ValidationSeverity.INFO < ValidationSeverity.ERROR
        True
        >>> ValidationSeverity.CRITICAL > ValidationSeverity.WARNING
        True
    """

    INFO = "info"           # Informational (e.g., "File size: 2.5 GB")
    WARNING = "warning"     # Non-critical issue (e.g., "Large file may be slow")
    ERROR = "error"         # Critical issue (e.g., "File not found")
    CRITICAL = "critical"   # Blocking issue (e.g., "Corrupt file format")

    def __lt__(self, other: 'ValidationSeverity') -> bool:
        """
        Enable severity comparison (less than).

        Args:
            other: Another ValidationSeverity instance

        Returns:
            bool: True if this severity is less severe than other

        Raises:
            TypeError: If other is not a ValidationSeverity instance
        """
        if not isinstance(other, ValidationSeverity):
            return NotImplemented
        severity_order = {
            ValidationSeverity.INFO: 0,
            ValidationSeverity.WARNING: 1,
            ValidationSeverity.ERROR: 2,
            ValidationSeverity.CRITICAL: 3
        }
        return severity_order[self] < severity_order[other]

    def __le__(self, other: 'ValidationSeverity') -> bool:
        """
        Enable severity comparison (less than or equal).

        Args:
            other: Another ValidationSeverity instance

        Returns:
            bool: True if this severity is less severe or equal to other
        """
        return self == other or self < other

    def __gt__(self, other: 'ValidationSeverity') -> bool:
        """
        Enable severity comparison (greater than).

        Args:
            other: Another ValidationSeverity instance

        Returns:
            bool: True if this severity is more severe than other

        Raises:
            TypeError: If other is not a ValidationSeverity instance
        """
        if not isinstance(other, ValidationSeverity):
            return NotImplemented
        return not self <= other

    def __ge__(self, other: 'ValidationSeverity') -> bool:
        """
        Enable severity comparison (greater than or equal).

        Args:
            other: Another ValidationSeverity instance

        Returns:
            bool: True if this severity is more severe or equal to other
        """
        return self == other or self > other


@dataclass
class ValidationResult:
    """
    Single validation check result.

    Represents the outcome of one validation check with severity, pass/fail status,
    descriptive message, and optional context details.

    Attributes:
        check_name: Name of the validation check performed (e.g., "format_check")
        severity: Severity level of this result (ValidationSeverity enum)
        passed: True if check passed, False if failed
        message: Human-readable description of result
        details: Optional dictionary with additional context (default: empty dict)

    Example:
        >>> from ras_commander.validation_base import ValidationSeverity, ValidationResult
        >>> result = ValidationResult(
        ...     check_name="file_exists",
        ...     severity=ValidationSeverity.ERROR,
        ...     passed=False,
        ...     message="DSS file not found at specified path",
        ...     details={"path": "/data/boundary.dss", "suggestion": "Check file path"}
        ... )
        >>> print(result)
        [ERROR] [FAIL] file_exists: DSS file not found at specified path
        >>> print(result.details["suggestion"])
        Check file path

    See Also:
        ValidationReport: For aggregating multiple ValidationResult objects
    """

    check_name: str
    severity: ValidationSeverity
    passed: bool
    message: str
    details: Dict[str, Any] = field(default_factory=dict)

    def __str__(self) -> str:
        """
        Human-readable string representation.

        Returns:
            str: Formatted string like "[ERROR] [FAIL] check_name: message"

        Example:
            >>> result = ValidationResult(
            ...     check_name="format",
            ...     severity=ValidationSeverity.WARNING,
            ...     passed=True,
            ...     message="Non-standard format detected"
            ... )
            >>> str(result)
            '[WARNING] [PASS] format: Non-standard format detected'
        """
        status = "[PASS]" if self.passed else "[FAIL]"
        return f"[{self.severity.value.upper()}] {status} {self.check_name}: {self.message}"


@dataclass
class ValidationReport:
    """
    Comprehensive validation report.

    Aggregates multiple validation check results with summary statistics
    and overall validity status. Provides methods for filtering, categorization,
    and formatted output.

    Attributes:
        target: File path, DSS pathname, or other validation target identifier
        timestamp: When validation was performed (datetime)
        results: List of ValidationResult objects

    Properties:
        is_valid: True if no ERROR or CRITICAL results exist
        has_warnings: True if any WARNING results exist
        summary: Human-readable summary string

    Example:
        >>> from datetime import datetime
        >>> from ras_commander.validation_base import (
        ...     ValidationSeverity, ValidationResult, ValidationReport
        ... )
        >>> results = [
        ...     ValidationResult("check1", ValidationSeverity.INFO, True, "Pass"),
        ...     ValidationResult("check2", ValidationSeverity.WARNING, True, "Warning"),
        ...     ValidationResult("check3", ValidationSeverity.ERROR, False, "Error")
        ... ]
        >>> report = ValidationReport(
        ...     target="boundary.dss",
        ...     timestamp=datetime.now(),
        ...     results=results
        ... )
        >>> print(report.is_valid)
        False
        >>> print(report.summary)
        1 info, 1 warnings, 1 errors, 0 critical

    See Also:
        ValidationResult: Individual validation check result
    """

    target: str
    timestamp: datetime
    results: List[ValidationResult]

    @property
    def is_valid(self) -> bool:
        """
        Check if validation passed (no ERROR or CRITICAL results).

        Returns:
            bool: True if validation passed (no blocking issues)

        Example:
            >>> report = ValidationReport(
            ...     target="test.dss",
            ...     timestamp=datetime.now(),
            ...     results=[
            ...         ValidationResult("check", ValidationSeverity.INFO, True, "OK")
            ...     ]
            ... )
            >>> report.is_valid
            True

            >>> report.results.append(
            ...     ValidationResult("check2", ValidationSeverity.ERROR, False, "Failed")
            ... )
            >>> report.is_valid
            False
        """
        return not any(
            r.severity in [ValidationSeverity.ERROR, ValidationSeverity.CRITICAL]
            for r in self.results
        )

    @property
    def has_warnings(self) -> bool:
        """
        Check if any WARNING results exist.

        Returns:
            bool: True if there are warnings

        Example:
            >>> report = ValidationReport(
            ...     target="test.dss",
            ...     timestamp=datetime.now(),
            ...     results=[
            ...         ValidationResult("check", ValidationSeverity.WARNING, True, "Warning")
            ...     ]
            ... )
            >>> report.has_warnings
            True
        """
        return any(r.severity == ValidationSeverity.WARNING for r in self.results)

    @property
    def summary(self) -> str:
        """
        Human-readable summary of results.

        Returns:
            str: Summary like "3 info, 1 warnings, 0 errors, 0 critical"

        Example:
            >>> report = ValidationReport(
            ...     target="test.dss",
            ...     timestamp=datetime.now(),
            ...     results=[
            ...         ValidationResult("c1", ValidationSeverity.INFO, True, "OK"),
            ...         ValidationResult("c2", ValidationSeverity.INFO, True, "OK"),
            ...         ValidationResult("c3", ValidationSeverity.WARNING, True, "Warn")
            ...     ]
            ... )
            >>> report.summary
            '2 info, 1 warnings, 0 errors, 0 critical'
        """
        counts = Counter(r.severity for r in self.results)
        return (
            f"{counts[ValidationSeverity.INFO]} info, "
            f"{counts[ValidationSeverity.WARNING]} warnings, "
            f"{counts[ValidationSeverity.ERROR]} errors, "
            f"{counts[ValidationSeverity.CRITICAL]} critical"
        )

    def get_results_by_severity(
        self,
        severity: ValidationSeverity
    ) -> List[ValidationResult]:
        """
        Filter results by severity level.

        Args:
            severity: Severity level to filter

        Returns:
            List[ValidationResult]: Results matching severity

        Example:
            >>> report = ValidationReport(
            ...     target="test.dss",
            ...     timestamp=datetime.now(),
            ...     results=[
            ...         ValidationResult("c1", ValidationSeverity.ERROR, False, "Error 1"),
            ...         ValidationResult("c2", ValidationSeverity.WARNING, True, "Warning"),
            ...         ValidationResult("c3", ValidationSeverity.ERROR, False, "Error 2")
            ...     ]
            ... )
            >>> errors = report.get_results_by_severity(ValidationSeverity.ERROR)
            >>> len(errors)
            2
            >>> errors[0].message
            'Error 1'
        """
        return [r for r in self.results if r.severity == severity]

    def get_failed_checks(self) -> List[ValidationResult]:
        """
        Get all failed validation checks.

        Returns:
            List[ValidationResult]: Results where passed=False

        Example:
            >>> report = ValidationReport(
            ...     target="test.dss",
            ...     timestamp=datetime.now(),
            ...     results=[
            ...         ValidationResult("c1", ValidationSeverity.INFO, True, "Pass"),
            ...         ValidationResult("c2", ValidationSeverity.ERROR, False, "Fail 1"),
            ...         ValidationResult("c3", ValidationSeverity.ERROR, False, "Fail 2")
            ...     ]
            ... )
            >>> failed = report.get_failed_checks()
            >>> len(failed)
            2
            >>> all(not r.passed for r in failed)
            True
        """
        return [r for r in self.results if not r.passed]

    def print_report(self, show_passed: bool = False) -> None:
        """
        Print formatted validation report to console.

        Args:
            show_passed: If True, show passed checks. If False, only show failures.

        Example:
            >>> report = ValidationReport(
            ...     target="boundary.dss",
            ...     timestamp=datetime.now(),
            ...     results=[
            ...         ValidationResult("format", ValidationSeverity.INFO, True, "Valid"),
            ...         ValidationResult("exists", ValidationSeverity.ERROR, False, "Not found")
            ...     ]
            ... )
            >>> report.print_report(show_passed=False)
            ================================================================================
            Validation Report: boundary.dss
            Timestamp: 2025-12-15T10:30:00
            ================================================================================
            <BLANKLINE>
            Summary: 1 info, 0 warnings, 1 errors, 0 critical
            Overall Status: INVALID
            <BLANKLINE>
            ================================================================================
            Detailed Results:
            ================================================================================
            <BLANKLINE>
            [ERROR] [FAIL] exists: Not found
            <BLANKLINE>
            ================================================================================
        """
        print(f"\n{'='*80}")
        print(f"Validation Report: {self.target}")
        print(f"Timestamp: {self.timestamp.isoformat()}")
        print(f"{'='*80}")
        print(f"\nSummary: {self.summary}")
        print(f"Overall Status: {'VALID' if self.is_valid else 'INVALID'}")
        print(f"\n{'='*80}")
        print("Detailed Results:")
        print(f"{'='*80}\n")

        for result in self.results:
            # Skip passed checks if show_passed=False
            if not show_passed and result.passed and result.severity == ValidationSeverity.INFO:
                continue

            print(result)
            if result.details:
                for key, value in result.details.items():
                    print(f"  {key}: {value}")
                print()

        print(f"{'='*80}\n")

    def __str__(self) -> str:
        """
        String representation.

        Returns:
            str: Brief summary like "ValidationReport(target=test.dss, 2 info, 1 warnings, 0 errors, 0 critical)"

        Example:
            >>> report = ValidationReport(
            ...     target="test.dss",
            ...     timestamp=datetime.now(),
            ...     results=[
            ...         ValidationResult("c1", ValidationSeverity.INFO, True, "OK")
            ...     ]
            ... )
            >>> str(report)
            'ValidationReport(target=test.dss, 1 info, 0 warnings, 0 errors, 0 critical)'
        """
        return f"ValidationReport(target={self.target}, {self.summary})"
