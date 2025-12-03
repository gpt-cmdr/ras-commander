#!/bin/bash
# HEC-RAS Linux Execution Script
# This script runs HEC-RAS plans in the Docker container
#
# Usage: run_ras.sh <plan_number> [geometry_number]
#   plan_number: Two-digit plan number (e.g., 01, 04)
#   geometry_number: Optional geometry number (extracted from plan file if not provided)

set -e  # Exit on error

# Get plan number from argument
PLAN_NUMBER=${1:-"01"}
PLAN_NUMBER=$(printf "%02d" $PLAN_NUMBER 2>/dev/null || echo "$PLAN_NUMBER")

echo "========================================"
echo " HEC-RAS Linux Execution"
echo "========================================"
echo "$(date '+%Y-%m-%d %H:%M:%S') - Starting execution for plan $PLAN_NUMBER"

# Set environment variables
export LD_LIBRARY_PATH="/app/libs:/app/libs/mkl:/app/libs/rhel_8:$LD_LIBRARY_PATH"
export PATH="/app/bin:$PATH"
export MAX_RUNTIME=${MAX_RUNTIME_MINUTES:-480}
GEOMETRY_NUMBER=${GEOMETRY_NUMBER:-${2:-""}}

# Navigate to input directory
cd /app/input

# Find project file
PRJ_FILE=$(ls *.prj 2>/dev/null | head -1)
if [ -z "$PRJ_FILE" ]; then
    echo "$(date '+%Y-%m-%d %H:%M:%S') - Error: No project file (.prj) found in /app/input"
    exit 1
fi

PROJECT_NAME="${PRJ_FILE%.prj}"
echo "$(date '+%Y-%m-%d %H:%M:%S') - Project: $PROJECT_NAME"

# Check if .tmp.hdf or .hdf exists
TMP_HDF="${PROJECT_NAME}.p${PLAN_NUMBER}.tmp.hdf"
FULL_HDF="${PROJECT_NAME}.p${PLAN_NUMBER}.hdf"

if [ -f "$TMP_HDF" ]; then
    echo "$(date '+%Y-%m-%d %H:%M:%S') - Found preprocessed file: $TMP_HDF"
    INPUT_HDF="$TMP_HDF"
elif [ -f "$FULL_HDF" ]; then
    echo "$(date '+%Y-%m-%d %H:%M:%S') - Found full HDF file: $FULL_HDF"
    echo "$(date '+%Y-%m-%d %H:%M:%S') - Using full HDF as input (preprocessing may already be complete)"
    # Copy to .tmp.hdf for consistency
    cp "$FULL_HDF" "$TMP_HDF"
    INPUT_HDF="$TMP_HDF"
else
    echo "$(date '+%Y-%m-%d %H:%M:%S') - Error: No preprocessed file found"
    echo "Looking for: $TMP_HDF or $FULL_HDF"
    echo "Available .hdf files:"
    ls -la *.hdf 2>/dev/null || echo "  No .hdf files found"
    echo "Available .tmp.hdf files:"
    ls -la *.tmp.hdf 2>/dev/null || echo "  No .tmp.hdf files found"
    exit 1
fi

echo "$(date '+%Y-%m-%d %H:%M:%S') - Input file: $INPUT_HDF ($(du -h "$INPUT_HDF" | cut -f1))"

# Determine geometry number
if [ -z "$GEOMETRY_NUMBER" ]; then
    # Try to extract from plan file
    PLAN_FILE="${PROJECT_NAME}.p${PLAN_NUMBER}"
    if [ -f "$PLAN_FILE" ]; then
        GEOMETRY_NUMBER=$(grep "^Geom File=" "$PLAN_FILE" 2>/dev/null | sed 's/Geom File=g//' | head -1)
    fi

    # Default to plan number if still not found
    if [ -z "$GEOMETRY_NUMBER" ]; then
        GEOMETRY_NUMBER="$PLAN_NUMBER"
        echo "$(date '+%Y-%m-%d %H:%M:%S') - Warning: Could not determine geometry number, using plan number: $GEOMETRY_NUMBER"
    else
        echo "$(date '+%Y-%m-%d %H:%M:%S') - Extracted geometry number from plan file: $GEOMETRY_NUMBER"
    fi
else
    echo "$(date '+%Y-%m-%d %H:%M:%S') - Using provided geometry number: $GEOMETRY_NUMBER"
fi

# Check for execution file
X_FILE="${PROJECT_NAME}.x${GEOMETRY_NUMBER}"
if [ ! -f "$X_FILE" ]; then
    echo "$(date '+%Y-%m-%d %H:%M:%S') - Warning: Execution file not found: $X_FILE"
    echo "Available .x files:"
    ls -la *.x* 2>/dev/null || echo "  No .x files found"
fi

# Set timeout for execution
TIMEOUT_SECONDS=$((MAX_RUNTIME * 60))
echo "$(date '+%Y-%m-%d %H:%M:%S') - Maximum runtime: ${MAX_RUNTIME} minutes"

# Function to run with timeout
run_with_timeout() {
    local cmd="$1"
    local timeout="$2"

    timeout --preserve-status --kill-after=10 "$timeout" $cmd
    local exit_code=$?

    if [ $exit_code -eq 124 ]; then
        echo "$(date '+%Y-%m-%d %H:%M:%S') - Error: Execution timed out after ${MAX_RUNTIME} minutes"
        return 1
    elif [ $exit_code -ne 0 ]; then
        echo "$(date '+%Y-%m-%d %H:%M:%S') - Error: Execution failed with exit code $exit_code"
        return $exit_code
    fi

    return 0
}

# Step 1: Run Geometry Preprocessor (if needed)
echo ""
echo "$(date '+%Y-%m-%d %H:%M:%S') - Step 1: Geometry Preprocessing"
echo "----------------------------------------"

# Check if .x file needs updating
if [ -f "$X_FILE" ]; then
    echo "$(date '+%Y-%m-%d %H:%M:%S') - Execution file exists, checking if preprocessing needed..."
    # Could add timestamp comparison here
else
    echo "$(date '+%Y-%m-%d %H:%M:%S') - Running RasGeomPreprocess..."
    if run_with_timeout "RasGeomPreprocess $INPUT_HDF x${GEOMETRY_NUMBER}" 300; then
        echo "$(date '+%Y-%m-%d %H:%M:%S') - Geometry preprocessing completed"
    else
        echo "$(date '+%Y-%m-%d %H:%M:%S') - Geometry preprocessing failed, continuing anyway..."
    fi
fi

# Step 2: Run Unsteady Simulation
echo ""
echo "$(date '+%Y-%m-%d %H:%M:%S') - Step 2: Unsteady Flow Simulation"
echo "----------------------------------------"
echo "$(date '+%Y-%m-%d %H:%M:%S') - Running RasUnsteady $INPUT_HDF x${GEOMETRY_NUMBER}"

if run_with_timeout "RasUnsteady $INPUT_HDF x${GEOMETRY_NUMBER}" "$TIMEOUT_SECONDS"; then
    echo "$(date '+%Y-%m-%d %H:%M:%S') - Unsteady simulation completed successfully"
else
    exit_code=$?
    echo "$(date '+%Y-%m-%d %H:%M:%S') - Unsteady simulation failed"
    exit $exit_code
fi

# Step 3: Copy results to output directory
echo ""
echo "$(date '+%Y-%m-%d %H:%M:%S') - Step 3: Finalizing results..."
echo "----------------------------------------"

# Rename .tmp.hdf to .hdf if simulation completed in .tmp.hdf
if [ -f "$INPUT_HDF" ] && [ "$INPUT_HDF" = "$TMP_HDF" ]; then
    # Check if results are in the tmp file
    if [ ! -f "$FULL_HDF" ] || [ "$TMP_HDF" -nt "$FULL_HDF" ]; then
        echo "$(date '+%Y-%m-%d %H:%M:%S') - Copying $TMP_HDF to $FULL_HDF"
        cp "$TMP_HDF" "$FULL_HDF"
    fi
fi

# Copy to output if different directory
if [ "/app/input" != "/app/output" ] && [ -d "/app/output" ]; then
    echo "$(date '+%Y-%m-%d %H:%M:%S') - Copying results to /app/output..."

    # Copy HDF results
    for hdf_file in ${PROJECT_NAME}.p${PLAN_NUMBER}*.hdf; do
        if [ -f "$hdf_file" ]; then
            cp -f "$hdf_file" "/app/output/" 2>/dev/null && \
                echo "$(date '+%Y-%m-%d %H:%M:%S') - Copied $hdf_file"
        fi
    done

    # Copy log files if they exist
    for log_file in *.log ${PROJECT_NAME}.p${PLAN_NUMBER}.computeMsgs.txt; do
        if [ -f "$log_file" ]; then
            cp -f "$log_file" "/app/output/" 2>/dev/null && \
                echo "$(date '+%Y-%m-%d %H:%M:%S') - Copied $log_file"
        fi
    done
fi

echo ""
echo "========================================"
echo " Execution Complete"
echo "========================================"
echo "$(date '+%Y-%m-%d %H:%M:%S') - Plan $PLAN_NUMBER completed successfully"

exit 0
