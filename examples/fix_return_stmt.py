import json

# Read the notebook
with open(r'C:\GH\ras-commander\examples\103_Running_AEP_Events_from_Atlas_14.ipynb', 'r', encoding='utf-8') as f:
    nb = json.load(f)

# Find cell 22 and fix the return statement
for i, cell in enumerate(nb['cells']):
    if cell['cell_type'] == 'code':
        source = ''.join(cell['source'])
        if 'def create_plan_for_aep' in source:
            print(f'Found create_plan_for_aep in cell {i}')

            # The block comment to remove (including the return statement inside it)
            old_block = """    '''
    # Update the plan description
    description = f"AEP {aep_years}-year, {duration_hours}-hour storm\\n"
    description += f"Created: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\\n"
    description += f"Based on plan {base_plan}\\n"
    description += f"Hyetograph from: {os.path.basename(hyetograph_file)}"

    RasPlan.update_plan_description(new_plan_number, description, ras_object=project)
    print(f"Updated plan description for plan {new_plan_number}")

    return new_plan_number, new_unsteady_number
    '''"""

            # The replacement - just the return statement outside the comment
            new_block = """    # Return the plan and unsteady numbers
    return new_plan_number, new_unsteady_number"""

            new_source = source.replace(old_block, new_block)

            if new_source == source:
                print("WARNING: Pattern not found, trying alternate pattern...")
                # Try alternate pattern without escaped newlines
                old_block2 = "    '''\n    # Update the plan description\n    description = f\"AEP {aep_years}-year, {duration_hours}-hour storm\\n\"\n    description += f\"Created: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\\n\"\n    description += f\"Based on plan {base_plan}\\n\"\n    description += f\"Hyetograph from: {os.path.basename(hyetograph_file)}\"\n    \n    RasPlan.update_plan_description(new_plan_number, description, ras_object=project)\n    print(f\"Updated plan description for plan {new_plan_number}\")\n    \n    return new_plan_number, new_unsteady_number\n    '''"
                new_source = source.replace(old_block2, new_block)

            if new_source == source:
                print("Still not found. Let me print what we have...")
                # Find the triple quotes
                idx = source.find("    '''")
                if idx != -1:
                    print(f"Triple quote block starts at index {idx}")
                    print("Block content (next 500 chars):")
                    print(repr(source[idx:idx+500]))
            else:
                print("Fixed successfully!")

            # Convert back to list format for notebook
            lines = new_source.split('\n')
            cell['source'] = [line + '\n' if j < len(lines)-1 else line for j, line in enumerate(lines)]
            break

# Write back
with open(r'C:\GH\ras-commander\examples\103_Running_AEP_Events_from_Atlas_14.ipynb', 'w', encoding='utf-8') as f:
    json.dump(nb, f, indent=1)
print('Notebook saved')
