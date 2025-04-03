import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import os
import re

# Try to import tkinterdnd2 for drag and drop support
try:
    from tkinterdnd2 import DND_FILES, TkinterDnD
    HAS_DND = True
except ImportError:
    HAS_DND = False

def process_file(file_path, left_overbank, main_channel, right_overbank, progress_callback=None):
    """
    Process a HEC-RAS geometry file to convert non-standard Manning's n values to use normal subsection breaks.
    
    Args:
        file_path: Path to the input HEC-RAS geometry file
        left_overbank: Manning's n value for left overbank
        main_channel: Manning's n value for main channel
        right_overbank: Manning's n value for right overbank
        progress_callback: Function to call with progress updates
        
    Returns:
        Tuple of (list of edited cross sections, message)
    """
    try:
        with open(file_path, 'r') as f:
            lines = f.readlines()
        
        total_lines = len(lines)
        modified_lines = []
        edited_cross_sections = []
        current_cross_section = ""
        i = 0
        
        while i < len(lines):
            line = lines[i]
            modified_lines.append(line)
            
            # Update progress every 100 lines
            if progress_callback and i % 100 == 0:
                progress_callback(i, total_lines)
            
            # Check for new cross section
            if line.strip().startswith("Type RM Length L Ch R"):
                match = re.search(r'=\s*\d+\s*,([^,]+)', line)
                if match:
                    current_cross_section = match.group(1).strip()
                else:
                    current_cross_section = f"Unknown_{i}"
            
            # Check for Manning's line
            elif line.strip().startswith("#Mann="):
                mann_parts = line.strip().split(',')
                
                # Check for non-standard subsection format
                if len(mann_parts) >= 2 and mann_parts[1].strip() == '-1':
                    # Look ahead for bank stations
                    bank_line_idx = i
                    bank_line = None
                    
                    # Look for Bank Sta line within next 20 lines
                    for j in range(i+1, min(i+21, len(lines))):
                        if lines[j].strip().startswith("Bank Sta="):
                            bank_line = lines[j]
                            bank_line_idx = j
                            break
                    
                    if bank_line:
                        bank_match = re.search(r'Bank Sta=([^,]+),([^\n]+)', bank_line)
                        
                        if bank_match:
                            left_bank = bank_match.group(1).strip()
                            right_bank = bank_match.group(2).strip()
                            
                            # Replace the Manning's line
                            modified_lines[-1] = f"#Mann= 3 ,0,0\n"
                            
                            # Skip the next line which has the old Manning's values
                            i += 1
                            # Don't append the old values line
                            
                            # Add the new Manning's values line
                            modified_lines.append(f"       0    {left_overbank}       0 {left_bank}    {main_channel}       0 {right_bank}    {right_overbank}       0\n")
                            
                            edited_cross_sections.append(current_cross_section)
            i += 1
        
        # Final progress update
        if progress_callback:
            progress_callback(total_lines, total_lines)
        
        # Create a backup file with .bak extension (with incremental numbering if needed)
        base_name = file_path
        backup_num = 0
        backup_path = f"{base_name}.bak"
        
        # Check if backup already exists, increment number if needed
        while os.path.exists(backup_path):
            backup_num += 1
            backup_path = f"{base_name}.bak{backup_num}"
        
        # Create the backup
        with open(backup_path, 'w') as f:
            f.writelines(lines)
        
        # Write changes back to the original file
        with open(file_path, 'w') as f:
            f.writelines(modified_lines)
        
        return edited_cross_sections, f"Original file backed up as: {os.path.basename(backup_path)}"
    
    except Exception as e:
        import traceback
        return [], f"Error: {str(e)}\n{traceback.format_exc()}"

def create_gui():
    def update_progress(current, total):
        progress_var.set(int(current / total * 100))
        progress_label.config(text=f"Processing: {current}/{total} lines ({int(current / total * 100)}%)")
        root.update_idletasks()
    
    def on_submit():
        try:
            left_n = float(left_entry.get())
            main_n = float(main_entry.get())
            right_n = float(right_entry.get())
            
            if not file_path:
                messagebox.showerror("Error", "Please select a file first.")
                return
            
            # Validate input values
            if left_n <= 0 or main_n <= 0 or right_n <= 0:
                messagebox.showerror("Error", "Manning's n values must be positive numbers.")
                return
            
            # Show progress
            progress_frame.pack(fill=tk.X, pady=5)
            progress_var.set(0)
            progress_label.config(text="Processing: 0%")
            root.update_idletasks()
            
            # Process the file
            edited_sections, result_message = process_file(
                file_path, 
                f"{left_n:.3f}", 
                f"{main_n:.3f}", 
                f"{right_n:.3f}", 
                update_progress
            )
            
            # Hide progress
            progress_frame.pack_forget()
            
            # Show results
            result_text.delete(1.0, tk.END)
            if edited_sections:
                result_text.insert(tk.END, f"Original file has been modified.\n")
                result_text.insert(tk.END, f"{result_message}\n\n")
                result_text.insert(tk.END, f"Edited {len(edited_sections)} Cross Sections:\n")
                for section in edited_sections:
                    result_text.insert(tk.END, f"- {section}\n")
            else:
                if result_message.startswith("Error:"):
                    result_text.insert(tk.END, f"{result_message}\n")
                else:
                    result_text.insert(tk.END, "No cross sections were found that needed editing.\n")
                    result_text.insert(tk.END, "This could mean either:\n")
                    result_text.insert(tk.END, "1. All cross sections already use normal subsection breaks\n")
                    result_text.insert(tk.END, "2. The file format is different than expected\n")
        
        except ValueError:
            messagebox.showerror("Error", "Please enter valid numbers for Manning's n values.")
    
    def on_browse():
        nonlocal file_path
        file_path = filedialog.askopenfilename(
            title="Select HEC-RAS Geometry File",
            filetypes=[("All Files", "*.*"), ("Text Files", "*.txt")]
        )
        if file_path:
            file_label.config(text=os.path.basename(file_path))
    
    def on_drop(event):
        nonlocal file_path
        file_path = event.data
        if file_path:
            # Clean up the path (may contain curly braces or quotes depending on OS)
            file_path = file_path.strip('{}')
            file_path = file_path.strip('"')
            file_label.config(text=os.path.basename(file_path))
    
    # Initialize the main window
    if HAS_DND:
        root = TkinterDnD.Tk()
    else:
        root = tk.Tk()
    
    root.title("HEC-RAS Manning's n Editor")
    root.geometry("600x500")
    
    file_path = ""
    
    # Create the main frame with padding that works in all tkinter versions
    main_frame = ttk.Frame(root)
    main_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=20)
    
    # File selection section
    file_frame = ttk.LabelFrame(main_frame, text="Select HEC-RAS Geometry File")
    file_frame.pack(fill=tk.X, pady=10, padx=10)
    
    file_subframe = ttk.Frame(file_frame)
    file_subframe.pack(fill=tk.X, expand=True, padx=10, pady=10)
    
    browse_button = ttk.Button(file_subframe, text="Browse...", command=on_browse)
    browse_button.pack(side=tk.LEFT, padx=5)
    
    file_label = ttk.Label(file_subframe, text="No file selected")
    file_label.pack(side=tk.LEFT, padx=5, fill=tk.X, expand=True)
    
    # Drop area setup if DND is available
    if HAS_DND:
        file_frame.drop_target_register(DND_FILES)
        file_frame.dnd_bind('<<Drop>>', on_drop)
        drag_label = ttk.Label(file_subframe, text="Drag and drop file here")
        drag_label.pack(side=tk.RIGHT, padx=5)
    
    # Manning's n values section
    values_frame = ttk.LabelFrame(main_frame, text="Manning's n Values")
    values_frame.pack(fill=tk.X, pady=10, padx=10)
    
    values_subframe = ttk.Frame(values_frame)
    values_subframe.pack(fill=tk.X, expand=True, padx=10, pady=10)
    
    # Left overbank
    ttk.Label(values_subframe, text="Left Overbank:").grid(row=0, column=0, sticky=tk.W, padx=5, pady=5)
    left_entry = ttk.Entry(values_subframe, width=10)
    left_entry.grid(row=0, column=1, sticky=tk.W, padx=5, pady=5)
    left_entry.insert(0, "0.11")
    
    # Main channel
    ttk.Label(values_subframe, text="Main Channel:").grid(row=1, column=0, sticky=tk.W, padx=5, pady=5)
    main_entry = ttk.Entry(values_subframe, width=10)
    main_entry.grid(row=1, column=1, sticky=tk.W, padx=5, pady=5)
    main_entry.insert(0, "0.08")
    
    # Right overbank
    ttk.Label(values_subframe, text="Right Overbank:").grid(row=2, column=0, sticky=tk.W, padx=5, pady=5)
    right_entry = ttk.Entry(values_subframe, width=10)
    right_entry.grid(row=2, column=1, sticky=tk.W, padx=5, pady=5)
    right_entry.insert(0, "0.12")
    
    # Process button
    process_button = ttk.Button(main_frame, text="Process File", command=on_submit)
    process_button.pack(pady=10)
    
    # Progress frame
    progress_frame = ttk.Frame(main_frame)
    progress_var = tk.IntVar()
    progress_bar = ttk.Progressbar(progress_frame, variable=progress_var, maximum=100)
    progress_bar.pack(fill=tk.X, padx=10, pady=5)
    progress_label = ttk.Label(progress_frame, text="Processing: 0%")
    progress_label.pack(pady=5)
    # Don't pack the progress_frame initially - it will be shown during processing
    
    # Results section
    results_frame = ttk.LabelFrame(main_frame, text="Results")
    results_frame.pack(fill=tk.BOTH, expand=True, pady=10, padx=10)
    
    results_subframe = ttk.Frame(results_frame)
    results_subframe.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
    
    result_text = tk.Text(results_subframe, height=10, wrap=tk.WORD)
    result_text.pack(fill=tk.BOTH, expand=True, side=tk.LEFT)
    
    result_scrollbar = ttk.Scrollbar(results_subframe, orient=tk.VERTICAL, command=result_text.yview)
    result_text.configure(yscrollcommand=result_scrollbar.set)
    result_scrollbar.pack(fill=tk.Y, side=tk.RIGHT)
    
    # Add some initial help text
    result_text.insert(tk.END, "Instructions:\n")
    result_text.insert(tk.END, "1. Select a HEC-RAS geometry file\n")
    result_text.insert(tk.END, "2. Set Manning's n values for each section\n")
    result_text.insert(tk.END, "3. Click 'Process File' to convert non-standard Manning's to normal subsection breaks\n\n")
    result_text.insert(tk.END, "The script will find cross sections where Manning's doesn't use normal subsection breaks\n")
    result_text.insert(tk.END, "(lines with #Mann= X ,-1,0) and convert them to use the standard format (#Mann= 3 ,0,0)\n")
    result_text.insert(tk.END, "with the specified n values for left overbank, main channel, and right overbank.\n\n")
    result_text.insert(tk.END, "Note: The original file will be backed up with .bak extension before modifications.")
    
    root.mainloop()

if __name__ == "__main__":
    create_gui()