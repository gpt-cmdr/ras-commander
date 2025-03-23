# Notebook Preprocessing for Library Assistant

This document explains the notebook preprocessing functionality added to the Library Assistant. This feature creates a clean copy of the context folder in a temporary directory, processes Jupyter notebooks to remove images and truncate dataframes, and integrates with the existing filtering mechanisms.

## Overview

When enabled, the Library Assistant will:

1. Create a temporary copy of your context folder
2. Process all Jupyter notebooks in that copy to:
   - Remove binary image data from outputs
   - Truncate dataframe outputs to show only headers and the first row
3. Use this clean copy for context processing
4. Preserve your original files untouched
5. Automatically clean up the temporary folder when the application exits

## Implementation Details

The implementation consists of three main components:

1. **Context Preprocessor** (`utils/context_preprocessor.py`): Handles the creation and processing of a clean copy of the context folder.
2. **Integration Module** (`utils/context_integration.py`): Connects the preprocessor with the Library Assistant's workflow.
3. **Modified Initialization** (changes to existing files): Allows for seamless integration with minimal changes to the core functionality.

### How It Works

1. During initialization, the Library Assistant checks if the notebook preprocessing functionality is available.
2. If available, it creates a temporary directory using Python's `tempfile` module.
3. A clean copy of the context folder is created in this temporary directory.
4. All Jupyter notebooks in this copy are processed to:
   - Remove `image/png` data from cell outputs (replaced with a placeholder text)
   - Truncate HTML dataframe outputs to show only headers and the first row
   - Replace large plain text dataframe outputs with a placeholder
5. The Library Assistant uses this clean copy for all subsequent operations.
6. When the application exits, the temporary directory is automatically deleted.

### Benefits

- **Preserves Original Files**: All processing happens on a copy, keeping your original notebooks untouched.
- **Reduces Token Usage**: By removing large binary data and truncating dataframes, token usage is significantly reduced.
- **Improves Context Quality**: Removes noise from the context, allowing the AI to focus on the code and text.
- **Seamless Integration**: Works with existing filtering mechanisms (`omit_folders`, `omit_extensions`, and `omit_files`).

## Technical Details

### Folder Structure

The temporary folder is created with a structure that mirrors your original context folder:

```
/tmp/library_assistant_context_XXXXXX/
└── <original_folder_name>/
    ├── file1.py
    ├── file2.md
    ├── notebook1.ipynb (processed)
    └── subfolder/
        └── notebook2.ipynb (processed)
```

### Notebook Processing

For each Jupyter notebook, the preprocessor:

1. Parses the notebook JSON structure
2. For each cell with outputs:
   - Removes `image/png` data from display_data outputs
   - Truncates HTML dataframe outputs to show only headers and the first row
   - Replaces large plain text dataframe outputs with a placeholder
3. Preserves other cell outputs

### Error Handling

The implementation includes comprehensive error handling:

- If processing a notebook fails, the original notebook is copied instead
- If the preprocessing module is unavailable, the system falls back to the original context handling
- All errors are logged for debugging

## Troubleshooting

### Temporary Files Not Cleaned Up

In case of abnormal termination, temporary directories may not be automatically cleaned up. You can manually remove directories that:

- Are located in your system's temporary directory (e.g., `/tmp` on Linux, `C:\Users\<username>\AppData\Local\Temp` on Windows)
- Start with the prefix `library_assistant_context_`

### Performance Issues

If you notice any performance issues:

- Check the logs for errors or warnings
- Consider increasing the log level to debug for more detailed information
- Verify that the temporary directory has enough disk space

## How to Disable

To disable notebook preprocessing and revert to the original context handling:

1. Comment out the code in `utils/context_processing.py` that attempts to import and use the context integration module.
2. The Library Assistant will automatically fall back to the original implementation.

## Future Enhancements

Possible future enhancements to consider:

1. Make preprocessing configurable through the settings interface
2. Add more granular control over what gets processed and how
3. Implement caching to avoid reprocessing unchanged notebooks
4. Add support for processing other file types that might contain large binary data 