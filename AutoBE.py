import json5
import os as _os
import zipfile as _zipfile
import json as _json
import random as _random
import shutil as _shutil
import ctypes as _ctypes
import tkinter as _tk
from tkinter import filedialog as _filedialog, messagebox as _messagebox, ttk as _ttk
import uuid as _uuid
import hashlib
import platform
import datetime as _datetime
import subprocess
import re as _re
import logging
_logging = logging
import tempfile as _tempfile
import requests as _requests
import base64
import sys
import traceback
import math
import csv
import io
import threading
from collections import defaultdict

GITHUB_TOKEN = "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"
GITHUB_REPO = "FrostyHostMC/AutoBE"

logging.basicConfig(filename="error_log.txt", level=logging.ERROR, encoding="utf-8")

def load_json_data(content):
    """Load JSON content with robust comment stripping and optional JSON5 support."""
    if not content: return None
    if isinstance(content, bytes):
        try: content = content.decode('utf-8')
        except UnicodeDecodeError: content = content.decode('latin-1', errors='ignore')

    try: return json5.loads(content)
    except Exception: pass

    # Fallback: manual comment removal
    content_clean = _re.sub(r'/\*.*?\*/', '', content, flags=_re.DOTALL)
    lines = content_clean.split('\n')
    cleaned_lines = []
    for line in lines:
        in_string, escape_next, new_line = False, False, []
        for i, char in enumerate(line):
            if escape_next: new_line.append(char); escape_next = False
            elif char == '\\' and in_string: new_line.append(char); escape_next = True
            elif char == '"': in_string = not in_string; new_line.append(char)
            elif char == '/' and i + 1 < len(line) and line[i+1] == '/' and not in_string: break
            else: new_line.append(char)
        cleaned_lines.append(''.join(new_line))
    content_clean = '\n'.join(cleaned_lines)
    content_clean = _re.sub(r',\s*([}\]])', r'\1', content_clean)

    try: return _json.loads(content_clean)
    except Exception:
        try:
            start_idx = content_clean.find('{')
            if start_idx >= 0:
                brace_count, in_string, escape_next = 0, False, False
                for i in range(start_idx, len(content_clean)):
                    char = content_clean[i]
                    if escape_next: escape_next = False
                    elif char == '\\' and in_string: escape_next = True
                    elif char == '"': in_string = not in_string
                    elif not in_string:
                        if char == '{': brace_count += 1
                        elif char == '}':
                            brace_count -= 1
                            if brace_count == 0:
                                return _json.loads(content_clean[start_idx:i+1])
        except Exception: pass
    return None

def normalize_bedrock_string(s):
    """Normalize Minecraft Bedrock specific strings for comparison."""
    if not isinstance(s, str): return s
    s = _re.sub(r'\s*=\s*', '=', s)
    replacements = {
        "1st_person": "first_person", "3rd_person": "third_person",
        "v.is_first_person": "variable.is_first_person", "q.is_spectator": "query.is_spectator"
    }
    for old, new in replacements.items(): s = s.replace(old, new)
    return s

def deep_merge_json(target, source):
    """Advanced recursive merge for Minecraft Bedrock JSON files."""
    if isinstance(source, str): return normalize_bedrock_string(source)
    if not isinstance(source, (dict, list)): return source
    if isinstance(source, list):
        if not isinstance(target, list): return source
        combined = target + source
        res, seen = [], set()
        for item in combined:
            s = _json.dumps(item, sort_keys=True)
            if s not in seen: res.append(item); seen.add(s)
        return res
    if not isinstance(target, dict): return source

    for k, v in source.items():
        if k == "format_version" and k in target:
            try:
                v1 = [int(x) for x in str(target[k]).split('.')]
                v2 = [int(x) for x in str(v).split('.')]
                if v2 > v1: target[k] = v
            except Exception: pass
        elif k in ["components", "component_groups", "events"] and isinstance(v, dict):
            if k not in target: target[k] = {}
            for sub_k, sub_v in v.items():
                target[k][sub_k] = deep_merge_json(target[k].get(sub_k), sub_v)
        elif k == "permutations" and isinstance(v, list):
            if k not in target: target[k] = []
            for perm in v:
                cond = perm.get("condition")
                found = False
                for t_perm in target[k]:
                    if t_perm.get("condition") == cond:
                        deep_merge_json(t_perm, perm)
                        found = True; break
                if not found: target[k].append(perm)
        elif isinstance(v, dict) and k in target and isinstance(target[k], dict):
            deep_merge_json(target[k], v)
        elif isinstance(v, list) and k in target and isinstance(target[k], list):
            target[k] = deep_merge_json(target[k], v)
        else:
            target[k] = v
    return target

def _generate_hwid_shared():
    """Shared hardware-based unique identifier generation."""
    try:
        if platform.system() == "Windows":
            cmd = 'powershell -command "(Get-CimInstance Win32_ComputerSystemProduct).UUID"'
            uuid_v = subprocess.check_output(cmd, shell=True, text=True).strip()
            if uuid_v and len(uuid_v) > 10: return uuid_v.upper()
            output = subprocess.check_output("wmic csproduct get uuid", shell=True, text=True).splitlines()
            for line in output:
                c = line.strip()
                if c and "UUID" not in c.upper(): return c.upper()
        elif platform.system() == "Linux":
            with open("/etc/machine-id", "r") as f: return f.read().strip()
        elif platform.system() == "Darwin":
            c = "system_profiler SPHardwareDataType | grep 'Hardware UUID'"
            return subprocess.check_output(c, shell=True).decode().split(": ")[1].strip().upper()
    except Exception: pass
    return hashlib.md5(platform.node().encode()).hexdigest()

def log_error(e):
    logging.error(str(e), exc_info=True)

def log_uncaught_exceptions(ex_cls, ex, tb):
    with open("error_log.txt", "w", encoding="utf-8") as f:
        traceback.print_exception(ex_cls, ex, tb, file=f)
    print("An error occurred. See error_log.txt for details.")

sys.excepthook = log_uncaught_exceptions

# --- Recursive Extraction Utilities ---
def is_pack_folder(folder):
    """Returns True if manifest.json and pack_icon (png/jpg) exist at root."""
    has_manifest = _os.path.isfile(_os.path.join(folder, 'manifest.json'))
    has_icon = any(
        _os.path.isfile(_os.path.join(folder, f'pack_icon{ext}'))
        for ext in ['.png', '.jpg', '.jpeg']
    )
    return has_manifest and has_icon

def recursive_extract_pack(archive_path, dest_dir=None, max_depth=10):
    """
    Recursively extracts nested mcpack/mcaddon/zip files until it finds a folder with
    manifest.json & pack_icon in the root. It stops extracting deeper at that point.
    Returns a list of all top-level valid pack folders found.
    """
    if max_depth < 1:
        return []
    if dest_dir is None:
        dest_dir = _tempfile.mkdtemp(prefix='mcpack_unpack_')
    packs_found = []

    # Unzip the file to dest_dir
    with _zipfile.ZipFile(archive_path, 'r') as z:
        z.extractall(dest_dir)

    # Case 1: dest_dir itself is a real pack folder
    if is_pack_folder(dest_dir):
        packs_found.append(dest_dir)
        return packs_found

    # Case 2: Multiple .mcpack/.mcaddon/.zip files inside (multi-pack)
    for f in _os.listdir(dest_dir):
        file_path = _os.path.join(dest_dir, f)
        # If it's a nested archive, extract recursively
        if _os.path.isfile(file_path) and f.lower().endswith(('.mcpack', '.mcaddon', '.zip')):
            sub_dest_dir = _tempfile.mkdtemp(prefix='mcpack_unpack_')
            packs_found += recursive_extract_pack(file_path, dest_dir=sub_dest_dir, max_depth=max_depth-1)

        # If it's a folder, check if it's a valid pack
        elif _os.path.isdir(file_path) and is_pack_folder(file_path):
            packs_found.append(file_path)
    return packs_found

class IdentifierManager:
    """
    Manages identifier conflicts by:
    1. Scanning all identifiers in packs
    2. Detecting conflicts
    3. Generating unique namespaces
    4. Prefixing identifiers
    5. Tracking and updating references
    """
    
    def __init__(self):
        self.all_identifiers = defaultdict(set)  # type -> set of identifiers
        self.pack_identifiers = {}  # pack_path -> {type -> set of identifiers}
        self.identifier_mapping = {}  # (pack_path, old_id) -> new_id
        self.pack_namespaces = {}  # pack_path -> namespace_prefix
        self.conflict_map = defaultdict(list)  # identifier -> [pack_paths]
        self.reference_files = defaultdict(set)  # identifier -> set of file_paths
        
    def scan_pack_identifiers(self, pack_zip, pack_path):
        """
        Scan a pack for all identifiers (entities, items, blocks, loot tables, recipes).
        Returns dict of identifier types and their values.
        """
        identifiers = {
            'entities': set(),
            'items': set(),
            'blocks': set(),
            'loot_tables': set(),
            'recipes': set(),
            'animation_controllers': set(),
            'render_controllers': set(),
            'textures': set()
        }
        
        try:
            for item_name in pack_zip.namelist():
                if item_name.startswith('subpacks/'):
                    continue
                    
                # Scan entity files
                if item_name.startswith('entities/') and item_name.endswith('.json'):
                    identifiers['entities'].update(self._extract_entity_identifiers(pack_zip, item_name))
                    
                # Scan item files
                if item_name.startswith('items/') and item_name.endswith('.json'):
                    identifiers['items'].update(self._extract_item_identifiers(pack_zip, item_name))
                    
                # Scan block files
                if item_name.startswith('blocks/') and item_name.endswith('.json'):
                    identifiers['blocks'].update(self._extract_block_identifiers(pack_zip, item_name))
                    
                # Scan loot tables
                if item_name.startswith('loot_tables/') and item_name.endswith('.json'):
                    loot_id = self._extract_loot_table_id(item_name)
                    if loot_id:
                        identifiers['loot_tables'].add(loot_id)
                        
                # Scan recipes
                if item_name.startswith('recipes/') and item_name.endswith('.json'):
                    identifiers['recipes'].update(self._extract_recipe_identifiers(pack_zip, item_name))
                    
                # Scan animation controllers
                if 'animation_controllers' in item_name and item_name.endswith('.json'):
                    identifiers['animation_controllers'].update(self._extract_animation_controller_identifiers(pack_zip, item_name))
                    
                # Scan render controllers
                if 'render_controllers' in item_name and item_name.endswith('.json'):
                    identifiers['render_controllers'].update(self._extract_render_controller_identifiers(pack_zip, item_name))
                    
        except Exception as e:
            _logging.warning(f"Error scanning identifiers in {pack_path}: {e}")
            
        return identifiers
    
    def _extract_entity_identifiers(self, pack_zip, item_name):
        """Extract entity identifiers from entity JSON file."""
        identifiers = set()
        try:
            with pack_zip.open(item_name) as f:
                try:
                    data = load_json_data(f.read())
                    # Check for minecraft:entity or minecraft:client_entity
                    for key in ['minecraft:entity', 'minecraft:client_entity']:
                        if key in data:
                            desc = data[key].get('description', {})
                            entity_id = desc.get('identifier')
                            if entity_id and entity_id != 'minecraft:player':
                                identifiers.add(entity_id)
                except:
                    pass
        except:
            pass
        return identifiers
    
    def _extract_item_identifiers(self, pack_zip, item_name):
        """Extract item identifiers from item JSON file."""
        identifiers = set()
        try:
            with pack_zip.open(item_name) as f:
                try:
                    data = load_json_data(f.read())
                    if 'minecraft:item' in data:
                        desc = data['minecraft:item'].get('description', {})
                        item_id = desc.get('identifier')
                        if item_id:
                            identifiers.add(item_id)
                except:
                    pass
        except:
            pass
        return identifiers
    
    def _extract_block_identifiers(self, pack_zip, item_name):
        """Extract block identifiers from block JSON file."""
        identifiers = set()
        try:
            with pack_zip.open(item_name) as f:
                try:
                    data = load_json_data(f.read())
                    if 'minecraft:block' in data:
                        desc = data['minecraft:block'].get('description', {})
                        block_id = desc.get('identifier')
                        if block_id:
                            identifiers.add(block_id)
                except:
                    pass
        except:
            pass
        return identifiers
    
    def _extract_loot_table_id(self, item_name):
        """Extract loot table identifier from file path."""
        # Format: loot_tables/entities/zombie.json -> minecraft:entities/zombie
        if item_name.startswith('loot_tables/'):
            path_part = item_name[12:]  # Remove 'loot_tables/'
            if path_part.endswith('.json'):
                path_part = path_part[:-5]  # Remove '.json'
                # Convert path to identifier format
                parts = path_part.split('/')
                if len(parts) >= 2:
                    return f"{parts[0]}:{'/'.join(parts[1:])}"
                elif len(parts) == 1:
                    return f"loot_tables:{parts[0]}"
        return None
    
    def _extract_recipe_identifiers(self, pack_zip, item_name):
        """Extract recipe identifiers from recipe JSON file."""
        identifiers = set()
        try:
            with pack_zip.open(item_name) as f:
                try:
                    data = load_json_data(f.read())
                    # Recipes can have identifier in description or as key
                    if 'minecraft:recipe_furnace' in data or 'minecraft:recipe_shaped' in data or 'minecraft:recipe_shapeless' in data:
                        for key in data.keys():
                            if 'recipe' in key.lower():
                                recipe_data = data[key]
                                if isinstance(recipe_data, dict):
                                    desc = recipe_data.get('description', {})
                                    recipe_id = desc.get('identifier')
                                    if recipe_id:
                                        identifiers.add(recipe_id)
                except:
                    pass
        except:
            pass
        return identifiers
    
    def _extract_animation_controller_identifiers(self, pack_zip, item_name):
        """Extract animation controller identifiers."""
        identifiers = set()
        try:
            with pack_zip.open(item_name) as f:
                try:
                    data = load_json_data(f.read())
                    # Animation controllers are keyed by identifier
                    for key in data.keys():
                        if ':' in key:  # Has namespace:name format
                            identifiers.add(key)
                except:
                    pass
        except:
            pass
        return identifiers
    
    def _extract_render_controller_identifiers(self, pack_zip, item_name):
        """Extract render controller identifiers."""
        identifiers = set()
        try:
            with pack_zip.open(item_name) as f:
                try:
                    data = load_json_data(f.read())
                    # Render controllers are keyed by identifier
                    for key in data.keys():
                        if ':' in key:
                            identifiers.add(key)
                except:
                    pass
        except:
            pass
        return identifiers
    
    def detect_conflicts(self, all_pack_identifiers):
        """
        Detect identifier conflicts across all packs.
        all_pack_identifiers: dict of pack_path -> identifiers dict
        """
        # Aggregate all identifiers by type
        type_identifiers = defaultdict(set)
        self.pack_identifiers = all_pack_identifiers
        
        for pack_path, identifiers in all_pack_identifiers.items():
            for id_type, id_set in identifiers.items():
                type_identifiers[id_type].update(id_set)
                # Track which packs use each identifier
                for identifier in id_set:
                    self.conflict_map[identifier].append(pack_path)
        
        # Generate namespace prefixes for each pack
        for idx, pack_path in enumerate(all_pack_identifiers.keys()):
            # Create unique namespace prefix (pack1_merge, pack2_merge, etc.)
            pack_name = _os.path.basename(pack_path).replace('.mcpack', '').replace('.mcaddon', '')
            # Clean up pack name for namespace (only alphanumeric and underscore)
            clean_name = _re.sub(r'[^a-zA-Z0-9_]', '_', pack_name)[:20]
            self.pack_namespaces[pack_path] = f"{clean_name}_merge"
    
    def generate_identifier_mappings(self):
        """
        Generate mappings from old identifiers to new prefixed identifiers.
        Only maps identifiers that have conflicts.
        """
        # Find all identifiers that appear in multiple packs
        conflicted_identifiers = {id: packs for id, packs in self.conflict_map.items() if len(packs) > 1}
        
        for identifier, pack_paths in conflicted_identifiers.items():
            # For each pack that uses this identifier, create a mapping
            for pack_path in pack_paths:
                namespace = self.pack_namespaces.get(pack_path, 'pack_merge')
                # Create new identifier with namespace prefix
                if ':' in identifier:
                    namespace_part, name_part = identifier.split(':', 1)
                    # If namespace is already custom, prepend our prefix
                    if namespace_part not in ['minecraft', 'minecraft_vanilla']:
                        new_id = f"{namespace}:{name_part}"
                    else:
                        # Keep minecraft namespace but add prefix to name
                        new_id = f"{namespace_part}:{namespace}_{name_part}"
                else:
                    new_id = f"{namespace}:{identifier}"
                
                self.identifier_mapping[(pack_path, identifier)] = new_id
        
        _logging.info(f"Generated {len(self.identifier_mapping)} identifier mappings for conflict resolution")
    
    def get_new_identifier(self, pack_path, old_identifier):
        """Get the new identifier for a given pack and old identifier."""
        return self.identifier_mapping.get((pack_path, old_identifier), old_identifier)
    
    def should_rename_identifier(self, identifier):
        """Check if an identifier needs to be renamed (has conflicts)."""
        return len(self.conflict_map.get(identifier, [])) > 1
    
    def update_json_identifiers(self, json_data, pack_path):
        """
        Recursively update all identifier references in JSON data.
        Returns updated JSON data structure.
        """
        if isinstance(json_data, dict):
            updated = {}
            for key, value in json_data.items():
                # Update identifier fields
                if key == 'identifier' and isinstance(value, str):
                    updated[key] = self.get_new_identifier(pack_path, value)
                elif key in ['entity', 'item', 'block', 'loot_table', 'recipe'] and isinstance(value, str):
                    # Update references to entities/items/blocks
                    updated[key] = self.get_new_identifier(pack_path, value)
                else:
                    # Recursively update nested structures
                    updated[key] = self.update_json_identifiers(value, pack_path)
            return updated
        elif isinstance(json_data, list):
            return [self.update_json_identifiers(item, pack_path) for item in json_data]
        elif isinstance(json_data, str):
            # Check if string is an identifier reference (contains :)
            if ':' in json_data and not json_data.startswith('http'):
                # Try to update if it matches a known identifier
                new_id = self.get_new_identifier(pack_path, json_data)
                return new_id
        return json_data
    
    def update_text_identifiers(self, text, pack_path):
        """
        Update identifier references in text content (scripts, lang files, etc.).
        Uses regex to find and replace identifier patterns.
        """
        # Pattern to match identifiers (namespace:name format)
        identifier_pattern = r'\b([a-zA-Z0-9_]+:[a-zA-Z0-9_\./]+)\b'
        
        def replace_identifier(match):
            old_id = match.group(1)
            new_id = self.get_new_identifier(pack_path, old_id)
            return new_id
        
        updated_text = _re.sub(identifier_pattern, replace_identifier, text)
        return updated_text

def find_valid_packs(entry, max_depth=10):
    """
    Recursively find all pack folders (manifest.json at root) inside entry.
    Returns a list of absolute paths to valid pack folders.
    """
    found = []
    if max_depth < 1:
        return []
    if _os.path.isdir(entry):
        if _os.path.isfile(_os.path.join(entry, 'manifest.json')):
            found.append(entry)
            return found
        for child in _os.listdir(entry):
            child_path = _os.path.join(entry, child)
            found += find_valid_packs(child_path, max_depth-1)
        return found
    ext = _os.path.splitext(entry)[1].lower()
    if ext in ('.mcpack', '.mcaddon', '.zip'):
        tempdir = _tempfile.mkdtemp(prefix='mcpacker_temp_')
        try:
            with _zipfile.ZipFile(entry, 'r') as z:
                z.extractall(tempdir)
            for item in _os.listdir(tempdir):
                child_path = _os.path.join(tempdir, item)
                found += find_valid_packs(child_path, max_depth-1)
            if _os.path.isfile(_os.path.join(tempdir, 'manifest.json')):
                found.append(tempdir)
        except Exception as e:
            print(f"Failed to unzip {entry}: {e}")
        # Don't delete tempdir here! (wait until after zipping result)
    return found

def zip_pack_folder(folder, output_mcpack_path):
    with _zipfile.ZipFile(output_mcpack_path, 'w', _zipfile.ZIP_DEFLATED) as zf:
        for root, dirs, files in _os.walk(folder):
            rel = _os.path.relpath(root, folder)
            for file in files:
                abs_path = _os.path.join(root, file)
                arcname = _os.path.join(rel, file) if rel != '.' else file
                zf.write(abs_path, arcname)

class _T1:
    def __init__(self, _p1):
        self._p1 = _p1
        self._w1 = _tk.Toplevel(_p1)
        self._w1.title("Terms of Use and License - AutoBE - CodeNex")
        self._w1.geometry("800x600")
        self._w1.configure(bg='#0f1419')

        # Container frame for better layout
        container = _tk.Frame(self._w1, bg='#0f1419')
        container.pack(fill=_tk.BOTH, expand=True, padx=15, pady=15)

        # Text widget with modern styling
        self._t1 = _tk.Text(container, wrap=_tk.WORD, bg='#0A0A0A', fg='#FFFFFF', font=("Segoe UI", 11), insertbackground='#a855f7', relief='flat')
        self._t1.pack(side=_tk.LEFT, fill=_tk.BOTH, expand=True, padx=(0, 5))

        # Scrollbar with modern styling
        self._s1 = _tk.Scrollbar(container, orient=_tk.VERTICAL, command=self._t1.yview, bg='#1a1a1a', troughcolor='#0A0A0A', activebackground='#9333ea')
        self._s1.pack(side=_tk.RIGHT, fill=_tk.Y)
        self._t1.config(yscrollcommand=self._s1.set)

        _terms_text = """SOFTWARE LICENSE AGREEMENT

AutoBE by CodeNex

Last updated: 2026

This Software License Agreement ("Agreement") is a legally binding contract between you ("User", "Licensee", or "you") and CodeNex, a software developer based in Rockingham, North Carolina, United States ("CodeNex", "we", "us", or "our"). This Agreement governs your purchase, download, installation, access to, and use of the software product known as AutoBE ("Software").

By purchasing, downloading, installing, or using the Software, you agree to be bound by this Agreement. If you do not agree, do not purchase or use the Software.

⸻

1. NO AFFILIATION

AutoBE is an independent third-party software tool. CodeNex is not affiliated with, endorsed by, or associated with Mojang Studios or Microsoft Corporation. Minecraft is a trademark of Microsoft Corporation and is referenced for descriptive purposes only.

⸻

2. GRANT OF LICENSE

CodeNex grants you a non-exclusive, non-transferable, revocable, limited license to install and use the Software on one compatible device for personal addon management purposes.

The Software is licensed, not sold. All rights not expressly granted are reserved by CodeNex.

⸻

3. LICENSE RESTRICTIONS

You may not, directly or indirectly:
• Reverse engineer, decompile, or disassemble the Software
• Modify or create derivative works of the Software
• Redistribute, resell, sublicense, rent, or share the Software or access to it
• Remove proprietary notices or branding
• Use the Software in violation of applicable laws or third-party rights
• Use the Software to redistribute or monetize addons without proper permission

Violation of these terms may result in termination of your license.

⸻

4. THIRD-PARTY ADDONS & USER RESPONSIBILITY

AutoBE does not include, distribute, or license any third-party addons.

You are solely responsible for ensuring you have the legal right to use, merge, modify, or distribute any addons processed using the Software. Addon creators retain all rights to their work, and their individual licenses apply at all times.

CodeNex is not responsible for misuse of addons or violations of third-party licenses.

⸻

5. TERM AND TERMINATION

This Agreement remains effective until terminated.

CodeNex may terminate your license if you violate this Agreement. Upon termination, you must cease all use of the Software and delete all copies.

Termination for violation does not entitle you to a refund, except where required by applicable law.

⸻

6. DIGITAL DELIVERY & RIGHT OF WITHDRAWAL (EU NOTICE)

By purchasing AutoBE, you acknowledge that the Software is digital content delivered immediately.

Where permitted by law, you expressly consent to immediate delivery and acknowledge that this may limit or remove statutory withdrawal rights once delivery has begun.

This section does not affect any mandatory consumer rights under applicable law.

⸻

7. REFUNDS

All sales are final except where refunds are required by applicable law.

If you are entitled to a refund under mandatory consumer protection laws (such as for non-conforming digital content), such refunds will be handled in accordance with those laws.

⸻

8. DISCLAIMER OF WARRANTIES

The Software is provided "as is" and "as available".

To the maximum extent permitted by law, CodeNex disclaims all warranties, express or implied.
This disclaimer does not exclude statutory warranties that cannot be waived under applicable consumer protection laws.

⸻

9. LIMITATION OF LIABILITY

To the maximum extent permitted by law, CodeNex shall not be liable for indirect, incidental, or consequential damages arising from use of the Software.

Where liability cannot be excluded by law, CodeNex's total liability shall be limited to the amount paid for the Software.

⸻

10. GOVERNING LAW

This Agreement is governed by the laws of the State of North Carolina, USA, without prejudice to mandatory consumer protection laws applicable in your country of residence.

⸻

11. SEVERABILITY

If any provision is found unenforceable, the remaining provisions remain in full force.

⸻

12. CONTACT

Support and licensing inquiries:
📧 thebedrocklabhelp@gmail.com

⸻

ACKNOWLEDGMENT

By purchasing or using AutoBE, you confirm that you have read and understood this Agreement and agree to be bound by its terms.

© 2024 CodeNex. All rights reserved."""

        self._t1.insert(_tk.END, _terms_text)
        self._t1.config(state=_tk.DISABLED)

        # Button with modern styling
        button_frame = _tk.Frame(self._w1, bg='#0f1419')
        button_frame.pack(pady=(0, 15))
        
        self._b1 = _tk.Button(button_frame, text="✓ I Agree", command=self._accept, bg='#9333ea', fg='#FFFFFF', font=("Segoe UI", 12, "bold"), relief='flat', cursor='hand2', activebackground='#a855f7', padx=30, pady=10)
        self._b1.pack()

    def _accept(self):
        self._w1.destroy()
        self._p1.deiconify()

class _ActivationWindow:
    def __init__(self, _p1):
        self._p1 = _p1
        self._w1 = _tk.Toplevel(_p1)
        self._w1.title("Enter Activation Key")
        self._w1.geometry("400x200")
        self._w1.configure(bg='#0A0A0A')

        self._label = _tk.Label(self._w1, text="Enter Activation Key:", bg='#0A0A0A', fg='#E1E1E1', font=("Helvetica", 12))
        self._label.pack(pady=10)

        self._entry_key = _tk.Entry(self._w1, width=40, bg='#1A1A1A', fg='#A50CAC', font=("Helvetica", 12))
        self._entry_key.pack(pady=10)

        self._btn_submit = _tk.Button(self._w1, text="Submit", command=self._submit_key, bg='#A50CAC', fg='#FFFFFF', font=("Helvetica", 12, "bold"))
        self._btn_submit.pack(pady=10)

    def _submit_key(self):
        _key = self._entry_key.get().strip()
        if not _key:
            _messagebox.showerror("Error", "Please enter an activation key.")
            return

        _url_keys = f"https://raw.githubusercontent.com/{GITHUB_REPO}/main/keys.csv"
        _headers = {"Authorization": f"token {GITHUB_TOKEN}"}

        try:
            response = _requests.get(_url_keys, headers=_headers, timeout=10)
            response.raise_for_status()
            response.encoding = 'utf-8'
            
            csv_reader = csv.reader(io.StringIO(response.text))
            valid_keys = []
            for row in csv_reader:
                for key in row:
                    key = key.strip()
                    if key: valid_keys.append(key)
            
            normalized_input = _key.strip().replace(' ', '')
            if normalized_input not in valid_keys:
                _messagebox.showerror("Error", "Invalid activation key.")
                return

            valid_keys.remove(normalized_input)
            self._update_keys_csv(valid_keys)

            _hwid = self._generate_hwid()
            self._append_hwid(_hwid)

            _messagebox.showinfo("Success", "Activation successful! Please Wait About 10 Minutes And Reopen The Tool.")
            self._send_discord_notification(_key)
            self._w1.destroy()
            self._p1.destroy()
        except Exception as e:
            log_error(e)
            _messagebox.showerror("Error", f"Failed to validate key. Error: {str(e)}")

    def _update_keys_csv(self, valid_keys):
        _keys_file_url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/keys.csv"
        _headers = {"Authorization": f"token {GITHUB_TOKEN}", "Content-Type": "application/json"}
        new_content = "\n".join(valid_keys).encode('latin-1')
        encoded_content = base64.b64encode(new_content).decode('latin-1')
        try:
            response = _requests.get(_keys_file_url, headers=_headers)
            response.raise_for_status()
            sha = response.json()['sha']
            update_data = {"message": "Remove used activation key", "content": encoded_content, "sha": sha}
            _requests.put(_keys_file_url, json=update_data, headers=_headers).raise_for_status()
        except Exception as e:
            log_error(e)
            raise Exception(f"Failed to update keys.csv: {str(e)}")

    def _append_hwid(self, _hwid):
        _hwid_file_url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/hwid_address.txt"
        _headers = {"Authorization": f"token {GITHUB_TOKEN}", "Content-Type": "application/json"}
        try:
            response = _requests.get(_hwid_file_url, headers=_headers)
            response.raise_for_status()
            file_data = response.json()
            current_content = base64.b64decode(file_data['content']).decode('utf-8').rstrip()
            updated_content = f"{current_content}\n{_hwid}\n"
            encoded_content = base64.b64encode(updated_content.encode('utf-8')).decode('utf-8')
            update_data = {"message": "Add new HWID", "content": encoded_content, "sha": file_data['sha']}
            _requests.put(_hwid_file_url, json=update_data, headers=_headers).raise_for_status()
        except Exception as e:
            log_error(e)
            raise Exception(f"Failed to update hwid_address.txt: {str(e)}")

    def _send_discord_notification(self, _key):
        _hwid = self._generate_hwid()
        _webhook_url = "https://discord.com/api/webhooks/1279960853969502248/Y7VR7m6qEEe0UScvkZLe1IJO4lK-p7AP8_RAoXsWbsbrBui_geLnA_DW1TFJvvEA-ptg"
        _data = {"content": f"Activation key used: {_key}\nHWID: {_hwid}"}
        _requests.post(_webhook_url, json=_data)

    def _generate_hwid(self): return _generate_hwid_shared()

class _App1:
    def __init__(self, _root):
        self._root = _root
        self._root.title("AutoBE - CodeNex")
        self._root.geometry("900x700")
        self._root.minsize(900, 700)
        # Modern dark theme background - pure black for activation window
        self._root.configure(bg='#000000')

        # Allow the main window to be resized
        self._root.columnconfigure(0, weight=1)
        self._root.rowconfigure(0, weight=1)

        # Create activation overlay frame (shown first, covers everything)
        self._activation_overlay = _tk.Frame(self._root, bg='#000000')
        self._activation_overlay.grid(row=0, column=0, sticky="nsew")
        self._activation_overlay.columnconfigure(0, weight=1)
        self._activation_overlay.rowconfigure(0, weight=1)
        
        # Create subpack selection overlay frame (hidden by default)
        self._subpack_overlay = _tk.Frame(self._root, bg='#0f1419')
        self._subpack_overlay.grid(row=0, column=0, sticky="nsew")
        self._subpack_overlay.columnconfigure(0, weight=1)
        self._subpack_overlay.rowconfigure(0, weight=1)
        self._subpack_overlay.grid_remove()  # Hide initially
        
        # Create version check overlay frame (hidden by default)
        self._version_check_overlay = _tk.Frame(self._root, bg='#0f1419')
        self._version_check_overlay.grid(row=0, column=0, sticky="nsew")
        self._version_check_overlay.columnconfigure(0, weight=1)
        self._version_check_overlay.rowconfigure(0, weight=1)
        self._version_check_overlay.grid_remove()  # Hide initially
        
        # Create Notebook for Tabs (hidden until activation)
        self.notebook = _ttk.Notebook(self._root)
        self.notebook.grid(row=0, column=0, sticky="nsew")
        self.notebook.grid_remove()  # Hide initially

        # Create Frames for each Tab - Black background
        self.app1_frame = _tk.Frame(self.notebook, bg='#0f1419')
        self.mcpacker_frame = _tk.Frame(self.notebook, bg='#0f1419')
        self.list_maker_frame = _tk.Frame(self.notebook, bg='#0f1419')  # New List Maker Tab
        self.help_frame = _tk.Frame(self.notebook, bg='#0f1419')

        # Adding Tabs to Notebook
        self.notebook.add(self.app1_frame, text="AutoBE")
        self.notebook.add(self.mcpacker_frame, text="MCPACKER")
        self.notebook.add(self.list_maker_frame, text="List Maker")  # Add List Maker Tab
        self.notebook.add(self.help_frame, text="Help")

        # Configure resizing for the notebook's frames
        for frame in [self.app1_frame, self.mcpacker_frame, self.list_maker_frame, self.help_frame]:
            frame.columnconfigure(0, weight=1)
            frame.rowconfigure(0, weight=1)

        # Initialize App1 Tab Content
        # Initialize MCPACKER Tab Content
        self.init_mcpacker_tab()

        # Initialize List Maker Tab Content
        self.init_list_maker_tab()

        # Initialize Help Tab Content
        self.init_help_tab()
        
        # Track loading state for close protection
        self._is_loading = False
        
        # Set up window close protocol handler
        self._original_protocol = None
        self._root.protocol("WM_DELETE_WINDOW", self._on_window_close)
        
        # Defer activation until UI is ready to avoid root destruction errors
        self._root.after(0, self._check_activation)

    def _is_root_alive(self):
        """Safely check if root window exists without raising exceptions."""
        try:
            return self._root and self._root.winfo_exists()
        except (_tk.TclError, RuntimeError):
            return False
    
    def _is_pack_obfuscated(self, file_path):
            """Checks if a pack contains closed-source/obfuscated JSON files."""
            try:
                with _zipfile.ZipFile(file_path, 'r') as pack:
                    for name in pack.namelist():
                        if name.endswith('.json'):
                            with pack.open(name) as f:
                                try:
                                    # Read the beginning of the file to check for protection markers
                                    raw = f.read(2048).decode('utf-8', errors='ignore').strip()
                                    # Marker 1: Starts with */ (illegal JSON syntax used for protection)
                                    # Marker 2: High density of Unicode escapes (\u0065 format)
                                    if raw.startswith('*/') or len(_re.findall(r'\\u[0-9a-fA-F]{4}', raw)) > 15:
                                        return True
                                except:
                                    continue
            except:
                pass
            return False

    def _on_window_close(self):
        """Handle window close attempts - prevent closing during loading."""
        if self._is_loading:
            self._show_close_warning()
        else:
            self._root.destroy()
    
    def _show_close_warning(self):
        """Show warning overlay in the main window when user tries to close during loading."""
        if not self._is_root_alive():
            return
        
        # Create warning overlay frame (on top of loading overlay)
        if not hasattr(self, '_warning_overlay'):
            self._warning_overlay = _tk.Frame(self._root, bg='#0A0A0A')
            self._warning_overlay.grid(row=0, column=0, sticky="nsew")
            self._warning_overlay.columnconfigure(0, weight=1)
            self._warning_overlay.rowconfigure(0, weight=1)
        else:
            # Clear existing widgets
            for widget in self._warning_overlay.winfo_children():
                widget.destroy()
        
        # Create centered container
        center_frame = _tk.Frame(self._warning_overlay, bg='#0A0A0A')
        center_frame.place(relx=0.5, rely=0.5, anchor='center')
        
        # Warning icon (using emoji for modern look)
        icon_label = _tk.Label(
            center_frame,
            text="⚠️",
            bg='#0A0A0A',
            fg='#FFAA00',
            font=("Helvetica", 48)
        )
        icon_label.pack(pady=(0, 20))
        
        # Title
        title_label = _tk.Label(
            center_frame,
            text="Activation In Progress",
            bg='#0A0A0A',
            fg='#E1E1E1',
            font=("Helvetica", 18, "bold")
        )
        title_label.pack(pady=(0, 15))
        
        # Message
        message_label = _tk.Label(
            center_frame,
            text="Please wait while activation is being processed.\nClosing the window now may cause issues.",
            bg='#0A0A0A',
            fg='#CCCCCC',
            font=("Helvetica", 11),
            justify=_tk.CENTER
        )
        message_label.pack(pady=(0, 25))
        
        # Button container
        button_frame = _tk.Frame(center_frame, bg='#0A0A0A')
        button_frame.pack()
        
        # Continue button (hides warning, returns to loading)
        continue_button = _tk.Button(
            button_frame,
            text="Continue Waiting",
            command=self._hide_close_warning,
            bg='#A50CAC',
            fg='#FFFFFF',
            font=("Helvetica", 11, "bold"),
            relief=_tk.FLAT,
            bd=0,
            cursor="hand2",
            activebackground='#8B0A9C',
            activeforeground='#FFFFFF',
            padx=30,
            pady=10,
            width=15
        )
        continue_button.pack()
        
        # Show the warning overlay (on top)
        self._warning_overlay.tkraise()
        
        # Bind Enter and Escape keys
        self._root.bind('<Return>', lambda e: self._hide_close_warning())
        self._root.bind('<Escape>', lambda e: self._hide_close_warning())
    
    def _hide_close_warning(self):
        """Hide warning overlay and return to loading screen."""
        if hasattr(self, '_warning_overlay'):
            self._warning_overlay.grid_remove()
        # Return to loading overlay (which should still be visible underneath)
        if hasattr(self, '_activation_overlay'):
            self._activation_overlay.tkraise()
        # Unbind keys
        self._root.unbind('<Return>')
        self._root.unbind('<Escape>')

    def _generate_hwid(self): return _generate_hwid_shared()

    def _check_activation(self):
        _hwid = self._generate_hwid()
        _url_hwid_addresses = f"https://raw.githubusercontent.com/{GITHUB_REPO}/main/hwid_address.txt"
        _url_blacklist = f"https://raw.githubusercontent.com/{GITHUB_REPO}/main/blacklist.txt"
        _url_version = f"https://raw.githubusercontent.com/{GITHUB_REPO}/main/version.txt"

        _headers = {
            "Authorization": f"token {GITHUB_TOKEN}"
        }

        try:
            # --- Check version from GitHub ---
            try:
                _version_response = _requests.get(_url_version, headers=_headers, timeout=10)
                _version_response.raise_for_status()
                _version = _version_response.text.strip()
                if _version != "7.0.0.0":
                    _messagebox.showerror("Update Required", "This version of AutoBE is outdated or blocked.")
                    sys.exit()
            except (_requests.exceptions.RequestException, _requests.exceptions.Timeout) as e:
                log_error(f"Version check failed: {e}")
                # Continue without version check if network fails
                pass

            # --- Check blacklist from GitHub ---
            try:
                blacklist_response = _requests.get(_url_blacklist, headers=_headers, timeout=10)
                blacklist_response.raise_for_status()
                blacklist = blacklist_response.text.strip().splitlines()
                if _hwid in blacklist:
                    _messagebox.showerror("Banned", "You are banned from using AutoBE.")
                    sys.exit()
            except (_requests.exceptions.RequestException, _requests.exceptions.Timeout) as e:
                log_error(f"Blacklist check failed: {e}")
                # Continue without blacklist check if network fails
                pass

            # --- Check for spoofed system (Windows only) ---
            if platform.system() == "Windows":
                try:
                    output = subprocess.check_output(
                        ["wmic", "baseboard", "get", "serialnumber"],
                        stderr=subprocess.STDOUT,
                        text=True
                    ).splitlines()
                    serial = next(
                        (line.strip().lower() for line in output if line.strip() and "serialnumber" not in line.lower()),
                        ""
                    )
                    if serial in ["to be filled by o.e.m.", "", "default string", "oem"]:
                        _messagebox.showerror("Spoofer Detected", "Spoofed or virtual machine detected.")
                        sys.exit()
                except Exception:
                    pass  # If detection fails or WMIC is unavailable, allow user through

            # --- Check HWID whitelist ---
            try:
                response = _requests.get(_url_hwid_addresses, headers=_headers, timeout=10)
                response.raise_for_status()
                valid_hwids = [hwid.strip() for hwid in response.text.splitlines()]

                if _hwid in valid_hwids:
                    # HWID is valid - unlock application immediately
                    if self._is_root_alive():
                        self._root.after(0, self._unlock_application)
                else:
                    # Schedule safely to ensure root is alive
                    if self._is_root_alive():
                        self._root.after(0, self._show_activation_window)
            except Exception as e:
                log_error(f"HWID check failed: {e}")
                # If network fails, show activation window as fallback - schedule safely
                if self._is_root_alive():
                    self._root.after(0, self._show_activation_window)
                
        except Exception as e:
            _logging.error("Activation failed", exc_info=e)
            # Schedule safely to avoid recursion and ensure root is alive
            if self._is_root_alive():
                self._root.after(0, self._show_activation_window)

    def _create_activation_overlay(self):
        """Create the activation overlay UI in the main window."""
        if not self._is_root_alive():
            return
        
        # Ensure root is visible
        try:
            self._root.deiconify()
        except:
            pass
            
        # Clear any existing widgets in the overlay
        for widget in self._activation_overlay.winfo_children():
            widget.destroy()
        
        # Create centered container with modern styling
        center_frame = _tk.Frame(self._activation_overlay, bg='#000000')
        center_frame.place(relx=0.5, rely=0.5, anchor='center')
        
        # Modern lock icon with subtle glow effect
        lock_label = _tk.Label(
            center_frame,
            text="🔒",
            bg='#000000',
            fg='#A50CAC',
            font=("Segoe UI", 56, "bold")
        )
        lock_label.pack(pady=(0, 40))
        
        # Instructions with modern typography
        instruction_label = _tk.Label(
            center_frame,
            text="Enter Activation Key",
            bg='#000000',
            fg='#FFFFFF',
            font=("Segoe UI", 16, "normal")
        )
        instruction_label.pack(pady=(0, 25))
        
        # Modern entry field - pure black, no borders
        self._activation_entry = _tk.Entry(
            center_frame,
            width=45,
            bg='#000000',
            fg='#FFFFFF',
            font=("Segoe UI", 13),
            insertbackground='#A50CAC',
            relief=_tk.FLAT,
            bd=0,
            highlightthickness=0
        )
        self._activation_entry.pack(pady=10, padx=20, ipady=8)
        self._activation_entry.focus()
        
        # Bind Enter key to submit
        self._activation_entry.bind('<Return>', lambda e: self._submit_activation_key())
        
        # Modern submit button with hover effect
        submit_btn = _tk.Button(
            center_frame,
            text="Activate",
            command=self._submit_activation_key,
            bg='#A50CAC',
            fg='#FFFFFF',
            font=("Segoe UI", 13, "bold"),
            relief=_tk.FLAT,
            bd=0,
            cursor="hand2",
            activebackground='#8B0A9C',
            activeforeground='#FFFFFF',
            padx=40,
            pady=12,
            highlightthickness=0
        )
        submit_btn.pack(pady=(20, 10))
        
        # Error label with modern styling
        self._activation_error_label = _tk.Label(
            center_frame,
            text="",
            bg='#000000',
            fg='#FF6B6B',
            font=("Segoe UI", 11)
        )
        self._activation_error_label.pack(pady=(5, 0))
        
        # Show the overlay
        self._activation_overlay.tkraise()
    
    def _show_loading_animation(self, wait_seconds=120):
        """Show RGB loading animation while processing activation."""
        if not self._is_root_alive():
            return
        
        # Set loading state to prevent closing
        self._is_loading = True
            
        # Clear any existing widgets in the overlay
        for widget in self._activation_overlay.winfo_children():
            widget.destroy()
        
        # Create centered container
        center_frame = _tk.Frame(self._activation_overlay, bg='#000000')
        center_frame.place(relx=0.5, rely=0.5, anchor='center')
        
        # Title
        title_label = _tk.Label(
            center_frame,
            text="Processing Activation...",
            bg='#000000',
            fg='#FFFFFF',
            font=("Segoe UI", 20, "bold")
        )
        title_label.pack(pady=(0, 40))
        
        # Loading spinner container
        spinner_frame = _tk.Frame(center_frame, bg='#000000')
        spinner_frame.pack(pady=20)
        
        # Create multiple spinning circles for RGB effect
        self._loading_dots = []
        dot_colors = ['#FF0000', '#00FF00', '#0000FF', '#FFFF00', '#FF00FF', '#00FFFF']
        for i in range(6):
            dot = _tk.Label(
                spinner_frame,
                text="●",
                bg='#000000',
                fg=dot_colors[i],
                font=("Segoe UI", 24, "bold")
            )
            dot.pack(side=_tk.LEFT, padx=5)
            self._loading_dots.append(dot)
        
        # Status text
        self._loading_status_label = _tk.Label(
            center_frame,
            text="Syncing with server...",
            bg='#000000',
            fg='#A50CAC',
            font=("Segoe UI", 12)
        )
        self._loading_status_label.pack(pady=30)
        
        # Progress counter
        self._loading_progress_label = _tk.Label(
            center_frame,
            text="",
            bg='#000000',
            fg='#CCCCCC',
            font=("Segoe UI", 11)
        )
        self._loading_progress_label.pack(pady=10)
        
        # Store animation state
        self._loading_animation_step = 0
        self._loading_wait_remaining = wait_seconds
        self._loading_animation_id = None
        
        # Start animation
        self._loading_status_messages = [
            "Syncing with server...",
            "Processing activation key...",
            "Updating database...",
            "Finalizing activation...",
            "Almost done..."
        ]
        self._loading_status_index = 0
        
        # Update progress label
        self._loading_progress_label.config(text=f"Please wait {wait_seconds} seconds...")
        
        # Start the RGB animation
        self._animate_loading_rgb()
        
        # Start countdown
        self._loading_countdown()
    
    def _animate_loading_rgb(self):
        """Animate RGB colors in the loading dots."""
        if not self._is_root_alive() or not hasattr(self, '_loading_dots'):
            return
        
        # RGB color cycling
        step = self._loading_animation_step
        
        for i, dot in enumerate(self._loading_dots):
            # Create RGB color wave effect
            phase = (step + i * 60) % 360
            r = int(127.5 * (1 + math.sin(math.radians(phase))))
            g = int(127.5 * (1 + math.sin(math.radians(phase + 120))))
            b = int(127.5 * (1 + math.sin(math.radians(phase + 240))))
            
            color = f"#{r:02x}{g:02x}{b:02x}"
            dot.config(fg=color)
        
        # Update status message periodically
        if step % 30 == 0 and hasattr(self, '_loading_status_label'):
            self._loading_status_label.config(
                text=self._loading_status_messages[self._loading_status_index % len(self._loading_status_messages)]
            )
            self._loading_status_index += 1
        
        self._loading_animation_step += 5
        self._loading_animation_id = self._root.after(50, self._animate_loading_rgb)
    
    def _loading_countdown(self):
        """Countdown timer for loading."""
        if not self._is_root_alive() or not hasattr(self, '_loading_wait_remaining'):
            return
        
        if self._loading_wait_remaining > 0:
            minutes = self._loading_wait_remaining // 60
            seconds = self._loading_wait_remaining % 60
            if minutes > 0:
                time_text = f"Please wait {minutes}m {seconds}s..."
            else:
                time_text = f"Please wait {seconds}s..."
            
            if hasattr(self, '_loading_progress_label'):
                self._loading_progress_label.config(text=time_text)
            
            self._loading_wait_remaining -= 1
            self._root.after(1000, self._loading_countdown)
        else:
            # Stop animation and unlock
            if hasattr(self, '_loading_animation_id') and self._loading_animation_id:
                self._root.after_cancel(self._loading_animation_id)
            
            # Clean up loading state
            if hasattr(self, '_loading_dots'):
                del self._loading_dots
            if hasattr(self, '_loading_animation_step'):
                del self._loading_animation_step
            
            # Re-enable window closing
            self._is_loading = False
            
            # Unlock the application
            self._unlock_application()
        
    def _show_activation_window(self):
        """Show activation overlay in the main window."""
        if not self._is_root_alive():
            return
        
        # Ensure root window is visible (in case it was withdrawn)
        self._root.deiconify()
        self._root.lift()
        self._root.focus_force()
        self._root.update_idletasks()
        self._root.update()
        
        # Ensure overlay is visible and on top
        self._activation_overlay.grid()
        self._activation_overlay.tkraise()
        
        # Hide notebook if it's visible
        self.notebook.grid_remove()
        
        self._create_activation_overlay()
        
        # Force update after creating overlay
        self._root.update_idletasks()
        self._root.update()
        
        _logging.debug('Activation overlay displayed.')
    
    def _submit_activation_key(self):
        """Handle activation key submission."""
        if not hasattr(self, '_activation_entry'):
            return
            
        _key = self._activation_entry.get().strip()

        if not _key:
            if hasattr(self, '_activation_error_label'):
                self._activation_error_label.config(text="Please enter an activation key.")
            return

        _url_keys = f"https://raw.githubusercontent.com/{GITHUB_REPO}/main/keys.csv"
        _headers = {
            "Authorization": f"token {GITHUB_TOKEN}"
        }

        try:
            # Clear error message
            if hasattr(self, '_activation_error_label'):
                self._activation_error_label.config(text="")
            
            # Fetch the current list of valid keys using requests (handles UTF-8 properly)
            response = _requests.get(_url_keys, headers=_headers, timeout=10)
            response.raise_for_status()
            response.encoding = 'utf-8'  # Ensure UTF-8 encoding
            
            # Parse CSV properly - handles quoted values and escaped quotes ("" becomes ")
            csv_reader = csv.reader(io.StringIO(response.text))
            valid_keys = []
            for row in csv_reader:
                for key in row:
                    key = key.strip()
                    if key:
                        valid_keys.append(key)
            
            # Remove any spaces from input key (in case user accidentally added spaces when pasting)
            normalized_input = _key.strip().replace(' ', '')

            if normalized_input not in valid_keys:
                if hasattr(self, '_activation_error_label'):
                    self._activation_error_label.config(text="Invalid activation key.")
                return

            # Remove the key from keys.csv (use normalized key)
            valid_keys.remove(normalized_input)
            self._update_keys_csv(valid_keys)

            _hwid = self._generate_hwid()
            self._append_hwid(_hwid)

            # Send notification
            self._send_discord_notification(_key)
            
            # Show loading animation and wait for GitHub processing
            self._show_loading_animation(120)  # 2 minutes (120 seconds)

        except Exception as e:
            log_error(e)
            error_msg = f"Failed to validate key. Error: {str(e)}"
            if hasattr(self, '_activation_error_label'):
                self._activation_error_label.config(text=error_msg)
            else:
                _messagebox.showerror("Error", error_msg)
    
    def _add_btn(self, parent, text, command, **kwargs):
        kwargs.setdefault('bg', '#9333ea'); kwargs.setdefault('fg', '#FFFFFF')
        kwargs.setdefault('font', ("Segoe UI", 11, "bold")); kwargs.setdefault('relief', 'flat')
        kwargs.setdefault('cursor', 'hand2'); kwargs.setdefault('activebackground', '#a855f7')
        return _tk.Button(parent, text=text, command=command, **kwargs)

    def _add_lbl_frame(self, parent, text, **kwargs):
        kwargs.setdefault('font', ("Segoe UI", 13, "bold"))
        kwargs.setdefault('bg', '#1a1a1a'); kwargs.setdefault('fg', '#FFFFFF')
        return _tk.LabelFrame(parent, text=text, **kwargs)

    def _add_lbl(self, parent, text, **kwargs):
        kwargs.setdefault('bg', '#1a1a1a'); kwargs.setdefault('fg', '#FFFFFF')
        kwargs.setdefault('font', ("Segoe UI", 10))
        return _tk.Label(parent, text=text, **kwargs)

    def _unlock_application(self):
        """Hide activation overlay and show the main application."""
        if not self._is_root_alive(): return
        self._activation_overlay.grid_remove()
        self.notebook.grid()
        self._show_terms()
        self._create_widgets()
        _logging.debug('Application unlocked.')
    
    def _update_keys_csv(self, valid_keys):
        """Update the keys.csv file by removing the used key"""
        _keys_file_url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/keys.csv"
        _headers = {
            "Authorization": f"token {GITHUB_TOKEN}",
            "Content-Type": "application/json"
        }
        # Recreate the keys.csv content
        new_content = "\n".join(valid_keys).encode('latin-1')
        
        # Base64 encode the content
        encoded_content = base64.b64encode(new_content).decode('latin-1')
        
        try:
            # Get the SHA of the current file
            response = _requests.get(_keys_file_url, headers=_headers)
            response.raise_for_status()
            sha = response.json()['sha']

            # Update the file on GitHub with the new content
            update_data = {
                "message": "Remove used activation key",
                "content": encoded_content,
                "sha": sha
            }
            response = _requests.put(_keys_file_url, json=update_data, headers=_headers)
            response.raise_for_status()
        except Exception as e:
            log_error(e)
            raise Exception(f"Failed to update keys.csv: {str(e)}")

    def _append_hwid(self, _hwid):
        """Append HWID to the whitelist on GitHub"""
        _hwid_file_url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/hwid_address.txt"
        _headers = {
            "Authorization": f"token {GITHUB_TOKEN}",
            "Content-Type": "application/json"
        }
        try:
            response = _requests.get(_hwid_file_url, headers=_headers)
            response.raise_for_status()
            
            file_data = response.json()
            current_content = base64.b64decode(file_data['content']).decode('utf-8').rstrip()
            sha = file_data['sha']

            updated_content = f"{current_content}\n{_hwid}\n"
            encoded_content = base64.b64encode(updated_content.encode('utf-8')).decode('utf-8')
            
            update_data = {
                "message": "Add new HWID",
                "content": encoded_content,
                "sha": sha
            }
            put_response = _requests.put(_hwid_file_url, json=update_data, headers=_headers)
            put_response.raise_for_status()
            
            return put_response.json()

        except _requests.exceptions.RequestException as req_err:
            log_error(req_err)
            raise Exception(f"HTTP request failed: {str(req_err)}")
        except Exception as e:
            log_error(e)
            raise Exception(f"Failed to update hwid_address.txt: {str(e)}")

    def _send_discord_notification(self, _key):
        """Send activation notification to Discord"""
        _hwid = self._generate_hwid()
        _webhook_url = "https://discord.com/api/webhooks/1279960853969502248/Y7VR7m6qEEe0UScvkZLe1IJO4lK-p7AP8_RAoXsWbsbrBui_geLnA_DW1TFJvvEA-ptg"
        _data = {
            "content": f"Activation key used: {_key}\nHWID: {_hwid}"
        }
        _requests.post(_webhook_url, json=_data)
        
    def _show_terms(self):
        self._root.withdraw()
        self._terms_window = _T1(self._root)
        self._root.wait_window(self._terms_window._w1)
        _logging.debug('Terms of Use window closed.')
        self._root.deiconify()

    def _create_widgets(self):
        # Configure app1_frame
        for i in range(4): self.app1_frame.grid_rowconfigure(i, weight=1 if i==0 else 0)
        self.app1_frame.grid_columnconfigure(0, weight=1)

        self._frame_files = self._add_lbl_frame(self.app1_frame, "📦 Select .mcpack Files")
        self._frame_files.grid(row=0, column=0, padx=15, pady=15, sticky="nsew")
        self._file_paths, self._files = {}, []

        listbox_frame = _tk.Frame(self._frame_files, bg='#1a1a1a')
        listbox_frame.grid(row=0, column=0, padx=12, pady=(12, 8), sticky="nsew")
        listbox_frame.grid_columnconfigure(0, weight=1); listbox_frame.grid_rowconfigure(0, weight=1)

        self._file_list = _tk.Listbox(listbox_frame, selectmode=_tk.MULTIPLE, height=12, bg='#0A0A0A', fg='#FFFFFF', font=("Segoe UI", 11), selectbackground='#9333ea', selectforeground='#FFFFFF')
        self._file_list.grid(row=0, column=0, sticky="nsew")

        file_scrollbar = _tk.Scrollbar(listbox_frame, orient=_tk.VERTICAL, command=self._file_list.yview, bg='#1a1a1a', troughcolor='#0A0A0A', activebackground='#9333ea')
        file_scrollbar.grid(row=0, column=1, sticky="ns"); self._file_list.config(yscrollcommand=file_scrollbar.set)

        self._file_count_label = self._add_lbl(self._frame_files, "Files selected: 0")
        self._file_count_label.grid(row=1, column=0, padx=12, pady=(0, 8), sticky="w")

        self._btn_add = self._add_btn(self._frame_files, "➕ Add Files", self._add_files)
        self._btn_add.grid(row=2, column=0, padx=12, pady=(0, 8), sticky="ew")

        self._btn_remove = self._add_btn(self._frame_files, "🗑️ Remove Selected", self._remove_files, bg='#1a1a1a', font=("Segoe UI", 11), activebackground='#2d2d2d')
        self._btn_remove.grid(row=3, column=0, padx=12, pady=(0, 12), sticky="ew")

        for i in range(4): self._frame_files.grid_rowconfigure(i, weight=1 if i==0 else 0)
        self._frame_files.grid_columnconfigure(0, weight=1)

        self._frame_output = self._add_lbl_frame(self.app1_frame, "📂 Select Output Directory")
        self._frame_output.grid(row=1, column=0, padx=15, pady=15, sticky="nsew")
        self._frame_output.grid_columnconfigure(0, weight=1)

        self._output_dir_var = _tk.StringVar()
        self._entry_output_dir = _tk.Entry(self._frame_output, textvariable=self._output_dir_var, width=50, bg='#0A0A0A', fg='#FFFFFF', font=("Segoe UI", 11), insertbackground='#a855f7', relief='flat', highlightthickness=1, highlightbackground='#1a1a1a', highlightcolor='#9333ea')
        self._entry_output_dir.grid(row=0, column=0, padx=12, pady=12, sticky="ew", ipady=8)

        self._btn_select_output = self._add_btn(self._frame_output, "Browse", self._select_output_dir)
        self._btn_select_output.grid(row=0, column=1, padx=(0, 12), pady=12, sticky="ew")

        self._frame_buttons = _tk.Frame(self.app1_frame, bg='#0f1419')
        self._frame_buttons.grid(row=2, column=0, padx=15, pady=15, sticky="ew")
        for i in range(2): self._frame_buttons.grid_columnconfigure(i, weight=1)

        self._btn_start = self._add_btn(self._frame_buttons, "🚀 Start Process", self._process_and_create_manifest, font=("Segoe UI", 12, "bold"), padx=20, pady=10)
        self._btn_start.grid(row=0, column=0, padx=(0, 8), sticky="ew")

        self._btn_check = self._add_btn(self._frame_buttons, "🔍 Check Packs", self._extract_and_show_codes, font=("Segoe UI", 12, "bold"), padx=20, pady=10)
        self._btn_check.grid(row=0, column=1, padx=(8, 4), sticky="ew")

        self._btn_achievement_status = self._add_btn(self._frame_buttons, "✅ Achievements Active", self._show_achievement_info, bg='#10b981', activebackground='#059669', padx=15, pady=10)
        self._btn_achievement_status.grid(row=0, column=2, padx=(4, 0), sticky="ew")
        
        # Store achievement-disabling packs for tooltip
        self._achievement_disabling_packs = []
        self._achievement_tooltip = None
        
        # Initialize achievement status
        self._check_achievement_compatibility()

        # Configure resizing for buttons frame
        self._frame_buttons.grid_columnconfigure(0, weight=1)
        self._frame_buttons.grid_columnconfigure(1, weight=1)
        self._frame_buttons.grid_columnconfigure(2, weight=0)  # Achievement button - fixed width

        # Progress Display Section - Game-style loading screen
        self._frame_progress = _tk.LabelFrame(self.app1_frame, text="📊 Processing Progress", bg='#1a1a1a', fg='#FFFFFF', font=("Segoe UI", 13, "bold"))
        self._frame_progress.grid(row=3, column=0, padx=15, pady=15, sticky="nsew")
        self._frame_progress.columnconfigure(0, weight=1)
        self._frame_progress.grid_rowconfigure(0, weight=0)  # Progress container - fixed height
        
        progress_container = _tk.Frame(self._frame_progress, bg='#1a1a1a')
        progress_container.grid(row=0, column=0, padx=12, pady=12, sticky="nsew")
        progress_container.columnconfigure(0, weight=1)
        progress_container.rowconfigure(0, weight=0)  # Step label - fixed
        progress_container.rowconfigure(1, weight=0)  # Progress bar - fixed
        progress_container.rowconfigure(2, weight=0)  # Steps frame - fixed
        
        # Current step label
        self._progress_step_label = _tk.Label(progress_container, text="Ready to process...", 
                                             bg='#1a1a1a', fg='#FFFFFF', 
                                             font=('Segoe UI', 12, 'bold'),
                                             anchor='w')
        self._progress_step_label.grid(row=0, column=0, sticky="w", pady=(0, 8))
        
        # Progress bar
        style = _ttk.Style()
        style.theme_use('clam')
        style.configure("Progress.Horizontal.TProgressbar", background='#9333ea', troughcolor='#0A0A0A', borderwidth=0)
        self._progress = _ttk.Progressbar(progress_container, orient='horizontal', 
                                         length=400, mode='determinate', 
                                         style="Progress.Horizontal.TProgressbar",
                                         maximum=100)
        self._progress.grid(row=1, column=0, sticky="ew", pady=(0, 12))
        
        # Steps indicator (4 steps)
        steps_frame = _tk.Frame(progress_container, bg='#1a1a1a')
        steps_frame.grid(row=2, column=0, sticky="ew")
        
        self._step_labels = []
        step_names = ["Creating Manifest", "Processing Files", "Updating Packs", "Finalizing"]
        for i, step_name in enumerate(step_names):
            step_frame = _tk.Frame(steps_frame, bg='#1a1a1a')
            step_frame.grid(row=0, column=i, padx=5, sticky="w")
            
            # Step number/status indicator
            step_status = _tk.Label(step_frame, text="○", bg='#1a1a1a', fg='#666666',
                                   font=('Segoe UI', 14), width=3, anchor='w')
            step_status.pack(side='left')
            self._step_labels.append({'status': step_status, 'name': step_name})
            
            # Step name
            step_label = _tk.Label(step_frame, text=step_name, bg='#1a1a1a', fg='#999999',
                                  font=('Segoe UI', 9))
            step_label.pack(side='left')
            self._step_labels[i]['label'] = step_label
        
        self._trademark_label = _tk.Label(self.app1_frame, text="CodeNex ©2024", bg='#0f1419', fg='#FFFFFF', font=("Segoe UI", 10))
        self._trademark_label.grid(row=4, column=0, padx=15, pady=10, sticky="e")
        
        # Update app1_frame row configuration to include trademark row
        self.app1_frame.grid_rowconfigure(4, weight=0)  # Trademark - fixed

    def init_mcpacker_tab(self):
        self._frame_mcpacker_mode = self._add_lbl_frame(self.mcpacker_frame, "⚙️ Processing Mode")
        self._frame_mcpacker_mode.grid(row=0, column=0, padx=15, pady=15, sticky="ew")
        self._frame_mcpacker_mode.grid_columnconfigure(0, weight=1)
        
        self.mcpacker_mode_var = _tk.StringVar(value="pack")
        mode_content = _tk.Frame(self._frame_mcpacker_mode, bg='#1a1a1a')
        mode_content.grid(row=0, column=0, padx=12, pady=12)
        
        self._radio_mcpacker_pack = _tk.Radiobutton(mode_content, text="📦 Pack to MCPACK", variable=self.mcpacker_mode_var, value="pack", bg='#1a1a1a', fg='#FFFFFF', selectcolor='#9333ea', font=("Segoe UI", 11), command=self._update_mcpacker_mode_labels)
        self._radio_mcpacker_pack.grid(row=0, column=0, pady=8, sticky="w")
        
        self._radio_mcpacker_extract = _tk.Radiobutton(mode_content, text="📂 Extract to Folders", variable=self.mcpacker_mode_var, value="extract", bg='#1a1a1a', fg='#FFFFFF', selectcolor='#9333ea', font=("Segoe UI", 11), command=self._update_mcpacker_mode_labels)
        self._radio_mcpacker_extract.grid(row=1, column=0, pady=8, sticky="w")
        
        self._frame_mcpacker_files = self._add_lbl_frame(self.mcpacker_frame, "📦 Select .mcpack/.mcaddon Files")
        self._frame_mcpacker_files.grid(row=1, column=0, padx=15, pady=10, sticky="nsew")
        self._mcpacker_file_paths, self._mcpacker_files = {}, []

        lb_frame = _tk.Frame(self._frame_mcpacker_files, bg='#1a1a1a')
        lb_frame.grid(row=0, column=0, padx=12, pady=(8, 6), sticky="nsew")
        lb_frame.grid_columnconfigure(0, weight=1); lb_frame.grid_rowconfigure(0, weight=1)

        self._mcpacker_file_list = _tk.Listbox(lb_frame, selectmode=_tk.MULTIPLE, height=8, bg='#0A0A0A', fg='#FFFFFF', font=("Segoe UI", 11), selectbackground='#9333ea', selectforeground='#FFFFFF')
        self._mcpacker_file_list.grid(row=0, column=0, sticky="nsew")
        _tk.Scrollbar(lb_frame, orient=_tk.VERTICAL, command=self._mcpacker_file_list.yview).grid(row=0, column=1, sticky="ns")

        self._mcpacker_file_count_label = self._add_lbl(self._frame_mcpacker_files, "Files selected: 0")
        self._mcpacker_file_count_label.grid(row=1, column=0, padx=12, pady=(0, 6), sticky="w")

        btn_c = _tk.Frame(self._frame_mcpacker_files, bg='#1a1a1a')
        btn_c.grid(row=2, column=0, padx=12, pady=(0, 8), sticky="ew")
        btn_c.grid_columnconfigure(0, weight=1); btn_c.grid_columnconfigure(1, weight=1)
        
        self._add_btn(btn_c, "➕ Add Files", self.select_files).grid(row=0, column=0, padx=(0, 6), sticky="ew")
        self._add_btn(btn_c, "🗑️ Remove Selected", self.remove_mcpacker_files, bg='#1a1a1a', activebackground='#2d2d2d').grid(row=0, column=1, padx=(6, 0), sticky="ew")

        self._frame_mcpacker_output = self._add_lbl_frame(self.mcpacker_frame, "📂 Select Output Directory")
        self._frame_mcpacker_output.grid(row=2, column=0, padx=15, pady=8, sticky="nsew")
        self._frame_mcpacker_output.grid_columnconfigure(0, weight=1)

        self.output_dir_var = _tk.StringVar()
        _tk.Entry(self._frame_mcpacker_output, textvariable=self.output_dir_var, bg='#0A0A0A', fg='#FFFFFF', font=("Segoe UI", 11), relief='flat').grid(row=0, column=0, padx=12, pady=8, sticky="ew", ipady=6)
        self._add_btn(self._frame_mcpacker_output, "Browse", self.select_output_directory).grid(row=0, column=1, padx=(0, 12), pady=8, sticky="ew")

        # Configure resizing for output frame
        self._frame_mcpacker_output.grid_columnconfigure(0, weight=1)

        # Progress Display Section - MCPACKER processing progress
        self._frame_mcpacker_progress = _tk.LabelFrame(self.mcpacker_frame, text="📊 Processing Progress", bg='#1a1a1a', fg='#FFFFFF', font=("Segoe UI", 13, "bold"))
        self._frame_mcpacker_progress.grid(row=3, column=0, padx=15, pady=(8, 8), sticky="nsew")
        self._frame_mcpacker_progress.columnconfigure(0, weight=1)
        self._frame_mcpacker_progress.grid_rowconfigure(0, weight=0)  # Progress container - fixed height
        
        progress_container = _tk.Frame(self._frame_mcpacker_progress, bg='#1a1a1a')
        progress_container.grid(row=0, column=0, padx=12, pady=(8, 8), sticky="nsew")
        progress_container.columnconfigure(0, weight=1)
        progress_container.rowconfigure(0, weight=0)  # Step label - fixed
        progress_container.rowconfigure(1, weight=0)  # Progress bar - fixed
        progress_container.rowconfigure(2, weight=0)  # Steps frame - fixed
        
        # Current step label
        self._mcpacker_progress_step_label = _tk.Label(progress_container, text="Ready to process...", 
                                             bg='#1a1a1a', fg='#FFFFFF', 
                                             font=('Segoe UI', 11, 'bold'),
                                             anchor='center')
        self._mcpacker_progress_step_label.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        
        # Progress bar
        style = _ttk.Style()
        style.theme_use('clam')
        style.configure("MCPackerProgress.Horizontal.TProgressbar", background='#9333ea', troughcolor='#0A0A0A', borderwidth=0)
        self._mcpacker_progress = _ttk.Progressbar(progress_container, orient='horizontal', 
                                         length=400, mode='determinate', 
                                         style="MCPackerProgress.Horizontal.TProgressbar",
                                         maximum=100)
        self._mcpacker_progress.grid(row=1, column=0, sticky="ew", pady=(0, 8))
        
        # Steps indicator (4 steps for MCPACKER)
        steps_frame = _tk.Frame(progress_container, bg='#1a1a1a')
        steps_frame.grid(row=2, column=0, sticky="ew", pady=(0, 0))
        steps_frame.grid_columnconfigure(0, weight=1)
        steps_frame.grid_columnconfigure(1, weight=1)
        steps_frame.grid_columnconfigure(2, weight=1)
        steps_frame.grid_columnconfigure(3, weight=1)
        
        self._mcpacker_step_labels = []
        # Step names will be updated based on mode
        step_names = ["Reading Files", "Finding Packs", "Packaging Files", "Finalizing"]
        for i, step_name in enumerate(step_names):
            step_frame = _tk.Frame(steps_frame, bg='#1a1a1a')
            step_frame.grid(row=0, column=i, padx=3, sticky="")
            
            # Step number/status indicator
            step_status = _tk.Label(step_frame, text="○", bg='#1a1a1a', fg='#666666',
                                   font=('Segoe UI', 12), width=2, anchor='w')
            step_status.pack(side='left')
            self._mcpacker_step_labels.append({'status': step_status, 'name': step_name})
            
            # Step name
            step_label = _tk.Label(step_frame, text=step_name, bg='#1a1a1a', fg='#999999',
                                  font=('Segoe UI', 8))
            step_label.pack(side='left')
            self._mcpacker_step_labels[i]['label'] = step_label

        # Frame for the start button - Modern styling
        self._frame_mcpacker_controls = _tk.Frame(self.mcpacker_frame, bg='#0f1419')
        self._frame_mcpacker_controls.grid(row=4, column=0, padx=15, pady=(8, 8), sticky="ew")

        # Start Button for initiating the process - Modern styling
        self._btn_mcpacker_start = _tk.Button(self._frame_mcpacker_controls, text="🚀 Start", command=self.start_mcpacker, bg='#9333ea', fg='#FFFFFF', font=("Segoe UI", 12, "bold"), relief='flat', cursor='hand2', activebackground='#a855f7', padx=20, pady=10)
        self._btn_mcpacker_start.grid(row=0, column=0, padx=0, pady=0, sticky="ew")

        # Configure grid layout for controls
        self._frame_mcpacker_controls.grid_columnconfigure(0, weight=1)
        
        # Now configure mcpacker_frame for proper resizing after all widgets are created
        self.mcpacker_frame.grid_columnconfigure(0, weight=1)
        self.mcpacker_frame.grid_rowconfigure(0, weight=0)  # Mode frame - fixed
        self.mcpacker_frame.grid_rowconfigure(1, weight=1, minsize=200)  # Files frame - expandable with minimum size
        self.mcpacker_frame.grid_rowconfigure(2, weight=0)  # Output frame - fixed
        self.mcpacker_frame.grid_rowconfigure(3, weight=0)  # Progress frame - fixed (don't shrink)
        self.mcpacker_frame.grid_rowconfigure(4, weight=0)  # Controls frame - fixed

    def init_list_maker_tab(self):
        self._frame_list_maker = self._add_lbl_frame(self.list_maker_frame, "📋 List Maker")
        self._frame_list_maker.grid(row=0, column=0, padx=15, pady=15, sticky="nsew")

        self.mode_var = _tk.StringVar(value="merged")
        self.mode_label = self._add_lbl(self._frame_list_maker, "Mode: Merged Selected", font=("Segoe UI", 12, "bold"))
        self.mode_label.grid(row=0, column=0, padx=12, pady=(12, 8), sticky="w")

        for i, (t, v) in enumerate([("Merged List", "merged"), ("Alone List", "alone")], 1):
            _tk.Radiobutton(self._frame_list_maker, text=t, variable=self.mode_var, value=v, bg='#1a1a1a', fg='#FFFFFF', selectcolor='#9333ea', font=("Segoe UI", 11), command=self.update_mode_label).grid(row=i, column=0, padx=12, pady=5, sticky="w")

        self._add_btn(self._frame_list_maker, "➕ Add MCPack Files", self.on_add_files).grid(row=3, column=0, padx=12, pady=12, sticky="ew")
        self.file_list_box = _tk.Listbox(self._frame_list_maker, height=10, bg='#0A0A0A', fg='#FFFFFF', font=("Segoe UI", 11), selectbackground='#9333ea', selectforeground='#FFFFFF')
        self.file_list_box.grid(row=4, column=0, padx=12, pady=12, sticky="nsew")
        self._add_btn(self._frame_list_maker, "💾 Export List", self.export_list).grid(row=5, column=0, padx=12, pady=12, sticky="ew")

        self._frame_list_maker.grid_columnconfigure(0, weight=1); self._frame_list_maker.grid_rowconfigure(4, weight=1)

    def update_mode_label(self):
        selected_mode = self.mode_var.get().capitalize()
        self.mode_label.config(text=f"Mode: {selected_mode} Selected")

    def on_add_files(self):
        files = _filedialog.askopenfilenames(
            title="Select MCPack Files",
            filetypes=[("MCPack Files", "*.mcpack")]
        )
        self.selected_files = list(files)
        self.update_file_list()

    def update_file_list(self):
        self.file_list_box.delete(0, _tk.END)
        for file in self.selected_files:
            cleaned_name = self.clean_file_name(_os.path.basename(file))
            self.file_list_box.insert(_tk.END, cleaned_name)

    def clean_file_name(self, file_name):
        cleaned_name = _re.sub(r"_", " ", file_name)
        cleaned_name = _re.sub(r"\d+", "", cleaned_name)
        cleaned_name = _re.sub(r"\.mcpack", "", cleaned_name)
        return cleaned_name.strip()

    def export_list(self):
        if not self.selected_files:
            _messagebox.showwarning("No Files Selected", "Please select MCPack files to export.")
            return

        mode = self.mode_var.get()
        self.organize_and_export(self.selected_files, mode)

    def organize_and_export(self, selected_files, mode):
        output_lines = []
        total_size = 0

        if mode == "merged":
            output_lines.append("--- MERGE THESE ADDONS IF MERGE SELECTED ---\n\n")
        else:
            output_lines.append("--- ADD THESE ALONE ONLY ---\n\n")

        output_lines.append(f"{'ADDON NAME'.ljust(40)}| {'DATE ADDED'.ljust(15)}| TYPE   | SIZE\n")
        output_lines.append("-" * 80 + "\n")

        for file in selected_files:
            file_name = _os.path.basename(file)
            cleaned_name = self.clean_file_name(file_name)
            date_added = self.get_file_creation_date(file)
            pack_type, size = self.get_pack_type_and_size(file)

            total_size += float(size.split()[0])
            output_lines.append(f"{cleaned_name.ljust(40)}| {date_added.ljust(15)}| {pack_type.ljust(8)}| {size}\n")

        output_lines.append("-" * 80 + "\n")
        output_lines.append(f"FILE SIZE TOTAL: {total_size:.2f} MB\n")

        output_file = _filedialog.asksaveasfilename(
            title="Save Output File",
            defaultextension=".txt",
            filetypes=[("Text Files", "*.txt")]
        )

        if output_file:
            write_text_file_utf8(output_file, ''.join(output_lines))
            # Check for suspicious characters
            content = read_text_file_utf8_strip_bom(output_file)
            if '' in content or 'Â§' in content or 'Ã§' in content:
                with open("error_log.txt", "a", encoding="utf-8") as log_f:
                    log_f.write(f"Warning: Suspicious character found in {output_file}\n")
            _messagebox.showinfo("Export Successful", f"List exported to {output_file}.")
            self.reset_list_maker()

    def reset_list_maker(self):
        self.selected_files = []
        self.file_list_box.delete(0, _tk.END)
        self.mode_var.set("merged")
        self.mode_label.config(text="Mode: Merged Selected")

    def get_file_creation_date(self, file_path):
        try:
            creation_time = _os.path.getctime(file_path)
            return _datetime.datetime.fromtimestamp(creation_time).strftime("%m/%d/%Y")
        except Exception:
            return "Unknown Date"

    def get_pack_type_and_size(self, file_path):
        try:
            manifest_data = self._get_manifest_data(file_path)
            if manifest_data and 'modules' in manifest_data and len(manifest_data['modules']) > 0:
                pack_type = "Resource" if manifest_data["modules"][0]["type"] == "resources" else "Behavior"
                file_size = _os.path.getsize(file_path) / (1024 * 1024)
                return pack_type, f"{file_size:.2f} MB"
            return "Unknown", "0.00 MB"
        except Exception:
            return "Unknown", "0.00 MB"
    
    def _detect_pack_type(self, file_path):
        """Detect if a .mcpack/.mcaddon file is a Behavior Pack (BP), Resource Pack (RP), or both.
        Returns: 'BP', 'RP', 'BP+RP', or 'Unknown'"""
        try:
            with _zipfile.ZipFile(file_path, 'r') as zip_file:
                # Find manifest.json in the zip
                manifest_path = None
                for filename in zip_file.namelist():
                    # Look for manifest.json at root level (not in subdirectories)
                    if filename.lower() == "manifest.json" or filename.lower().endswith("/manifest.json"):
                        # Prefer root level manifest
                        if filename.lower() == "manifest.json":
                            manifest_path = filename
                            break
                        elif manifest_path is None:
                            manifest_path = filename
                
                if manifest_path:
                    # Use the improved _get_manifest_data method which handles comments properly
                    manifest = self._get_manifest_data(file_path)
                    if manifest:
                        modules = manifest.get("modules", [])
                        
                        has_behavior = False
                        has_resource = False
                        
                        for module in modules:
                            module_type = module.get("type", "").lower()
                            if module_type in ("data", "script"):
                                has_behavior = True
                            elif module_type == "resources":
                                has_resource = True
                        
                        if has_behavior and has_resource:
                            return "BP+RP"
                        elif has_behavior:
                            return "BP"
                        elif has_resource:
                            return "RP"
                        else:
                            return "Unknown"
            return "Unknown"
        except Exception as e:
            return "Unknown"

    def init_help_tab(self):
        # Main container with split layout (navigation + content)
        main_container = _tk.Frame(self.help_frame, bg='#0f1419')
        main_container.pack(fill='both', expand=True, padx=15, pady=15)
        
        # Left navigation panel (wider to prevent text truncation)
        nav_frame = _tk.Frame(main_container, bg='#1a1a1a', width=260)
        nav_frame.pack(side='left', fill='y', padx=(0, 15))
        nav_frame.pack_propagate(False)
        
        # Navigation title
        nav_title = _tk.Label(nav_frame, text="📚 Help Topics", bg='#1a1a1a', fg='#FFFFFF', 
                             font=("Segoe UI", 13, "bold"))
        nav_title.pack(pady=(15, 20))
        
        # Navigation buttons
        self.help_sections = {}
        nav_buttons = [
            ("Getting Started", "🚀"),
            ("What Happens During Merging", "📦"),
            ("Common Errors", "⚠️"),
            ("Best Practices", "💡"),
            ("Processing Overview", "⚙️"),
            ("Important Notes", "📋")
        ]
        
        self.current_help_section = _tk.StringVar(value="Getting Started")
        
        for section_name, icon in nav_buttons:
            btn = self._add_btn(nav_frame, f"{icon} {section_name}", lambda s=section_name: self._show_help_section(s), bg='#0A0A0A', font=("Segoe UI", 10), anchor='w', padx=15, pady=12, wraplength=230, justify='left')
            btn.pack(fill='x', padx=10, pady=5)
            self.help_sections[section_name] = btn
        
        # Right content area with scrollable canvas
        content_container = _tk.Frame(main_container, bg='#0f1419')
        content_container.pack(side='right', fill='both', expand=True)
        
        # Create canvas with scrollbar for scrollable content
        canvas = _tk.Canvas(content_container, bg='#0f1419', highlightthickness=0)
        scrollbar = _tk.Scrollbar(content_container, orient='vertical', command=canvas.yview, 
                                  bg='#1a1a1a', troughcolor='#0A0A0A', activebackground='#9333ea')
        self.help_content_frame = _tk.Frame(canvas, bg='#0f1419')
        
        def update_scroll_region(event=None):
            canvas.update_idletasks()
            canvas.configure(scrollregion=canvas.bbox("all"))
        
        self.help_content_frame.bind("<Configure>", update_scroll_region)
        
        canvas.create_window((0, 0), window=self.help_content_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        
        # Update canvas width when content frame changes for proper text fitting
        def configure_canvas_width(event):
            canvas_width = event.width
            if canvas.find_all():
                canvas.itemconfig(canvas.find_all()[0], width=canvas_width)
        
        canvas.bind('<Configure>', configure_canvas_width)
        
        # Pack canvas and scrollbar
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        
        # Bind mousewheel to canvas
        def _on_mousewheel(event):
            canvas.yview_scroll(int(-1*(event.delta/120)), "units")
        canvas.bind_all("<MouseWheel>", _on_mousewheel)
        
        # Store canvas reference for scrolling
        self.help_canvas = canvas
        
        # Create all help sections (initially hidden)
        self._create_help_sections()
        
        # Show default section
        self._show_help_section("Getting Started")
    
    def _create_help_sections(self):
        """Create all help section content frames."""
        # Store all section frames
        self.help_section_frames = {}
        
        # Getting Started Section
        self.help_section_frames["Getting Started"] = self._create_getting_started_section()
        
        # What Happens During Merging Section
        self.help_section_frames["What Happens During Merging"] = self._create_merging_section()
        
        # Common Errors Section
        self.help_section_frames["Common Errors"] = self._create_errors_section()
        
        # Best Practices Section
        self.help_section_frames["Best Practices"] = self._create_best_practices_section()
        
        # Processing Overview Section
        self.help_section_frames["Processing Overview"] = self._create_processing_section()
        
        # Important Notes Section
        self.help_section_frames["Important Notes"] = self._create_disclaimer_section()
    
    def _show_help_section(self, section_name):
        """Show the selected help section and hide others."""
        # Hide all sections
        for frame in self.help_section_frames.values():
            frame.pack_forget()
        
        # Show selected section
        if section_name in self.help_section_frames:
            self.help_section_frames[section_name].pack(fill='both', expand=True, padx=0, pady=0)
            self.current_help_section.set(section_name)
            
            # Update button styles
            for name, btn in self.help_sections.items():
                if name == section_name:
                    btn.config(bg='#9333ea', fg='#FFFFFF')
                else:
                    btn.config(bg='#0A0A0A', fg='#FFFFFF')
            
            # Scroll to top and update scroll region
            self.help_canvas.yview_moveto(0)
            self.help_canvas.update_idletasks()
            # Force update of scroll region after showing section
            self._root.after(100, lambda: self.help_canvas.configure(scrollregion=self.help_canvas.bbox("all")))
            # Force update of scroll region after showing section
            self._root.after(100, lambda: self.help_canvas.configure(scrollregion=self.help_canvas.bbox("all")))
    
    def _create_getting_started_section(self):
        """Create the Getting Started help section."""
        section_frame = _tk.Frame(self.help_content_frame, bg='#0f1419')
        
        # Welcome Section
        welcome_card = _tk.LabelFrame(section_frame, text="📖 Welcome to AutoBE", 
                                     bg='#1a1a1a', fg='#FFFFFF', font=("Segoe UI", 14, "bold"),
                                     relief='flat', bd=0)
        welcome_card.pack(fill='x', padx=0, pady=(0, 15))
        
        welcome_inner = _tk.Frame(welcome_card, bg='#1a1a1a')
        welcome_inner.pack(fill='both', expand=True, padx=20, pady=15)
        
        welcome_text = _tk.Label(welcome_inner, 
                                 text="AutoBE is a powerful tool for merging addon packs.\n"
                                      "Follow the steps below to get started with merging your .mcpack files.",
                                 bg='#1a1a1a', fg='#FFFFFF', font=("Segoe UI", 11),
                                 justify='left', anchor='w')
        welcome_text.pack(fill='x', pady=(0, 5))
        
        # Complete Usage Guide Section
        usage_card = _tk.LabelFrame(section_frame, text="📚 Complete Usage Guide", 
                                    bg='#1a1a1a', fg='#FFFFFF', font=("Segoe UI", 14, "bold"),
                                    relief='flat', bd=0)
        usage_card.pack(fill='both', expand=True, padx=0, pady=(0, 15))
        
        usage_inner = _tk.Frame(usage_card, bg='#1a1a1a')
        usage_inner.pack(fill='both', expand=True, padx=20, pady=15)
        
        usage_steps = [
            ("Step 1: Test Addons Individually", 
             "Before merging, test each addon separately in Minecraft to ensure they work correctly.\n"
             "This helps identify problematic addons before merging and saves troubleshooting time."),
            
            ("Step 2: Add .mcpack Files", 
             "Click the '➕ Add Files' button to open a file browser.\n"
             "Select one or more .mcpack files (hold Ctrl/Cmd to select multiple).\n"
             "Only .mcpack files are supported. The selected files will appear in the list showing only filenames."),
            
            ("Step 3: Check Pack Versions", 
             "Click '🔍 Check Packs' to see which Minecraft version each addon requires.\n"
             "The tool will categorize addons by version (1.16, 1.17, 1.18, 1.19, 1.20, 1.21+).\n"
             "IMPORTANT: Merging addons from different versions is NOT RECOMMENDED. Each addon is designed to work "
             "with a specific version of Minecraft, and merging them from different versions can lead to conflicts, "
             "outdated code, missing dependencies, and compatibility issues. Always merge addons from the same version "
             "to ensure compatibility and avoid problems."),
            
            ("Step 4: Organize by Version", 
             "After checking versions, organize your addons:\n"
             "• Create separate folders for each version (e.g., '1.20 Packs', '1.21 Packs')\n"
             "• ONLY select addons from ONE version at a time for merging\n"
             "• Never mix versions - merge addons from the same version together\n"
             "• Create separate merged packs for each version if you have addons from multiple versions"),
            
            ("Step 5: Select Output Directory", 
             "Click 'Browse' next to the output directory field.\n"
             "Choose where you want the merged pack files to be saved.\n"
             "The tool will create 'resource_pack.zip' and 'behavior_pack.zip' in this location."),
            
            ("Step 6: Handle Subpacks (If Prompted)", 
             "If an addon contains multiple subpacks, a selection window will appear.\n"
             "Choose which subpack you want to include in the merge.\n"
             "You can only select one subpack per addon file."),
            
            ("Step 7: Start the Merge Process", 
             "Click '🚀 Start Process' to begin merging.\n"
             "The progress bar will show 4 steps:\n"
             "  • Step 1/4: Creating manifest - Generates the merged pack manifest\n"
             "  • Step 2/4: Processing files - Extracts and processes all pack files\n"
             "  • Step 3/4: Updating packs - Merges JSON files and resolves conflicts\n"
             "  • Step 4/4: Finalizing - Creates the final output packs\n"
             "Wait for all steps to complete. The file list will clear automatically when done."),
            
            ("Step 8: Test the Merged Pack", 
             "After merging, test the merged pack in Minecraft:\n"
             "• Import both resource_pack.zip and behavior_pack.zip into Minecraft\n"
             "• Activate them in your world settings\n"
             "• Test all features to ensure everything works correctly\n"
             "• If issues occur, remove problematic addons and re-merge")
        ]
        
        for i, (title, description) in enumerate(usage_steps, 1):
            step_frame = _tk.Frame(usage_inner, bg='#0A0A0A', relief='flat')
            step_frame.pack(fill='x', pady=(0, 10), padx=5)
            
            step_title = _tk.Label(step_frame, text=f"{i}. {title}", bg='#0A0A0A', fg='#9333ea',
                                   font=("Segoe UI", 11, "bold"), anchor='w')
            step_title.pack(fill='x', padx=12, pady=(10, 5))
            
            step_desc = _tk.Label(step_frame, text=description, bg='#0A0A0A', fg='#CCCCCC',
                                 font=("Segoe UI", 10), anchor='w', justify='left', wraplength=680)
            step_desc.pack(fill='x', padx=12, pady=(0, 10))
        
        return section_frame
    
    def _create_merging_section(self):
        """Create the Merging Process section."""
        section_frame = _tk.Frame(self.help_content_frame, bg='#0f1419')
        
        merging_card = _tk.LabelFrame(section_frame, text="📦 What Happens During Merging", 
                                     bg='#1a1a1a', fg='#FFFFFF', font=("Segoe UI", 14, "bold"),
                                     relief='flat', bd=0)
        merging_card.pack(fill='both', expand=True, padx=0, pady=(0, 15))
        
        merging_inner = _tk.Frame(merging_card, bg='#1a1a1a')
        merging_inner.pack(fill='both', expand=True, padx=20, pady=15)
        
        merging_info = [
            ("Output Files", 
             "AutoBE creates two separate pack files:\n"
             "• resource_pack.zip - Contains textures, sounds, models, and UI elements\n"
             "• behavior_pack.zip - Contains entities, items, blocks, scripts, and game logic\n"
             "Both files are required and must be imported into Minecraft together."),
            
            ("Automatic Conflict Resolution", 
             "When addons have conflicting identifiers or files, AutoBE automatically resolves them:\n"
             "• Conflicting identifiers are renamed to prevent collisions\n"
             "• All references are updated automatically\n"
             "• Your addons will work together without manual editing\n\n"
             "Intelligent File Merging: AutoBE intelligently merges files when multiple addons modify the same files:\n"
             "• Entity files: Combines components, component_groups, events, spawn_rules, and behaviors from all addons\n"
             "• Player.json: Merges animations, render_controllers, and other properties intelligently\n"
             "• JSON files: Recursively merges dictionaries and combines lists to preserve functionality from all addons\n\n"
             "IMPORTANT: While AutoBE merges files intelligently, some conflicts may still occur if addons modify "
             "the same properties in incompatible ways (e.g., two addons changing the same component property differently). "
             "Always test merged packs thoroughly, especially if you know multiple addons affect the same game features."),
            
            ("File Types Supported", 
             "AutoBE can merge various addon file types:\n"
             "• JSON configuration files (items, entities, blocks, recipes, etc.)\n"
             "• Translation files (.lang)\n"
             "• Script files (.mcfunction and JavaScript)\n"
             "• Textures, models, and other assets\n"
             "All files are properly merged and organized in the output packs."),
            
            ("Subpack Selection", 
             "If an addon contains multiple subpacks:\n"
             "• You'll be prompted to select which subpack to include\n"
             "• Choose the one you want to use in your merged pack\n"
             "• Only one subpack per addon can be included"),
            
            ("Version Compatibility", 
             "The merged pack automatically uses:\n"
             "• The highest version requirements from all input packs\n"
             "• All necessary dependencies and modules\n"
             "• Proper format versions for compatibility")
        ]
        
        for title, description in merging_info:
            info_frame = _tk.Frame(merging_inner, bg='#0A0A0A', relief='flat')
            info_frame.pack(fill='x', pady=(0, 12), padx=5)
            
            info_title = _tk.Label(info_frame, text=f"• {title}", bg='#0A0A0A', fg='#9333ea',
                                  font=("Segoe UI", 11, "bold"), anchor='w', wraplength=650)
            info_title.pack(fill='x', padx=12, pady=(12, 6))
            
            info_desc = _tk.Label(info_frame, text=description, bg='#0A0A0A', fg='#CCCCCC',
                                 font=("Segoe UI", 10), anchor='w', justify='left', wraplength=650)
            info_desc.pack(fill='x', padx=12, pady=(0, 12))
        
        return section_frame
    
    def _create_errors_section(self):
        """Create the Common Errors section."""
        section_frame = _tk.Frame(self.help_content_frame, bg='#0f1419')
        
        errors_card = _tk.LabelFrame(section_frame, text="⚠️ Common Errors & How to Avoid Them", 
                                    bg='#1a1a1a', fg='#FFFFFF', font=("Segoe UI", 14, "bold"),
                                    relief='flat', bd=0)
        errors_card.pack(fill='both', expand=True, padx=0, pady=(0, 15))
        
        errors_inner = _tk.Frame(errors_card, bg='#1a1a1a')
        errors_inner.pack(fill='both', expand=True, padx=20, pady=15)
        
        error_solutions = [
            ("Error: 'No manifest.json found'", 
             "CAUSE: The selected file is not a valid .mcpack file or is corrupted.\n"
             "SOLUTION: \n"
             "• Ensure you're selecting .mcpack files, not .zip or other formats\n"
             "• Try opening the file in Minecraft first to verify it's valid\n"
             "• Re-download the addon if it's corrupted\n"
             "• Check that the file isn't password-protected or encrypted"),
            
            ("Error: Version Mismatch / Addon Not Working", 
             "CAUSE: Merging addons from different Minecraft versions causes compatibility issues.\n"
             "SOLUTION: \n"
             "• Use 'Check Packs' to verify all addon versions\n"
             "• ONLY merge addons from the same version (e.g., all 1.20 or all 1.21)\n"
             "• Merging different versions is NOT RECOMMENDED and will likely cause problems\n"
             "• Each addon is designed for a specific version - mixing versions leads to conflicts\n"
             "• Create separate merged packs for each version - never mix versions in one merge"),
            
            ("Error: Addon Features Not Working After Merge", 
             "CAUSE: Identifier conflicts, file conflicts, or incompatible addons.\n"
             "SOLUTION: \n"
             "• Test each addon individually first to identify the problematic one\n"
             "• Check if multiple addons modify the same files (like player.json or entity files)\n"
             "• When addons modify the same file, they may conflict - try merging them separately\n"
             "• Remove the problematic addon and re-merge the rest\n"
             "• Some addons may be incompatible with others - merge compatible ones separately\n"
             "• Check Minecraft's error logs for specific error messages\n"
             "• If mobs stop spawning or entities behave strangely, check if multiple addons affect "
             "the same entity files or spawning mechanics"),
            
            ("Error: Missing Textures or Models", 
             "CAUSE: Resource pack files not properly merged or missing references.\n"
             "SOLUTION: \n"
             "• Ensure you're importing BOTH resource_pack.zip AND behavior_pack.zip\n"
             "• Check that all addons included their resource packs\n"
             "• Some addons may be behavior-only - they won't have textures\n"
             "• Verify the output directory contains both pack files"),
            
            ("Error: Scripts Not Working", 
             "CAUSE: JavaScript import conflicts or missing dependencies.\n"
             "SOLUTION: \n"
             "• AutoBE handles most script conflicts automatically\n"
             "• Ensure all addons are from the same Minecraft version\n"
             "• Check that the manifest includes required script modules\n"
             "• Some scripts may require specific API versions"),
            
            ("Error: Subpack Selection Required", 
             "CAUSE: The addon contains multiple subpacks and you need to choose one.\n"
             "SOLUTION: \n"
             "• A selection window will appear automatically\n"
             "• Read the subpack names and descriptions\n"
             "• Select the subpack you want to include\n"
             "• If unsure, test each subpack individually first"),
            
            ("Error: Process Freezes or Takes Too Long", 
             "CAUSE: Processing very large packs or too many packs at once.\n"
             "SOLUTION: \n"
             "• The UI may appear frozen but processing continues in the background\n"
             "• Wait for the progress bar to complete all 4 steps\n"
             "• Try merging fewer packs at a time (5-10 packs per merge)\n"
             "• Close other applications to free up system resources"),
            
            ("Error: Output Files Not Created", 
             "CAUSE: Output directory permissions or disk space issues.\n"
             "SOLUTION: \n"
             "• Ensure the output directory is writable\n"
             "• Check that you have enough disk space\n"
             "• Try selecting a different output directory\n"
             "• Run the application as administrator if permission errors occur")
        ]
        
        for title, description in error_solutions:
            error_frame = _tk.Frame(errors_inner, bg='#0A0A0A', relief='flat')
            error_frame.pack(fill='x', pady=(0, 12), padx=5)
            
            error_title = _tk.Label(error_frame, text=title, bg='#0A0A0A', fg='#FF6B6B',
                                   font=("Segoe UI", 11, "bold"), anchor='w', wraplength=650)
            error_title.pack(fill='x', padx=12, pady=(12, 6))
            
            error_desc = _tk.Label(error_frame, text=description, bg='#0A0A0A', fg='#CCCCCC',
                                  font=("Segoe UI", 10), anchor='w', justify='left', wraplength=650)
            error_desc.pack(fill='x', padx=12, pady=(0, 12))
        
        return section_frame
    
    def _create_best_practices_section(self):
        """Create the Best Practices section."""
        section_frame = _tk.Frame(self.help_content_frame, bg='#0f1419')
        
        best_practices_card = _tk.LabelFrame(section_frame, text="💡 Best Practices", 
                                            bg='#1a1a1a', fg='#FFFFFF', font=("Segoe UI", 14, "bold"),
                                            relief='flat', bd=0)
        best_practices_card.pack(fill='both', expand=True, padx=0, pady=(0, 15))
        
        best_practices_inner = _tk.Frame(best_practices_card, bg='#1a1a1a')
        best_practices_inner.pack(fill='both', expand=True, padx=20, pady=15)
        
        practices = [
            "Always test addons individually before merging to identify any issues",
            "Use 'Check Packs' to verify version compatibility before merging",
            "Merge addons in small batches (5-10 packs) rather than all at once",
            "Keep backups of original addon files before merging",
            "Test merged packs immediately after creation to catch issues early",
            "Organize addons by version in separate folders for easier management",
            "If a merged pack has issues, remove problematic addons one by one to identify the culprit",
            "Read addon descriptions/comments to understand compatibility requirements",
            "Be aware that addons modifying the same files (player.json, entity files, spawning rules) may conflict",
            "If multiple addons affect the same game mechanics (mob spawning, entity behavior), test carefully",
            "Check if addons modify the same JSON files - these are more likely to have conflicts",
            "Keep track of which addons you've merged together for easier troubleshooting"
        ]
        
        for practice in practices:
            practice_label = _tk.Label(best_practices_inner, text=f"✓ {practice}", bg='#1a1a1a', fg='#CCCCCC',
                                      font=("Segoe UI", 10), anchor='w', justify='left', wraplength=650)
            practice_label.pack(fill='x', pady=(0, 8))
        
        return section_frame
    
    def _create_processing_section(self):
        """Create the Processing Overview section."""
        section_frame = _tk.Frame(self.help_content_frame, bg='#0f1419')
        
        processing_card = _tk.LabelFrame(section_frame, text="⚙️ Processing Overview", 
                                       bg='#1a1a1a', fg='#FFFFFF', font=("Segoe UI", 14, "bold"),
                                       relief='flat', bd=0)
        processing_card.pack(fill='both', expand=True, padx=0, pady=(0, 15))
        
        processing_inner = _tk.Frame(processing_card, bg='#1a1a1a')
        processing_inner.pack(fill='both', expand=True, padx=20, pady=15)
        
        processing_steps = [
            ("Step 1: Creating Manifest", 
             "AutoBE analyzes all your selected packs and creates a unified manifest file that combines all necessary information and version requirements."),
            
            ("Step 2: Processing Files", 
             "All pack files are extracted and organized. Resource packs and behavior packs are separated automatically."),
            
            ("Step 3: Updating Packs", 
             "Files are merged together, conflicts are resolved automatically, and all references are updated to work correctly."),
            
            ("Step 4: Finalizing", 
             "The final pack files are created and prepared for use in Minecraft. Both resource_pack.zip and behavior_pack.zip are generated.")
        ]
        
        for title, description in processing_steps:
            step_frame = _tk.Frame(processing_inner, bg='#0A0A0A', relief='flat')
            step_frame.pack(fill='x', pady=(0, 10), padx=5)
            
            step_title = _tk.Label(step_frame, text=f"• {title}", bg='#0A0A0A', fg='#9333ea',
                                  font=("Segoe UI", 11, "bold"), anchor='w')
            step_title.pack(fill='x', padx=12, pady=(10, 5))
            
            step_desc = _tk.Label(step_frame, text=description, bg='#0A0A0A', fg='#CCCCCC',
                                 font=("Segoe UI", 10), anchor='w', justify='left', wraplength=680)
            step_desc.pack(fill='x', padx=12, pady=(0, 10))
        
        return section_frame
    
    def _create_disclaimer_section(self):
        """Create the Important Notes section."""
        section_frame = _tk.Frame(self.help_content_frame, bg='#0f1419')
        
        disclaimer_card = _tk.LabelFrame(section_frame, text="📋 Important Notes & Disclaimer", 
                                         bg='#1a1a1a', fg='#FFFFFF', font=("Segoe UI", 14, "bold"),
                                         relief='flat', bd=0)
        disclaimer_card.pack(fill='both', expand=True, padx=0, pady=(0, 15))
        
        disclaimer_inner = _tk.Frame(disclaimer_card, bg='#1a1a1a')
        disclaimer_inner.pack(fill='both', expand=True, padx=20, pady=15)
        
        disclaimer_items = [
            ("Important Notes", 
             "This section contains important information to help you use AutoBE effectively and avoid common issues. "
             "For legal terms, license agreements, and policies, please refer to the Terms of Service & License Agreement "
             "that you accepted when first launching the application."),
            
            ("Testing & Compatibility", 
             "Always test addons individually before merging to ensure they work correctly. After merging, test the merged "
             "pack thoroughly to verify all features function as expected. Some addons may be incompatible with others "
             "due to game mechanic conflicts - AutoBE handles technical conflicts (identifier conflicts, file merging) "
             "but cannot resolve gameplay incompatibilities.\n\n"
             "File Conflict Awareness: When multiple addons modify the same files (like player.json, entity files, or "
             "spawning rules), AutoBE merges them together. However, if addons modify the same properties in conflicting "
             "ways (e.g., two addons changing mob spawning rules differently), some functionality may not work. If you "
             "experience issues like mobs not spawning, entities behaving strangely, or features not working, check if "
             "multiple addons in your merge affect the same game files or mechanics. You may need to merge compatible "
             "addons separately or remove conflicting ones."),
            
            ("Version Compatibility", 
             "Merging addons from different game versions is NOT RECOMMENDED. Each addon is designed to work with a "
             "specific version of Minecraft, and merging them from different versions can lead to conflicts, outdated "
             "code, missing dependencies, and compatibility issues. Always merge addons from the same version to ensure "
             "compatibility and avoid problems. Create separate merged packs for each version if you have addons from "
             "multiple versions."),
            
            ("Addon Creator Rights", 
             "Always respect addon creators' terms of service and licensing agreements. Each creator has different rules "
             "regarding use, distribution, modification, and commercial use of their addons. It's your responsibility to "
             "review and comply with each addon creator's terms before using their addons with AutoBE."),
            
            ("Support & Contact", 
             "For technical support, questions, or assistance, contact us via email at thebedrocklabhelp@gmail.com or "
             "join our Discord community 'TheCodeNex'. You can also reach our owners directly: FrostyHostMC (Owner) or "
             "Eldas (Co-Owner) on Discord."),
            
            ("Legal & Policy Information", 
             "For information about refunds, bans, prohibited activities, license terms, and other legal matters, please "
             "refer to the Terms of Service & License Agreement accessible from the initial startup window or by reviewing "
             "the legal documentation provided with your purchase.")
        ]
        
        for title, description in disclaimer_items:
            item_frame = _tk.Frame(disclaimer_inner, bg='#0A0A0A', relief='flat')
            item_frame.pack(fill='x', pady=(0, 12), padx=5)
            
            item_title = _tk.Label(item_frame, text=f"• {title}", bg='#0A0A0A', fg='#9333ea',
                                  font=("Segoe UI", 11, "bold"), anchor='w', wraplength=600)
            item_title.pack(fill='x', padx=12, pady=(12, 6))
            
            item_desc = _tk.Label(item_frame, text=description, bg='#0A0A0A', fg='#CCCCCC',
                                 font=("Segoe UI", 10), anchor='w', justify='left', wraplength=600)
            item_desc.pack(fill='x', padx=12, pady=(0, 12))
        
        # Footer
        footer_label = _tk.Label(section_frame, text="CodeNex ©2024", 
                                 bg='#0f1419', fg='#666666', font=("Segoe UI", 9))
        footer_label.pack(fill='x', pady=(10, 20))
        
        return section_frame


    def select_files(self):
        """Open file dialog to select .mcpack and .mcaddon files."""
        file_paths = _filedialog.askopenfilenames(
            title="Select .mcpack and .mcaddon Files",
            filetypes=[("Minecraft Files", "*.mcpack *.mcaddon")]
        )
        for file_path in file_paths:
            file_name = _os.path.basename(file_path)
            # Detect pack type and append to display name
            pack_type = self._detect_pack_type(file_path)
            if pack_type != "Unknown":
                display_name = f"{file_name} [{pack_type}]"
            else:
                display_name = file_name
            # Store mapping and add display name to listbox
            self._mcpacker_file_paths[display_name] = file_path
            self._mcpacker_file_list.insert(_tk.END, display_name)
        # Update files list with full paths
        self._mcpacker_files = list(self._mcpacker_file_paths.values())
        self._update_mcpacker_file_count()

    def remove_mcpacker_files(self):
        """Remove selected files from the MCPACKER listbox."""
        selected_indices = self._mcpacker_file_list.curselection()
        for index in reversed(selected_indices):
            display_name = self._mcpacker_file_list.get(index)
            # Remove from mapping and listbox
            if display_name in self._mcpacker_file_paths:
                del self._mcpacker_file_paths[display_name]
            self._mcpacker_file_list.delete(index)
        # Update files list with remaining full paths
        self._mcpacker_files = list(self._mcpacker_file_paths.values())
        self._update_mcpacker_file_count()

    def _update_mcpacker_file_count(self):
        """Update the file count label for MCPACKER."""
        count = len(self._mcpacker_files)
        self._mcpacker_file_count_label.config(text=f"Files selected: {count}")

    def select_output_directory(self):
        """Open file dialog to select the output directory."""
        directory = _filedialog.askdirectory(title="Select Output Directory")
        self.output_dir_var.set(directory)

        

    def _update_progress(self, step, progress_percent, message):
        """Update the progress display with current step and message."""
        if hasattr(self, '_progress_step_label'):
            self._progress_step_label.config(text=message)
            self._progress['value'] = progress_percent
            self._root.update_idletasks()
            
            # Update step indicators
            if hasattr(self, '_step_labels') and 1 <= step <= 4:
                for i in range(4):
                    if i < step - 1:
                        # Completed steps
                        self._step_labels[i]['status'].config(text="✓", fg='#9333ea')
                        self._step_labels[i]['label'].config(fg='#FFFFFF')
                    elif i == step - 1:
                        # Current step
                        self._step_labels[i]['status'].config(text="→", fg='#9333ea')
                        self._step_labels[i]['label'].config(fg='#9333ea')
                    else:
                        # Pending steps
                        self._step_labels[i]['status'].config(text="○", fg='#666666')
                        self._step_labels[i]['label'].config(fg='#999999')
                # Mark all as complete if step 4 is done
                if step == 4:
                    for i in range(4):
                        self._step_labels[i]['status'].config(text="✓", fg='#9333ea')
                        self._step_labels[i]['label'].config(fg='#FFFFFF')

    def _reset_progress(self):
        """Reset progress display to initial state."""
        if hasattr(self, '_progress_step_label'):
            self._progress_step_label.config(text="Ready to process...")
            self._progress['value'] = 0
            if hasattr(self, '_step_labels'):
                for step_info in self._step_labels:
                    step_info['status'].config(text="○", fg='#666666')
                    step_info['label'].config(fg='#999999')

    def _show_subpack_selection(self, file_name, subpack_options):
        """Show a themed subpack selection overlay that matches the tool's theme."""
        # Clear existing widgets in overlay
        for widget in self._subpack_overlay.winfo_children():
            widget.destroy()
        
        # Create a variable to track when selection is complete
        selection_done = _tk.BooleanVar(self._root, False)
        selected_index = [None]
        
        # Create centered container
        center_frame = _tk.Frame(self._subpack_overlay, bg='#0f1419')
        center_frame.place(relx=0.5, rely=0.5, anchor='center')
        
        # Card frame
        card_frame = _tk.Frame(center_frame, bg='#1a1a1a', relief='flat', bd=0)
        card_frame.pack()
        
        # Card border
        border_frame = _tk.Frame(card_frame, bg='#9333ea', height=3)
        border_frame.pack(fill='x')
        
        # Inner container
        inner_frame = _tk.Frame(card_frame, bg='#1a1a1a')
        inner_frame.pack(fill='both', expand=True, padx=30, pady=30)
        
        # Title
        title_label = _tk.Label(inner_frame, text="📦 Select Subpack", 
                               bg='#1a1a1a', fg='#FFFFFF', 
                               font=('Segoe UI', 16, 'bold'))
        title_label.pack(pady=(0, 10))
        
        # File name
        file_label = _tk.Label(inner_frame, text=f"File: {file_name}", 
                              bg='#1a1a1a', fg='#999999', 
                              font=('Segoe UI', 10))
        file_label.pack(pady=(0, 20))
        
        # Instructions
        instruction_label = _tk.Label(inner_frame, text="Select a subpack to use:", 
                                     bg='#1a1a1a', fg='#FFFFFF', 
                                     font=('Segoe UI', 11))
        instruction_label.pack(pady=(0, 12), anchor='w')
        
        # Listbox container with scrollbar
        list_container = _tk.Frame(inner_frame, bg='#1a1a1a', height=250)
        list_container.pack(fill='both', expand=True, pady=(0, 20))
        list_container.pack_propagate(False)
        
        # Scrollbar
        scrollbar = _tk.Scrollbar(list_container, orient='vertical',
                                 bg='#0A0A0A', troughcolor='#1a1a1a',
                                 activebackground='#2d2d2d')
        scrollbar.pack(side='right', fill='y')
        
        # Listbox
        listbox = _tk.Listbox(list_container, 
                             bg='#0A0A0A', fg='#FFFFFF', 
                             font=('Segoe UI', 10),
                             selectbackground='#9333ea',
                             selectforeground='#FFFFFF',
                             relief='flat', bd=0,
                             yscrollcommand=scrollbar.set,
                             highlightthickness=0)
        listbox.pack(side='left', fill='both', expand=True)
        scrollbar.config(command=listbox.yview)
        
        # Populate listbox
        for i, option in enumerate(subpack_options):
            listbox.insert(_tk.END, f"{i+1}. {option}")
        
        # Select first item by default
        if subpack_options:
            listbox.selection_set(0)
            listbox.see(0)
        
        def on_ok():
            selection = listbox.curselection()
            if selection:
                selected_index[0] = selection[0] + 1  # +1 because list is 1-indexed
            selection_done.set(True)
            self._subpack_overlay.grid_remove()
        
        def on_cancel():
            selected_index[0] = None
            selection_done.set(True)
            self._subpack_overlay.grid_remove()
        
        def on_double_click(event):
            on_ok()
        
        # Bind double-click
        listbox.bind('<Double-Button-1>', on_double_click)
        
        # Button container
        button_frame = _tk.Frame(inner_frame, bg='#1a1a1a')
        button_frame.pack(pady=(10, 0))
        
        # Select button
        ok_button = _tk.Button(button_frame, text="Select", command=on_ok,
                              bg='#9333ea', fg='#FFFFFF',
                              font=('Segoe UI', 11, 'bold'),
                              relief='flat', bd=0, cursor='hand2',
                              activebackground='#a855f7',
                              activeforeground='#FFFFFF',
                              padx=30, pady=10)
        ok_button.pack(side='left', padx=(0, 10))
        
        # Cancel button
        cancel_button = _tk.Button(button_frame, text="Cancel", command=on_cancel,
                                  bg='#2d2d2d', fg='#FFFFFF',
                                  font=('Segoe UI', 11),
                                  relief='flat', bd=0, cursor='hand2',
                                  activebackground='#3d3d3d',
                                  activeforeground='#FFFFFF',
                                  padx=30, pady=10)
        cancel_button.pack(side='left')
        
        # Show the overlay
        self._subpack_overlay.grid()
        self._subpack_overlay.tkraise()
        self._root.update()
        
        # Wait for selection (modal behavior)
        self._root.wait_variable(selection_done)
        
        return selected_index[0]

    def _add_files(self):
        _files = _filedialog.askopenfilenames(filetypes=[("McPack files", "*.mcpack")])
        mcpack_names = []  # List to store the names of MCPACKs
        for _file in _files:
            mcpack_name = _os.path.basename(_file)
            # Detect pack type and append to display name
            pack_type = self._detect_pack_type(_file)
            if pack_type != "Unknown":
                display_name = f"{mcpack_name} [{pack_type}]"
            else:
                display_name = mcpack_name
            # Store mapping: display_name -> full_path, and also original name -> full_path for lookup
            self._file_paths[display_name] = _file
            self._file_list.insert(_tk.END, display_name)
            mcpack_names.append(mcpack_name)
        # Update files list with full paths
        self._files = list(self._file_paths.values())
        self.mcpack_names = mcpack_names  # Store MCPACK names for later use
        self._update_file_count()

    def _remove_files(self):
        _selected_indices = self._file_list.curselection()
        for _index in reversed(_selected_indices):
            display_name = self._file_list.get(_index)
            # Remove from mapping and listbox
            if display_name in self._file_paths:
                del self._file_paths[display_name]
            self._file_list.delete(_index)
        # Update files list with remaining full paths
        self._files = list(self._file_paths.values())
        self._update_file_count()

    def _update_file_count(self):
        """Update the file count label for AutoBE section."""
        count = len(self._files)
        self._file_count_label.config(text=f"Files selected: {count}")
        # Update achievement status when files change
        self._check_achievement_compatibility()

    def _check_achievement_compatibility(self):
        """Check if any packs disable achievements and update the status button."""
        if not hasattr(self, '_btn_achievement_status'):
            return
        
        self._achievement_disabling_packs = []
        
        # If no files selected, show default status
        if not self._files:
            self._btn_achievement_status.config(text="✅ Achievements Active", bg='#10b981', activebackground='#059669')
            return
        
        # Check each pack for achievement-disabling features
        for _file in self._files:
            manifest_data = self._get_manifest_data(_file)
            if not manifest_data:
                continue
            
            pack_name = _os.path.basename(_file)
            disables_achievements = False
            
            # Check for script_eval capability (most common cause)
            if 'capabilities' in manifest_data:
                capabilities = manifest_data['capabilities']
                if isinstance(capabilities, list):
                    if 'script_eval' in capabilities or 'experimental_custom_syntax' in capabilities:
                        disables_achievements = True
            
            # Check for script modules (type: "script")
            if 'modules' in manifest_data:
                modules = manifest_data['modules']
                if isinstance(modules, list):
                    for module in modules:
                        if isinstance(module, dict) and module.get('type') == 'script':
                            disables_achievements = True
                            break
            
            # Check for experimental gameplay features in header
            if 'header' in manifest_data:
                header = manifest_data['header']
                if isinstance(header, dict):
                    # Check for experimental field
                    if header.get('experimental') is True:
                        disables_achievements = True
            
            if disables_achievements:
                self._achievement_disabling_packs.append(pack_name)
        
        # Update button appearance and tooltip
        if self._achievement_disabling_packs:
            self._btn_achievement_status.config(text="❌ Achievements Disabled", bg='#ef4444', activebackground='#dc2626')
            # Create tooltip on hover
            self._btn_achievement_status.bind('<Enter>', self._show_achievement_tooltip)
            self._btn_achievement_status.bind('<Leave>', self._hide_achievement_tooltip)
        else:
            self._btn_achievement_status.config(text="✅ Achievements Active", bg='#10b981', activebackground='#059669')
            self._btn_achievement_status.unbind('<Enter>')
            self._btn_achievement_status.unbind('<Leave>')
            if self._achievement_tooltip:
                self._achievement_tooltip.destroy()
                self._achievement_tooltip = None

    def _show_achievement_tooltip(self, event=None):
        """Show tooltip with list of packs that disable achievements."""
        if not self._achievement_disabling_packs:
            return
        
        # Destroy existing tooltip if any
        if self._achievement_tooltip:
            self._hide_achievement_tooltip()
        
        # Create tooltip window
        self._achievement_tooltip = _tk.Toplevel(self._root)
        self._achievement_tooltip.wm_overrideredirect(True)
        self._achievement_tooltip.configure(bg='#1a1a1a', highlightthickness=1, highlightbackground='#9333ea')
        
        # Get button position
        button_x = self._btn_achievement_status.winfo_rootx()
        button_y = self._btn_achievement_status.winfo_rooty()
        button_height = self._btn_achievement_status.winfo_height()
        
        # Create tooltip content
        tooltip_frame = _tk.Frame(self._achievement_tooltip, bg='#1a1a1a')
        tooltip_frame.pack(fill='both', expand=True, padx=2, pady=2)
        
        title_label = _tk.Label(tooltip_frame, text="Packs Disabling Achievements:", 
                               bg='#1a1a1a', fg='#ef4444', font=("Segoe UI", 10, "bold"))
        title_label.pack(padx=10, pady=(8, 4), anchor='w')
        
        # List packs
        for pack_name in self._achievement_disabling_packs:
            pack_label = _tk.Label(tooltip_frame, text=f"• {pack_name}", 
                                  bg='#1a1a1a', fg='#FFFFFF', font=("Segoe UI", 9),
                                  anchor='w', justify='left')
            pack_label.pack(padx=10, pady=2, anchor='w')
        
        # Update tooltip size
        self._achievement_tooltip.update_idletasks()
        tooltip_width = self._achievement_tooltip.winfo_reqwidth()
        tooltip_height = self._achievement_tooltip.winfo_reqheight()
        
        # Position tooltip above button
        self._achievement_tooltip.geometry(f"{tooltip_width}x{tooltip_height}+{button_x}+{button_y - tooltip_height - 5}")

    def _hide_achievement_tooltip(self, event=None):
        """Hide the achievement tooltip."""
        if self._achievement_tooltip:
            self._achievement_tooltip.destroy()
            self._achievement_tooltip = None

    def _show_achievement_info(self):
        """Show detailed achievement compatibility information in a dialog."""
        if not self._files:
            _messagebox.showinfo("Achievement Status", "No packs selected. Add packs to check achievement compatibility.")
            return
        
        if not self._achievement_disabling_packs:
            _messagebox.showinfo("Achievement Status", 
                               "✅ All selected packs are compatible with achievements!\n\n"
                               "Achievements will remain active when using these packs.")
        else:
            packs_list = "\n".join([f"• {pack}" for pack in self._achievement_disabling_packs])
            _messagebox.showwarning("Achievement Status", 
                                  f"❌ Achievements will be DISABLED!\n\n"
                                  f"The following pack(s) disable achievements:\n\n"
                                  f"{packs_list}\n\n"
                                  f"Reason: These packs use script_eval capabilities, script modules, "
                                  f"or experimental features that require achievements to be disabled.")

    def _select_output_dir(self):
        _dir_name = _filedialog.askdirectory()
        if _dir_name:
            self._output_dir_var.set(_dir_name)
            self._out_dir = _dir_name

    def _process_and_create_manifest(self):
        if not self._files:
            _messagebox.showerror("Error", "Please select .mcpack files")
            _logging.error("No .mcpack files selected")
            return
        if not self._out_dir:
            _messagebox.showerror("Error", "Please select an output directory")
            _logging.error("No output directory selected")
            return

        if not self._validate_files():
            return

        # Disable start button during processing
        self._btn_start.config(state='disabled')
        
        # Run processing in a separate thread to prevent UI freezing
        def process_thread():
            try:
                self._root.after(0, lambda: self._reset_progress())
                self._root.after(0, lambda: self._update_progress(0, 0, "Initializing process..."))
                self._start_process()
                self._root.after(0, lambda: self._update_progress(4, 100, "All steps completed successfully! ✓"))
            
                # Reset memory and clear the list on main thread
                self._root.after(0, lambda: self._reset_file_list())
            except Exception as _e:
                log_error(_e)
                _logging.error("An error occurred during the process", exc_info=True)
                self._root.after(0, lambda: _messagebox.showerror("Error", f"An error occurred: {_e}"))
            finally:
                # Re-enable start button
                self._root.after(0, lambda: self._btn_start.config(state='normal'))
        
        threading.Thread(target=process_thread, daemon=True).start()
    
    def _reset_file_list(self):
        """Reset file list (called from main thread)."""
        self._files = []
        self._file_paths = {}
        self._file_list.delete(0, _tk.END)

    def _start_process(self):
        """
        Starts the processing of selected .mcpack files and saves the output to the specified directory.
        """
        # Use full file paths from _files list (listbox now only shows filenames)
        _selected_files = self._files
        _output_dir = self._output_dir_var.get()

        if not _selected_files:
            self._root.after(0, lambda: _messagebox.showerror("Error", "Please select at least one .mcpack file."))
            return
        if not _output_dir:
            self._root.after(0, lambda: _messagebox.showerror("Error", "Please select an output directory."))
            return

        new_selected_files = []  # Stores all files to be processed (modified and unmodified)
        new_mcpack_paths = []    # Stores paths of modified files for cleanup later

        for file_path in _selected_files:
            try:
                # Use the improved _get_manifest_data method which handles comments and malformed JSON
                manifest_data = self._get_manifest_data(file_path)
                if manifest_data is None:
                    _messagebox.showerror("Error", f"No 'manifest.json' found or failed to parse in {file_path}.")
                    continue

                # Check if 'subpacks' exists in manifest
                if 'subpacks' not in manifest_data:
                    # No subpacks found, add the original file to the list
                    new_selected_files.append(file_path)
                    continue

                subpacks = manifest_data['subpacks']
                if not subpacks:
                    # No subpacks defined, add the original file to the list
                    new_selected_files.append(file_path)
                    continue

                # Prepare subpack options for the user
                subpack_options = []
                for subpack in subpacks:
                    folder_name = subpack.get('folder_name', '')
                    name = subpack.get('name', '')
                    if folder_name and name:
                        subpack_options.append(f"{name} (Folder: {folder_name})")

                if not subpack_options:
                    new_selected_files.append(file_path)
                    continue

                # Prompt the user to select a subpack using themed dialog
                file_name_display = _os.path.basename(file_path)
                # Must call from main thread for dialog
                import threading
                if threading.current_thread() is threading.main_thread():
                    selected_subpack_index = self._show_subpack_selection(file_name_display, subpack_options)
                else:
                    # If in background thread, we need to call on main thread and wait
                    selected_index_var = [None]
                    event = threading.Event()
                    
                    def show_dialog():
                        try:
                            selected_index_var[0] = self._show_subpack_selection(file_name_display, subpack_options)
                        finally:
                            event.set()
                    
                    self._root.after(0, show_dialog)
                    event.wait()  # Wait for dialog to complete
                    selected_subpack_index = selected_index_var[0]

                if selected_subpack_index is None:
                    continue

                selected_subpack = subpacks[selected_subpack_index - 1]
                selected_subpack_name = selected_subpack['folder_name']

                # Create temporary directory
                temp_dir = _tempfile.mkdtemp(prefix='temp_extract_')
                # Extract the selected subpack folder
                with _zipfile.ZipFile(file_path, 'r') as zip_ref:
                    zip_ref.extractall(temp_dir)

                subpack_path = _os.path.join(temp_dir, 'subpacks', selected_subpack_name)

                # Check if subpack_path exists
                if not _os.path.exists(subpack_path):
                    new_selected_files.append(file_path)
                    continue

                # Move the contents of the selected folder outside the 'subpacks' folder
                for item in _os.listdir(subpack_path):
                    s = _os.path.join(subpack_path, item)
                    d = _os.path.join(temp_dir, item)
                    if _os.path.exists(d):
                        if _os.path.isdir(d):
                            _shutil.copytree(s, d, dirs_exist_ok=True)
                        else:
                            _shutil.move(s, d)
                    else:
                        _shutil.move(s, d)

                # Remove the now empty 'subpacks' folder
                subpacks_dir = _os.path.join(temp_dir, 'subpacks')
                if _os.path.exists(subpacks_dir):
                    _shutil.rmtree(subpacks_dir)

                # Repack the .mcpack file
                new_mcpack_path = file_path.replace('.mcpack', '_modified.mcpack')
                with _zipfile.ZipFile(new_mcpack_path, 'w') as new_zip_ref:
                    for folder_name, subfolders, filenames in _os.walk(temp_dir):
                        for filename in filenames:
                            file_path_in_temp = _os.path.join(folder_name, filename)
                            arcname = _os.path.relpath(file_path_in_temp, temp_dir)
                            new_zip_ref.write(file_path_in_temp, arcname)

                # Clean up the temporary directory
                if _os.path.exists(temp_dir):
                    _shutil.rmtree(temp_dir)

                # Add the new modified file to the list
                new_selected_files.append(new_mcpack_path)
                new_mcpack_paths.append(new_mcpack_path)

            except Exception as e:
                log_error(e)
                _messagebox.showerror("Error", f"An error occurred while processing {file_path}: {str(e)}")
                continue

        if not new_selected_files:
            _messagebox.showerror("Error", "No valid .mcpack files to process.")
            return

        # Process packs sequence
        steps = [
            (self._extract_and_store_highest_versions, None, None, ""),
            (self._process_packs, (new_selected_files, _output_dir), None, ""),
            (self._delete_manifest_files, None, None, ""),
            (self._create_manifest, None, (1, 5, "Step 1/4: Creating manifest..."), "Step 1/4: Creating manifest... ✓ Complete"),
            (self._move_tick_and_delete_functions, None, None, ""),
            (self._process_files, (new_selected_files,), (2, 25, "Step 2/4: Processing files..."), "Step 2/4: Processing files... ✓ Complete"),
            (self._move_and_cleanup, None, None, ""),
            (self._update_behavior_pack, None, (3, 50, "Step 3/4: Updating packs..."), "Step 3/4: Updating packs... ✓ Complete"),
            (self._merge_flipbook_textures, (new_selected_files,), None, ""),
            (self._merge_textures_list, (new_selected_files,), None, ""),
            (self._extract_and_delete_zip_files, None, None, ""),
            (self._move_to_resource_pack, None, (4, 75, "Step 4/4: Finalizing..."), "Step 4/4: Finalizing... ✓ Complete")
        ]

        for func, args, prog_start, prog_done in steps:
            try:
                if prog_start: self._update_progress(*prog_start)
                if args: func(*args)
                else: func()
                if prog_done: self._update_progress(prog_start[0], prog_start[0]*25, prog_done)
            except Exception as e:
                log_error(e)
                if prog_start: self._update_progress(prog_start[0], prog_start[0]*25, f"Step {prog_start[0]}/4: Error - {str(e)}")

        # Define paths for behavior and resource packs
        _bp_path = _os.path.join(self._out_dir, "behavior_pack.zip")
        _rp_path = _os.path.join(self._out_dir, "resource_pack.zip")
        
        _bp_new_path = _os.path.join(self._out_dir, "behavior_pack.mcpack")
        _rp_new_path = _os.path.join(self._out_dir, "resource_pack.mcpack")
        
        _scripts_path = _os.path.join(self._out_dir, "scripts")
        _temp_dir = _tempfile.mkdtemp(prefix='temp_unpack_')
        _tempr_dir = _tempfile.mkdtemp(prefix='temp_unpack_resource_pack_')
        _flipbook_textures_source = _os.path.join(self._out_dir, "flipbook_textures.json")
        _textures_list_source = _os.path.join(self._out_dir, "textures_list.json")
            

        # Final cleanup and renaming
        paths_to_move = [(_bp_path, _bp_new_path), (_rp_path, _rp_new_path)]
        for src, dst in paths_to_move:
            try:
                if _os.path.exists(src): _shutil.move(src, dst)
            except Exception as e: log_error(e)

        cleanup_paths = [_scripts_path, _temp_dir, _tempr_dir, _flipbook_textures_source, _textures_list_source]
        for p in cleanup_paths:
            try:
                if _os.path.exists(p):
                    if _os.path.isdir(p): _shutil.rmtree(p)
                    else: _os.remove(p)
            except Exception: pass
            
        for new_file in new_mcpack_paths:
            try:
                if _os.path.exists(new_file): _os.remove(new_file)
            except Exception as e: log_error(e)

        # Process completed - progress display will show completion

    def _check_compatibility(self):
        _incompatible_files = []
        _missing_manifest_files = []

        _selected_files = self._files

        for _file in _selected_files:
            with _zipfile.ZipFile(_file, 'r') as _pack_zip:
                _pack_namelist = _pack_zip.namelist()

                if 'manifest.json' not in _pack_namelist:
                    _missing_manifest_files.append(_file)

        if _incompatible_files or _missing_manifest_files:
            _message = "The Following Issues Were Found With Selected MCPacks:\n\n"

            if _missing_manifest_files:
                _message += "Missing manifest.json:\n"
                for _file in _missing_manifest_files:
                    _message += f"- {_os.path.basename(_file)}\n"
                _message += "\n"

            _messagebox.showwarning("Compatibility Check", _message)
        else:
            _messagebox.showinfo("Compatibility Check", "All Selected MCPacks Have Manifest.")

    def _validate_files(self):
        invalid_files = []

        for _file in self._files:
            try:
                with _zipfile.ZipFile(_file, 'r') as _pack_zip:
                    if 'manifest.json' not in _pack_zip.namelist():
                        invalid_files.append(_file)
            except _zipfile.BadZipFile:
                invalid_files.append(_file)

        if invalid_files:
            _message = "The following files are invalid or missing manifest.json:\n\n"
            for _file in invalid_files:
                _message += f"- {_os.path.basename(_file)}\n"
            _messagebox.showerror("Invalid Files", _message)
            _logging.error(f"Invalid files detected: {invalid_files}")
            return False
        
        return True

    def _extract_and_store_highest_versions(self):
        if not hasattr(self, 'mcpack_names'):
            _messagebox.showinfo("Error", "No MCPACK files have been added.")
            return

        # Sections for storing classified packs
        sections = {
            "These Addons Are Using 1.21+ Codes": [],
            "These Addons Are Using 1.20+ Codes": [],
            "These Addons Are Using 1.19+ Codes": [],
            "These Addons Are Using 1.18+ Codes": [],
            "These Addons Are Using 1.17+ Codes": [],
            "These Addons Are Using '1.16 And Below' Codes": []
        }

        # Set initial version as low as possible for comparison
        highest_rp_version = None
        highest_bp_version = None
        
        # Set initial highest versions for dependencies, None to indicate no version found yet
        highest_server_version = None
        highest_server_ui_version = None
        highest_gametest_version = None

        # Store the actual versions (including '-beta') for manifest creation
        highest_server_version_full = None
        highest_server_ui_version_full = None
        highest_gametest_version_full = None

        for _file in self._files:
            manifest_data = self._get_manifest_data(_file)
            if manifest_data and 'header' in manifest_data and 'min_engine_version' in manifest_data['header']:
                min_engine_version_raw = manifest_data['header']['min_engine_version']
                mcpack_name = _os.path.basename(_file)

                # Normalize version to list format [major, minor, patch]
                if isinstance(min_engine_version_raw, str):
                    # Convert string like "1.21.30" to [1, 21, 30]
                    min_engine_version = [int(x) for x in min_engine_version_raw.split('.')]
                elif isinstance(min_engine_version_raw, list):
                    # Already a list, make a copy
                    min_engine_version = list(min_engine_version_raw)
                else:
                    # Try to convert to list
                    min_engine_version = [int(x) for x in str(min_engine_version_raw).split('.')]

                # Ensure version is a 3-part list (pad if necessary)
                while len(min_engine_version) < 3:
                    min_engine_version.append(0)

                # Determine if it's a resource pack or behavior pack
                if 'modules' in manifest_data:
                    for module in manifest_data['modules']:
                        if module['type'] == 'resources':
                            # Compare versions properly: [major, minor, patch]
                            if (highest_rp_version is None or
                                min_engine_version[0] > highest_rp_version[0] or
                                (min_engine_version[0] == highest_rp_version[0] and min_engine_version[1] > highest_rp_version[1]) or
                                (min_engine_version[0] == highest_rp_version[0] and min_engine_version[1] == highest_rp_version[1] and min_engine_version[2] > highest_rp_version[2])):
                                highest_rp_version = min_engine_version
                        elif module['type'] == 'data':
                            # Compare versions properly: [major, minor, patch]
                            if (highest_bp_version is None or
                                min_engine_version[0] > highest_bp_version[0] or
                                (min_engine_version[0] == highest_bp_version[0] and min_engine_version[1] > highest_bp_version[1]) or
                                (min_engine_version[0] == highest_bp_version[0] and min_engine_version[1] == highest_bp_version[1] and min_engine_version[2] > highest_bp_version[2])):
                                highest_bp_version = min_engine_version

                # Extract the dependencies if they exist
                if 'dependencies' in manifest_data:
                    for dependency in manifest_data['dependencies']:
                        module_name = dependency.get('module_name')
                        version = dependency.get('version')

                        if version:
                            # Store the full version (including any '-beta') for later use in manifest
                            version_full = version

                            # Extract only the numeric part for comparison (ignore '-beta' unless specified)
                            version_numeric_parts = [int(v) for v in version.replace('-beta', '').split('.')]
                            while len(version_numeric_parts) < 3:
                                version_numeric_parts.append(0)

                            # Compare and update highest versions for dependencies
                            if module_name == "@minecraft/server":
                                if not highest_server_version or version_numeric_parts > highest_server_version:
                                    highest_server_version = version_numeric_parts
                                    highest_server_version_full = version_full  # Keep '-beta' for highest version
                            elif module_name == "@minecraft/server-ui":
                                if not highest_server_ui_version or version_numeric_parts > highest_server_ui_version:
                                    highest_server_ui_version = version_numeric_parts
                                    highest_server_ui_version_full = version_full  # Keep '-beta' for highest version
                            elif module_name == "@minecraft/server-gametest":
                                if not highest_gametest_version or version_numeric_parts > highest_gametest_version:
                                    highest_gametest_version = version_numeric_parts
                                    highest_gametest_version_full = version_full  # Keep '-beta' for highest version

                # Determine section based on min_engine_version
                if min_engine_version[0] == 1:
                    if min_engine_version[1] >= 21:
                        section = "These Addons Are Using 1.21+ Codes"
                    elif min_engine_version[1] == 20:
                        section = "These Addons Are Using 1.20+ Codes"
                    elif min_engine_version[1] == 19:
                        section = "These Addons Are Using 1.19+ Codes"
                    elif min_engine_version[1] == 18:
                        section = "These Addons Are Using 1.18+ Codes"
                    elif min_engine_version[1] == 17:
                        section = "These Addons Are Using 1.17+ Codes"
                    else:
                        section = "These Addons Are Using '1.16 And Below' Codes"
                else:
                    section = "These Addons Are Using '1.16 And Below' Codes"

                sections[section].append(f"{mcpack_name} (Version: {'.'.join(map(str, min_engine_version))})")

        # Set defaults if no versions were found
        if highest_server_version is None:
            highest_server_version = [1, 13, 0]
            highest_server_version_full = "1.13.0"
        if highest_server_ui_version is None:
            highest_server_ui_version = [1, 2, 0]
            highest_server_ui_version_full = "1.2.0"

        # Store the highest versions for later use in manifest creation
        self.highest_rp_version = highest_rp_version
        self.highest_bp_version = highest_bp_version
        self.highest_server_version_full = highest_server_version_full
        self.highest_server_ui_version_full = highest_server_ui_version_full
        self.highest_gametest_version_full = highest_gametest_version_full
        
    def _extract_and_show_codes(self):
            # Check for manifest
            self._check_compatibility()
            
            if not hasattr(self, 'mcpack_names'):
                _messagebox.showinfo("Error", "No MCPACK files have been added.")
                return

            # Track closed source packs
            bad_packs = []
            
            # Sections for storing classified packs
            sections = {
                "These Addons Are Using 1.21+ Codes": [],
                "These Addons Are Using 1.20+ Codes": [],
                "These Addons Are Using 1.19+ Codes": [],
                "These Addons Are Using 1.18+ Codes": [],
                "These Addons Are Using 1.17+ Codes": [],
                "These Addons Are Using '1.16 And Below' Codes": []
            }

            highest_rp_version = [0, 0, 0]
            highest_bp_version = [0, 0, 0]
            pack_info_list = []

            for _file in self._files:
                file_name = _os.path.basename(_file)
                
                # --- NEW: Check for Closed Source Obfuscation ---
                if self._is_pack_obfuscated(_file):
                    bad_packs.append(file_name)

                manifest_data = self._get_manifest_data(_file)
                if manifest_data and 'header' in manifest_data and 'min_engine_version' in manifest_data['header']:
                    min_engine_version = manifest_data['header']['min_engine_version']

                    while len(min_engine_version) < 3:
                        min_engine_version.append(0)
                    
                    version_str = f"{min_engine_version[0]}.{min_engine_version[1]}.{min_engine_version[2]}"

                    pack_types = []
                    if 'modules' in manifest_data:
                        for module in manifest_data['modules']:
                            if module['type'] == 'resources':
                                pack_types.append("RP")
                                if min_engine_version > highest_rp_version:
                                    highest_rp_version = min_engine_version
                            elif module['type'] == 'data':
                                pack_types.append("BP")
                                if min_engine_version > highest_bp_version:
                                    highest_bp_version = min_engine_version

                    pack_type_str = " + ".join(pack_types) if pack_types else "Unknown"
                    
                    pack_info_list.append({
                        'name': file_name,
                        'version': version_str,
                        'version_tuple': min_engine_version,
                        'type': pack_type_str
                    })

            # --- NEW: Show Warning for Bad Packs ---
            if bad_packs:
                msg = "⚠ CRITICAL: CLOSED-SOURCE PACKS DETECTED\n\n"
                msg += "The following packs contain '*/' or Unicode-obfuscated JSON files. "
                msg += "Merging these WILL CORRUPT the final output and cause Minecraft to crash.\n\n"
                msg += "Please REMOVE these files from the list before merging:\n\n• "
                msg += "\n• ".join(bad_packs)
                _messagebox.showwarning("Corrupted Pack Warning", msg)

            # Show the version check overlay
            self._show_version_check_overlay(pack_info_list)

            self.highest_rp_version = highest_rp_version
            self.highest_bp_version = highest_bp_version

    def _show_version_check_overlay(self, pack_info_list):
        """Show a themed version check overlay that matches the tool's theme, grouped by version."""
        # Clear existing widgets in overlay
        for widget in self._version_check_overlay.winfo_children():
            widget.destroy()
        
        # Create a variable to track when overlay should close
        overlay_done = _tk.BooleanVar(self._root, False)
        
        # Configure overlay for proper resizing
        self._version_check_overlay.grid_columnconfigure(0, weight=1)
        self._version_check_overlay.grid_rowconfigure(0, weight=1)
        
        # Create main container that fills the overlay
        main_container = _tk.Frame(self._version_check_overlay, bg='#0f1419')
        main_container.grid(row=0, column=0, sticky="nsew", padx=20, pady=20)
        main_container.grid_columnconfigure(0, weight=1)
        main_container.grid_rowconfigure(1, weight=1)
        
        # Card frame with proper sizing
        card_frame = _tk.Frame(main_container, bg='#1a1a1a', relief='flat', bd=0)
        card_frame.grid(row=0, column=0, sticky="nsew")
        card_frame.grid_columnconfigure(0, weight=1)
        card_frame.grid_rowconfigure(1, weight=1)
        
        # Card border
        border_frame = _tk.Frame(card_frame, bg='#9333ea', height=3)
        border_frame.grid(row=0, column=0, sticky="ew")
        
        # Inner container with proper padding
        inner_frame = _tk.Frame(card_frame, bg='#1a1a1a')
        inner_frame.grid(row=1, column=0, sticky="nsew", padx=25, pady=25)
        inner_frame.grid_columnconfigure(0, weight=1)
        inner_frame.grid_rowconfigure(2, weight=1)
        
        # Title
        title_label = _tk.Label(inner_frame, text="🔍 Pack Version Check", 
                               bg='#1a1a1a', fg='#FFFFFF', 
                               font=('Segoe UI', 16, 'bold'))
        title_label.grid(row=0, column=0, pady=(0, 10), sticky="w")
        
        # Warning message
        warning_label = _tk.Label(inner_frame, 
                                text="⚠️ Packs with the same version can be safely merged together. Different versions may cause conflicts.",
                                bg='#1a1a1a', fg='#ff6b6b', 
                                font=('Segoe UI', 10),
                                wraplength=700, justify='left')
        warning_label.grid(row=1, column=0, pady=(0, 15), sticky="w")
        
        if not pack_info_list:
            no_packs_label = _tk.Label(inner_frame, text="No valid min_engine_version found in selected packs.",
                                      bg='#1a1a1a', fg='#999999', 
                                      font=('Segoe UI', 11))
            no_packs_label.grid(row=2, column=0, pady=20)
        else:
            # Group packs by version
            version_groups = {}
            for pack_info in pack_info_list:
                version = pack_info['version']
                if version not in version_groups:
                    version_groups[version] = []
                version_groups[version].append(pack_info)
            
            # Sort versions (newest first)
            sorted_versions = sorted(version_groups.keys(), reverse=True, 
                                    key=lambda v: tuple(map(int, v.split('.'))))
            
            # Create scrollable frame for categorized pack list
            canvas_container = _tk.Frame(inner_frame, bg='#1a1a1a')
            canvas_container.grid(row=2, column=0, sticky="nsew")
            canvas_container.grid_columnconfigure(0, weight=1)
            canvas_container.grid_rowconfigure(0, weight=1)
            
            canvas = _tk.Canvas(canvas_container, bg='#1a1a1a', highlightthickness=0)
            scrollbar = _tk.Scrollbar(canvas_container, orient='vertical', command=canvas.yview,
                                     bg='#0A0A0A', troughcolor='#1a1a1a',
                                     activebackground='#2d2d2d', width=15)
            scrollable_frame = _tk.Frame(canvas, bg='#1a1a1a')
            
            def update_scroll_region(event=None):
                canvas.update_idletasks()
                canvas.configure(scrollregion=canvas.bbox("all"))
            
            scrollable_frame.bind("<Configure>", update_scroll_region)
            canvas.bind("<Configure>", lambda e: canvas.itemconfig(canvas.find_all()[0], width=e.width))
            
            canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
            canvas.configure(yscrollcommand=scrollbar.set)
            
            # Display packs grouped by version
            row_num = 0
            for version in sorted_versions:
                packs_in_version = version_groups[version]
                count = len(packs_in_version)
                
                # Version category header
                version_header = _tk.Frame(scrollable_frame, bg='#9333ea', height=35)
                version_header.grid(row=row_num, column=0, sticky="ew", padx=0, pady=(0, 8))
                version_header.grid_columnconfigure(0, weight=1)
                
                version_text = f"Version {version} ({count} pack{'s' if count != 1 else ''}) - Safe to merge together"
                _tk.Label(version_header, text=version_text, bg='#9333ea', fg='#FFFFFF',
                         font=('Segoe UI', 12, 'bold'), anchor='w').grid(row=0, column=0, padx=15, pady=8, sticky="w")
                row_num += 1
                
                # Pack rows for this version
                for pack_info in packs_in_version:
                    row_frame = _tk.Frame(scrollable_frame, bg='#1a1a1a')
                    row_frame.grid(row=row_num, column=0, sticky="ew", padx=10, pady=3)
                    row_frame.grid_columnconfigure(0, weight=1)
                    
                    # Pack name (truncate if too long)
                    pack_name = pack_info['name']
                    if len(pack_name) > 50:
                        pack_name = pack_name[:47] + "..."
                    
                    name_label = _tk.Label(row_frame, text=pack_name, bg='#1a1a1a', fg='#FFFFFF',
                                         font=('Segoe UI', 10), anchor='w')
                    name_label.grid(row=0, column=0, padx=(15, 10), pady=6, sticky="ew")
                    
                    type_label = _tk.Label(row_frame, text=pack_info['type'], bg='#1a1a1a', fg='#60a5fa',
                                         font=('Segoe UI', 10))
                    type_label.grid(row=0, column=1, padx=10, pady=6, sticky="e")
                    
                    row_num += 1
            
            # Configure scrollable frame columns
            scrollable_frame.grid_columnconfigure(0, weight=1)
            scrollable_frame.grid_columnconfigure(1, weight=0)
            
            canvas.grid(row=0, column=0, sticky="nsew")
            scrollbar.grid(row=0, column=1, sticky="ns")
            
            # Make canvas expandable
            canvas_container.grid_rowconfigure(0, weight=1)
            canvas_container.grid_columnconfigure(0, weight=1)
        
        def on_close():
            overlay_done.set(True)
            self._version_check_overlay.grid_remove()
        
        # Close button
        button_frame = _tk.Frame(inner_frame, bg='#1a1a1a')
        button_frame.grid(row=3, column=0, pady=(15, 0))
        
        close_btn = _tk.Button(button_frame, text="Close", command=on_close,
                              bg='#9333ea', fg='#FFFFFF', 
                              font=('Segoe UI', 11, 'bold'),
                              relief='flat', cursor='hand2',
                              activebackground='#a855f7',
                              padx=30, pady=10)
        close_btn.pack()
        
        # Show overlay
        self._version_check_overlay.grid()
        self._version_check_overlay.lift()  # Bring to front
        
        # Update scroll region after a moment to ensure proper sizing
        self._root.after(100, update_scroll_region)
        
        # Wait for user to close
        self._root.wait_variable(overlay_done)


    def _process_packs(self, _files, _output_dir):
        _output_zip_path_resource = _os.path.join(_output_dir, "resource_pack.zip")
        _output_zip_path_behavior = _os.path.join(_output_dir, "behavior_pack.zip")

        _json_contents_resource = {}
        _json_contents_behavior = {}
        _lang_contents_resource = {}
        _lang_contents_behavior = {}
        _material_contents = {}
        _mcfunction_contents = {}

        # Dictionary to store player-related JSON data
        _player_json_contents_resource = {}  # For resource packs (entity folder)
        _player_json_contents_behavior = {}  # For behavior packs (entities folder)
        
        # Dictionary to store entity files grouped by identifier for intelligent merging
        # Format: {identifier: {file_path: json_data}}
        _entity_files_by_identifier_resource = {}  # For resource packs (entity folder)
        _entity_files_by_identifier_behavior = {}  # For behavior packs (entities folder)
        
        # Dictionary to store item/block files grouped by identifier
        _item_files_by_identifier = {}  # For items
        _block_files_by_identifier = {}  # For blocks

        _mergeable_files = {
            "item_texture.json", "terrain_texture.json", "tick.json", "sounds.json", "blocks.json",
            "biomes_client.json", "sound_definitions.json", "music_definitions.json", "flipbook_textures.json",
            "textures_list.json", "_ui_defs.json", "hud_screen.json", "npc_interact_screen.json", 
            "_global_variables.json", "ui_common.json", "splashes.json",
            "player.animation_controllers.json", "player.animation.json", "player.render_controllers.json"
        }

        # Initialize identifier conflict resolution system for universal addon compatibility
        identifier_manager = None
        try:
            identifier_manager = IdentifierManager()
            # First pass: Scan all packs for identifiers to detect conflicts
            all_pack_identifiers = {}
            for scan_file in _files:
                scan_file_path = scan_file
                if _os.path.isdir(scan_file_path):
                    # For directories, create a temp zip to scan
                    temp_zip_path = _os.path.join(_output_dir, f"temp_scan_{_os.path.basename(scan_file_path)}.mcpack")
                    with _zipfile.ZipFile(temp_zip_path, 'w', _zipfile.ZIP_DEFLATED) as zf:
                        for root, dirs, files in _os.walk(scan_file_path):
                            for file in files:
                                file_path = _os.path.join(root, file)
                                arcname = _os.path.relpath(file_path, scan_file_path)
                                zf.write(file_path, arcname)
                    scan_file_path = temp_zip_path
                
                try:
                    with _zipfile.ZipFile(scan_file_path, 'r') as scan_zip:
                        all_pack_identifiers[scan_file] = identifier_manager.scan_pack_identifiers(scan_zip, scan_file)
                except Exception as e:
                    _logging.warning(f"Could not scan identifiers from {scan_file}: {e}")
            
            # Detect conflicts and generate mappings
            if all_pack_identifiers:
                identifier_manager.detect_conflicts(all_pack_identifiers)
                identifier_manager.generate_identifier_mappings()
                _logging.info(f"Identifier conflict resolution initialized: {len(identifier_manager.identifier_mapping)} mappings created")
        except Exception as e:
            _logging.warning(f"Identifier manager initialization failed (merging will continue without conflict resolution): {e}")
            identifier_manager = None

        self._progress['value'] = 0
        self._progress['maximum'] = len(_files)

        for _i, _file in enumerate(_files):
            # If _file is a folder, zip it up as a .mcpack and process as usual
            if _os.path.isdir(_file):
                # Only treat as a pack if manifest.json and pack_icon are at the root
                manifest_path = _os.path.join(_file, 'manifest.json')
                has_icon = any(_os.path.isfile(_os.path.join(_file, f'pack_icon{ext}')) for ext in ['.png', '.jpg', '.jpeg'])
                if not (_os.path.isfile(manifest_path) and has_icon):
                    _logging.warning(f"Skipping {_file} - not a valid pack folder.")
                    continue
                # Zip the folder into a temp .mcpack
                temp_mcpack = _os.path.join(_output_dir, f"temp_{_os.path.basename(_file)}.mcpack")
                with _zipfile.ZipFile(temp_mcpack, 'w', _zipfile.ZIP_DEFLATED) as zf:
                    for root, dirs, files in _os.walk(_file):
                        # If we find a subfolder named 'subpacks', copy it as-is (do not iterate into it for manifests/icons)
                        rel_root = _os.path.relpath(root, _file)
                        if rel_root == 'subpacks':
                            for subpack_name in dirs:
                                subpack_path = _os.path.join(root, subpack_name)
                                for sub_root, sub_dirs, sub_files in _os.walk(subpack_path):
                                    for sub_file in sub_files:
                                        abs_path = _os.path.join(sub_root, sub_file)
                                        arcname = _os.path.relpath(abs_path, _file)
                                        zf.write(abs_path, arcname)
                            # Skip further walk into subpacks
                            dirs.clear()
                        else:
                            for file in files:
                                abs_path = _os.path.join(root, file)
                                arcname = _os.path.relpath(abs_path, _file)
                                zf.write(abs_path, arcname)
                _file = temp_mcpack  # Now process as a .mcpack file

            _manifest_data = self._get_manifest_data(_file)
            if not _manifest_data:
                _logging.warning(f"Skipping {_file} - manifest.json not found or invalid.")
                continue

            _module_type = _manifest_data.get("modules", [{}])[0].get("type", "")
            if _module_type == "resources":
                _output_zip_path = _output_zip_path_resource
                _player_json_contents = _player_json_contents_resource  # Use resource pack player data
                _entity_folder = "entity"  # Resource packs use 'entity' folder
            elif _module_type in {"data", "script"}:
                _output_zip_path = _output_zip_path_behavior
                _player_json_contents = _player_json_contents_behavior  # Use behavior pack player data
                _entity_folder = "entities"  # Behavior packs use 'entities' folder
            else:
                _logging.warning(f"Skipping {_file} - Unsupported module type '{_module_type}' in manifest.json.")
                continue

            with _zipfile.ZipFile(_file, 'r') as _pack_zip:
                with _zipfile.ZipFile(_output_zip_path, 'a') as _output_zip:
                    for _item in _pack_zip.infolist():
                        _item_name = _item.filename
                        # If this is a subpacks/ file or folder, just copy as-is, do not process for manifests/icons
                        if _item_name.startswith('subpacks/'):
                            self._copy_to_zip(_pack_zip, _item, _output_zip, None, _file, identifier_manager)
                            continue
                        if _item_name.startswith("feature_rules"):
                            _feature_rules_folder_name = f"feature_rules/{_os.path.basename(_file).replace('.mcpack', '')}"
                            self._extract_feature_rules(_pack_zip, _item, _feature_rules_folder_name, _output_zip)
                            continue
                        if _item_name.endswith(".json"):
                            # Check if the JSON file is in the 'entity' or 'entities' folder
                            if _os.path.dirname(_item_name) in {"entity", "entities"}:
                                with _pack_zip.open(_item) as _json_file:
                                    try:
                                        _json_data = self._load_json_with_comments(_json_file)
                                        # Update identifiers in entity files if manager is available
                                        if identifier_manager:
                                            try:
                                                _json_data = identifier_manager.update_json_identifiers(_json_data, _file)
                                            except Exception as e:
                                                _logging.warning(f"Error updating entity identifiers in {_item_name}: {e}")
                                        # Check for 'minecraft:client_entity' -> 'description' -> 'identifier'
                                        client_entity = _json_data.get("minecraft:client_entity")
                                        if client_entity and isinstance(client_entity, dict):
                                            description = client_entity.get("description")
                                            if description and isinstance(description, dict):
                                                identifier = description.get("identifier")
                                                if identifier == "minecraft:player":
                                                    # Store player-related JSON data for merging
                                                    _player_json_contents.setdefault(_item_name, []).append(_json_data)
                                                    continue  # Skip copying this file directly
                                    except _json.JSONDecodeError:
                                        _logging.warning(f"Failed to parse JSON file: {_item_name}")
                            # Handle other JSON files
                            if _os.path.basename(_item_name) not in _mergeable_files:
                                # For entity/item/block files, collect by identifier for intelligent merging
                                dir_name = _os.path.dirname(_item_name)
                                if dir_name in {"entities", "entity", "items", "blocks"}:
                                    try:
                                        with _pack_zip.open(_item) as _json_file:
                                            _json_data = self._load_json_with_comments(_json_file)
                                            
                                            # Extract identifier BEFORE renaming (we need original identifier for grouping)
                                            # This allows us to merge entities with the same identifier
                                            if dir_name in {"entities", "entity"}:
                                                entity_id = self._extract_entity_identifier_from_json(_json_data)
                                                if entity_id:
                                                    # Group by identifier for merging same entities
                                                    entity_dict = _entity_files_by_identifier_behavior if _module_type in {"data", "script"} else _entity_files_by_identifier_resource
                                                    if entity_id not in entity_dict:
                                                        entity_dict[entity_id] = []
                                                    entity_dict[entity_id].append({
                                                        'file_path': _item_name,
                                                        'data': _json_data,
                                                        'pack_path': _file,
                                                        'original_id': entity_id
                                                    })
                                                    continue  # Skip copying - will be merged later
                                                else:
                                                    # No identifier found, copy as-is
                                                    self._copy_to_zip(_pack_zip, _item, _output_zip, _json_data, _file, identifier_manager)
                                            elif dir_name == "items":
                                                item_id = self._extract_item_identifier_from_json(_json_data)
                                                if item_id:
                                                    if item_id not in _item_files_by_identifier:
                                                        _item_files_by_identifier[item_id] = []
                                                    _item_files_by_identifier[item_id].append({
                                                        'file_path': _item_name,
                                                        'data': _json_data,
                                                        'pack_path': _file,
                                                        'original_id': item_id
                                                    })
                                                    continue  # Skip copying - will be merged later
                                                else:
                                                    self._copy_to_zip(_pack_zip, _item, _output_zip, _json_data, _file, identifier_manager)
                                            elif dir_name == "blocks":
                                                block_id = self._extract_block_identifier_from_json(_json_data)
                                                if block_id:
                                                    if block_id not in _block_files_by_identifier:
                                                        _block_files_by_identifier[block_id] = []
                                                    _block_files_by_identifier[block_id].append({
                                                        'file_path': _item_name,
                                                        'data': _json_data,
                                                        'pack_path': _file,
                                                        'original_id': block_id
                                                    })
                                                    continue  # Skip copying - will be merged later
                                                else:
                                                    self._copy_to_zip(_pack_zip, _item, _output_zip, _json_data, _file, identifier_manager)
                                    except Exception as e:
                                        _logging.warning(f"Error processing {_item_name}: {e}")
                                        self._copy_to_zip(_pack_zip, _item, _output_zip, None, _file, identifier_manager)
                                else:
                                    self._copy_to_zip(_pack_zip, _item, _output_zip, None, _file, identifier_manager)
                            else:
                                self._handle_json_item(_pack_zip, _item, 
                                    _json_contents_resource if _module_type == "resources" else _json_contents_behavior, 
                                    _output_zip, _module_type, _file, identifier_manager)
                        elif _item_name.endswith(".lang"):
                            if _module_type == "resources":
                                with _pack_zip.open(_item) as _lang_file:
                                    _lang_data = _lang_file.read().decode('latin-1')
                                    _lang_contents_resource.setdefault(_item_name, []).append(_lang_data)
                            elif _module_type in {"data", "script"}:
                                with _pack_zip.open(_item) as _lang_file:
                                    _lang_data = _lang_file.read().decode('latin-1')
                                    _lang_contents_behavior.setdefault(_item_name, []).append(_lang_data)
                        elif _item_name.endswith(".material"):
                            self._handle_json_item(_pack_zip, _item, _material_contents, _output_zip, _module_type, _file, identifier_manager)
                        elif _item_name.endswith(".mcfunction"):
                            with _pack_zip.open(_item) as _mcfunction_file:
                                try:
                                    _mcfunction_data = _mcfunction_file.read().decode('utf-8')
                                except UnicodeDecodeError:
                                    _mcfunction_data = _mcfunction_file.read().decode('latin-1')
                                _mcfunction_data = strip_bom(_mcfunction_data)
                                # Update identifiers in mcfunction files
                                if identifier_manager:
                                    try:
                                        _mcfunction_data = identifier_manager.update_text_identifiers(_mcfunction_data, _file)
                                    except Exception as e:
                                        _logging.warning(f"Error updating identifiers in {_item_name}: {e}")
                                _mcfunction_contents.setdefault(_item_name, []).append(_mcfunction_data)
                        else:
                            self._copy_to_zip(_pack_zip, _item, _output_zip, None, _file, identifier_manager)

            self._progress['value'] = _i + 1

        # Merge player-related JSON files for resource packs (entity folder)
        if _player_json_contents_resource:
            merged_player_data = {}
            for _item_name, _json_data_list in _player_json_contents_resource.items():
                for _json_data in _json_data_list:
                    self._merge_json_data(merged_player_data, _json_data)
            with _zipfile.ZipFile(_output_zip_path_resource, 'a') as _output_zip:
                _output_zip.writestr("entity/player.json", _json.dumps(merged_player_data, indent=2))

        # Merge player-related JSON files for behavior packs (entities folder)
        if _player_json_contents_behavior:
            merged_player_data = {}
            for _item_name, _json_data_list in _player_json_contents_behavior.items():
                for _json_data in _json_data_list:
                    self._merge_json_data(merged_player_data, _json_data)
            with _zipfile.ZipFile(_output_zip_path_behavior, 'a') as _output_zip:
                _output_zip.writestr("entities/player.json", _json.dumps(merged_player_data, indent=2))
        
        # Merge entity files by identifier (intelligent merging - same entity from multiple addons)
        # IMPORTANT: When merging entities with the same identifier, we keep the original identifier
        # and merge their components. We only rename identifiers if they're different entities.
        
        # Resource packs (entity folder)
        with _zipfile.ZipFile(_output_zip_path_resource, 'a') as _output_zip:
            for entity_id, entity_list in _entity_files_by_identifier_resource.items():
                if len(entity_list) > 1:
                    # Multiple addons modify same entity - merge them intelligently
                    # Keep the original identifier (don't rename when merging)
                    merged_entity = {}
                    for entity_file in entity_list:
                        # Merge data from each addon
                        self._merge_json_data(merged_entity, entity_file['data'])
                    # Ensure the merged entity keeps the original identifier
                    if 'minecraft:client_entity' in merged_entity:
                        if 'description' not in merged_entity['minecraft:client_entity']:
                            merged_entity['minecraft:client_entity']['description'] = {}
                        merged_entity['minecraft:client_entity']['description']['identifier'] = entity_id
                    # Use the first file's path as the output path
                    output_path = entity_list[0]['file_path']
                    _output_zip.writestr(output_path, _json.dumps(merged_entity, indent=2))
                else:
                    # Only one addon modifies this entity
                    # Check if identifier needs renaming (different entity with same identifier)
                    entity_file = entity_list[0]
                    final_data = entity_file['data']
                    # Only rename if IdentifierManager says to (for different entities with same ID)
                    if identifier_manager and identifier_manager.should_rename_identifier(entity_file['original_id']):
                        final_data = identifier_manager.update_json_identifiers(final_data, entity_file['pack_path'])
                    _output_zip.writestr(entity_file['file_path'], _json.dumps(final_data, indent=2))
        
        # Behavior packs (entities folder)
        with _zipfile.ZipFile(_output_zip_path_behavior, 'a') as _output_zip:
            for entity_id, entity_list in _entity_files_by_identifier_behavior.items():
                if len(entity_list) > 1:
                    # Multiple addons modify same entity - merge them intelligently
                    merged_entity = {}
                    for entity_file in entity_list:
                        self._merge_json_data(merged_entity, entity_file['data'])
                    # Ensure the merged entity keeps the original identifier
                    if 'minecraft:entity' in merged_entity:
                        if 'description' not in merged_entity['minecraft:entity']:
                            merged_entity['minecraft:entity']['description'] = {}
                        merged_entity['minecraft:entity']['description']['identifier'] = entity_id
                    output_path = entity_list[0]['file_path']
                    _output_zip.writestr(output_path, _json.dumps(merged_entity, indent=2))
                else:
                    entity_file = entity_list[0]
                    final_data = entity_file['data']
                    if identifier_manager and identifier_manager.should_rename_identifier(entity_file['original_id']):
                        final_data = identifier_manager.update_json_identifiers(final_data, entity_file['pack_path'])
                    _output_zip.writestr(entity_file['file_path'], _json.dumps(final_data, indent=2))
        
        # Merge item files by identifier
        with _zipfile.ZipFile(_output_zip_path_behavior, 'a') as _output_zip:
            for item_id, item_list in _item_files_by_identifier.items():
                if len(item_list) > 1:
                    # Multiple addons modify same item - merge them, keep original identifier
                    merged_item = {}
                    for item_file in item_list:
                        self._merge_json_data(merged_item, item_file['data'])
                    if 'minecraft:item' in merged_item:
                        if 'description' not in merged_item['minecraft:item']:
                            merged_item['minecraft:item']['description'] = {}
                        merged_item['minecraft:item']['description']['identifier'] = item_id
                    output_path = item_list[0]['file_path']
                    _output_zip.writestr(output_path, _json.dumps(merged_item, indent=2))
                else:
                    item_file = item_list[0]
                    final_data = item_file['data']
                    if identifier_manager and identifier_manager.should_rename_identifier(item_file['original_id']):
                        final_data = identifier_manager.update_json_identifiers(final_data, item_file['pack_path'])
                    _output_zip.writestr(item_file['file_path'], _json.dumps(final_data, indent=2))
        
        # Merge block files by identifier
        with _zipfile.ZipFile(_output_zip_path_behavior, 'a') as _output_zip:
            for block_id, block_list in _block_files_by_identifier.items():
                if len(block_list) > 1:
                    # Multiple addons modify same block - merge them, keep original identifier
                    merged_block = {}
                    for block_file in block_list:
                        self._merge_json_data(merged_block, block_file['data'])
                    if 'minecraft:block' in merged_block:
                        if 'description' not in merged_block['minecraft:block']:
                            merged_block['minecraft:block']['description'] = {}
                        merged_block['minecraft:block']['description']['identifier'] = block_id
                    output_path = block_list[0]['file_path']
                    _output_zip.writestr(output_path, _json.dumps(merged_block, indent=2))
                else:
                    block_file = block_list[0]
                    final_data = block_file['data']
                    if identifier_manager and identifier_manager.should_rename_identifier(block_file['original_id']):
                        final_data = identifier_manager.update_json_identifiers(final_data, block_file['pack_path'])
                    _output_zip.writestr(block_file['file_path'], _json.dumps(final_data, indent=2))

        # Merge other JSON, .lang, .material, and .mcfunction files
        self._merge_and_write_files(_json_contents_resource, _output_zip_path_resource)
        self._merge_and_write_files(_json_contents_behavior, _output_zip_path_behavior)
        self._merge_and_write_lang_files(_lang_contents_resource, _output_zip_path_resource)
        self._merge_and_write_lang_files(_lang_contents_behavior, _output_zip_path_behavior)
        self._merge_and_write_material_files(_material_contents, _output_zip_path_resource)
        self._merge_and_write_mcfunction_files(_mcfunction_contents, _output_zip_path_behavior)

        self._progress['value'] = len(_files)

        self._remove_empty_files(_output_zip_path_resource)
        self._remove_empty_files(_output_zip_path_behavior)

    def _merge_json_data(self, target, source):
        """Advanced recursive merge for Minecraft Bedrock JSON files."""
        return deep_merge_json(target, source)

    def _copy_to_zip(self, _pack_zip, _item, _output_zip, _json_data=None, _pack_path=None, _identifier_manager=None):
        with _pack_zip.open(_item) as _file_data:
            if _json_data is not None:
                # If identifier manager is provided, update identifiers in JSON data
                if _identifier_manager and _pack_path:
                    try:
                        _json_data = _identifier_manager.update_json_identifiers(_json_data, _pack_path)
                    except Exception as e:
                        _logging.warning(f"Error updating identifiers in {_item.filename}: {e}")
                _output_zip.writestr(_item.filename, _json.dumps(_json_data, indent=2))
            else:
                file_data = _file_data.read()
                # Update identifiers in text-based files (scripts, etc.)
                if _identifier_manager and _pack_path and _item.filename.endswith(('.js', '.mcfunction', '.lang')):
                    try:
                        text_content = file_data.decode('utf-8', errors='ignore')
                        updated_text = _identifier_manager.update_text_identifiers(text_content, _pack_path)
                        file_data = updated_text.encode('utf-8')
                    except Exception as e:
                        _logging.warning(f"Error updating identifiers in {_item.filename}: {e}")
                _output_zip.writestr(_item.filename, file_data)

    def _handle_json_item(self, _pack_zip, _item, _json_contents, _output_zip, _module_type=None, _pack_path=None, _identifier_manager=None):
        with _pack_zip.open(_item) as _json_file:
            try:
                _json_data = self._load_json_with_comments(_json_file)
                if isinstance(_json_data, dict):
                    # Update identifiers before storing for merging
                    if _identifier_manager and _pack_path:
                        try:
                            _json_data = _identifier_manager.update_json_identifiers(_json_data, _pack_path)
                        except Exception as e:
                            _logging.warning(f"Error updating identifiers in {_item.filename}: {e}")
                    _json_contents.setdefault(_item.filename, []).append(_json_data)
            except _json.JSONDecodeError:
                self._copy_to_zip(_pack_zip, _item, _output_zip, None, _pack_path, _identifier_manager)

    def _merge_and_write_files(self, _json_contents, _output_zip_path):
        for _json_file, _json_list in _json_contents.items():
            _merged_content = self._merge_json(_json_list, _os.path.basename(_json_file))
            with _zipfile.ZipFile(_output_zip_path, 'a') as _output_zip:
                _output_zip.writestr(_json_file, _json.dumps(_merged_content, indent=2))

    def _merge_and_write_lang_files(self, _lang_contents, _output_zip_path):
        for _lang_file, _lang_list in _lang_contents.items():
            _merged_lang_content = self._merge_lang_files(_lang_list)
            with _zipfile.ZipFile(_output_zip_path, 'a') as _output_zip:
                _output_zip.writestr(_lang_file, _merged_lang_content)

    def _merge_and_write_material_files(self, _material_contents, _output_zip_path):
        for _material_file, _material_list in _material_contents.items():
            _merged_material_content = self._merge_json(_material_list, _os.path.basename(_material_file))
            with _zipfile.ZipFile(_output_zip_path, 'a') as _output_zip:
                _output_zip.writestr(_material_file, _json.dumps(_merged_material_content, indent=2))

    def _merge_and_write_mcfunction_files(self, _mcfunction_contents, _output_zip_path):
        for _mcfunction_file, _mcfunction_list in _mcfunction_contents.items():
            _merged_mcfunction_content = "\n".join(strip_bom(x) for x in _mcfunction_list)
            _merged_mcfunction_content = strip_bom(_merged_mcfunction_content)
            with _zipfile.ZipFile(_output_zip_path, 'a') as _output_zip:
                _output_zip.writestr(_mcfunction_file, _merged_mcfunction_content)

    def _remove_empty_files(self, _zip_path):
        with _zipfile.ZipFile(_zip_path, 'r') as _zip:
            file_list = _zip.infolist()
            temp_file_path = _zip_path + ".temp"
            with _zipfile.ZipFile(temp_file_path, 'w') as temp_zip:
                for file in file_list:
                    if file.file_size > 0:
                        temp_zip.writestr(file, _zip.read(file.filename))

        _os.remove(_zip_path)
        _os.rename(temp_file_path, _zip_path)
    
    def _process_files(self, _selected_files):
        _renamed_files = {}
        _imported_files = []

        _bp_path = _os.path.join(self._out_dir, "Behavior_packs")
        _scripts_path = _os.path.join(_bp_path, "scripts")

        # Ensure the scripts directory is empty or create it if it doesn't exist
        if _os.path.exists(_scripts_path):
            _shutil.rmtree(_scripts_path)  # Remove the existing directory and its contents

        _main_js_path = _os.path.join(_scripts_path, "CodeNex.js")

        # Track renamed JS files for each pack
        _pack_renamed_files = {}

        for _mcpack_file in _selected_files:
            _pack_renamed_files[_mcpack_file] = {}
            try:
                with _zipfile.ZipFile(_mcpack_file, 'r') as _zip_ref:
                    for _item in _zip_ref.namelist():
                        if _item.startswith('scripts/'):
                            _zip_ref.extract(_item, _scripts_path)
                    try:
                        # Use the improved _get_manifest_data method which handles comments properly
                        _manifest_json = self._get_manifest_data(_mcpack_file)
                        if _manifest_json is None:
                            raise ValueError("Failed to parse manifest.json")
                    except KeyError:
                        log_error(KeyError)
                        _messagebox.showerror("Error", f"manifest.json not found in {_os.path.basename(_mcpack_file)}")
                        continue
                    except Exception as _e:
                        log_error(_e)
                        _messagebox.showerror("Error", f"Error reading manifest.json in {_os.path.basename(_mcpack_file)}: {str(_e)}")
                        continue

                    _entries = [_module.get("entry") for _module in _manifest_json.get("modules", []) if "entry" in _module]

                    for _entry in _entries:
                        if _entry:
                            try:
                                _script_folder = _os.path.dirname(_entry)
                                for _item in _zip_ref.namelist():
                                    if _item.startswith(_script_folder):
                                        _zip_ref.extract(_item, _scripts_path)

                                _old_script_path = _os.path.join(_scripts_path, _entry)
                                if _os.path.exists(_old_script_path):
                                    _random_number = _random.randint(1000, 9999)
                                    _new_script_name = f"{_random_number}_{_os.path.basename(_entry)}"
                                    _new_script_path = _os.path.join(_scripts_path, _script_folder, _new_script_name)
                                    _os.rename(_old_script_path, _new_script_path)
                                    _renamed_files[_os.path.basename(_entry)] = _new_script_name
                                    _pack_renamed_files[_mcpack_file][_os.path.basename(_entry)] = _new_script_name
                                    _imported_files.append(_new_script_path)
                                else:
                                    _imported_files.append(_os.path.join(_scripts_path, _entry))

                            except Exception as _e:
                                log_error(_e)
                                _messagebox.showerror("Error", f"Error processing entry {_entry} in {_os.path.basename(_mcpack_file)}: {str(_e)}")
                                continue
            except Exception as _e:
                log_error(_e)
                _messagebox.showerror("Error", f"Failed to process {_os.path.basename(_mcpack_file)}: {str(_e)}")

        # Update references between renamed files for each pack
        for _mcpack_file, _renamed_files_in_pack in _pack_renamed_files.items():
            for _root, _, _files in _os.walk(_scripts_path):
                for _file in _files:
                    if _file.endswith('.js'):
                        try:
                            _file_path = _os.path.join(_root, _file)
                            with open(_file_path, 'r', encoding='latin-1') as _js_file:
                                _content = _js_file.read()

                            for _old_name, _new_name in _renamed_files_in_pack.items():
                                # Prepare the old name patterns
                                _old_name_without_ext = _old_name.rsplit('.', 1)[0]  # Old name without extension
                                _new_name_without_ext = _new_name.rsplit('.', 1)[0]  # New name without extension

                                # Regex to match old name with or without extension after the last /
                                # Handles both single and double quotes by including both in the lookbehind and lookahead
                                _old_name_pattern_with_ext = rf"(?<=['\"/]){_re.escape(_old_name)}(?=['\";])"
                                _old_name_pattern_without_ext = rf"(?<=['\"/]){_re.escape(_old_name_without_ext)}(?=['\";])"

                                # Update content for old names with or without the .js extension (for both single and double quotes)
                                _content = _re.sub(_old_name_pattern_with_ext, _new_name, _content)
                                _content = _re.sub(_old_name_pattern_without_ext, _new_name_without_ext, _content)

                            # Write the updated content back to the file
                            with open(_file_path, 'w', encoding='latin-1') as _js_file:
                                _js_file.write(_content)
                        except Exception as _e:
                            log_error(_e)
                            _messagebox.showerror("Error", f"Error updating import statements in {_file}: {str(_e)}")
                            continue
                    
        # Write imports to CodeNex.js only if the files exist
        with open(_main_js_path, 'w', encoding='utf-8') as _main_js_file:
            for _imported_file in _imported_files:
                if _os.path.exists(_imported_file):
                    try:
                        _file_name = _os.path.relpath(_imported_file, _scripts_path).replace("\\", "/")
                        _main_js_file.write(f'import "./{_file_name}";\n')
                    except Exception as _e:
                        log_error(_e)
                        _messagebox.showerror("Error", f"Error writing to CodeNex.js for {_imported_file}: {str(_e)}")
                        continue

        try:
            with open(_main_js_path, 'r') as _main_js_file:
                _main_js_content = _main_js_file.read()

            _main_js_content = _main_js_content.replace('./scripts', '.')
            _main_js_content = _main_js_content.replace('import "./main.js";', '')
            _main_js_content = _main_js_content.replace('import "./Main.js";', '')

            with open(_main_js_path, 'w', encoding='utf-8') as _main_js_file:
                _main_js_file.write(_main_js_content)
        except Exception as _e:
            log_error(_e)
            _messagebox.showerror("Error", f"Error finalizing CodeNex.js: {str(_e)}")
    
    def _extract_feature_rules(self, _pack_zip, _item, _folder_name, _output_zip):
        with _pack_zip.open(_item) as _file_data:
            _output_zip.writestr(_os.path.join(_folder_name, _os.path.basename(_item.filename)), _file_data.read())
        
    def _merge_json(self, _json_list, _file_name):
        _merged = {}
        for _json in _json_list:
            _merged = deep_merge_json(_merged, _json)
        return _merged
    

    def _merge_dicts(self, _dict1, _dict2):
        for _key, _value in _dict2.items():
            if _key in _dict1:
                if isinstance(_dict1[_key], dict) and isinstance(_value, dict):
                    _dict1[_key] = self._merge_dicts(_dict1[_key], _value)
                elif isinstance(_dict1[_key], list) and isinstance(_value, list):
                    _dict1[_key].extend(_value)
                else:
                    _dict1[_key] = _value
            else:
                _dict1[_key] = _value
        return _dict1

    def _merge_lang_files(self, _lang_list):
        _merged_lang = {}
        for _lang_data in _lang_list:
            for _line in _lang_data.splitlines():
                if '=' in _line:
                    _key, _value = _line.split('=', 1)
                    _merged_lang[_key] = _value
        return '\n'.join([f"{_key}={_value}" for _key, _value in _merged_lang.items()])

    def _load_json_with_comments(self, _file):
        """Load JSON file with robust comment and error handling."""
        try:
            return load_json_data(_file.read())
        except Exception as e:
            _logging.error(f"Error reading JSON file: {e}")
            return None

    def _get_manifest_data(self, _file):
        """Extract and parse manifest.json from a pack file. Handles JSON with comments using json5."""
        try:
            with _zipfile.ZipFile(_file, 'r') as _pack_zip:
                # Try to find manifest.json (case-insensitive, may be in root or subdirectory)
                # Prefer root level, but accept subdirectories
                manifest_path = None
                root_manifest = None
                for name in _pack_zip.namelist():
                    name_lower = name.lower()
                    # Check for root level manifest.json
                    if name_lower == 'manifest.json':
                        root_manifest = name
                        break
                    # Check for manifest.json in subdirectories
                    elif name_lower.endswith('/manifest.json') and manifest_path is None:
                        manifest_path = name
                
                # Use root manifest if found, otherwise use subdirectory one
                if root_manifest:
                    manifest_path = root_manifest
                
                if manifest_path:
                    with _pack_zip.open(manifest_path) as _manifest_file:
                        return load_json_data(_manifest_file.read())
                else:
                    _logging.warning(f"manifest.json not found in file: {_file}")
                    return None
        except _zipfile.BadZipFile:
            _logging.error(f"Invalid ZIP file: {_file}")
            return None
        except Exception as e:
            _logging.error(f"Error opening file: {_file}: {e}")
            return None
        
        return None

    def _create_manifest(self):
        # Generate UUIDs for packs and modules
        _bp_header_uuid = str(_uuid.uuid4())
        _rp_header_uuid = str(_uuid.uuid4())
        _bp_module_uuid = str(_uuid.uuid4())
        _rp_module_uuid = str(_uuid.uuid4())

        # Retrieve highest versions found during extraction
        highest_bp_version = getattr(self, 'highest_bp_version', None)
        highest_rp_version = getattr(self, 'highest_rp_version', None)
        highest_server_version_full = getattr(self, 'highest_server_version_full', "1.13.0")
        highest_server_ui_version_full = getattr(self, 'highest_server_ui_version_full', "1.2.0")
        highest_gametest_version_full = getattr(self, 'highest_gametest_version_full', None)

        # Minimum required version for Minecraft Bedrock (1.13.0 is the minimum)
        min_required_version = [1, 13, 0]
        # Default fallback version (only used if no versions were found at all)
        default_version = [1, 21, 30]

        def compare_versions(version_a, version_b):
            """Compares two versions (assumed to be lists of integers). Returns True if version_a >= version_b"""
            if version_a is None:
                return False
            if version_b is None:
                return True
            for i in range(3):
                if version_a[i] > version_b[i]:
                    return True
                elif version_a[i] < version_b[i]:
                    return False
            return True  # Equal versions

        # Use the highest found version, ensuring it's at least the minimum required
        if highest_bp_version is None:
            # No version found, use default
            highest_bp_version = default_version
        elif not compare_versions(highest_bp_version, min_required_version):
            # Version found but below minimum, use minimum
            highest_bp_version = min_required_version

        if highest_rp_version is None:
            # No version found, use default
            highest_rp_version = default_version
        elif not compare_versions(highest_rp_version, min_required_version):
            # Version found but below minimum, use minimum
            highest_rp_version = min_required_version

        # Behavior Pack Manifest
        _manifest_behavior = {
            "format_version": 2,
            "header": {
                "description": "Modpack Created Using AutoBE - CodeNex",
                "name": "AutoBE Behavior",
                "uuid": _bp_header_uuid,
                "version": [1, 0, 0],
                "min_engine_version": highest_bp_version
            },
            "modules": [
                {
                    "description": "Created Using AutoBE - CodeNex",
                    "type": "data",
                    "uuid": _bp_module_uuid,
                    "version": [1, 0, 0]
                },
                {
                    "description": "gametesting",
                    "language": "javascript",
                    "type": "script",
                    "uuid": "a96a2dd3-86e9-4f82-ae5f-a717282d3f1c",
                    "version": [1, 0, 0],
                    "entry": "scripts/CodeNex.js"
                }
            ],
            "capabilities": ["script_eval"],
            "dependencies": [
                {
                    "uuid": _rp_header_uuid,
                    "version": [1, 0, 0]
                },
                {
                    "module_name": "@minecraft/server",
                    "version": highest_server_version_full
                },
                {
                    "module_name": "@minecraft/server-ui",
                    "version": highest_server_ui_version_full
                }
            ],
            "metadata": {
                "authors": ["CodeNex"]
            }
        }

        # Add @minecraft/server-gametest dependency if a version was found
        if highest_gametest_version_full:
            _manifest_behavior["dependencies"].append({
                "module_name": "@minecraft/server-gametest",
                "version": highest_gametest_version_full
            })

        # Resource Pack Manifest
        _manifest_resource = {
            "format_version": 2,
            "header": {
                "description": "Modpack Created Using AutoBE - CodeNex",
                "name": "AutoBE Resource",
                "uuid": _rp_header_uuid,
                "version": [1, 0, 0],
                "min_engine_version": highest_rp_version
            },
            "modules": [
                {
                    "description": "Created Using AutoBE - CodeNex",
                    "type": "resources",
                    "uuid": _rp_module_uuid,
                    "version": [1, 0, 0]
                }
            ],
            "dependencies": [
                {
                    "uuid": _bp_header_uuid,
                    "version": [1, 0, 0]
                }
            ],
            "metadata": {
                "authors": ["CodeNex"]
            }
        }

        # Paths for the pack files
        _bp_path = _os.path.join(self._out_dir, "behavior_pack.zip")
        _rp_path = _os.path.join(self._out_dir, "resource_pack.zip")

        try:
            # Write behavior pack manifest to zip
            with _zipfile.ZipFile(_bp_path, 'a') as _bp_zip:
                _bp_zip.writestr("manifest.json", _json.dumps(_manifest_behavior, indent=2))

            # Write resource pack manifest to zip
            with _zipfile.ZipFile(_rp_path, 'a') as _rp_zip:
                _rp_zip.writestr("manifest.json", _json.dumps(_manifest_resource, indent=2))

            # Convert zip files to .mcpack files
            _bp_new_path = _os.path.join(self._out_dir, "behavior_pack.mcpack")
            _shutil.move(_bp_path, _bp_new_path)

            _rp_new_path = _os.path.join(self._out_dir, "resource_pack.mcpack")
            _shutil.move(_rp_path, _rp_new_path)

        except Exception as e:
            log_error(e)
            _messagebox.showerror("Error", f"An error occurred during manifest creation: {str(e)}")

    def _move_tick_and_delete_functions(self):
        _functions_folder = _os.path.join(self._out_dir, "functions")
        _entities_folder = _os.path.join(self._out_dir, "entities")
        
        _bp_path = _os.path.join(self._out_dir, "behavior_pack.mcpack")
        _rp_path = _os.path.join(self._out_dir, "resource_pack.mcpack")

        _bp_functions_folder = "functions"
        _rp_functions_folder = f"{_bp_functions_folder}/"
        
        _bp_entities_folder = "entities"
        _rp_entities_folder = f"{_bp_entities_folder}/"

        _bp_tick_path = f"{_bp_functions_folder}/tick.json"
        _rp_tick_path = f"{_rp_functions_folder}tick.json"
        
        _bp_player_path = f"{_bp_entities_folder}/player.json"
        _rp_player_path = f"{_rp_entities_folder}player.json"

        try:
            # Move tick.json from resource pack to behavior pack
            with _zipfile.ZipFile(_rp_path, 'r') as _rp_zip:
                with _zipfile.ZipFile(_bp_path, 'a') as _bp_zip:
                    try:
                        _tick_data = _rp_zip.read(_rp_tick_path)
                        _bp_zip.writestr(_bp_tick_path, _tick_data)
                    except KeyError:
                        _logging.warning(f"'{_rp_tick_path}' not found in resource pack.")
                    
                    try:
                        _player_data = _rp_zip.read(_rp_player_path)
                        _bp_zip.writestr(_bp_player_path, _player_data)
                    except KeyError:
                        _logging.warning(f"'{_rp_player_path}' not found in resource pack.")

        except Exception as _e:
            _logging.error(f"An error occurred during the initial file operations: {_e}")

        try:
            # Extract and delete functions folder
            with _zipfile.ZipFile(_rp_path, 'a') as _rp_zip:
                for _file in list(_rp_zip.namelist()):
                    if _file.startswith(_rp_functions_folder):
                        try:
                            _rp_zip.extract(_file, self._out_dir)
                            _os.remove(_os.path.join(self._out_dir, _file))
                        except FileNotFoundError:
                            _logging.warning(f"File '{_file}' not found during extraction.")
                try:
                    _shutil.rmtree(_functions_folder)
                except FileNotFoundError:
                    _logging.warning(f"Folder '{_functions_folder}' not found during removal.")

        except Exception as _e:
            _logging.error(f"An error occurred while processing functions folder: {_e}")

        try:
            # Extract and delete entities folder
            with _zipfile.ZipFile(_rp_path, 'a') as _rp_zip:
                for _file in list(_rp_zip.namelist()):
                    if _file.startswith(_rp_entities_folder):
                        try:
                            _rp_zip.extract(_file, self._out_dir)
                            _os.remove(_os.path.join(self._out_dir, _file))
                        except FileNotFoundError:
                            _logging.warning(f"File '{_file}' not found during extraction.")
                try:
                    _shutil.rmtree(_entities_folder)
                except FileNotFoundError:
                    _logging.warning(f"Folder '{_entities_folder}' not found during removal.")

        except Exception as _e:
            _messagebox.showinfo("Error", f"An error occurred: {_e}")

    def _delete_manifest_files(self):
        _packs = ["behavior_pack.zip", "resource_pack.zip"]

        for _pack in _packs:
            _pack_path = _os.path.join(self._out_dir, _pack)
            _temp_pack_path = _os.path.join(self._out_dir, f"temp_{_pack}")

            try:
                with _zipfile.ZipFile(_pack_path, 'r') as _zip_read:
                    with _zipfile.ZipFile(_temp_pack_path, 'w') as _zip_write:
                        for _item in _zip_read.infolist():
                            if _item.filename not in ["manifest.json", "package.json", "contents.json", ".data", "package-lock.json", "signatures.json"]:
                                _data = _zip_read.read(_item.filename)
                                _zip_write.writestr(_item, _data)

                _os.remove(_pack_path)
                _os.rename(_temp_pack_path, _pack_path)

            except _zipfile.BadZipFile:
                _logging.error(f"Bad ZIP file: {_pack_path}", exc_info=True)
                _messagebox.showerror("Error", f"Bad ZIP file: {_pack_path}")
            except FileNotFoundError:
                _logging.error(f"File not found: {_pack_path}", exc_info=True)
                pass
            except Exception as _e:
                pass

    def _move_and_cleanup(self):
        _bp_path = _os.path.join(self._out_dir, "Behavior_packs", "scripts", "scripts")
        _mainjs_path = _os.path.join(self._out_dir, "Behavior_packs", "scripts", "CodeNex.js")
        _scriptswe_path = _os.path.join(self._out_dir, "scripts")

        try:
            _shutil.move(_bp_path, self._out_dir)
        except FileNotFoundError:
            print(f"Directory '{_bp_path}' does not exist.")

        try:
            _shutil.move(_mainjs_path, _scriptswe_path)
        except FileNotFoundError:
            print(f"File '{_mainjs_path}' does not exist.")

        try:
            _bp_path = _os.path.join(self._out_dir, "Behavior_packs")
            _shutil.rmtree(_bp_path)
        except FileNotFoundError:
            print(f"Directory '{_bp_path}' does not exist.")

    def _update_behavior_pack(self):
        _bp_path = _os.path.join(self._out_dir, "behavior_pack.mcpack")
        _scripts_folder = _os.path.join(self._out_dir, "scripts")

        if _os.path.exists(_bp_path):
            _temp_dir = _tempfile.mkdtemp(prefix='temp_unpack_')
            _os.makedirs(_temp_dir, exist_ok=True)

            with _zipfile.ZipFile(_bp_path, 'r') as _zip_ref:
                _zip_ref.extractall(_temp_dir)

            _scripts_path_in_temp = _os.path.join(_temp_dir, "scripts")
            if (_os.path.exists(_scripts_path_in_temp)):
                _shutil.rmtree(_scripts_path_in_temp)
                
            _subpacks_path_in_temp = _os.path.join(_temp_dir, "subpacks")
            if (_os.path.exists(_subpacks_path_in_temp)):
                _shutil.rmtree(_subpacks_path_in_temp)

            _shutil.copytree(_scripts_folder, _scripts_path_in_temp)

            _new_bp_path = _os.path.join(self._out_dir, "behavior_pack.mcpack")
            with _zipfile.ZipFile(_new_bp_path, 'w') as _zip_ref:
                for _root, _dirs, _files in _os.walk(_temp_dir):
                    for _file in _files:
                        _file_path = _os.path.join(_root, _file)
                        _arcname = _os.path.relpath(_file_path, _temp_dir)
                        _zip_ref.write(_file_path, _arcname)

            _shutil.rmtree(_temp_dir)
            _shutil.rmtree(_scripts_folder)
            _logging.info("Process 3/4 Completed Successfully!")
        else:
            _logging.error("behavior_pack.mcpack not found", exc_info=True)
            _messagebox.showwarning("Error", "behavior_pack.mcpack not found")

    def _merge_flipbook_textures(self, _selected_files):
        if not _selected_files:
            _logging.error("No .mcpack files selected", exc_info=True)
            _messagebox.showerror("Error", "Please select .mcpack files")
            return

        _merged_textures = []

        for _mcpack_file in _selected_files:
            try:
                with _zipfile.ZipFile(_mcpack_file, 'r') as _zip_ref:
                    try:
                        _merged_textures.extend(load_json_data(_zip_ref.read('textures/flipbook_textures.json')) or [])
                    except KeyError: pass
            except Exception as _e:
                _logging.error(f"An error occurred while merging flipbook textures: {_e}", exc_info=True)

        _merged_zip_path = _os.path.join(self._out_dir, "flipbook_textures.zip")
        with _zipfile.ZipFile(_merged_zip_path, 'w') as _merged_zip:
            _merged_zip.writestr('flipbook_textures.json', _json.dumps(_merged_textures))

    def _merge_textures_list(self, _selected_files):
        if not _selected_files:
            _logging.error("No .mcpack files selected", exc_info=True)
            _messagebox.showerror("Error", "Please select .mcpack files")
            return

        _merged_textures = []

        for _mcpack_file in _selected_files:
            try:
                with _zipfile.ZipFile(_mcpack_file, 'r') as _zip_ref:
                    try:
                        _merged_textures.extend(load_json_data(_zip_ref.read('textures/textures_list.json')) or [])
                    except KeyError: pass
            except Exception as _e:
                _logging.error(f"An error occurred while merging textures list: {_e}", exc_info=True)

        _merged_zip_path = _os.path.join(self._out_dir, "textures_list.zip")
        with _zipfile.ZipFile(_merged_zip_path, 'w') as _merged_zip:
            _merged_zip.writestr('textures_list.json', _json.dumps(_merged_textures))

    def _extract_and_delete_zip_files(self):
        _flipbook_zip_path = _os.path.join(self._out_dir, "flipbook_textures.zip")
        _textures_zip_path = _os.path.join(self._out_dir, "textures_list.zip")

        try:
            with _zipfile.ZipFile(_flipbook_zip_path, 'r') as _flipbook_zip:
                _flipbook_zip.extract('flipbook_textures.json', self._out_dir)
        except FileNotFoundError:
            pass

        try:
            with _zipfile.ZipFile(_textures_zip_path, 'r') as _textures_zip:
                _textures_zip.extract('textures_list.json', self._out_dir)
        except FileNotFoundError:
            pass

        try:
            _os.remove(_flipbook_zip_path)
        except FileNotFoundError:
            pass

        try:
            _os.remove(_textures_zip_path)
        except FileNotFoundError:
            pass

    def _move_to_resource_pack(self):
        _rp_path = _os.path.join(self._out_dir, "resource_pack.mcpack")
        _textures_folder_name = "textures"

        if not _os.path.exists(_rp_path):
            _logging.warning("resource_pack.mcpack not found in output directory", exc_info=True)
            _messagebox.showwarning("Warning", "resource_pack.mcpack not found in output directory")
            return

        try:
            _temp_dir = _tempfile.mkdtemp(prefix='temp_unpack_resource_pack_')
            _os.makedirs(_temp_dir, exist_ok=True)
                
            with _zipfile.ZipFile(_rp_path, 'r') as _zip_ref:
                _zip_ref.extractall(_temp_dir)

            _functions_path_in_temp = _os.path.join(_temp_dir, "functions")
            if (_os.path.exists(_functions_path_in_temp)):
                _shutil.rmtree(_functions_path_in_temp)
                
            _entities_path_in_temp = _os.path.join(_temp_dir, "entities")
            if (_os.path.exists(_entities_path_in_temp)):
                _shutil.rmtree(_entities_path_in_temp)
                
            _subpacks_path_in_temp = _os.path.join(_temp_dir, "subpacks")
            if (_os.path.exists(_subpacks_path_in_temp)):
                _shutil.rmtree(_subpacks_path_in_temp)

            _textures_folder = _os.path.join(_temp_dir, _textures_folder_name)

            _flipbook_textures_source = _os.path.join(self._out_dir, "flipbook_textures.json")
            _flipbook_textures_dest = _os.path.join(_textures_folder, "flipbook_textures.json")
            _shutil.move(_flipbook_textures_source, _flipbook_textures_dest)

            _textures_list_source = _os.path.join(self._out_dir, "textures_list.json")
            _textures_list_dest = _os.path.join(_textures_folder, "textures_list.json")
            _shutil.move(_textures_list_source, _textures_list_dest)

            _new_rp_path = _os.path.join(self._out_dir, "updated_resource_pack.mcpack")
            with _zipfile.ZipFile(_new_rp_path, 'w') as _zip_ref:
                for _root, _dirs, _files in _os.walk(_temp_dir):
                    for _file in _files:
                        _file_path = _os.path.join(_root, _file)
                        _arcname = _os.path.relpath(_file_path, _temp_dir)
                        _zip_ref.write(_file_path, _arcname)

            _shutil.rmtree(_temp_dir)
            _shutil.move(_new_rp_path, _rp_path)
            _shutil.rmtree(_flipbook_textures_source)
            _shutil.rmtree(_textures_list_source)
            _logging.info("Process 4/4 Completed Successfully!")

        except Exception as _e:
            pass
            

    def mcpacker_process_files(self, input_files, output_dir):
        import shutil
        failed, success, tempdirs = [], [], []
        total_files = len(input_files)
        
        # Get the selected mode
        mode = getattr(self, 'mcpacker_mode_var', _tk.StringVar(value="pack")).get()
        
        # Step 1: Reading Files
        self._root.after(0, lambda: self._update_mcpacker_progress(1, 10, f"Reading {total_files} file(s)..."))
        
        if mode == "extract":
            # Extraction mode: Extract .mcpack/.mcaddon files to folders
            self._root.after(0, lambda: self._update_mcpacker_progress(2, 25, "Preparing extraction..."))
            
            for idx, in_file in enumerate(input_files):
                try:
                    progress = 25 + int((idx / total_files) * 70)
                    file_name = _os.path.basename(in_file)
                    self._root.after(0, lambda p=progress, f=file_name: self._update_mcpacker_progress(2, p, f"Extracting: {f}..."))
                    
                    # Check if file is .mcpack or .mcaddon
                    if not in_file.lower().endswith(('.mcpack', '.mcaddon', '.zip')):
                        failed.append((in_file, "Not a .mcpack, .mcaddon, or .zip file"))
                        continue
                    
                    # Create output folder name
                    base_name = _os.path.splitext(_os.path.basename(in_file))[0]
                    out_folder = _os.path.join(output_dir, base_name)
                    
                    # If folder exists, add number suffix
                    counter = 1
                    original_out_folder = out_folder
                    while _os.path.exists(out_folder):
                        out_folder = f"{original_out_folder}_{counter}"
                        counter += 1
                    
                    # Extract the archive
                    with _zipfile.ZipFile(in_file, 'r') as zip_ref:
                        zip_ref.extractall(out_folder)
                    
                    success.append(out_folder)
                    
                except Exception as e:
                    failed.append((in_file, str(e)))
            
            # Step 4: Finalizing
            self._root.after(0, lambda: self._update_mcpacker_progress(4, 90, "Finalizing..."))
            
        else:
            # Pack mode: Original behavior - convert folders to .mcpack
            # Step 2: Finding Packs
            self._root.after(0, lambda: self._update_mcpacker_progress(2, 25, "Finding valid packs in files..."))
            all_packs = []
            for idx, in_file in enumerate(input_files):
                try:
                    progress = 25 + int((idx / total_files) * 30)
                    self._root.after(0, lambda p=progress, f=_os.path.basename(in_file): self._update_mcpacker_progress(2, p, f"Finding packs in: {f}..."))
                    packs = find_valid_packs(in_file)
                    if not packs:
                        failed.append((in_file, "No manifest.json found"))
                        continue
                    all_packs.append((in_file, packs))
                except Exception as e:
                    failed.append((in_file, str(e)))
            
            # Step 3: Packaging Files
            self._root.after(0, lambda: self._update_mcpacker_progress(3, 55, "Packaging files into MCPACK format..."))
            
            total_packs = sum(len(packs) for _, packs in all_packs)
            pack_count = 0
            for in_file, packs in all_packs:
                for pack_folder in packs:
                    try:
                        base_name = _os.path.splitext(_os.path.basename(in_file))[0]
                        out_name = base_name + ".mcpack"
                        if len(packs) > 1:
                            idx = packs.index(pack_folder) + 1
                            out_name = f"{base_name}_{idx}.mcpack"
                        out_path = _os.path.join(output_dir, out_name)
                        
                        progress = 55 + int((pack_count / total_packs) * 35) if total_packs > 0 else 55
                        self._root.after(0, lambda p=progress, n=out_name: self._update_mcpacker_progress(3, p, f"Packaging: {n}..."))
                        
                        zip_pack_folder(pack_folder, out_path)
                        success.append(out_path)
                        if pack_folder.startswith(_tempfile.gettempdir()):
                            tempdirs.append(pack_folder)
                        pack_count += 1
                    except Exception as e:
                        failed.append((in_file, str(e)))
            
            # Step 4: Finalizing
            self._root.after(0, lambda: self._update_mcpacker_progress(4, 90, "Finalizing and cleaning up..."))
        for d in tempdirs:
            try:
                shutil.rmtree(d)
            except:
                pass
        
        # Show completion message in progress display
        if failed:
            failed_list = "\n".join([f"- {_os.path.basename(fname)}: {reason}" for fname, reason in failed[:5]])
            if len(failed) > 5:
                failed_list += f"\n... and {len(failed) - 5} more"
            if mode == "extract":
                message = f"Completed: {len(success)} extracted, {len(failed)} failed"
                self._root.after(0, lambda: self._update_mcpacker_progress(4, 100, message))
                error_msg = f"Extracted {len(success)} folder(s).\n\nFailed files:\n{failed_list}"
                self._root.after(0, lambda: _messagebox.showerror("MCPACKER Result - Some Files Failed", error_msg))
            else:
                message = f"Completed: {len(success)} exported, {len(failed)} failed"
                self._root.after(0, lambda: self._update_mcpacker_progress(4, 100, message))
                error_msg = f"Exported {len(success)} MCPACK(s).\n\nFailed files:\n{failed_list}"
                self._root.after(0, lambda: _messagebox.showerror("MCPACKER Result - Some Files Failed", error_msg))
        else:
            if mode == "extract":
                message = f"Successfully extracted {len(success)} folder(s)! ✓"
                self._root.after(0, lambda: self._update_mcpacker_progress(4, 100, message))
            else:
                message = f"Successfully exported {len(success)} MCPACK(s)! ✓"
                self._root.after(0, lambda: self._update_mcpacker_progress(4, 100, message))

    def _update_mcpacker_progress(self, step, progress_percent, message):
        """Update the MCPACKER progress display with current step and message."""
        if hasattr(self, '_mcpacker_progress_step_label'):
            self._mcpacker_progress_step_label.config(text=message)
            self._mcpacker_progress['value'] = progress_percent
            self._root.update_idletasks()
            
            # Update step indicators
            if hasattr(self, '_mcpacker_step_labels') and 1 <= step <= 4:
                for i in range(4):
                    if i < step - 1:
                        # Completed steps
                        self._mcpacker_step_labels[i]['status'].config(text="✓", fg='#9333ea')
                        self._mcpacker_step_labels[i]['label'].config(fg='#FFFFFF')
                    elif i == step - 1:
                        # Current step
                        self._mcpacker_step_labels[i]['status'].config(text="→", fg='#9333ea')
                        self._mcpacker_step_labels[i]['label'].config(fg='#9333ea')
                    else:
                        # Pending steps
                        self._mcpacker_step_labels[i]['status'].config(text="○", fg='#666666')
                        self._mcpacker_step_labels[i]['label'].config(fg='#999999')
                # Mark all as complete if step 4 is done
                if step == 4:
                    for i in range(4):
                        self._mcpacker_step_labels[i]['status'].config(text="✓", fg='#9333ea')
                        self._mcpacker_step_labels[i]['label'].config(fg='#FFFFFF')

    def _update_mcpacker_mode_labels(self):
        """Update step labels based on selected mode."""
        if hasattr(self, '_mcpacker_step_labels') and len(self._mcpacker_step_labels) >= 4:
            mode = self.mcpacker_mode_var.get()
            if mode == "extract":
                self._mcpacker_step_labels[2]['label'].config(text="Extracting Files")
            else:
                self._mcpacker_step_labels[2]['label'].config(text="Packaging Files")
    
    def _reset_mcpacker_progress(self):
        """Reset MCPACKER progress display to initial state."""
        if hasattr(self, '_mcpacker_progress_step_label'):
            self._mcpacker_progress_step_label.config(text="Ready to process...")
            self._mcpacker_progress['value'] = 0
            if hasattr(self, '_mcpacker_step_labels'):
                for step_info in self._mcpacker_step_labels:
                    step_info['status'].config(text="○", fg='#666666')
                    step_info['label'].config(fg='#999999')

    def start_mcpacker(self):
        files = self._mcpacker_files  # Use stored file paths
        output_dir = self.output_dir_var.get()
        if not files or not output_dir:
            _messagebox.showerror("Error", "Please select files and an output directory.")
            return
        
        # Disable start button during processing
        self._btn_mcpacker_start.config(state='disabled')
        
        # Run processing in a separate thread to prevent UI freezing
        def process_thread():
            try:
                self._root.after(0, lambda: self._reset_mcpacker_progress())
                self._root.after(0, lambda: self._update_mcpacker_progress(0, 0, "Initializing process..."))
                self.mcpacker_process_files(files, output_dir)
                self._root.after(0, lambda: self._update_mcpacker_progress(4, 100, "Processing completed successfully! ✓"))
                
            except Exception as e:
                _logging.error("An error occurred during MCPACKER process", exc_info=True)
                self._root.after(0, lambda: _messagebox.showerror("Error", f"An error occurred: {e}"))
                self._root.after(0, lambda: self._update_mcpacker_progress(0, 0, f"Error: {str(e)}"))
            finally:
                # Re-enable start button
                self._root.after(0, lambda: self._btn_mcpacker_start.config(state='normal'))
        
        threading.Thread(target=process_thread, daemon=True).start()

def strip_bom(text):
    # Remove Unicode BOM
    if text.startswith('\ufeff'):
        text = text[1:]
    # Remove UTF-8 BOM interpreted as latin-1 (ï»¿)
    if text.startswith('ï»¿'):
        text = text[3:]
    return text

def read_text_file_utf8_strip_bom(path):
    with open(path, 'r', encoding='utf-8') as f:
        text = f.read()
    if text.startswith('\ufeff'):
        text = text[1:]
    return text

def write_text_file_utf8(path, content):
    with open(path, 'w', encoding='utf-8') as f:
        f.write(content)

if __name__ == "__main__":
    _logging.basicConfig(level=_logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')
    if platform.system() == "Windows":
        try:
            _ctypes.windll.user32.ShowWindow(_ctypes.windll.kernel32.GetConsoleWindow(), 0)
        except Exception:
            pass
    _root = _tk.Tk()
    _root.withdraw()  # Hide window initially to prevent white screen flash
    _app = _App1(_root)
    _root.mainloop()
