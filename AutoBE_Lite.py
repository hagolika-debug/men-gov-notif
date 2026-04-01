import os
import zipfile
import json
import uuid
import re
import logging
import tempfile
import shutil
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from collections import defaultdict
import threading
import random

# --- Logging Configuration ---
logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s - %(levelname)s - %(message)s')

def log_info(msg):
    logging.info(msg)
    print(msg)

def log_error(msg, e=None):
    if e:
        logging.error(f"{msg}: {e}", exc_info=True)
    else:
        logging.error(msg)
    print(f"ERROR: {msg}")

# --- JSON & Merging Utilities ---

def load_json_robust(content_str):
    """Parses JSON string by removing comments and trailing commas."""
    # Remove block comments /* ... */
    content = re.sub(r'/\*.*?\*/', '', content_str, flags=re.DOTALL)

    # Remove line comments // ... (robustly handles strings)
    lines = content.splitlines()
    cleaned_lines = []
    for line in lines:
        in_string = False
        escape_next = False
        new_line = []
        i = 0
        while i < len(line):
            char = line[i]
            if escape_next:
                new_line.append(char)
                escape_next = False
            elif char == '\\' and in_string:
                new_line.append(char)
                escape_next = True
            elif char == '"' and not escape_next:
                in_string = not in_string
                new_line.append(char)
            elif char == '/' and i + 1 < len(line) and line[i+1] == '/' and not in_string:
                break
            else:
                new_line.append(char)
            i += 1
        cleaned_lines.append(''.join(new_line))
    content = '\n'.join(cleaned_lines)

    # Remove trailing commas before closing braces/brackets
    content = re.sub(r',\s*([}\]])', r'\1', content)

    try:
        return json.loads(content)
    except json.JSONDecodeError:
        # Last resort: try to find the first { and match it
        try:
            start_idx = content.find('{')
            if start_idx >= 0:
                brace_count = 0
                in_string = False
                escape_next = False
                for i in range(start_idx, len(content)):
                    char = content[i]
                    if escape_next: escape_next = False
                    elif char == '\\' and in_string: escape_next = True
                    elif char == '"' and not escape_next: in_string = not in_string
                    elif not in_string:
                        if char == '{': brace_count += 1
                        elif char == '}':
                            brace_count -= 1
                            if brace_count == 0:
                                return json.loads(content[start_idx:i+1])
        except: pass
        return None

def normalize_string(s):
    """Normalize Minecraft-specific strings for comparison."""
    if not isinstance(s, str): return s
    s = s.replace("1st_person", "first_person").replace("3rd_person", "third_person")
    s = s.replace("v.is_first_person", "variable.is_first_person").replace("q.is_spectator", "query.is_spectator")
    return s

def recursive_merge(target, source):
    """Recursively merges source dict into target dict with intelligent list merging."""
    for key, value in source.items():
        if key in target:
            if isinstance(target[key], dict) and isinstance(value, dict):
                recursive_merge(target[key], value)
            elif isinstance(target[key], list) and isinstance(value, list):
                # Combine lists and remove duplicates
                combined = target[key] + value
                seen = set()
                unique_list = []
                for item in combined:
                    norm_item = item
                    if isinstance(item, str):
                        norm_item = normalize_string(item)

                    # Create a stable representation for comparison
                    if isinstance(item, (dict, list)):
                        item_repr = json.dumps(item, sort_keys=True)
                    else:
                        item_repr = norm_item

                    if item_repr not in seen:
                        unique_list.append(item)
                        seen.add(item_repr)
                target[key] = unique_list
            else:
                # Primitive value override (except format_version)
                if key != "format_version":
                    target[key] = value
        else:
            target[key] = value
    return target

# --- Identifier Management ---

class IdentifierManager:
    def __init__(self):
        self.conflict_map = defaultdict(list)
        self.pack_namespaces = {}
        self.identifier_mapping = {}

    def scan_pack(self, pack_path):
        """Scans a pack for identifiers."""
        ids = set()
        try:
            with zipfile.ZipFile(pack_path, 'r') as z:
                for name in z.namelist():
                    if name.endswith('.json') and any(name.startswith(d) for d in ['entities/', 'items/', 'blocks/', 'recipes/', 'animation_controllers/', 'render_controllers/']):
                        with z.open(name) as f:
                            data = load_json_robust(f.read().decode('utf-8', errors='ignore'))
                            if not data: continue
                            found_id = self._extract_id_from_json(data, name)
                            if found_id: ids.add(found_id)
        except Exception as e:
            log_error(f"Error scanning {pack_path}", e)
        return ids

    def _extract_id_from_json(self, data, filename):
        # Entities
        for k in ['minecraft:entity', 'minecraft:client_entity']:
            if k in data: return data[k].get('description', {}).get('identifier')
        # Items
        if 'minecraft:item' in data: return data['minecraft:item'].get('description', {}).get('identifier')
        # Blocks
        if 'minecraft:block' in data: return data['minecraft:block'].get('description', {}).get('identifier')
        # Recipes
        if any(k in data for k in ['minecraft:recipe_shaped', 'minecraft:recipe_shapeless', 'minecraft:recipe_furnace']):
            for k, v in data.items():
                if 'recipe' in k and isinstance(v, dict):
                    return v.get('description', {}).get('identifier')
        # Controllers (keyed by identifier)
        if 'animation_controllers' in filename or 'render_controllers' in filename:
            for k in data.keys():
                if ':' in k: return k
        return None

    def detect_conflicts(self, all_pack_ids):
        for pack_path, ids in all_pack_ids.items():
            for ident in ids:
                self.conflict_map[ident].append(pack_path)

            pack_name = os.path.basename(pack_path).split('.')[0]
            clean_name = re.sub(r'[^a-zA-Z0-9_]', '_', pack_name)[:20]
            self.pack_namespaces[pack_path] = f"{clean_name}_merge"

    def generate_mappings(self):
        conflicts = {id: packs for id, packs in self.conflict_map.items() if len(packs) > 1}
        for ident, packs in conflicts.items():
            if ident == 'minecraft:player': continue
            for p_path in packs:
                ns = self.pack_namespaces.get(p_path, 'pack_merge')
                if ':' in ident:
                    old_ns, name = ident.split(':', 1)
                    new_id = f"{ns}:{name}" if old_ns not in ['minecraft', 'minecraft_vanilla'] else f"{old_ns}:{ns}_{name}"
                else:
                    new_id = f"{ns}:{ident}"
                self.identifier_mapping[(p_path, ident)] = new_id

    def update_json(self, data, pack_path):
        if isinstance(data, dict):
            return {k: self.update_json(v, pack_path) if k not in ['identifier', 'entity', 'item', 'block'] else self.identifier_mapping.get((pack_path, v), v) for k, v in data.items()}
        elif isinstance(data, list):
            return [self.update_json(i, pack_path) for i in data]
        elif isinstance(data, str) and ':' in data and not data.startswith('http'):
            return self.identifier_mapping.get((pack_path, data), data)
        return data

    def update_text(self, text, pack_path):
        def repl(match):
            return self.identifier_mapping.get((pack_path, match.group(1)), match.group(1))
        return re.sub(r'\b([a-zA-Z0-9_]+:[a-zA-Z0-9_\./]+)\b', repl, text)

# --- Main Application Logic ---

class AutoBELite:
    def __init__(self, root):
        self.root = root
        self.root.title("AutoBE Lite - Open Source")
        self.root.geometry("600x500")
        self._setup_ui()
        self.files = []
        self.temp_files = []
        self.output_dir = ""

    def _setup_ui(self):
        style = ttk.Style()
        style.theme_use('clam')

        main_frame = ttk.Frame(self.root, padding="20")
        main_frame.pack(fill=tk.BOTH, expand=True)

        ttk.Label(main_frame, text="Select .mcpack files to merge:", font=('Segoe UI', 12, 'bold')).pack(anchor=tk.W)

        self.file_listbox = tk.Listbox(main_frame, height=10, selectmode=tk.MULTIPLE)
        self.file_listbox.pack(fill=tk.X, pady=10)

        btn_frame = ttk.Frame(main_frame)
        btn_frame.pack(fill=tk.X)
        ttk.Button(btn_frame, text="Add Files", command=self.add_files).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="Remove Selected", command=self.remove_files).pack(side=tk.LEFT)

        ttk.Label(main_frame, text="Output Directory:", font=('Segoe UI', 10, 'bold')).pack(anchor=tk.W, pady=(20, 0))
        out_frame = ttk.Frame(main_frame)
        out_frame.pack(fill=tk.X, pady=5)
        self.out_entry = ttk.Entry(out_frame)
        self.out_entry.pack(side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Button(out_frame, text="Browse", command=self.select_out).pack(side=tk.RIGHT, padx=5)

        self.progress = ttk.Progressbar(main_frame, mode='determinate')
        self.progress.pack(fill=tk.X, pady=20)

        ttk.Button(main_frame, text="🚀 START MERGE", command=self.start_process).pack(fill=tk.X)

    def add_files(self):
        fs = filedialog.askopenfilenames(filetypes=[("Minecraft Packs", "*.mcpack *.mcaddon *.zip")])
        for f in fs:
            # Handle multi-pack archives (.mcaddon) or nested zips
            packs = self._find_packs(f)
            for p in packs:
                if p not in self.files:
                    self.files.append(p)
                    self.file_listbox.insert(tk.END, os.path.basename(p))

    def _find_packs(self, path):
        """Recursively finds valid packs (containing manifest.json) in a file or directory."""
        found = []
        if os.path.isdir(path):
            if os.path.exists(os.path.join(path, "manifest.json")):
                # Zip the folder to a temp file so we can process it like other packs
                temp_zip = os.path.join(tempfile.gettempdir(), f"temp_{uuid.uuid4().hex}.mcpack")
                with zipfile.ZipFile(temp_zip, 'w', zipfile.ZIP_DEFLATED) as zf:
                    for root, dirs, files in os.walk(path):
                        for file in files:
                            abs_p = os.path.join(root, file)
                            zf.write(abs_p, os.path.relpath(abs_p, path))
                found.append(temp_zip)
                self.temp_files.append(temp_zip)
            else:
                for item in os.listdir(path):
                    found.extend(self._find_packs(os.path.join(path, item)))
        elif zipfile.is_zipfile(path):
            with zipfile.ZipFile(path, 'r') as z:
                if 'manifest.json' in z.namelist():
                    found.append(path)
                else:
                    # Nested archives
                    temp_extract = tempfile.mkdtemp(prefix="pack_extract_")
                    z.extractall(temp_extract)
                    found.extend(self._find_packs(temp_extract))
        return found

    def remove_files(self):
        idxs = sorted(self.file_listbox.curselection(), reverse=True)
        for i in idxs:
            self.file_listbox.delete(i)
            self.files.pop(i)

    def select_out(self):
        d = filedialog.askdirectory()
        if d:
            self.output_dir = d
            self.out_entry.delete(0, tk.END)
            self.out_entry.insert(0, d)

    def _is_obfuscated(self, path):
        try:
            with zipfile.ZipFile(path, 'r') as z:
                for name in z.namelist():
                    if name.endswith('.json'):
                        with z.open(name) as f:
                            raw = f.read(2048).decode('utf-8', errors='ignore').strip()
                            if raw.startswith('*/') or len(re.findall(r'\\u[0-9a-fA-F]{4}', raw)) > 15:
                                return True
        except: pass
        return False

    def start_process(self):
        if not self.files or not self.out_entry.get():
            messagebox.showerror("Error", "Please select files and output directory.")
            return
        self.output_dir = self.out_entry.get()

        bad_packs = [os.path.basename(f) for f in self.files if self._is_obfuscated(f)]
        if bad_packs:
            msg = "The following packs appear to be obfuscated/protected:\n\n" + "\n".join(bad_packs)
            msg += "\n\nMerging obfuscated packs may fail or result in corrupted output. Continue?"
            if not messagebox.askyesno("Warning", msg):
                return

        threading.Thread(target=self.run_merge, daemon=True).start()

    def run_merge(self):
        try:
            self.progress['value'] = 10
            log_info("Starting merge process...")

            # 1. Identifier Scanning
            id_manager = IdentifierManager()
            all_pack_ids = {}
            for f in self.files:
                all_pack_ids[f] = id_manager.scan_pack(f)
            id_manager.detect_conflicts(all_pack_ids)
            id_manager.generate_mappings()
            self.progress['value'] = 30

            # 2. Preparation
            temp_dir = tempfile.mkdtemp(prefix="autobe_merge_")
            bp_zip_path = os.path.join(temp_dir, "behavior_pack.zip")
            rp_zip_path = os.path.join(temp_dir, "resource_pack.zip")

            json_contents = defaultdict(list) # (target_zip, filename/identifier) -> [data]
            json_paths = {} # identifier -> original_filename
            lang_contents = defaultdict(list)

            scripts_dir = os.path.join(temp_dir, "scripts")
            os.makedirs(scripts_dir, exist_ok=True)
            imported_scripts = []

            # 3. Processing each pack
            for idx, pack_path in enumerate(self.files):
                log_info(f"Processing {os.path.basename(pack_path)}...")

                # Detect pack type from manifest
                module_type = "resources"
                try:
                    with zipfile.ZipFile(pack_path, 'r') as z:
                        if 'manifest.json' in z.namelist():
                            with z.open('manifest.json') as f:
                                m_data = load_json_robust(f.read().decode('utf-8', errors='ignore'))
                                if m_data and 'modules' in m_data:
                                    module_type = m_data['modules'][0].get('type', 'resources')
                except: pass

                target_zip = rp_zip_path if module_type == 'resources' else bp_zip_path

                with zipfile.ZipFile(pack_path, 'r') as z:
                    for name in z.namelist():
                        if name == 'manifest.json' or name.endswith('pack_icon.png') or name.endswith('pack_icon.jpg'): continue

                        # Scripts
                        if name.startswith('scripts/') and name.endswith('.js'):
                            z.extract(name, temp_dir)
                            old_path = os.path.join(temp_dir, name)
                            new_name = f"{uuid.uuid4().hex[:8]}_{os.path.basename(name)}"
                            new_path = os.path.join(scripts_dir, new_name)
                            os.rename(old_path, new_path)
                            imported_scripts.append(new_name)
                            continue

                        # JSON Merging
                        if name.endswith('.json'):
                            mergeable = any(x in name for x in ['item_texture', 'terrain_texture', 'blocks.json', 'sounds.json', 'player.json', 'flipbook_textures', 'textures_list', 'ui_defs', 'hud_screen'])
                            with z.open(name) as f:
                                content = f.read().decode('utf-8', errors='ignore')
                                data = load_json_robust(content)
                                if data:
                                    ident = id_manager._extract_id_from_json(data, name)
                                    data = id_manager.update_json(data, pack_path)
                                    if mergeable or ident:
                                        key = (target_zip, ident if ident else name)
                                        json_contents[key].append(data)
                                        if ident and key not in json_paths:
                                            json_paths[key] = name
                                        continue

                        # Lang
                        if name.endswith('.lang'):
                            with z.open(name) as f:
                                lang_contents[(target_zip, name)].append(f.read().decode('latin-1'))
                            continue

                        # Other files: Copy as is
                        with z.open(name) as f, zipfile.ZipFile(target_zip, 'a') as out_z:
                            data = f.read()
                            if name.endswith('.mcfunction'):
                                text = data.decode('utf-8', errors='ignore')
                                data = id_manager.update_text(text, pack_path).encode('utf-8')
                            out_z.writestr(name, data)

            self.progress['value'] = 70

            # 4. Finalizing Merged Files
            for (target_zip, key_id), data_list in json_contents.items():
                merged = {}
                for d in data_list:
                    if isinstance(d, dict): recursive_merge(merged, d)
                    elif isinstance(d, list):
                        if not isinstance(merged, list): merged = []
                        merged.extend(d)

                # Determine output filename
                out_name = json_paths.get((target_zip, key_id), key_id)
                with zipfile.ZipFile(target_zip, 'a') as out_z:
                    out_z.writestr(out_name, json.dumps(merged, indent=2))

            for (target_zip, name), lang_list in lang_contents.items():
                merged_lang = "\n".join(lang_list)
                with zipfile.ZipFile(target_zip, 'a') as out_z:
                    out_z.writestr(name, merged_lang)

            # 5. Create Master Script
            if imported_scripts:
                master_script = "\n".join([f'import "./{s}";' for s in imported_scripts])
                with open(os.path.join(scripts_dir, "CodeNex.js"), 'w') as f:
                    f.write(master_script)
                # Pack scripts into BP
                with zipfile.ZipFile(bp_zip_path, 'a') as out_z:
                    for f in os.listdir(scripts_dir):
                        out_z.write(os.path.join(scripts_dir, f), f"scripts/{f}")

            # 6. Manifest Generation
            self.create_manifests(bp_zip_path, rp_zip_path)

            # 7. Move to Final Destination
            for p, name in [(bp_zip_path, "behavior_pack.mcpack"), (rp_zip_path, "resource_pack.mcpack")]:
                if os.path.exists(p):
                    shutil.move(p, os.path.join(self.output_dir, name))

            shutil.rmtree(temp_dir)
            # Cleanup temp zips
            for tf in self.temp_files:
                try: os.remove(tf)
                except: pass
            self.temp_files = []

            self.progress['value'] = 100
            messagebox.showinfo("Success", f"Merging complete! Packs saved to {self.output_dir}")
            log_info("Merge process completed successfully.")

        except Exception as e:
            log_error("Merge failed", e)
            messagebox.showerror("Error", f"Merge failed: {e}")

    def create_manifests(self, bp_path, rp_path):
        bp_uuid = str(uuid.uuid4())
        rp_uuid = str(uuid.uuid4())

        if os.path.exists(bp_path):
            manifest = {
                "format_version": 2,
                "header": {"name": "AutoBE Lite BP", "description": "Merged by AutoBE Lite", "uuid": bp_uuid, "version": [1,0,0], "min_engine_version": [1,20,0]},
                "modules": [{"type": "data", "uuid": str(uuid.uuid4()), "version": [1,0,0]}],
                "dependencies": [{"uuid": rp_uuid, "version": [1,0,0]}]
            }
            # Add script module if scripts exist
            with zipfile.ZipFile(bp_path, 'r') as z:
                if any(n.startswith('scripts/') for n in z.namelist()):
                    manifest["modules"].append({
                        "type": "script", "language": "javascript", "uuid": str(uuid.uuid4()), "version": [1,0,0], "entry": "scripts/CodeNex.js"
                    })
                    manifest["capabilities"] = ["script_eval"]
                    manifest["dependencies"].append({"module_name": "@minecraft/server", "version": "1.13.0"})

            with zipfile.ZipFile(bp_path, 'a') as z:
                z.writestr("manifest.json", json.dumps(manifest, indent=2))

        if os.path.exists(rp_path):
            manifest = {
                "format_version": 2,
                "header": {"name": "AutoBE Lite RP", "description": "Merged by AutoBE Lite", "uuid": rp_uuid, "version": [1,0,0], "min_engine_version": [1,20,0]},
                "modules": [{"type": "resources", "uuid": str(uuid.uuid4()), "version": [1,0,0]}],
                "dependencies": [{"uuid": bp_uuid, "version": [1,0,0]}]
            }
            with zipfile.ZipFile(rp_path, 'a') as z:
                z.writestr("manifest.json", json.dumps(manifest, indent=2))

if __name__ == "__main__":
    root = tk.Tk()
    app = AutoBELite(root)
    root.mainloop()
