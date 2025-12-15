#!/usr/bin/env python3
"""
Audit Jupyter notebooks for issues without executing them.

Scans notebook cell outputs for:
- Stored exceptions (output_type: "error")
- Stderr stream outputs
- Traceback/error-like text in outputs
- Unexpected behavior patterns (empty results, missing files, no maps)
- Security issues (path leaks, IP leaks)

Generates audit.json and audit.md for LLM review.

Usage:
    python audit_ipynb.py                              # Audit all example notebooks
    python audit_ipynb.py notebook.ipynb               # Audit single notebook
    python audit_ipynb.py --out-dir working/audit_01   # Custom output directory
    python audit_ipynb.py --fail-on-error-outputs      # Exit 1 if errors found (CI mode)
    python audit_ipynb.py --fail-on-security-leaks     # Exit 1 if security leaks found
"""

import json
import re
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Any
import argparse
import sys


def scan_notebook(notebook_path: Path) -> Dict[str, Any]:
    """
    Scan a single notebook for issues.

    Args:
        notebook_path: Path to .ipynb file

    Returns:
        Dictionary with audit findings
    """
    with open(notebook_path, 'r', encoding='utf-8') as f:
        nb = json.load(f)

    findings = {
        'notebook': notebook_path.name,
        'path': str(notebook_path),
        'total_cells': len(nb.get('cells', [])),
        'exceptions': [],
        'stderr_outputs': [],
        'anomalies': [],
        'security_leaks': [],
        'summary': {}
    }

    for cell_idx, cell in enumerate(nb.get('cells', [])):
        cell_num = cell_idx + 1  # 1-indexed for user display

        # Scan outputs
        for output in cell.get('outputs', []):
            # Check for stored exceptions
            if output.get('output_type') == 'error':
                findings['exceptions'].append({
                    'cell': cell_num,
                    'error_name': output.get('ename', 'Unknown'),
                    'error_value': output.get('evalue', ''),
                    'traceback': output.get('traceback', [])
                })

            # Check for stderr streams
            if output.get('output_type') == 'stream' and output.get('name') == 'stderr':
                stderr_text = ''.join(output.get('text', []))
                if stderr_text.strip():
                    findings['stderr_outputs'].append({
                        'cell': cell_num,
                        'text': stderr_text
                    })

            # Scan text outputs for anomaly patterns and security leaks
            text_to_scan = []

            if output.get('output_type') == 'stream' and output.get('name') == 'stdout':
                text_to_scan.append(''.join(output.get('text', [])))

            if output.get('output_type') in ('display_data', 'execute_result'):
                if 'text/plain' in output.get('data', {}):
                    plain_text = output['data']['text/plain']
                    if isinstance(plain_text, list):
                        text_to_scan.append(''.join(plain_text))
                    else:
                        text_to_scan.append(plain_text)

            # Scan combined text
            for text in text_to_scan:
                # Anomaly detection
                anomalies_found = detect_anomalies(text, cell_num)
                findings['anomalies'].extend(anomalies_found)

                # Security scanning
                security_leaks = detect_security_leaks(text, cell_num)
                findings['security_leaks'].extend(security_leaks)

    # Generate summary
    findings['summary'] = {
        'exception_count': len(findings['exceptions']),
        'stderr_count': len(findings['stderr_outputs']),
        'anomaly_count': len(findings['anomalies']),
        'security_leak_count': len(findings['security_leaks']),
        'has_issues': any([
            findings['exceptions'],
            findings['stderr_outputs'],
            findings['anomalies'],
            findings['security_leaks']
        ])
    }

    return findings


def detect_anomalies(text: str, cell_num: int) -> List[Dict[str, Any]]:
    """
    Detect unexpected behavior patterns in output text.

    Args:
        text: Output text to scan
        cell_num: Cell index (1-indexed)

    Returns:
        List of anomaly findings
    """
    anomalies = []

    # Pattern: Empty results
    empty_patterns = [
        r'\b0\s+rows?\b',
        r'\bempty\s+(dataframe|array|list)\b',
        r'\bno\s+data\b',
        r'\bno\s+results?\b',
        r'len\([^)]+\)\s*==\s*0',
    ]

    for pattern in empty_patterns:
        if re.search(pattern, text, re.IGNORECASE):
            anomalies.append({
                'cell': cell_num,
                'type': 'empty_results',
                'pattern': pattern,
                'context': text[:200]  # First 200 chars for context
            })
            break  # Only flag once per cell

    # Pattern: Missing files
    missing_file_patterns = [
        r'file not found',
        r'does not exist',
        r'no such file',
        r'missing\s+file',
    ]

    for pattern in missing_file_patterns:
        if re.search(pattern, text, re.IGNORECASE):
            anomalies.append({
                'cell': cell_num,
                'type': 'missing_file',
                'pattern': pattern,
                'context': text[:200]
            })
            break

    # Pattern: No maps generated
    if re.search(r'\b0\s+maps?\s+(created|generated)\b', text, re.IGNORECASE):
        anomalies.append({
            'cell': cell_num,
            'type': 'no_maps_generated',
            'pattern': '0 maps generated',
            'context': text[:200]
        })

    # Pattern: All NaN or suspicious sentinel values
    if re.search(r'\ball\s+nan\b', text, re.IGNORECASE):
        anomalies.append({
            'cell': cell_num,
            'type': 'all_nan_values',
            'pattern': 'all NaN',
            'context': text[:200]
        })

    # Pattern: Suspicious sentinel values (-999, -9999)
    if re.search(r'-9{3,}(?:\.\d+)?', text):
        anomalies.append({
            'cell': cell_num,
            'type': 'sentinel_values',
            'pattern': '-999 (sentinel value)',
            'context': text[:200]
        })

    return anomalies


def detect_security_leaks(text: str, cell_num: int) -> List[Dict[str, Any]]:
    """
    Detect security issues like path leaks and IP leaks.

    Args:
        text: Output text to scan
        cell_num: Cell index (1-indexed)

    Returns:
        List of security leak findings
    """
    leaks = []

    # Pattern: Windows absolute paths with usernames
    windows_paths = re.findall(r'[A-Z]:\\Users\\([^\\]+)\\', text)
    if windows_paths:
        leaks.append({
            'cell': cell_num,
            'type': 'windows_path_leak',
            'usernames': list(set(windows_paths)),
            'context': text[:200]
        })

    # Pattern: Unix/Linux home paths
    unix_paths = re.findall(r'/home/([^/]+)/', text)
    if unix_paths:
        leaks.append({
            'cell': cell_num,
            'type': 'unix_path_leak',
            'usernames': list(set(unix_paths)),
            'context': text[:200]
        })

    # Pattern: Private network IP addresses (RFC1918)
    # 10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16
    ip_patterns = [
        r'\b10\.\d{1,3}\.\d{1,3}\.\d{1,3}\b',
        r'\b172\.(1[6-9]|2[0-9]|3[01])\.\d{1,3}\.\d{1,3}\b',
        r'\b192\.168\.\d{1,3}\.\d{1,3}\b',
    ]

    for pattern in ip_patterns:
        ips = re.findall(pattern, text)
        if ips:
            leaks.append({
                'cell': cell_num,
                'type': 'private_ip_leak',
                'ips': list(set(ips)),
                'context': text[:200]
            })
            break  # Only flag once per cell

    return leaks


def generate_markdown_report(findings: Dict[str, Any]) -> str:
    """
    Generate human-readable Markdown audit report.

    Args:
        findings: Audit findings dictionary

    Returns:
        Markdown formatted report
    """
    md = f"""# Notebook Audit Report

**Notebook**: {findings['notebook']}
**Path**: {findings['path']}
**Total Cells**: {findings['total_cells']}
**Scan Time**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

---

## Summary

- **Exceptions**: {findings['summary']['exception_count']}
- **Stderr Outputs**: {findings['summary']['stderr_count']}
- **Anomalies**: {findings['summary']['anomaly_count']}
- **Security Leaks**: {findings['summary']['security_leak_count']}
- **Has Issues**: {'Yes' if findings['summary']['has_issues'] else 'No'}

---

"""

    # Exceptions section
    if findings['exceptions']:
        md += "## Stored Exceptions\n\n"
        for exc in findings['exceptions']:
            md += f"### Cell [{exc['cell']}]: {exc['error_name']}\n\n"
            md += f"**Error Value**: `{exc['error_value']}`\n\n"
            if exc['traceback']:
                md += "**Traceback**:\n```\n"
                md += '\n'.join(exc['traceback'][:10])  # Limit to first 10 lines
                md += "\n```\n\n"

    # Stderr section
    if findings['stderr_outputs']:
        md += "## Stderr Outputs\n\n"
        for stderr in findings['stderr_outputs']:
            md += f"### Cell [{stderr['cell']}]\n\n"
            md += "```\n"
            md += stderr['text'][:500]  # Limit to first 500 chars
            if len(stderr['text']) > 500:
                md += "\n... (truncated)"
            md += "\n```\n\n"

    # Anomalies section
    if findings['anomalies']:
        md += "## Anomalies Detected\n\n"
        for anomaly in findings['anomalies']:
            md += f"### Cell [{anomaly['cell']}]: {anomaly['type']}\n\n"
            md += f"**Pattern**: `{anomaly['pattern']}`\n\n"
            md += f"**Context**:\n```\n{anomaly['context']}\n```\n\n"

    # Security leaks section
    if findings['security_leaks']:
        md += "## Security Leaks\n\n"
        for leak in findings['security_leaks']:
            md += f"### Cell [{leak['cell']}]: {leak['type']}\n\n"
            if 'usernames' in leak:
                md += f"**Usernames Leaked**: {', '.join(leak['usernames'])}\n\n"
            if 'ips' in leak:
                md += f"**IPs Leaked**: {', '.join(leak['ips'])}\n\n"
            md += f"**Context**:\n```\n{leak['context']}\n```\n\n"

    # No issues message
    if not findings['summary']['has_issues']:
        md += "## ✅ No Issues Found\n\n"
        md += "This notebook passed all audit checks.\n\n"

    md += "---\n\n"
    md += "*Generated by `scripts/notebooks/audit_ipynb.py`*\n"

    return md


def main():
    parser = argparse.ArgumentParser(
        description='Audit Jupyter notebooks for issues without executing them.'
    )
    parser.add_argument(
        'notebooks',
        nargs='*',
        help='Notebook files to audit (default: examples/*.ipynb)'
    )
    parser.add_argument(
        '--out-dir',
        type=Path,
        default=Path('working/notebook_runs') / datetime.now().strftime('%Y%m%d_%H%M%S'),
        help='Output directory for audit results'
    )
    parser.add_argument(
        '--fail-on-error-outputs',
        action='store_true',
        help='Exit with code 1 if any error outputs found (CI mode)'
    )
    parser.add_argument(
        '--fail-on-security-leaks',
        action='store_true',
        help='Exit with code 1 if any security leaks found'
    )

    args = parser.parse_args()

    # Determine notebooks to scan
    if args.notebooks:
        notebook_paths = [Path(nb) for nb in args.notebooks]
    else:
        # Default: scan all example notebooks
        examples_dir = Path(__file__).parent.parent.parent / 'examples'
        notebook_paths = sorted(examples_dir.glob('*.ipynb'))

    # Validate notebooks exist
    notebook_paths = [nb for nb in notebook_paths if nb.exists()]
    if not notebook_paths:
        print("ERROR: No notebooks found to audit")
        sys.exit(1)

    print(f"Auditing {len(notebook_paths)} notebooks...")
    print(f"Output directory: {args.out_dir}")

    # Create output directory
    args.out_dir.mkdir(parents=True, exist_ok=True)

    # Scan all notebooks
    all_findings = []
    has_errors = False
    has_security_leaks = False

    for nb_path in notebook_paths:
        print(f"  Scanning {nb_path.name}...", end=' ')

        try:
            findings = scan_notebook(nb_path)
            all_findings.append(findings)

            # Track issues for exit code
            if findings['summary']['exception_count'] > 0:
                has_errors = True
            if findings['summary']['security_leak_count'] > 0:
                has_security_leaks = True

            # Status indicator
            if findings['summary']['has_issues']:
                print(f"⚠️  {findings['summary']['exception_count']} errors, "
                      f"{findings['summary']['anomaly_count']} anomalies, "
                      f"{findings['summary']['security_leak_count']} leaks")
            else:
                print("✅")

        except Exception as e:
            print(f"❌ FAILED: {e}")
            continue

    # Write combined JSON
    json_path = args.out_dir / 'audit.json'
    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump({
            'scan_time': datetime.now().isoformat(),
            'notebooks_scanned': len(all_findings),
            'findings': all_findings
        }, f, indent=2)
    print(f"\nJSON report: {json_path}")

    # Write individual Markdown reports
    for findings in all_findings:
        md_filename = f"audit_{Path(findings['notebook']).stem}.md"
        md_path = args.out_dir / md_filename
        with open(md_path, 'w', encoding='utf-8') as f:
            f.write(generate_markdown_report(findings))

    # Write combined Markdown summary
    summary_md_path = args.out_dir / 'audit.md'
    with open(summary_md_path, 'w', encoding='utf-8') as f:
        f.write("# Combined Notebook Audit Report\n\n")
        f.write(f"**Scan Time**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"**Notebooks Scanned**: {len(all_findings)}\n\n")

        # Summary table
        f.write("## Summary Table\n\n")
        f.write("| Notebook | Cells | Errors | Anomalies | Leaks |\n")
        f.write("|----------|-------|--------|-----------|-------|\n")
        for findings in all_findings:
            f.write(f"| {findings['notebook']} | "
                   f"{findings['total_cells']} | "
                   f"{findings['summary']['exception_count']} | "
                   f"{findings['summary']['anomaly_count']} | "
                   f"{findings['summary']['security_leak_count']} |\n")

        f.write("\n---\n\n")
        f.write("See individual `audit_<notebook>.md` files for detailed findings.\n")

    print(f"Markdown summary: {summary_md_path}")

    # Exit code handling
    if args.fail_on_error_outputs and has_errors:
        print("\n❌ FAIL: Error outputs detected (--fail-on-error-outputs)")
        sys.exit(1)

    if args.fail_on_security_leaks and has_security_leaks:
        print("\n❌ FAIL: Security leaks detected (--fail-on-security-leaks)")
        sys.exit(1)

    print("\n✅ Audit complete")
    sys.exit(0)


if __name__ == '__main__':
    main()
