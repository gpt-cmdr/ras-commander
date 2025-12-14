"""Test script to verify the StormGenerator parser fix."""
import sys
sys.path.insert(0, r'C:\GH\ras-commander')

from ras_commander.precip.StormGenerator import StormGenerator

# Test the parsing directly with JavaScript-style syntax (semicolons)
test_content = """result = 'values';
quantiles = [['0.312', '0.371'], ['0.485', '0.579']];
upper = [['0.347', '0.412'], ['0.539', '0.642']];
region = 'ne';"""

print("Test content:")
print(test_content)
print()

result = StormGenerator._parse_noaa_response(test_content)
print(f'Parsed result keys: {list(result.keys())}')
for k, v in result.items():
    print(f'  {k}: {v}')

print()
if 'quantiles' in result and isinstance(result['quantiles'], list):
    print('SUCCESS: Parser fix is working!')

    # Now test the actual API call
    print('\n' + '='*60)
    print('Testing actual NOAA API call...')
    print('='*60)

    try:
        gen = StormGenerator.download_from_coordinates(
            lat=41.053028,
            lon=-77.574953,
            project_folder=None  # Don't cache for this test
        )
        print(f'\nSUCCESS: Downloaded Atlas 14 data')
        print(f'  Durations: {len(gen.durations_hours)}')
        print(f'  ARIs: {gen.ari_columns}')
    except Exception as e:
        print(f'\nAPI call FAILED: {e}')
else:
    print('FAILED: Parser is not correctly handling semicolons')

    # Debug: show what each line produces
    print('\nDebug - parsing line by line:')
    for line in test_content.split('\n'):
        line = line.strip()
        if '=' in line:
            print(f"  Line: {repr(line)}")
