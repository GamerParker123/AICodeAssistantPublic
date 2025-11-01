import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox, font as tkfont, filedialog
import sys
import threading
import traceback
from query import choose_files_by_summary, build_prompt, prepare_prompt_with_chunks, choose_chunks_by_instruction
import os
from config import OPENAI_API_KEY, CHROMA_DB_PATH, PROJECT_PATH
from openai import OpenAI
from logic import clean_code_output, normalize_path
from edit import preview_diff, apply_change, apply_chunks_cross_file, parse_updated_chunks
from embedding_utils import load_all_file_metadata, build_index
import chromadb
import shutil

client = OpenAI(api_key=OPENAI_API_KEY)

class AIEditorGUI:
    def __init__(self, master):
        self.master = master
        master.title("AI Editor")
        master.geometry("1100x750")
        master.minsize(900, 600)

        accent = "#00c0d8"        # teal/cyan accent
        panel_bg = "#e6fbff"      # very light cyan panels
        main_bg = "#f7feff"       # overall background
        header_fg = "#006b7a"     # darker teal for headers
        btn_fg = "#ffffff"
        btn_bg = "#00a6c1"

        master.configure(bg=main_bg)

        style = ttk.Style()
        style.configure("Card.TFrame", background=panel_bg)
        scrollable = ScrollableFrame(master, panel_style='Card.TFrame')
        scrollable.pack(fill=tk.BOTH, expand=True)

        # Improve overall styling
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except Exception:
            pass

        # Card style for frames
        style.configure("Card.TFrame", background=panel_bg)
        style.configure("TLabel", font=("Segoe UI", 10), background=panel_bg, foreground="#00343a")
        style.configure("Header.TLabel", font=("Segoe UI", 11, "bold"), background=panel_bg, foreground=header_fg)
        style.configure("Small.TLabel", font=("Segoe UI", 9), background=panel_bg, foreground="#00343a")
        style.configure("Banner.TLabel", font=("Segoe UI", 14, "bold"), background=panel_bg, foreground=accent)
        style.configure("Status.TLabel", background=panel_bg, foreground="#00343a")
        style.configure("TButton", font=("Segoe UI", 10), padding=6)

        default_font = tkfont.nametofont("TkDefaultFont")
        default_font.configure(size=10)
        monospace = ("Consolas", 11) if sys.platform == "win32" else ("Courier New", 11)

        top_frame = ttk.Frame(scrollable.scrollable_frame, padding=(10, 8), style="Card.TFrame")
        top_frame.pack(fill=tk.X, padx=8, pady=(8, 4))

        banner = ttk.Label(top_frame, text="AI Editor", style="Banner.TLabel")
        banner.pack(side=tk.LEFT, padx=(0, 12))

        # Use a paned window for resizable left/right panes
        mid_paned = ttk.Panedwindow(scrollable.scrollable_frame, orient=tk.HORIZONTAL)
        mid_paned.pack(fill=tk.BOTH, expand=True, padx=8, pady=6)

        bottom_frame = ttk.Frame(scrollable.scrollable_frame, padding=(10, 6), style="Card.TFrame")
        bottom_frame.pack(fill=tk.X, padx=8, pady=(4, 8))

        # Instruction entry
        ttk.Label(top_frame, text="Instruction:", style="Header.TLabel").pack(side=tk.LEFT)
        self.instruction_var = tk.StringVar()
        self.instruction_entry = ttk.Entry(top_frame, textvariable=self.instruction_var)
        self.instruction_entry.pack(side=tk.LEFT, padx=(10, 8), fill=tk.X, expand=True)
        self.generate_btn = ttk.Button(top_frame, text="Generate", command=self.on_generate)
        self.generate_btn.pack(side=tk.LEFT)

        # Bugfix mode toggle: when enabled, the GUI will include the last traceback (if any)
        # and include surrounding file chunks in the prompt to help the model fix runtime errors.
        self.bugfix_var = tk.BooleanVar(value=False)
        self.bugfix_check = ttk.Checkbutton(top_frame, text="Bugfix mode", variable=self.bugfix_var)
        self.bugfix_check.pack(side=tk.LEFT, padx=(8, 0))

        # Manage summaries button
        self.manage_btn = ttk.Button(top_frame, text="Manage Summaries", command=self.open_summary_manager)
        self.manage_btn.pack(side=tk.LEFT, padx=(8, 0))

        # Codebase chooser
        default_project = os.getenv("PROJECT_PATH", os.getcwd())
        self.codebase_var = tk.StringVar(value=default_project)
        self.codebase_label = ttk.Label(top_frame, text=f"Codebase: {self.codebase_var.get()}", style="Small.TLabel")
        self.codebase_label.pack(side=tk.LEFT, padx=(8,0))

        self.choose_codebase_btn = ttk.Button(top_frame, text="Change Codebase", command=self.change_codebase)
        self.choose_codebase_btn.pack(side=tk.LEFT, padx=(8,0))


        # Files list and file contents
        left_pane = ttk.Frame(mid_paned, padding=(6,6), relief=tk.GROOVE, style="Card.TFrame")
        right_pane = ttk.Frame(mid_paned, padding=(6,6), relief=tk.GROOVE, style="Card.TFrame")
        mid_paned.add(left_pane, weight=1)
        mid_paned.add(right_pane, weight=3)

        # Left pane content
        ttk.Label(left_pane, text="Relevant files:", style="Header.TLabel").pack(anchor=tk.W)
        listbox_frame = ttk.Frame(left_pane, style="Card.TFrame")
        listbox_frame.pack(fill=tk.BOTH, expand=False, pady=(6, 6))
        self.files_listbox = tk.Listbox(listbox_frame, height=8, activestyle='dotbox', selectbackground=accent)
        self.files_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        list_scroll = ttk.Scrollbar(listbox_frame, orient=tk.VERTICAL, command=self.files_listbox.yview)
        list_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.files_listbox.config(yscrollcommand=list_scroll.set)
        self.files_listbox.bind("<<ListboxSelect>>", self.on_file_select)
        self.files_listbox.bind("<Double-Button-1>", lambda e: self.on_file_select(e))

        # Add Summary and Symbols display under the files list
        ttk.Label(left_pane, text="Summary:", style="Header.TLabel").pack(anchor=tk.W, pady=(6, 0))
        self.summary_text = scrolledtext.ScrolledText(left_pane, height=5, wrap=tk.WORD, font=default_font)
        self.summary_text.pack(fill=tk.BOTH, expand=False)
        self.summary_text.config(state=tk.DISABLED, background=panel_bg)

        ttk.Label(left_pane, text="Symbols:", style="Header.TLabel").pack(anchor=tk.W, pady=(6, 0))
        self.symbols_var = tk.StringVar(value="")
        self.symbols_label = ttk.Label(left_pane, textvariable=self.symbols_var, wraplength=360, style="Small.TLabel")
        self.symbols_label.pack(fill=tk.BOTH, expand=False)

        ttk.Label(left_pane, text="Original code:", style="Header.TLabel").pack(anchor=tk.W, pady=(6,0))
        self.original_text = scrolledtext.ScrolledText(left_pane, height=18, font=monospace)
        self.original_text.pack(fill=tk.BOTH, expand=True)
        self.original_text.config(background="#ffffff")

        # Right pane content
        ttk.Label(right_pane, text="Generated new code:", style="Header.TLabel").pack(anchor=tk.W)
        self.new_text = scrolledtext.ScrolledText(right_pane, height=12, font=monospace, background="#f7ffff")
        self.new_text.pack(fill=tk.BOTH, expand=True, pady=(4,6))

        ttk.Label(right_pane, text="Prompt sent:", style="Header.TLabel").pack(anchor=tk.W, pady=(6,0))
        self.prompt_text = scrolledtext.ScrolledText(right_pane, height=7, wrap=tk.WORD, font=default_font)
        self.prompt_text.pack(fill=tk.BOTH, expand=False)
        self.prompt_text.config(state=tk.DISABLED, background=panel_bg)

        ttk.Label(right_pane, text="Preview diff:", style="Header.TLabel").pack(anchor=tk.W, pady=(6,0))
        self.diff_text = scrolledtext.ScrolledText(right_pane, height=10, font=monospace)
        self.diff_text.pack(fill=tk.BOTH, expand=True, pady=(4,0))
        self.diff_text.config(background="#ffffff")

        # Bottom buttons
        self.apply_btn = ttk.Button(bottom_frame, text="Apply Change", command=self.on_apply, state=tk.DISABLED)
        self.apply_btn.pack(side=tk.RIGHT, padx=(6,0))
        self.status_var = tk.StringVar(value="Ready")
        status_label = ttk.Label(bottom_frame, textvariable=self.status_var, relief=tk.SUNKEN, anchor=tk.W, style="Status.TLabel")
        status_label.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.tokens_var = tk.StringVar(value="Tokens: -")
        tokens_label = ttk.Label(bottom_frame, textvariable=self.tokens_var, style="Status.TLabel")
        tokens_label.pack(side=tk.RIGHT, padx=(10,0))

        # Internal state
        self.metas = []
        self.docs = []
        self.current_file_path = None
        self.current_new_code = None
        self.last_traceback = None

    def set_status(self, text):
        self.status_var.set(text)
        self.master.update_idletasks()

    def update_meta_display(self, meta):
        """
        Update the summary and symbols display for the provided meta.
        Should be called from the main/UI thread.
        """
        try:
            summary = meta.get("summary", "") if meta else ""
            symbols = meta.get("symbols", []) if meta else []
            # Update summary text (readonly)
            self.summary_text.config(state=tk.NORMAL)
            self.summary_text.delete("1.0", tk.END)
            self.summary_text.insert(tk.END, summary)
            self.summary_text.config(state=tk.DISABLED)
            # Update symbols label
            self.symbols_var.set(", ".join(symbols) if symbols else "")
        except Exception as e:
            # If UI update fails, show an error but continue
            messagebox.showerror("UI error", f"Could not update summary/symbols display: {e}")

    def clear_meta_display(self):
        self.summary_text.config(state=tk.NORMAL)
        self.summary_text.delete("1.0", tk.END)
        self.summary_text.config(state=tk.DISABLED)
        self.symbols_var.set("")

    def change_codebase(self):
        chroma_client = chromadb.PersistentClient(path=CHROMA_DB_PATH)
        try:
            chroma_client.delete_collection("codebase")
        except chromadb.errors.NotFoundError:
            pass
        new_dir = filedialog.askdirectory(initialdir=os.getcwd(), title="Select a codebase")
        if not new_dir:
            return
        self.codebase_var.set(new_dir)
        self.codebase_label.config(text=f"Codebase: {new_dir}")

        # update working directory so other parts (like load_all_file_metadata) pick it up
        os.chdir(new_dir)

        # reload file metadata
        try:
            build_index(new_dir)
            self.metas = load_all_file_metadata(root_dir=new_dir)
            self.docs = []
            self.files_listbox.delete(0, tk.END)
            for meta in self.metas:
                display_text = meta['path']
                if meta.get('summary'):
                    display_text += " — " + meta['summary'][:60]
                self.files_listbox.insert(tk.END, display_text)
            self.clear_meta_display()
            self.original_text.delete("1.0", tk.END)
            self.new_text.delete("1.0", tk.END)
            self.diff_text.delete("1.0", tk.END)
        
        except Exception as e:
            messagebox.showerror("Error", f"Failed to load new codebase: {e}")

    def update_prompt_display(self, prompt):
        try:
            s = ""
            if isinstance(prompt, (list, tuple)):
                parts = []
                for m in prompt:
                    if isinstance(m, dict):
                        role = m.get("role", "")
                        content = m.get("content", "")
                    else:
                        # Fallback for objects with attributes
                        role = getattr(m, "role", "")
                        content = getattr(m, "content", "")
                    parts.append(f"{role}:\n{content}")
                s = "\n\n".join(parts)
            else:
                s = str(prompt)
            self.prompt_text.config(state=tk.NORMAL)
            self.prompt_text.delete("1.0", tk.END)
            self.prompt_text.insert(tk.END, s)
            self.prompt_text.config(state=tk.DISABLED)
        except Exception as e:
            messagebox.showerror("UI error", f"Could not update prompt display: {e}")

    def clear_prompt_display(self):
        try:
            self.prompt_text.config(state=tk.NORMAL)
            self.prompt_text.delete("1.0", tk.END)
            self.prompt_text.config(state=tk.DISABLED)
            self.tokens_var.set("Tokens: -")
        except Exception:
            # don't block other operations for UI clear failures
            pass

    def on_generate(self):
        instruction = self.instruction_var.get().strip()
        if not instruction:
            messagebox.showwarning("Input required", "Please enter an instruction.")
            return

        # Run search and model call in background thread
        thread = threading.Thread(target=self.generate_for_instruction, args=(instruction,), daemon=True)
        thread.start()

    def generate_for_instruction(self, instruction):
        try:
            self.set_status("Searching context...")
            all_metas = load_all_file_metadata(root_dir=self.codebase_var.get())
            self.metas = all_metas

            # Choose relevant files
            ranked_metas = choose_files_by_summary(instruction, all_metas)
            if not ranked_metas:
                messagebox.showinfo("No results", "No relevant files found.")
                self.clear_file_views()
                self.set_status("Ready")
                return

            self.metas = ranked_metas
            self.files_listbox.delete(0, tk.END)
            for meta in ranked_metas:
                display_text = meta['path']
                if meta.get('summary'):
                    display_text += " — " + meta['summary'][:60]
                self.files_listbox.insert(tk.END, display_text)

            # Select first file
            first_meta = ranked_metas[0]
            selected_file_path = normalize_path(first_meta.get("path"))
            self.files_listbox.selection_clear(0, tk.END)
            self.files_listbox.selection_set(0)
            self.files_listbox.event_generate("<<ListboxSelect>>")
            self.master.after(0, lambda m=first_meta: self.update_meta_display(m))

            if not os.path.exists(selected_file_path):
                messagebox.showerror("File error", f"Invalid path: {selected_file_path}")
                self.set_status("Ready")
                return

            with open(selected_file_path, "r", encoding="utf-8") as f:
                orig_code = f.read()

            # Build filtered chunks
            chroma_client = chromadb.PersistentClient(path=CHROMA_DB_PATH)
            try:
                collection = chroma_client.get_collection(name="codebase")
            except chromadb.errors.NotFoundError:
                collection = chroma_client.create_collection(name="codebase")

            instruction_embedding = client.embeddings.create(
                model="text-embedding-3-small",
                input=instruction
            ).data[0].embedding

            results = collection.query(
                query_embeddings=[instruction_embedding],
                n_results=20,
                include=['metadatas', 'documents']
            )

            metadatas = results['metadatas'][0]
            documents = results['documents'][0]

            filtered_chunks = []
            MAX_IN_FILE = 5
            MAX_REFERENCE = 10
            in_file_count = 0
            reference_count = 0

            for meta, doc in zip(metadatas, documents):
                chunk_path = normalize_path(meta.get('path', ''))
                if chunk_path == selected_file_path and in_file_count < MAX_IN_FILE:
                    filtered_chunks.append({"code": doc, "metadata": meta})
                    in_file_count += 1
                elif chunk_path != selected_file_path and reference_count < MAX_REFERENCE:
                    filtered_chunks.append({"code": doc, "metadata": meta})
                    reference_count += 1

            # Build prompt
            prompt = build_prompt(instruction, filtered_chunks, selected_file_path)
            self.master.after(0, lambda p=prompt: self.update_prompt_display(p))

            self.set_status("Waiting for model response...")
            resp = client.chat.completions.create(
                model="gpt-5-mini",
                messages=prompt
            )
            ai_output = clean_code_output(resp.choices[0].message.content)
            updated_chunks = parse_updated_chunks(ai_output)

            # Normalize paths in chunks
            for chunk in updated_chunks:
                chunk["file_path"] = normalize_path(chunk["file_path"])

            # Merge chunks per file
            merged_per_file = apply_chunks_cross_file(updated_chunks)

            # Ensure current file is included even if no AI changes
            if selected_file_path not in merged_per_file:
                merged_per_file[selected_file_path] = orig_code

            # Save merged code for apply
            self.current_new_code = merged_per_file
            self.current_file_path = selected_file_path

            merged_code_for_ui = merged_per_file[selected_file_path]
            self.master.after(
                0,
                lambda: self.update_generated(selected_file_path, orig_code, merged_code_for_ui)
            )

            self.set_status("Ready")

        except Exception as e:
            traceback.print_exc()
            messagebox.showerror("Error", f"An error occurred: {e}")
            self.set_status("Ready")
        finally:
            self.generate_btn.config(state=tk.NORMAL)

    def clear_file_views(self):
        self.files_listbox.delete(0, tk.END)
        self.original_text.delete("1.0", tk.END)
        self.new_text.delete("1.0", tk.END)
        self.diff_text.delete("1.0", tk.END)
        self.apply_btn.config(state=tk.DISABLED)
        self.clear_prompt_display()

    def update_generated(self, file_path, orig_code, merged_code):
        try:
            # Highlight selected file
            try:
                idx = list(self.files_listbox.get(0, tk.END)).index(file_path)
                self.files_listbox.selection_clear(0, tk.END)
                self.files_listbox.selection_set(idx)
            except ValueError:
                pass

            # Update meta display
            meta_for_file = next((m for m in self.metas if m.get("path") == file_path), None)
            if meta_for_file:
                self.update_meta_display(meta_for_file)

            self.current_file_path = file_path

            # Original code
            self.original_text.delete("1.0", tk.END)
            self.original_text.insert(tk.END, orig_code)

            # Merged/AI code
            self.new_text.delete("1.0", tk.END)
            self.new_text.insert(tk.END, merged_code)

            # Save merged code to current_new_code for apply
            # Wrap in a dict so on_apply can iterate over it
            self.current_new_code = {file_path: merged_code}

            # Diff
            diff = preview_diff(orig_code, merged_code)
            self.diff_text.delete("1.0", tk.END)
            self.diff_text.insert(tk.END, diff)

            self.apply_btn.config(state=tk.NORMAL)
        except Exception as e:
            messagebox.showerror("UI update error", f"Could not update UI: {e}")

    def on_file_select(self, event):
            sel = self.files_listbox.curselection()
            if not sel:
                return
            idx = sel[0]
            meta = self.metas[idx]
            path = meta.get("path")
            if not path or not os.path.exists(path):
                messagebox.showerror("File error", f"Invalid path: {path}")
                return
            try:
                with open(path, "r", encoding="utf-8") as f:
                    code = f.read()
                self.current_file_path = path
                self.original_text.delete("1.0", tk.END)
                self.original_text.insert(tk.END, code)
                # Update summary/symbols for the selected file
                self.update_meta_display(meta)
                # Clear new/diff and prompt when switching files until regenerated
                self.new_text.delete("1.0", tk.END)
                self.diff_text.delete("1.0", tk.END)
                self.apply_btn.config(state=tk.DISABLED)
                self.current_new_code = None
                self.clear_prompt_display()
            except Exception as e:
                messagebox.showerror("Read error", f"Could not read file: {e}")

    def on_apply(self):
        if not self.current_file_path or self.current_new_code is None:
            messagebox.showwarning("Nothing to apply", "No generated change to apply.")
            return

        confirm = messagebox.askyesno(
            "Apply change",
            f"Apply changes to {self.current_file_path}? A backup will be saved with a .bak extension."
        )
        if not confirm:
            return

        try:
            for path, code in self.current_new_code.items():
                shutil.copy2(path, path + ".bak")
                with open(path, "w", encoding="utf-8") as f:
                    f.write(code)

            messagebox.showinfo(
                "Success",
                f"Changes applied to {self.current_file_path}. Backup saved as {self.current_file_path}.bak"
            )

            # Refresh views
            # After applying, refresh the currently selected file
            self.original_text.delete("1.0", tk.END)
            curr_path = self.current_file_path
            if curr_path in self.current_new_code:
                self.original_text.insert("1.0", self.current_new_code[curr_path])
            else:
                # fallback
                with open(curr_path, "r", encoding="utf-8") as f:
                    self.original_text.insert("1.0", f.read())

            self.diff_text.delete("1.0", tk.END)
            self.new_text.delete("1.0", tk.END)
            self.apply_btn.config(state=tk.DISABLED)

        except Exception as e:
            tb = traceback.format_exc()
            try:
                self.last_traceback = tb
            except Exception:
                pass
            messagebox.showerror("Apply error", f"Failed to apply change:\n{e}\n\nTraceback:\n{tb}")

    def open_summary_manager(self):
        try:
            mgr = tk.Toplevel(self.master)
            mgr.title("Manage Summaries")
            mgr.geometry("900x600")

            # Apply a subtle background tint
            try:
                mgr.configure(bg="#f7feff")
            except Exception:
                pass

            # Left: files list
            left = ttk.Frame(mgr, padding=6, style="Card.TFrame")
            left.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
            ttk.Label(left, text="Files in codebase:", style="Header.TLabel").pack(anchor=tk.W)
            list_frame = ttk.Frame(left, style="Card.TFrame")
            list_frame.pack(fill=tk.BOTH, expand=True, pady=(6,6))
            file_listbox = tk.Listbox(list_frame, activestyle='dotbox', selectbackground="#00c0d8")
            file_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
            fsb = ttk.Scrollbar(list_frame, orient=tk.VERTICAL, command=file_listbox.yview)
            fsb.pack(side=tk.RIGHT, fill=tk.Y)
            file_listbox.config(yscrollcommand=fsb.set)

            # Right: file content and summary editor
            right = ttk.Frame(mgr, padding=6, style="Card.TFrame")
            right.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True)
            ttk.Label(right, text="File content:", style="Header.TLabel").pack(anchor=tk.W)
            file_content = scrolledtext.ScrolledText(right, height=15, font=("Courier New", 10))
            file_content.pack(fill=tk.BOTH, expand=True, pady=(6,6))
            file_content.config(state=tk.DISABLED, background="#ffffff")
            ttk.Label(right, text="Summary (editable):", style="Header.TLabel").pack(anchor=tk.W, pady=(6,0))
            summary_editor = scrolledtext.ScrolledText(right, height=8, wrap=tk.WORD)
            summary_editor.pack(fill=tk.BOTH, expand=False)

            btn_frame = ttk.Frame(right, style="Card.TFrame")
            btn_frame.pack(fill=tk.X, pady=(6,0))
            save_btn = ttk.Button(btn_frame, text="Save Summary")
            save_btn.pack(side=tk.RIGHT, padx=(6,0))
            close_btn = ttk.Button(btn_frame, text="Close", command=mgr.destroy)
            close_btn.pack(side=tk.RIGHT)

            # Build file list
            root_dir = os.getcwd()
            exclude_dirs = {".git", "__pycache__", ".venv", "venv", "env", "node_modules", ".pytest_cache"}
            files = []
            for dirpath, dirnames, filenames in os.walk(root_dir):
                # filter out excluded directories in-place to avoid descending
                dirnames[:] = [d for d in dirnames if d not in exclude_dirs and not d.startswith(".")]
                for fn in filenames:
                    # skip hidden files at top level
                    if fn.startswith("."):
                        continue
                    full = os.path.join(dirpath, fn)
                    files.append(os.path.normpath(full))
            # sort and display relative paths
            files.sort()
            rel_paths = [os.path.relpath(p, root_dir) for p in files]
            for rp in rel_paths:
                file_listbox.insert(tk.END, rp)

            # Helper to get absolute path from selection
            def get_selected_path():
                sel = file_listbox.curselection()
                if not sel:
                    return None
                idx = sel[0]
                rel = file_listbox.get(idx)
                return os.path.normpath(os.path.join(root_dir, rel))

            # When selecting a file, show its content and summary if available
            def on_mgr_select(event):
                path = get_selected_path()
                if not path:
                    return
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        content = f.read()
                except Exception as e:
                    content = f"Could not read file: {e}"
                file_content.config(state=tk.NORMAL)
                file_content.delete("1.0", tk.END)
                file_content.insert(tk.END, content)
                file_content.config(state=tk.DISABLED)
                # Load existing summary from metas if present
                summary_text = ""
                abs_norm = os.path.normpath(path)
                for m in self.metas:
                    if os.path.normpath(m.get("path", "")) == abs_norm:
                        summary_text = m.get("summary", "")
                        break
                summary_editor.delete("1.0", tk.END)
                summary_editor.insert(tk.END, summary_text)

            file_listbox.bind("<<ListboxSelect>>", on_mgr_select)

            # Save summary handler
            def on_save_summary():
                path = get_selected_path()
                if not path:
                    messagebox.showwarning("Select file", "Please select a file first.")
                    return
                new_summary = summary_editor.get("1.0", tk.END).rstrip()
                abs_norm = os.path.normpath(path)
                updated = False
                for m in self.metas:
                    if os.path.normpath(m.get("path", "")) == abs_norm:
                        m["summary"] = new_summary
                        updated = True
                        break
                if not updated:
                    # Append a new meta entry so the rest of the UI can use it
                    self.metas.append({"path": abs_norm, "summary": new_summary, "symbols": []})
                    # If main files listbox currently doesn't include it, don't modify it here
                messagebox.showinfo("Saved", f"Summary updated for {path}")
                # If the main UI currently has this file selected, update its summary display
                try:
                    if os.path.normpath(self.current_file_path or "") == abs_norm:
                        # Update the main summary display to reflect new summary
                        current_meta = None
                        # try to find meta_for_file and update display
                        for m in self.metas:
                            if os.path.normpath(m.get("path", "")) == abs_norm:
                                current_meta = m
                                break
                        if current_meta:
                            self.update_meta_display(current_meta)
                except Exception:
                    pass

            save_btn.config(command=on_save_summary)

            # Pre-select first file if any
            if files:
                file_listbox.selection_set(0)
                file_listbox.event_generate("<<ListboxSelect>>")

        except Exception as e:
            messagebox.showerror("Error", f"Could not open summary manager: {e}")

class ScrollableFrame(ttk.Frame):
    def __init__(self, container, *args, panel_style="Card.TFrame", panel_bg="#e6fbff", **kwargs):
        style = ttk.Style()
        style.configure(panel_style, background=panel_bg)
        super().__init__(container, *args, style=panel_style, **kwargs)
        
        canvas = tk.Canvas(self, highlightthickness=0, bg=panel_bg)
        scrollbar = ttk.Scrollbar(self, orient="vertical", command=canvas.yview)
        # Use the provided panel style for the inner frame so the overall app has a consistent tint
        self.scrollable_frame = ttk.Frame(canvas, style=panel_style)

        self.scrollable_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )

        self._window = canvas.create_window((0, 0), window=self.scrollable_frame, anchor="nw")
        canvas.bind("<Configure>", lambda e: canvas.itemconfig(self._window, width=e.width))
        canvas.configure(yscrollcommand=scrollbar.set)

        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
