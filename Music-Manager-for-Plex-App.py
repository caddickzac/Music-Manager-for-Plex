from __future__ import annotations
import os
import io
import re
import json
import hashlib
import subprocess
import requests
import shutil
from dataclasses import dataclass, field
from typing import Dict, List
from glob import glob
import streamlit as st
import pandas as pd
from plexapi.server import PlexServer  # type: ignore
try:
    import networkx as nx
    import plotly.graph_objects as go
    import community.community_louvain as community_louvain
    HAS_GALAXY_DEPS = True
except ImportError:
    HAS_GALAXY_DEPS = False
from Scripts import plex_galaxy, artist_recommender  # Import from the subfolder

# --- Version Configuration ---
CURRENT_VERSION = "v2.3.1"
REPO_OWNER = "caddickzac"
REPO_NAME = "Music-Manager-for-Plex"

@st.cache_data(ttl=10800)  # Check every 4 hours
def check_github_updates():
    try:
        url = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/releases/latest"
        response = requests.get(url, timeout=2)
        if response.status_code == 200:
            data = response.json()
            latest_version = data["tag_name"]
            html_url = data["html_url"]
            return latest_version, html_url
    except:
        pass # Fail silently if no internet or API limit hit
    return None, None

APP_TITLE = "Music Manager for Plex"
APP_DIR = os.getcwd()
SCRIPTS_DIR = os.path.join(APP_DIR, "Scripts")
EXPORTS_DIR = os.path.join(APP_DIR, "Exports")
CONFIG_TXT = os.path.join(APP_DIR, "config.txt")
PLAYLIST_CREATOR_SCRIPT = os.path.join(SCRIPTS_DIR, "playlist_creator.py")
PRESETS_DIR = os.path.join(APP_DIR, "Playlist_Presets")

# 1. Define internal source files and external destination
INTERNAL_FILES = {
    "/app/Scripts/playlist_creator.py": "Scripts",
    "/app/Scripts/export_library_metadata.py": "Scripts",
    "/app/App Documentation.pdf": None,
    "/app/Music_Manager_Track_Level_Data_Dictionary.csv": None
}
EXTERNAL_EXTRAS_PATH = "/app/Extras"
EXAMPLES_DIR = os.path.join(EXTERNAL_EXTRAS_PATH, "Playlist Examples")

# 2. Define folders that need recursive permission syncing
FOLDERS_TO_UNLOCK = [EXPORTS_DIR, PRESETS_DIR, EXTERNAL_EXTRAS_PATH, EXAMPLES_DIR]

def apply_unraid_permissions():
    """Forces 777 permissions recursively to prevent SMB/Unraid lockouts."""
    for folder in FOLDERS_TO_UNLOCK:
        if os.path.exists(folder):
            try:
                os.chmod(folder, 0o777)
                for root, dirs, files in os.walk(folder):
                    for d in dirs:
                        os.chmod(os.path.join(root, d), 0o777)
                    for f in files:
                        os.chmod(os.path.join(root, f), 0o777)
            except Exception as e:
                print(f"Permission Sync Warning for {folder}: {e}")

# 3. Handle File Exposure logic
def expose_internal_files():
    """Copies internal documentation and scripts to the mapped Extras folder."""
    if not os.path.exists(EXTERNAL_EXTRAS_PATH):
        try:
            os.makedirs(EXTERNAL_EXTRAS_PATH)
            os.chmod(EXTERNAL_EXTRAS_PATH, 0o777)
        except:
            pass

    for source_path, subfolder in INTERNAL_FILES.items():
        if os.path.exists(source_path):
            filename = os.path.basename(source_path)
            dest_dir = os.path.join(EXTERNAL_EXTRAS_PATH, subfolder) if subfolder else EXTERNAL_EXTRAS_PATH
            
            if not os.path.exists(dest_dir):
                os.makedirs(dest_dir)
                os.chmod(dest_dir, 0o777)

            dest_path = os.path.join(dest_dir, filename)
            
            # CHANGED: Removed the 'if not os.path.exists' check.
            # We now ALWAYS overwrite to ensure the Extras folder matches the latest app version.
            try:
                shutil.copy(source_path, dest_path)
                os.chmod(dest_path, 0o777)
                print(f"Successfully updated {filename} in {dest_dir}")
            except Exception as e:
                print(f"Error updating {filename}: {e}")

def deploy_example_presets():
    """
    Copies bundled preset JSONs from /app/Bundled_Presets/ (baked into the image,
    never overridden by volume mounts) to two destinations:
      1. Extras/Playlist Examples/ — always overwrites (app-managed reference copy)
      2. Playlist_Presets/         — only if the file doesn't exist yet (user edits stick)
    """
    internal_presets_dir = "/app/Bundled_Presets"
    if not os.path.isdir(internal_presets_dir):
        return

    # Ensure destinations exist
    for d in [EXAMPLES_DIR, PRESETS_DIR]:
        try:
            os.makedirs(d, exist_ok=True)
            os.chmod(d, 0o777)
        except Exception:
            pass

    for fn in os.listdir(internal_presets_dir):
        if not fn.lower().endswith(".json"):
            continue
        src = os.path.join(internal_presets_dir, fn)

        # 1. Always overwrite in Extras/Playlist Examples/
        try:
            dst = os.path.join(EXAMPLES_DIR, fn)
            shutil.copy(src, dst)
            os.chmod(dst, 0o777)
        except Exception as e:
            print(f"Warning: could not deploy example to Extras '{fn}': {e}")

        # 2. Copy to user presets only if not already there (preserve customisations)
        try:
            dst_user = os.path.join(PRESETS_DIR, fn)
            if not os.path.exists(dst_user):
                shutil.copy(src, dst_user)
                os.chmod(dst_user, 0o777)
        except Exception as e:
            print(f"Warning: could not seed user preset '{fn}': {e}")

# Run setup logic before the UI loads
expose_internal_files()
deploy_example_presets()
apply_unraid_permissions()

# ---------------------------
# Config dataclass
# ---------------------------
@dataclass
class AppConfig:
    plex_baseurl: str = ""
    plex_token: str = ""
    plex_library: str = "Music"

# ---------------------------
# Utilities: config.txt loader
# ---------------------------
def _strip_wrapping_quotes(s: str) -> str:
    s = s.strip()
    if len(s) >= 2 and s[0] == s[-1] and s[0] in ("'", '"'):
        return s[1:-1].strip()
    return s

def load_config_txt() -> AppConfig:
    """
    Reads ./config.txt for settings.
    Supports: "Plex URL: ..." OR "PLEX_URL = ..."
    """
    baseurl = ""
    token = ""
    library = "Music"  # Default if missing
    
    if not os.path.isfile(CONFIG_TXT):
        return AppConfig(plex_baseurl=baseurl, plex_token=token, plex_library=library)

    try:
        with open(CONFIG_TXT, "r", encoding="utf-8") as f:
            for raw in f:
                line = raw.strip()
                # Skip comments or empty lines
                if not line or line.startswith("#"):
                    continue
                
                # Determine separator (: or =)
                sep = ":" if ":" in line else "="
                if sep not in line:
                    continue
                
                key, val = line.split(sep, 1)
                
                # Normalize key: lowercase and replace underscores with spaces
                # This makes "PLEX_URL" and "plex url" treated identical
                key = key.strip().lower().replace("_", " ") 
                val = _strip_wrapping_quotes(val)
                
                if key == "plex url":
                    baseurl = val
                elif key == "plex token":
                    token = val
                elif key == "plex library" or key == "plex library name":
                    library = val
                    
    except Exception as e:
        print(f"Error reading config.txt: {e}")
        pass
        
    return AppConfig(plex_baseurl=baseurl, plex_token=token, plex_library=library)

# ---------------------------
# Dynamic script discovery (folder-based)
# ---------------------------
def prettify_action_label(path: str) -> str:
    base = os.path.splitext(os.path.basename(path))[0]
    return base.replace("_", " ")

@dataclass
class ScriptInfo:
    action: str
    cmd: List[str]
    schema: List[str]
    path: str
    expected_values: List[str] = field(default_factory=list)

def scripts_signature() -> str:
    """
    Build a signature of all .py/.json files in ./Scripts so Streamlit cache
    invalidates whenever you add/edit/rename scripts or sidecars.
    """
    h = hashlib.sha1()
    paths = sorted(
        glob(os.path.join(SCRIPTS_DIR, "*.py")) +
        glob(os.path.join(SCRIPTS_DIR, "*.json"))
    )
    for p in paths:
        try:
            stt = os.stat(p)
            h.update(p.encode("utf-8"))
            h.update(str(stt.st_mtime_ns).encode("utf-8"))
            h.update(str(stt.st_size).encode("utf-8"))
        except FileNotFoundError:
            pass
    return h.hexdigest()

def discover_scripts(include_exports: bool = True, _sig: str = "") -> Dict[str, ScriptInfo]:
    """
    Discover scripts in SCRIPTS_DIR.
    Excludes system files (__init__.py) and UI modules (plex_galaxy.py).
    """
    reg: Dict[str, ScriptInfo] = {}
    if not os.path.isdir(SCRIPTS_DIR):
        return reg

    # Files to explicitly ignore in the dropdown
    IGNORED_FILES = {
        "__init__.py", 
        "plex_galaxy.py", 
        "playlist_creator.py",
        "artist_recommender.py"
    }

    for py in sorted(glob(os.path.join(SCRIPTS_DIR, "*.py"))):
        base = os.path.basename(py).lower()
        
        # SKIP IGNORED FILES
        if base in IGNORED_FILES:
            continue

        meta_path = os.path.splitext(py)[0] + ".json"
        action = prettify_action_label(py)
        schema: List[str] = []
        expected_values: List[str] = []

        try:
            if os.path.isfile(meta_path):
                with open(meta_path, "r", encoding="utf-8") as f:
                    meta = json.load(f)
                    action = meta.get("action", action)
                    schema = list(meta.get("expected_columns", []))
                    expected_values = list(meta.get("expected_values", []))
        except Exception:
            pass

        # Hide export scripts from Update tab
        is_export = (
            "export" in base or
            "export" in action.lower() or
            base == "export_library_metadata.py"
        )
        if not include_exports and is_export:
            continue

        # Ensure unique action names
        key = action
        suffix = 2
        while key in reg:
            key = f"{action} ({suffix})"
            suffix += 1
        reg[key] = ScriptInfo(
            action=key,
            cmd=["python", py],
            schema=schema,
            path=py,
            expected_values=expected_values,
        )

    return reg

# ---------------------------
# Export via external script
# ---------------------------

def export_library_metadata_via_script(cfg: AppConfig, limit: int = 0, include_playlists: bool = True, include_sonic: bool = False) -> pd.DataFrame:
    """Run external export script and load the resulting CSV."""
    if not (cfg.plex_baseurl and cfg.plex_token):
        raise RuntimeError("Missing Plex URL or Token.")

    script_path = os.path.join(SCRIPTS_DIR, "export_library_metadata.py")
    if not os.path.isfile(script_path):
        raise FileNotFoundError(f"Export script not found: {script_path}")

    out_path = os.path.join(EXPORTS_DIR, "Track_Level_Info.csv")

    env = os.environ.copy()
    env.update({
        "PLEX_BASEURL": cfg.plex_baseurl,
        "PLEX_TOKEN": cfg.plex_token,
        "PLEX_LIBRARY": cfg.plex_library,
        "OUTPUT_CSV": out_path,
        "PYTHONIOENCODING": "utf-8",
        "PYTHONUTF8": "1",
    })

    # --- Pass Variables to Script ---
    if limit > 0:
        env["EXPORT_LIMIT"] = str(limit)
    
    # Pass booleans as "1" (True) or "0" (False)
    env["EXPORT_PLAYLISTS"] = "1" if include_playlists else "0"

    log_box = st.empty()
    log_lines: List[str] = []

    st.write("Running external export script…")
    try:
        proc = subprocess.Popen(
            ["python", script_path],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            bufsize=1,
            env=env,
        )
        if proc.stdout is not None:
            for line in proc.stdout:
                log_lines.append(line.rstrip("\r\n"))
                tail = "\n".join(log_lines[-200:])
                log_box.code(tail or "…", language="bash")
        ret = proc.wait()
        if ret != 0:
            raise RuntimeError(f"export_library_metadata.py exited with code {ret}")
    except Exception as e:
        raise RuntimeError(f"Failed running export script: {e}")

    if not os.path.isfile(out_path):
        raise FileNotFoundError("Export finished but CSV not found. Ensure the script writes the file or honors OUTPUT_CSV.")

    try:
        df = pd.read_csv(out_path)
    except Exception as e:
        raise RuntimeError(f"Could not read exported CSV: {e}")

    return df

# ---------------------------
# Helpers for nicer success messages
# ---------------------------
def parse_edited_count(stdout: str) -> int | None:
    m = re.search(r"Edited\s*=\s*(\d+)", stdout, flags=re.IGNORECASE)
    if m:
        try:
            return int(m.group(1))
        except Exception:
            return None
    return None

def pluralize_last_word(phrase: str) -> str:
    parts = phrase.split()
    if not parts:
        return phrase
    last = parts[-1]
    if last.endswith("s"):
        return phrase
    if last.endswith("y") and len(last) > 1 and last[-2].lower() not in "aeiou":
        last_pl = last[:-1] + "ies"
    else:
        last_pl = last + "s"
    parts[-1] = last_pl
    return " ".join(parts)

def success_message_for_action(action_label: str, edited: int | None) -> str:
    target = action_label
    if ":" in action_label:
        target = action_label.split(":", 1)[1].strip()
    target_pl = pluralize_last_word(target.lower())
    if edited is not None:
        if "relabel" in action_label.lower():
            verb = "relabeled"
        elif "add" in action_label.lower():
            verb = "added"
        else:
            verb = "updated"
        return f"{edited} {target_pl} {verb} successfully."
    return f"{action_label}: completed successfully."

# ---------------------------
# Forgiving CSV reader
# ---------------------------
def read_csv_forgiving(source) -> pd.DataFrame:
    """
    Read a CSV with encoding fallbacks.
    Handles both uploaded file objects (Streamlit) and local file paths (Strings).
    """
    # 1. Determine if source is a path string or an uploaded file object
    if isinstance(source, str):
        # It's a file path string
        with open(source, "rb") as f:
            raw = f.read()
    else:
        # It's a Streamlit UploadedFile object
        raw = source.getvalue()

    # 2. Try various encodings to read the binary data
    for enc in ("utf-8", "utf-8-sig", "cp1252", "latin-1"):
        try:
            return pd.read_csv(io.BytesIO(raw), dtype=str, keep_default_na=False, encoding=enc)
        except UnicodeDecodeError:
            continue
        except Exception:
            pass

    # 3. Last resort fallback
    text = raw.decode("utf-8", errors="replace")
    return pd.read_csv(io.StringIO(text), dtype=str, keep_default_na=False)


# ---------------------------
# Track Search Function Helpers
# ---------------------------

@st.cache_data(ttl=3600)
def load_track_export_csv(filepath: str) -> pd.DataFrame:
    return pd.read_csv(filepath, dtype={"Track_ID": str})


def find_latest_track_csv(exports_dir: str):
    if not os.path.exists(exports_dir):
        return None
    files = [f for f in os.listdir(exports_dir) if "Track_Level_Info" in f and f.endswith(".csv")]
    if not files:
        return None
    return os.path.join(exports_dir, sorted(files, reverse=True)[0])

# ---------------------------
# Compare helpers
# ---------------------------
FALLBACK_KEY_COLS = ["Album_Artist", "Album", "Disc #", "Track #"]

def _norm_str(x) -> str:
    if x is None:
        return ""
    try:
        if isinstance(x, float) and pd.isna(x):
            return ""
    except Exception:
        pass
    return str(x).strip()

def _parse_set(cell: str) -> set[str]:
    s = _norm_str(cell)
    if not s:
        return set()
    parts = [p.strip() for p in s.split(",")]
    parts = [p for p in parts if p]
    parts = [" ".join(p.split()) for p in parts]
    return set(parts)

def _rating_to_float(x):
    s = _norm_str(x)
    if not s:
        return None
    try:
        return float(s)
    except Exception:
        return None

def _build_smart_key(df: pd.DataFrame) -> tuple[pd.Series, str]:
    """
    Generates a match key using the best available unique identifier.
    Priority: Track_ID > RatingKey > (Album_Artist + Album + Disc + Track)
    Returns: (KeySeries, MethodName)
    """
    # 1. Try Track_ID (Common in custom exports)
    if "Track_ID" in df.columns:
        return df["Track_ID"].astype(str).str.strip(), "Track_ID"
    
    # 2. Try RatingKey (Standard Plex ID)
    if "RatingKey" in df.columns:
        return df["RatingKey"].astype(str).str.strip(), "RatingKey"
    
    # 3. Fallback to Positional Text Matching
    missing = [c for c in FALLBACK_KEY_COLS if c not in df.columns]
    if not missing:
        parts = [df[c].astype(str).fillna("").str.strip() for c in FALLBACK_KEY_COLS]
        combined = parts[0].str.cat(parts[1:], sep=" | ")
        return combined, "Text Match (Artist+Album+Track)"
        
    raise ValueError(f"Could not find a match key. Requires 'Track_ID', 'RatingKey', or {FALLBACK_KEY_COLS}")

def compare_exports_add_match_cols(
    old_df: pd.DataFrame,
    new_df: pd.DataFrame,
    compare_vars: List[str],
    include_details: bool = False
) -> tuple[pd.DataFrame, dict]:
    old = old_df.copy()
    new = new_df.copy()

    # Build keys using the smart logic
    try:
        old["_key"], method_old = _build_smart_key(old)
        new["_key"], method_new = _build_smart_key(new)
    except ValueError as e:
        # If one file has IDs and the other doesn't, we might crash. 
        # For simplicity, we assume they share the same schema.
        raise ValueError(f"Key generation failed: {e}")

    old_dupes = int(old["_key"].duplicated().sum())
    new_dupes = int(new["_key"].duplicated().sum())

    old1 = old.drop_duplicates("_key", keep="first")
    new1 = new.drop_duplicates("_key", keep="first")

    # Only grab the columns you actually asked to compare
    old_cols = ["_key"] + [c for c in compare_vars if c in old1.columns]
    old_sub = old1[old_cols].copy()
    
    # Rename old columns
    old_sub = old_sub.rename(columns={c: f"{c}__old" for c in compare_vars if c in old_sub.columns})

    merged = new1.merge(old_sub, on="_key", how="left", indicator=True)
    found_mask = (merged["_merge"] == "both")

    per_key_cols = {}

    for i in range(len(merged)):
        k = merged.loc[i, "_key"]
        row_out = {}
        is_found = bool(found_mask.iloc[i])

        for c in compare_vars:
            match_col = f"{c}_Match"

            if not is_found:
                row_out[match_col] = "not found"
                if include_details:
                    row_out[f"{c}_Old"] = "not found"
                    row_out[f"{c}_Lost"] = "not found"
                    row_out[f"{c}_Gained"] = "not found"
                continue

            # Rating handling
            if c == "User_Rating":
                new_val = merged.loc[i, c] if c in merged.columns else ""
                old_val = merged.loc[i, f"{c}__old"] if f"{c}__old" in merged.columns else ""
                n = _rating_to_float(new_val)
                o = _rating_to_float(old_val)

                if n is None and o is None:
                    row_out[match_col] = "yes"
                elif (n is not None) and (o is not None) and (n == o):
                    row_out[match_col] = "yes"
                else:
                    row_out[match_col] = "no"

                if include_details:
                    row_out[f"{c}_Old"] = _norm_str(old_val)
            else:
                # Set/String handling
                new_val = merged.loc[i, c] if c in merged.columns else ""
                old_val = merged.loc[i, f"{c}__old"] if f"{c}__old" in merged.columns else ""
                nset = _parse_set(new_val)
                oset = _parse_set(old_val)

                row_out[match_col] = "yes" if nset == oset else "no"

                if include_details:
                    lost = oset - nset
                    gained = nset - oset
                    row_out[f"{c}_Old"] = ", ".join(sorted(oset, key=lambda x: x.lower()))
                    row_out[f"{c}_Lost"] = ", ".join(sorted(lost, key=lambda x: x.lower()))
                    row_out[f"{c}_Gained"] = ", ".join(sorted(gained, key=lambda x: x.lower()))

        per_key_cols[k] = row_out

    result = new.copy()
    
    # Map results back
    for c in compare_vars:
        mc = f"{c}_Match"
        result[mc] = result["_key"].map(lambda k: per_key_cols.get(k, {}).get(mc, "not found"))
        
    if include_details:
        for c in compare_vars:
            if c == "User_Rating":
                col = f"{c}_Old"
                result[col] = result["_key"].map(lambda k: per_key_cols.get(k, {}).get(col, "not found"))
            else:
                for suffix in ["Old", "Lost", "Gained"]:
                    col = f"{c}_{suffix}"
                    result[col] = result["_key"].map(lambda k: per_key_cols.get(k, {}).get(col, "not found"))

    result = result.drop(columns=["_key"])

    summary = {
        "old_rows": int(len(old_df)),
        "new_rows": int(len(new_df)),
        "match_method": method_new,
        "matched_keys": int(found_mask.sum()),
        "unmatched_new_keys": int((~found_mask).sum()),
        "old_duplicate_keys": old_dupes,
        "new_duplicate_keys": new_dupes,
    }

    for c in compare_vars:
        mc = f"{c}_Match"
        if mc in result.columns:
            vc = result[mc].value_counts(dropna=False).to_dict()
            summary[f"{mc}_counts"] = {str(k): int(v) for k, v in vc.items()}

    return result, summary

# ---------------------------
# Sidebar config
# ---------------------------

def ui_sidebar_config() -> AppConfig:
    st.sidebar.header("Plex Connection")

    # Check for updates
    latest, url = check_github_updates()
    if latest and latest != CURRENT_VERSION:
        st.sidebar.success(f"**Update available:** [{latest}]({url})")
    else:
        st.sidebar.caption(f"Version: {CURRENT_VERSION}")

    # Load defaults from config.txt or environment
    defaults = load_config_txt()
    env_url = os.getenv("PLEX_URL") or os.getenv("PLEX_BASEURL")
    env_token = os.getenv("PLEX_TOKEN")
    
    # Priority: Env > Config.txt > Empty
    def_url = env_url or defaults.plex_baseurl
    def_token = env_token or defaults.plex_token
    def_lib = defaults.plex_library

    # Draw Widgets
    baseurl = st.sidebar.text_input("Plex URL", value=def_url, placeholder="http://192.168.1.5:32400")
    token = st.sidebar.text_input("Plex Token", value=def_token, type="password")
    lib_name = st.sidebar.text_input("Music Library Name", value=def_lib)

    st.sidebar.divider()

    if not baseurl or not token:
        st.sidebar.warning("Please enter connection details.")

    return AppConfig(
        plex_baseurl=baseurl.strip(),
        plex_token=token.strip(),
        plex_library=lib_name.strip()
    )

def ui_compare_tab():
    from datetime import datetime
    try:
        from zoneinfo import ZoneInfo
        tz = ZoneInfo("Europe/Zurich")
    except Exception:
        tz = None

    st.subheader("Compare Exported Metadata")
    st.caption(
        "Upload an **old** and **new** export CSV. Tracks are matched by: "
        "**Album_Artist + Album + Disc # + Track #**."
    )

    col1, col2 = st.columns(2)
    with col1:
        old_up = st.file_uploader("Upload OLD export CSV", type=["csv"], key="compare_old")
    with col2:
        new_up = st.file_uploader("Upload NEW export CSV", type=["csv"], key="compare_new")

    if old_up is None or new_up is None:
        st.info("Upload both files to enable comparison.")
        return

    try:
        old_df = read_csv_forgiving(old_up)
        new_df = read_csv_forgiving(new_up)
    except Exception as e:
        st.error(f"Could not read one of the CSVs: {e}")
        return

    with st.expander("Preview (first 25 rows)"):
        st.markdown("**OLD**")
        st.dataframe(old_df.head(25), use_container_width=True)
        st.markdown("**NEW**")
        st.dataframe(new_df.head(25), use_container_width=True)

    st.divider()

    # Verify we have the columns needed to match rows
    missing_old = [c for c in KEY_COLS_POSITION if c not in old_df.columns]
    missing_new = [c for c in KEY_COLS_POSITION if c not in new_df.columns]
    if missing_old or missing_new:
        st.error(
            f"Missing key columns needed for matching.\n\n"
            f"- Missing in OLD: {missing_old}\n"
            f"- Missing in NEW: {missing_new}\n\n"
            f"Expected columns: {KEY_COLS_POSITION}"
        )
        return

    # --- DYNAMIC COLUMN SELECTOR (CHECKLIST STYLE) ---
    # 1. Find columns that exist in BOTH files (intersection)
    # 2. Allow ALL common columns (including Track #, Disc #, etc.)
    selectable_cols = [c for c in old_df.columns if c in new_df.columns]

    st.markdown("### Select Columns to Compare")
    st.caption("Check the variables you want to include in the comparison report.")

    # --- Vertical Checklist Loop ---
    selected_vars = []
    
    # Simple vertical list with NO defaults checked
    for col_name in selectable_cols:
        # value=False ensures they all start unchecked
        if st.checkbox(col_name, value=False, key=f"compare_chk_{col_name}"):
            selected_vars.append(col_name)
    # ------------------------------------

    st.divider()

    include_details = st.checkbox(
        "Include details (Old/Lost/Gained columns)",
        value=False,
        key="compare_details"
    )

    run = st.button("Run comparison", type="primary", key="compare_run")
    if not run:
        return
        
    if not selected_vars:
        st.error("Please select at least one column to compare.")
        return

    try:
        # Pass YOUR selected variables to the function
        result_df, summary = compare_exports_add_match_cols(
            old_df, new_df, 
            compare_vars=selected_vars, 
            include_details=include_details
        )
        st.success("Comparison complete.")

        st.markdown("### Summary")
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("OLD rows", summary["old_rows"])
        m2.metric("NEW rows", summary["new_rows"])
        m3.metric("Matched keys", summary["matched_keys"])
        m4.metric("Unmatched NEW keys", summary["unmatched_new_keys"])

        st.markdown("### Match breakdown")
        for c in selected_vars:
            mc = f"{c}_Match"
            counts = summary.get(f"{mc}_counts", {})
            st.write(
                f"**{mc}** — yes: {counts.get('yes', 0):,} | "
                f"no: {counts.get('no', 0):,} | "
                f"not found: {counts.get('not found', 0):,}"
            )

        st.markdown("### Output preview (first 50 rows)")
        st.dataframe(result_df.head(50), use_container_width=True)

        now = datetime.now(tz) if tz else datetime.now()
        date_prefix = now.strftime("%Y_%m_%d")
        out_filename = f"{date_prefix} metadata_comparison_output.csv"
        out_path = os.path.join(APP_DIR, out_filename)

        try:
            result_df.to_csv(out_path, index=False, encoding="utf-8")
            st.info(f"Saved to app folder: `{out_path}`")
        except Exception as e:
            st.error(f"Could not save file to app folder: {e}")

        out_buf = io.BytesIO()
        result_df.to_csv(out_buf, index=False)
        st.download_button(
            f"Download {out_filename}",
            data=out_buf.getvalue(),
            file_name=out_filename,
            mime="text/csv",
        )

    except Exception as e:
        st.error(f"Comparison failed: {e}")

# ---------------------------
# Export tab
# ---------------------------

# ---------------------------
# Export tab
# ---------------------------

def ui_export_tab(cfg: AppConfig):
    st.subheader("Export current metadata → CSV")
    if not (cfg.plex_baseurl and cfg.plex_token):
        st.info("Enter URL and Token in the left panel to enable export.")
        return

    # --- Options Checkboxes ---
    opt_playlists = st.checkbox(
        "Map Playlists", 
        value=True, 
        help="Scans every playlist to match tracks. Uncheck this to significantly speed up export."
    )
    st.divider()

    # --- Main Export ---
    # FIX: Changed label to static string, removed reference to undefined 'limit_val'
    if st.button("Export all track details", type="primary"):
        try:
            # Pass the checkboxes to the function
            df = export_library_metadata_via_script(
                cfg, 
                limit=0, 
                include_playlists=opt_playlists
            )
            st.success(f"Exported {len(df):,} tracks.")
            st.dataframe(df.head(50), use_container_width=True)
            out = io.BytesIO()
            df.to_csv(out, index=False)
            st.download_button(
                "Download Track_Level_Info.csv",
                data=out.getvalue(),
                file_name="Track_Level_Info.csv",
                mime="text/csv",
            )
        except Exception as e:
            st.error(f"Export failed: {e}")

    # --- Test Export ---
    st.divider()
    st.markdown("### Test Export")
    st.caption("Export a limited number of tracks from your library.")

    col1, col2 = st.columns([1, 4])
    
    with col1:
        # limit_val is defined HERE, so it can only be used below this line
        limit_val = st.number_input("Max Tracks", min_value=1, value=50, step=10)
    
    with col2:
        st.write("") 
        st.write("") 
        if st.button(f"Export first {limit_val} tracks"):
            try:
                # Pass the checkboxes here too
                df = export_library_metadata_via_script(
                    cfg, 
                    limit=limit_val,
                    include_playlists=opt_playlists
                )
                
                st.success(f"Test complete: Exported {len(df):,} tracks.")
                st.dataframe(df.head(50), use_container_width=True)
                
                out = io.BytesIO()
                df.to_csv(out, index=False)
                st.download_button(
                    f"Download Test Export ({limit_val})",
                    data=out.getvalue(),
                    file_name=f"Test_Export_{limit_val}_Tracks.csv",
                    mime="text/csv",
                )
            except Exception as e:
                st.error(f"Test export failed: {e}")

# ---------------------------
# Update single-script tab
# ---------------------------
def ui_update_tab(cfg: AppConfig):
    st.subheader("Submit changes from CSV → run a single script")
    registry = discover_scripts(include_exports=False, _sig=scripts_signature())
    if not registry:
        st.warning("No scripts found. Create a `Scripts/` folder with .py files. Optional: add a matching .json sidecar for schema & action name.")
        return

    action_labels = list(registry.keys())
    action = st.selectbox("Choose an action", action_labels)

    with st.expander("Expected CSV schema & values"):
        info = registry[action]
        cols = list(info.schema or [])
        vals = list(info.expected_values or [])
        n = max(len(cols), len(vals), 1)
        cols += [""] * (n - len(cols))
        vals += [""] * (n - len(vals))
        spec_df = pd.DataFrame({"expected_columns": cols, "expected_values": vals})
        try:
            st.dataframe(spec_df, use_container_width=True, hide_index=True)
        except TypeError:
            st.dataframe(spec_df.reset_index(drop=True), use_container_width=True)
        if not info.schema and not info.expected_values:
            st.caption("No schema provided for this action. Add a sidecar JSON with `expected_columns` (and optionally `expected_values`).")

    uploaded = st.file_uploader("Upload CSV", type=["csv"], accept_multiple_files=False, key="single_csv")

    if uploaded is not None:
        try:
            df = read_csv_forgiving(uploaded)
            st.write(f"CSV loaded with {len(df):,} rows.")
            st.dataframe(df.head(25), use_container_width=True)
        except Exception as e:
            st.error(f"Could not read CSV: {e}")
            return

        st.divider()
        st.warning("Writes to Plex are potentially destructive. Make a backup/export first.")

        confirm_phrase = st.text_input("Type CONFIRM to enable execution", key="single_confirm")
        ok = (confirm_phrase.strip().upper() == "CONFIRM")
        run_btn = st.button("Run script", type="primary", disabled=not ok, key="single_run")

        if run_btn and ok:
            tmp_path = os.path.join(APP_DIR, "uploaded.csv")
            with open(tmp_path, "wb") as f:
                f.write(uploaded.getvalue())

            try:
                spec = registry[action]
                env = os.environ.copy()
                env.update({
                    "PLEX_BASEURL": cfg.plex_baseurl,
                    "PLEX_TOKEN": cfg.plex_token,
                    "PYTHONIOENCODING": "utf-8",
                    "PYTHONUTF8": "1",
                })
                payload = json.dumps({
                    "action": spec.action,
                    "csv_path": tmp_path,
                })
                proc = subprocess.run(
                    spec.cmd,
                    input=payload,
                    env=env,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    encoding="utf-8",
                    check=False,
                )
                stdout = proc.stdout or ""
                stderr = proc.stderr or ""
                code = proc.returncode

                st.code(stdout or "<no stdout>", language="bash")
                if stderr:
                    st.error(stderr)

                if code == 0:
                    edited = parse_edited_count(stdout)
                    st.success(success_message_for_action(spec.action, edited))
                else:
                    st.error(f"{spec.action}: script failed with exit code {code}")
            except FileNotFoundError:
                st.error("Script not found. Check the `Scripts/` folder paths.")
            except Exception as e:
                st.error(f"Execution error: {e}")

# ---------------------------
# Update multi-script tab
# ---------------------------
def ui_update_multi_tab(cfg: AppConfig):
    st.subheader("Submit changes from CSV → run multiple scripts in sequence")

    registry = discover_scripts(include_exports=False, _sig=scripts_signature())
    if not registry:
        st.warning(
            "No scripts found. Create a `Scripts/` folder with .py files. "
            "Optional: add a matching .json sidecar for schema & action name."
        )
        return

    action_labels = list(registry.keys())

    st.caption("Select one or more actions to run (they will execute top-to-bottom).")

    if "multi_selected_actions" not in st.session_state:
        st.session_state["multi_selected_actions"] = []

    selected = []
    for label in action_labels:
        checked = st.checkbox(
            label,
            value=(label in st.session_state["multi_selected_actions"]),
            key=f"multi_{label}"
        )
        if checked:
            selected.append(label)

    st.session_state["multi_selected_actions"] = selected

    if not selected:
        st.info("Select at least one action to proceed.")
        return

    with st.expander("Expected CSV schema & values (selected actions)", expanded=True):
        rows = []
        for label in selected:
            info = registry[label]
            cols = list(info.schema or [])
            vals = list(info.expected_values or [])
            n = max(len(cols), len(vals), 1)
            cols += [""] * (n - len(cols))
            vals += [""] * (n - len(vals))

            if not info.schema and not info.expected_values:
                rows.append({"Action": info.action, "expected_columns": "", "expected_values": ""})
            else:
                for c, v in zip(cols, vals):
                    rows.append({"Action": info.action, "expected_columns": c, "expected_values": v})

        spec_df = pd.DataFrame(rows)
        try:
            st.dataframe(spec_df, use_container_width=True, hide_index=True)
        except TypeError:
            st.dataframe(spec_df.reset_index(drop=True), use_container_width=True)

        st.caption("Actions run in the order listed above.")

    uploaded = st.file_uploader(
        "Upload CSV (used for all selected scripts)",
        type=["csv"],
        accept_multiple_files=False,
        key="multi_csv"
    )
    if uploaded is None:
        return

    try:
        df = read_csv_forgiving(uploaded)
        st.write(f"CSV loaded with {len(df):,} rows.")
        st.dataframe(df.head(25), use_container_width=True)
    except Exception as e:
        st.error(f"Could not read CSV: {e}")
        return

    st.divider()
    st.warning("Writes to Plex are potentially destructive. Make a backup/export first.")

    confirm_phrase = st.text_input("Type CONFIRM to enable execution", key="multi_confirm")
    ok = (confirm_phrase.strip().upper() == "CONFIRM")

    run_btn = st.button(
        f"Run {len(selected)} script(s) in order",
        type="primary",
        disabled=not ok,
        key="multi_run"
    )

    if not (run_btn and ok):
        return

    tmp_path = os.path.join(APP_DIR, "uploaded.csv")
    try:
        with open(tmp_path, "wb") as f:
            f.write(uploaded.getvalue())
    except Exception as e:
        st.error(f"Could not write temporary CSV to disk: {e}")
        return

    st.divider()
    st.markdown("### Execution log")

    env = os.environ.copy()
    env.update({
        "PLEX_BASEURL": cfg.plex_baseurl,
        "PLEX_TOKEN": cfg.plex_token,
        "PYTHONIOENCODING": "utf-8",
        "PYTHONUTF8": "1",
    })

    any_fail = False

    for idx, label in enumerate(selected, start=1):
        spec = registry[label]
        st.markdown(f"#### {idx}. {spec.action}")

        try:
            payload = json.dumps({"action": spec.action, "csv_path": tmp_path})

            proc = subprocess.run(
                spec.cmd,
                input=payload,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                check=False,
            )

            stdout = proc.stdout or ""
            stderr = proc.stderr or ""
            code = proc.returncode

            st.code(stdout or "<no stdout>", language="bash")
            if stderr:
                st.error(stderr)

            if code == 0:
                edited = parse_edited_count(stdout)
                st.success(success_message_for_action(spec.action, edited))
            else:
                any_fail = True
                st.error(f"{spec.action}: script failed with exit code {code}")

        except FileNotFoundError:
            any_fail = True
            st.error("Script not found. Check the `Scripts/` folder paths.")
        except Exception as e:
            any_fail = True
            st.error(f"Execution error: {e}")

    st.divider()
    if any_fail:
        st.warning("Finished running selected scripts — at least one failed. Review logs above.")
    else:
        st.success("Finished running all selected scripts successfully.")

# ---------------------------
# Preset helpers for Playlist Creator
# ---------------------------
def ensure_presets_dir() -> None:
    try:
        os.makedirs(PRESETS_DIR, exist_ok=True)
    except Exception:
        pass

EXAMPLE_PREFIX = ""

def list_presets() -> List[str]:
    ensure_presets_dir()
    names = []
    # User presets
    try:
        for fn in os.listdir(PRESETS_DIR):
            if fn.lower().endswith(".json"):
                names.append(os.path.splitext(fn)[0])
        names.sort()
    except Exception:
        pass
    # Example presets — shown with prefix, sorted separately at the bottom
    try:
        if os.path.isdir(EXAMPLES_DIR):
            examples = []
            for fn in os.listdir(EXAMPLES_DIR):
                if fn.lower().endswith(".json"):
                    examples.append(EXAMPLE_PREFIX + os.path.splitext(fn)[0])
            names += sorted(examples)
    except Exception:
        pass
    return names

def load_preset_dict(name: str) -> dict:
    ensure_presets_dir()
    # Try user presets first, then fall back to example presets
    for path in [
        os.path.join(PRESETS_DIR, f"{name}.json"),
        os.path.join(EXAMPLES_DIR, f"{name}.json"),
    ]:
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}

def save_preset_dict(name: str, data: dict) -> None:
    ensure_presets_dir()
    path = os.path.join(PRESETS_DIR, f"{name}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def apply_preset_to_session(preset: dict) -> None:
    """
    Copy preset values into st.session_state for all known Playlist Creator keys.
    Handles backwards compatibility with older preset formats.
    """
    # --- Backwards compatibility: remap stale seed mode labels ---
    SEED_MODE_LABEL_REMAP = {
        "Auto (infer from seeds/history)": "Sonic Album Mix",
        "Sonic Journey": "Sonic Journey (Linear Path)",
    }
    if "pc_seed_mode_label" in preset:
        preset = dict(preset)  # don't mutate the original
        preset["pc_seed_mode_label"] = SEED_MODE_LABEL_REMAP.get(
            preset["pc_seed_mode_label"], preset["pc_seed_mode_label"]
        )

    keys = [
        "pc_lib",
        "pc_custom_title",
        "pc_preset_name",
        "pc_exclude_days",
        "pc_lookback_days",
        "pc_max_tracks",
        "pc_sonic_limit",
        "pc_deep_dive_target",
        "pc_hist_ratio",
        "pc_explore_exploit",
        "pc_sonic_smoothing",
        "pc_use_periods",
        "pc_min_track",
        "pc_min_album",
        "pc_min_artist",
        "pc_allow_unrated",
        "pc_min_play_count",
        "pc_max_play_count",
        "pc_min_year",
        "pc_max_year",
        "pc_min_duration",
        "pc_max_duration",
        "pc_recency_bias",
        "pc_max_artist",
        "pc_max_album",
        "pc_hist_min_rating",
        "pc_hist_max_play_count",
        "pc_seed_mode_label",
        "pc_seed_fallback_mode",
        "pc_seed_tracks",
        "pc_seed_artists",
        "pc_seed_playlists",
        "pc_seed_collections",
        "pc_seed_genres",
        "pc_genre_strict",
        "pc_allow_off_genre",
        "pc_exclude_genres",
        "pc_include_collections",
        "pc_exclude_collections",
        "pc_coverart_select",
        "pc_coverart_color_select",
        "pc_coverart_bg_color_select",
    ]
    # Preserve the user's existing library name — it's a per-server setting,
    # not a per-playlist one. Only apply pc_lib from the preset if the user
    # hasn't configured one yet.
    existing_lib = st.session_state.get("pc_lib", "").strip()

    # Clear track objects before applying — reconciliation loop will re-populate
    # from the new pc_seed_tracks value on the next render
    st.session_state["pc_seed_track_objects"] = []
    st.session_state["pc_track_search_results"] = []

    for k in keys:
        if k in preset:
            st.session_state[k] = preset[k]

    if existing_lib:
        st.session_state["pc_lib"] = existing_lib

# ---------------------------
# Playlist Creator tab (with presets)
# ---------------------------
def ui_playlist_creator_tab(cfg: AppConfig):

    def check_sonic_status(cfg: AppConfig):
        # Quick check to see if the server can even do sonic analysis
        try:
            plex = PlexServer(cfg.plex_baseurl, cfg.plex_token)
            music = plex.library.section(st.session_state.get("pc_lib", "Music"))
            
            # Check if the feature is enabled on the library
            if not music.enableSonicAnalysis:
                 st.error("🚨 Sonic Analysis is DISABLED on your Music library. This tool will not work until you enable it in Plex settings.")
                 return False
            return True
        except:
            # Fail gracefully if library doesn't exist yet
            return True 

    # Then call it at the start of the tab
    check_sonic_status(cfg)

    # 1. HANDLE LOADING FIRST (Before any widgets are instantiated)
    if "pc_preset_select" in st.session_state:
        # Check if the load button was pressed
        if st.get_option("server.runOnSave") or st.session_state.get("pc_btn_load"):
             selected_preset = st.session_state.get("pc_preset_select")
             if selected_preset and selected_preset != "<none>":
                 preset = load_preset_dict(selected_preset)
                 if preset:
                     # This will now work because the widgets haven't been "drawn" yet
                     apply_preset_to_session(preset)
                     
    st.subheader("Playlist Creator (sonic similarity + custom seeds)")

    st.caption(
        "Use Plex listening history, sonic similarity, and custom seeds "
        "to auto-generate a new playlist. This calls `playlist_creator.py` "
        "in the Scripts/ folder."
    )

    st.divider()

    # ---------------------------
    # Presets UI (TOP)
    # ---------------------------
    ensure_presets_dir()

    existing_presets = list_presets()
    preset_options = ["<none>"] + existing_presets

    # --- MASTER KEY LIST (Used for both Reset and Save) ---
    ALL_PRESET_KEYS = [
        "pc_lib", "pc_custom_title", "pc_preset_name",
        "pc_exclude_days", "pc_lookback_days", "pc_max_tracks",
        "pc_sonic_limit", "pc_deep_dive_target", 
        "pc_hist_ratio", "pc_explore_exploit", "pc_sonic_smoothing", "pc_use_periods",
        "pc_min_track", "pc_min_album", "pc_min_artist", "pc_allow_unrated",
        "pc_min_play_count", "pc_max_play_count",
        "pc_min_year", "pc_max_year", "pc_min_duration", "pc_max_duration",
        "pc_max_artist", "pc_max_album",
        "pc_recency_bias",
        "pc_hist_min_rating", "pc_hist_max_play_count",
        "pc_seed_mode_label", "pc_seed_fallback_mode",
        "pc_seed_tracks", "pc_seed_artists", "pc_seed_playlists",
        "pc_seed_collections", "pc_seed_genres",
        "pc_genre_strict", "pc_allow_off_genre", "pc_exclude_genres",
        "pc_include_collections", "pc_exclude_collections",
        "pc_coverart_select", "pc_coverart_color_select", "pc_coverart_bg_color_select",
    ]

    # --- CALLBACKS ---

    def handle_load_preset():
        sel = st.session_state.get("pc_preset_select")
        if sel and sel != "<none>":
            preset = load_preset_dict(sel)
            if preset:
                apply_preset_to_session(preset)

    def handle_reset_inputs():
        """Clears all playlist creator session keys, reverting widgets to their defaults."""
        defaults = {
            # Text fields → empty
            "pc_lib":                   "",
            "pc_custom_title":          "",
            "pc_preset_name":           "",
            "pc_seed_tracks":           "",
            "pc_seed_artists":          "",
            "pc_seed_playlists":        "",
            "pc_seed_collections":      "",
            "pc_seed_genres":           "",
            "pc_include_collections":   "",
            "pc_exclude_collections":   "",
            "pc_exclude_genres":        "",
            "pc_track_search_query":    "",
            # Numbers / sliders → widget defaults
            "pc_exclude_days":          0,
            "pc_lookback_days":         30,
            "pc_max_tracks":            50,
            "pc_sonic_limit":           20,
            "pc_deep_dive_target":      15,
            "pc_hist_ratio":            0.3,
            "pc_explore_exploit":       0.7,
            "pc_recency_bias":          0.0,
            "pc_min_track":             7,
            "pc_min_album":             0,
            "pc_min_artist":            0,
            "pc_min_play_count":        -1,
            "pc_max_play_count":        -1,
            "pc_min_year":              0,
            "pc_max_year":              0,
            "pc_min_duration":          0,
            "pc_max_duration":          0,
            "pc_max_artist":            6,
            "pc_max_album":             0,
            "pc_hist_min_rating":       0,
            "pc_hist_max_play_count":   -1,
            # Booleans → defaults
            "pc_allow_unrated":         True,
            "pc_sonic_smoothing":       False,
            "pc_use_periods":           False,
            "pc_genre_strict":          False,
            # Selects → defaults
            "pc_seed_mode_label":       "Sonic Album Mix",
            "pc_seed_fallback_mode":    "history",
            "pc_allow_off_genre":       0.2,
            # Preset selector & track state
            "pc_preset_select":         "<none>",
            "pc_seed_track_objects":    [],
            "pc_track_search_results":  [],
            # Cover art
            "pc_coverart_select":           "None",
            "pc_coverart_color_select":     "#FF0000",
            "pc_coverart_bg_color_select":  "#000000",
        }
        for k, v in defaults.items():
            st.session_state[k] = v

    # --- LAYOUT ---

    # ---------------------------
    # Core playlist UI
    # ---------------------------

    music_lib = cfg.plex_library

    from Cover_Art_Designs import (
        DESIGNS as cover_art_designs,
        wrap_title as _cover_wrap_title,
        generate_cover_art as _gen_preview_art,
    )

    # Single row: presets (left) | vertical divider | cover art (right)
    _pre_side, _pre_vdiv, _art_side = st.columns([6, 0.08, 3.92])

    with _pre_side:
        st.markdown("### Presets & Playlist Title")
        p1, p2, p3 = st.columns(3)
        with p1:
            st.selectbox(
                "Load preset",
                options=preset_options,
                index=0,
                key="pc_preset_select",
            )
            _cb1, _cb2 = st.columns(2)
            _cb1.button("Load", key="pc_btn_load", on_click=handle_load_preset, use_container_width=True)
            _cb2.button("Reset", key="pc_btn_reset", on_click=handle_reset_inputs, use_container_width=True)
        with p2:
            if "pc_preset_name" not in st.session_state:
                st.session_state["pc_preset_name"] = ""
            st.text_input(
                "Preset name",
                key="pc_preset_name",
                placeholder="e.g., Classic Rock 1960–79",
            )
            if st.button("Save as preset", key="pc_btn_save", use_container_width=True):
                _name = (st.session_state.get("pc_preset_name") or "").strip()
                if not _name:
                    st.error("Enter a preset name first.")
                else:
                    data = {k: st.session_state.get(k) for k in ALL_PRESET_KEYS}
                    data["pc_lib"] = cfg.plex_library
                    save_preset_dict(_name, data)
                    st.success(f"Saved: {_name}")
        with p3:
            st.session_state.setdefault("pc_custom_title", "")
            custom_title = st.text_input(
                "Custom playlist title",
                key="pc_custom_title",
                placeholder="e.g., Indie Hits",
                help="Used as the playlist title and printed on the cover art.",
            )

    with _pre_vdiv:
        st.markdown(
            '<div style="border-left:2px solid rgba(128,128,128,0.35);'
            'min-height:160px;margin-top:0px"></div>',
            unsafe_allow_html=True,
        )

    with _art_side:
        st.markdown("### Playlist Cover Art")
        col_p1, col_p2, col_p3, col_p4 = st.columns([2, 1, 1, 3])
        with col_p1:
            selected_cover_design = st.selectbox(
                "Choose cover art design",
                options=list(cover_art_designs.keys()),
                index=0,
                key="pc_coverart_select",
            )
        with col_p2:
            st.markdown("Primary  \ncolor")
            st.session_state.setdefault("pc_coverart_color_select", "#FF0000")
            selected_cover_color = st.color_picker(
                "Primary color",
                key="pc_coverart_color_select",
                label_visibility="collapsed",
            )
        with col_p3:
            st.markdown("Background  \ncolor")
            st.session_state.setdefault("pc_coverart_bg_color_select", "#000000")
            selected_cover_bg_color = st.color_picker(
                "Background color",
                key="pc_coverart_bg_color_select",
                label_visibility="collapsed",
            )
        with col_p4:
            _prev_design_key = cover_art_designs.get(
                st.session_state.get("pc_coverart_select", "None"), "none"
            )
            _prev_color  = st.session_state.get("pc_coverart_color_select", "#FF0000")
            _prev_bg     = st.session_state.get("pc_coverart_bg_color_select", "#000000")
            _prev_title  = st.session_state.get("pc_custom_title", "").strip() or "Preview"
            _prev_bytes  = _gen_preview_art(
                _prev_design_key, _prev_title, "MM/DD/YYYY",
                color=_prev_color, bg_color=_prev_bg, dpi=72,
            )
            if _prev_bytes:
                st.image(_prev_bytes, caption="Preview", width=150)

    _cover_title = st.session_state.get("pc_custom_title", "").strip()
    if _cover_title:
        _, _title_truncated = _cover_wrap_title(_cover_title)
        if _title_truncated:
            st.warning(
                "Cover art title is too long and will be truncated to 3 lines. "
                "Shorten the title to ensure it fits."
            )

    st.divider()
    st.markdown("### Playlist parameters")

    _pp1, _pp2, _pp3, _pp4 = st.columns([1, 1, 1, 5])
    with _pp1:
        st.session_state.setdefault("pc_max_tracks", 50)
        max_tracks = st.number_input(
            "Max tracks",
            min_value=5,
            max_value=300,
            step=1,
            key="pc_max_tracks",
        )
    with _pp2:
        st.session_state.setdefault("pc_sonic_limit", 20)
        sonic_similar_limit = st.number_input(
            "Sonically similar per seed",
            min_value=5,
            max_value=100,
            step=1,
            key="pc_sonic_limit",
        )
    with _pp3:
        st.session_state.setdefault("pc_deep_dive_target", 15)
        deep_dive_target = st.number_input(
            "Deep Dive Seeds per Artist",
            min_value=1, max_value=100, step=1,
            key="pc_deep_dive_target",
            help="Only for 'Deep Dive' mode. How many distinct tracks to harvest from a Seed Artist to ensure we cover their discography."
        )
    with _pp4:
        st.session_state.setdefault("pc_seed_fallback_mode", "history")
        seed_fallback_mode = st.radio(
            "When too few seeds, fill from:",
            options=["history", "genre"],
            key="pc_seed_fallback_mode",
        )

    _ps1, _ps2, _ps3, _ = st.columns([1, 1, 1, 2])
    with _ps1:
        st.session_state.setdefault("pc_explore_exploit", 0.7)
        explore_exploit = st.slider(
            "Explore vs. exploit (popularity)",
            min_value=0.0,
            max_value=1.0,
            step=0.05,
            key="pc_explore_exploit",
            help=(
                "0 = pure exploration (low popularity bias), "
                "1 = pure exploitation (strong bias toward most popular tracks)."
            ),
        )
    with _ps2:
        st.session_state.setdefault("pc_recency_bias", 0.0)
        recency_bias = st.slider(
            "Date Added Bias (0=Neutral, 1=Newest)",
            min_value=0.0,
            max_value=1.0,
            step=0.1,
            key="pc_recency_bias",
            help=(
                "Prioritizes tracks based on how recently they were added to your library.\n"
                "0.0 = Ignore date.\n"
                "1.0 = Prefer the newest tracks available in the current selection."
            )
        )
    with _ps3:
        st.session_state.setdefault("pc_sonic_smoothing", False)
        sonic_smoothing = st.checkbox(
            "Sonic Smoothing (Gradient Sort)",
            key="pc_sonic_smoothing",
            help="If checked, the final playlist will be reordered so each track flows sonically into the next."
        )

    exploit_weight = float(explore_exploit)

    st.divider()
    st.markdown("### History filters")
    _hr1, _hr2, _hr3, _hr4, _hr5, _hr6, _ = st.columns([1, 1, 1, 1, 1, 1, 1])
    with _hr1:
        st.session_state.setdefault("pc_exclude_days", 3)
        exclude_days = st.number_input(
            "Exclude played (days)",
            min_value=0,
            max_value=365,
            step=1,
            key="pc_exclude_days",
        )
    with _hr2:
        st.session_state.setdefault("pc_lookback_days", 30)
        lookback_days = st.number_input(
            "History lookback (days)",
            min_value=1,
            max_value=365,
            step=1,
            key="pc_lookback_days",
        )
    with _hr3:
        st.session_state.setdefault("pc_hist_ratio", 0.3)
        historical_ratio = st.slider(
            "Fraction of tracks from history",
            min_value=0.0,
            max_value=1.0,
            step=0.05,
            key="pc_hist_ratio",
        )
    with _hr4:
        st.session_state.setdefault("pc_hist_min_rating", 0)
        history_min_rating = st.number_input(
            "History: min track rating (0–10)",
            min_value=0, max_value=10,
            step=1,
            key="pc_hist_min_rating",
        )
    with _hr5:
        st.session_state.setdefault("pc_hist_max_play_count", -1)
        history_max_play_count = st.number_input(
            "History: max play count (–1 = no max)",
            min_value=-1, max_value=10000,
            step=1,
            key="pc_hist_max_play_count",
        )
    with _hr6:
        st.session_state.setdefault("pc_use_periods", False)
        use_time_periods = st.checkbox(
            "Use time-of-day periods",
            key="pc_use_periods",
            help=(
                "When enabled, history seeds are filtered to only tracks you listened to "
                "during the current time block:\n"
                "  • Morning (6am–11am)\n"
                "  • Afternoon (12pm–4pm)\n"
                "  • Evening (5pm–9pm)\n"
                "  • Late Night (10pm–5am)\n\n"
                "This makes playlists context-aware — e.g. an evening run won't pull "
                "from your early-morning listening history.\n\n"
                "Only affects history-based seeding. Sonic, genre, track, and artist "
                "seeds are unaffected."
            ),
        )

    st.divider()
    _row_r, _row_div, _row_pc, _ = st.columns([4, 0.08, 4, 1.92])

    with _row_r:
        st.markdown("### Rating filters")
        r1, r2, r3, r4 = st.columns([1, 1, 1, 2])
        with r1:
            st.session_state.setdefault("pc_min_track", 7)
            min_track = st.number_input(
                "Min track rating",
                min_value=0, max_value=10,
                step=1,
                key="pc_min_track",
            )
        with r2:
            st.session_state.setdefault("pc_min_album", 0)
            min_album = st.number_input(
                "Min album rating",
                min_value=0, max_value=10,
                step=1,
                key="pc_min_album",
            )
        with r3:
            st.session_state.setdefault("pc_min_artist", 0)
            min_artist = st.number_input(
                "Min artist rating",
                min_value=0, max_value=10,
                step=1,
                key="pc_min_artist",
            )
        with r4:
            st.session_state.setdefault("pc_allow_unrated", True)
            allow_unrated = st.checkbox(
                "Allow unrated items",
                key="pc_allow_unrated",
                help=(
                    "If checked, items with NO rating are allowed to pass, even if you set a minimum. "
                    "If unchecked, an unrated Album or Artist will block the track if a minimum is set for that level."
                ),
            )

    with _row_div:
        st.markdown(
            '<div style="border-left:2px solid rgba(128,128,128,0.35);'
            'min-height:160px;margin-top:0px"></div>',
            unsafe_allow_html=True,
        )

    with _row_pc:
        st.markdown("### Play count filters")
        pc1, pc2 = st.columns(2)
        with pc1:
            st.session_state.setdefault("pc_min_play_count", -1)
            min_play_count = st.number_input(
                "Min play count (–1 = no minimum)",
                min_value=-1, max_value=10000,
                step=1,
                key="pc_min_play_count",
            )
        with pc2:
            st.session_state.setdefault("pc_max_play_count", -1)
            max_play_count = st.number_input(
                "Max play count (–1 = no maximum; 0 = unplayed only)",
                min_value=-1, max_value=10000,
                step=1,
                key="pc_max_play_count",
            )

    st.divider()
    _row_yd, _row_yd_div, _row_aa, _ = st.columns([4, 0.08, 4, 1.92])

    with _row_yd:
        st.markdown("### Year & duration filters (0 = none)")
        y1, y2, d1, d2 = st.columns(4)
        with y1:
            st.session_state.setdefault("pc_min_year", 0)
            min_year = st.number_input(
                "Min album year",
                min_value=0, max_value=3000,
                step=1,
                key="pc_min_year",
            )
        with y2:
            st.session_state.setdefault("pc_max_year", 0)
            max_year = st.number_input(
                "Max album year",
                min_value=0, max_value=3000,
                step=1,
                key="pc_max_year",
            )
        with d1:
            st.session_state.setdefault("pc_min_duration", 0)
            min_duration_sec = st.number_input(
                "Min track duration (sec)",
                min_value=0, max_value=60 * 60 * 4,
                step=5,
                key="pc_min_duration",
            )
        with d2:
            st.session_state.setdefault("pc_max_duration", 0)
            max_duration_sec = st.number_input(
                "Max track duration (sec)",
                min_value=0, max_value=60 * 60 * 4,
                step=5,
                key="pc_max_duration",
            )

    with _row_yd_div:
        st.markdown(
            '<div style="border-left:2px solid rgba(128,128,128,0.35);'
            'min-height:160px;margin-top:0px"></div>',
            unsafe_allow_html=True,
        )

    with _row_aa:
        st.markdown("### Artist / album caps (0 = no cap)")
        aa1, aa2 = st.columns(2)
        with aa1:
            st.session_state.setdefault("pc_max_artist", 6)
            max_tracks_per_artist = st.number_input(
                "Max tracks per artist",
                min_value=0, max_value=1000,
                step=1,
                key="pc_max_artist",
            )
        with aa2:
            st.session_state.setdefault("pc_max_album", 0)
            max_tracks_per_album = st.number_input(
                "Max tracks per album",
                min_value=0, max_value=1000,
                step=1,
                key="pc_max_album",
            )


    st.divider()
    st.markdown("### Genre & collection rules")

    _gr1, _gr2, _gr3, _gr4 = st.columns([2, 2, 1, 1])
    with _gr1:
        st.session_state.setdefault("pc_seed_genres", "")
        genre_seeds_raw = st.text_input(
            "Genre seeds (comma-separated, track or album)",
            placeholder="e.g., Rock, Jazz, Ambient",
            key="pc_seed_genres",
        )
    with _gr2:
        st.session_state.setdefault("pc_exclude_genres", "")
        exclude_genres_raw = st.text_input(
            "Exclude genres (comma-separated)",
            placeholder="e.g., Holiday, Comedy",
            key="pc_exclude_genres",
        )
    with _gr3:
        st.session_state.setdefault("pc_genre_strict", False)
        genre_strict = st.checkbox(
            "Genre strict (enforce genre seeds)",
            key="pc_genre_strict",
            help=(
                "If checked, album genres must intersect with genre seeds. "
                "Off-genre tracks can still appear up to the allowed fraction."
            ),
        )
    with _gr4:
        st.session_state.setdefault("pc_allow_off_genre", 0.2)
        off_genre_fraction = st.slider(
            "Allow off-genre fraction",
            min_value=0.0, max_value=1.0,
            step=0.05,
            key="pc_allow_off_genre",
            help="Maximum fraction of tracks allowed that don't match the genre seeds (checks Track, Album, and Artist tags).",
        )

    _gc1, _gc2, _gc3 = st.columns(3)
    with _gc1:
        st.session_state.setdefault("pc_seed_collections", "")
        seed_collection_names_raw = st.text_input(
            "Seed collection names (comma-separated)",
            placeholder="e.g., All That Jazz",
            key="pc_seed_collections",
        )
    with _gc2:
        st.session_state.setdefault("pc_exclude_collections", "")
        exclude_collections_raw = st.text_input(
            "Exclude collections (comma-separated)",
            placeholder="e.g., Christmas, Kids Music",
            key="pc_exclude_collections",
        )
    with _gc3:
        st.session_state.setdefault("pc_include_collections", "")
        include_collections_raw = st.text_input(
            "Include only collections (comma-separated)",
            placeholder="e.g., Classic Rock, Jazz",
            key="pc_include_collections",
        )

    st.divider()
    st.markdown("### Seed strategy")

    seed_options = [
        "Deep Dive (Seed Albums)",
        "Genre seeds",
        "History + Seeds (Union)",
        "Sonic Artist Mix",
        "Sonic Album Mix",
        "Sonic Tracks Mix",
        "Sonic Combo (Albums + Artists)",
        "Sonic History (Intersection)",
        "Sonic Journey (Linear Path)",
        "Strict Collection"
    ]

    _ss_col, _ = st.columns([1, 2])
    with _ss_col:
        st.session_state.setdefault("pc_seed_mode_label", "Sonic Artist Mix")
        seed_mode_label = st.selectbox(
            "Seed mode",
            seed_options,
            key="pc_seed_mode_label",
            help=(
                "How to build the core candidate set:\n"
                "- Deep Dive: Deep search into the discography of your seed albums/artists (Mini-Box Set).\n"
                "- Genre seeds: Songs matching the specific genres.\n"
                "- History + Seeds: Your recent history PLUS any specific seeds you add (Union).\n"
                "- Sonic Album/Artist: Seed + sonically similar albums/artists (Broad).\n"
                "- Sonic Combo: Expands via both similar albums and artists (Dense).\n"
                "- Sonic Tracks: Strict, dynamic expansion directly from seed tracks (track-to-track similarity).\n"
                "- Sonic History: Only tracks from your history that sound like your seeds (Intersection).\n"
                "- Sonic Journey: Connects your seeds with a sonically similar path of tracks (e.g., Six Degrees of Separation).\n"
                "- Strict Collection: Only tracks from the specified collections (Curator Mode)."
            ),
        )

    st.divider()
    seed_mode_map = {
        "Deep Dive (Seed Albums)": "album_echoes",
        "Genre seeds": "genre",
        "History + Seeds (Union)": "history",
        "Sonic Artist Mix": "sonic_artist_mix",
        "Sonic Album Mix": "sonic_album_mix",
        "Sonic Tracks Mix": "track_sonic",  #
        "Sonic Combo (Albums + Artists)": "sonic_combo",
        "Sonic History (Intersection)": "sonic_history",
        "Sonic Journey (Linear Path)": "sonic_journey",
        "Strict Collection": "strict_collection"
    }
    seed_mode = seed_mode_map[st.session_state["pc_seed_mode_label"]]

    st.markdown("### Seed sources")

    st.caption(
        "Any combination of seeds can be used. Playlist Creator will deduplicate "
        "and then expand via sonic similarity and/or history."
    )

    def _parse_list(text: str) -> List[str]:
        return [p.strip() for p in (text or "").split(",") if p.strip()]

    col1, col2 = st.columns(2)

    with col1:
        # Seed artist names — moved above track search
        st.session_state.setdefault("pc_seed_artists", "")
        seed_artist_names_raw = st.text_input(
            "Seed artist names (comma-separated)",
            placeholder="e.g., Bill Evans, Miles Davis",
            key="pc_seed_artists",
        )

        st.markdown("**Seed Tracks**")

        # Initialize session state
        if "pc_seed_track_objects" not in st.session_state:
            st.session_state["pc_seed_track_objects"] = []
        if "pc_track_search_results" not in st.session_state:
            st.session_state["pc_track_search_results"] = []

        # Preset compatibility: add any keys from pc_seed_tracks not yet in objects
        stored_raw = st.session_state.get("pc_seed_tracks", "")
        stored_keys = [k.strip() for k in stored_raw.split(",") if k.strip()]
        obj_keys = {t["key"] for t in st.session_state["pc_seed_track_objects"]}
        for k in stored_keys:
            if k not in obj_keys:
                st.session_state["pc_seed_track_objects"].append({"key": k, "label": k, "short_label": k})

        # Auto-resolve preset-loaded keys from CSV (no Plex call needed)
        unresolved = [t for t in st.session_state["pc_seed_track_objects"] if t.get("short_label", t["key"]) == t["key"]]
        if unresolved:
            csv_path_resolve = find_latest_track_csv(EXPORTS_DIR)
            if csv_path_resolve:
                try:
                    resolve_df = load_track_export_csv(csv_path_resolve)
                    key_map = {str(row["Track_ID"]): row for _, row in resolve_df.iterrows()}
                    for t in unresolved:
                        if t["key"] in key_map:
                            row = key_map[t["key"]]
                            artist = str(row.get("Track_Artist", "Unknown")).strip()
                            title = str(row.get("Title", "Unknown")).strip()
                            album = str(row.get("Album", "Unknown")).strip()
                            year = row.get("Date_Cleaned", "")
                            year_str = f" ({int(year)})" if pd.notna(year) and year else ""
                            rating = row.get("User_Rating", None)
                            rating_str = f"Rating: {int(rating)}" if pd.notna(rating) and rating > 0 else "Unrated"
                            t["label"] = f"{artist} — {album}{year_str} — {title} [{rating_str}]"
                            t["short_label"] = f"{artist} - {title}"
                except:
                    pass

        objs = st.session_state["pc_seed_track_objects"]

        # Selected tracks — comma-separated compact display above search box
        if objs:
            short_labels = [t.get("short_label", t["key"]) for t in objs]
            st.caption("Selected: " + ", ".join(short_labels))

            def _handle_track_remove():
                sel = st.session_state.get("pc_track_to_remove", "")
                if sel and sel != "— remove a track —":
                    idx = next(
                        (i for i, t in enumerate(st.session_state["pc_seed_track_objects"])
                         if t.get("short_label", t["key"]) == sel),
                        None
                    )
                    if idx is not None:
                        st.session_state["pc_seed_track_objects"].pop(idx)
                        # Sync immediately so reconciliation loop doesn't re-add it on rerun
                        st.session_state["pc_seed_tracks"] = ",".join(
                            t["key"] for t in st.session_state["pc_seed_track_objects"]
                        )
                    st.session_state["pc_track_to_remove"] = "— remove a track —"

            st.selectbox(
                "Remove",
                ["— remove a track —"] + short_labels,
                key="pc_track_to_remove",
                label_visibility="collapsed",
                on_change=_handle_track_remove,
            )

        # Search row
        s_col, btn_col = st.columns([4, 1])
        with s_col:
            track_search_query = st.text_input(
                "Search tracks",
                key="pc_track_search_query",
                placeholder="Search by title, artist, or album...",
                label_visibility="collapsed",
            )
        with btn_col:
            search_btn = st.button("Search", key="pc_track_search_btn", use_container_width=True)

        # Show which CSV is being used
        csv_path_display = find_latest_track_csv(EXPORTS_DIR)
        if csv_path_display:
            st.caption(f"Searching: {os.path.basename(csv_path_display)}")
        else:
            st.caption("No export CSV found — will use Plex API")

        found = []
        if search_btn and track_search_query.strip():
            query = track_search_query.strip()
            q_tokens = query.lower().split()

            csv_path = find_latest_track_csv(EXPORTS_DIR)

            # --- PRIMARY: Search via local CSV export ---
            if csv_path:
                try:
                    df = load_track_export_csv(csv_path)
                    mask = pd.Series(True, index=df.index)
                    for token in q_tokens:
                        escaped = re.escape(token)
                        token_mask = (
                            df["Title"].str.lower().str.contains(escaped, na=False) |
                            df["Track_Artist"].str.lower().str.contains(escaped, na=False) |
                            df["Album"].str.lower().str.contains(escaped, na=False)
                        )
                        mask &= token_mask
                    for _, row in df[mask].head(20).iterrows():
                        year = row.get("Date_Cleaned", "")
                        year_str = f" ({int(year)})" if pd.notna(year) and year else ""
                        rating = row.get("User_Rating", None)
                        rating_str = f"Rating: {int(rating)}" if pd.notna(rating) and rating > 0 else "Unrated"
                        artist = str(row.get("Track_Artist", "Unknown")).strip()
                        album = str(row.get("Album", "Unknown")).strip()
                        title = str(row.get("Title", "Unknown")).strip()
                        label = f"{artist} — {album}{year_str} — {title} [{rating_str}]"
                        short_label = f"{artist} - {title}"
                        found.append({"key": str(row["Track_ID"]), "label": label, "short_label": short_label})
                except Exception as e:
                    st.warning(f"CSV search failed: {e}")

            # --- FALLBACK: Search via Plex API ---
            else:
                try:
                    _plex = PlexServer(cfg.plex_baseurl, cfg.plex_token)
                    _music = _plex.library.section(st.session_state.get("pc_lib", "Music"))
                    # Use hub search (same as Plex's own search box) — searches
                    # across title, artist, and album fields simultaneously
                    _hub_results = _plex.search(query, mediatype="track", limit=100)
                    _section_id = str(_music.key)
                    filtered = []
                    for t in _hub_results:
                        if str(getattr(t, "librarySectionID", "")) != _section_id:
                            continue
                        fields = " ".join([
                            (getattr(t, "title", "") or "").lower(),
                            (getattr(t, "grandparentTitle", "") or "").lower(),
                            (getattr(t, "parentTitle", "") or "").lower(),
                        ])
                        if all(re.search(re.escape(tok), fields) for tok in q_tokens):
                            filtered.append(t)
                        if len(filtered) >= 20:
                            break
                    for t in filtered:
                        year = getattr(t, "parentYear", None)
                        year_str = f" ({year})" if year else ""
                        rating = getattr(t, "userRating", None)
                        rating_str = f"Rating: {int(rating)}" if rating else "Unrated"
                        artist = getattr(t, "grandparentTitle", "Unknown")
                        album = getattr(t, "parentTitle", "Unknown")
                        label = f"{artist} — {album}{year_str} — {t.title} [{rating_str}]"
                        short_label = f"{artist} - {t.title}"
                        found.append({"key": str(t.ratingKey), "label": label, "short_label": short_label})
                except Exception as e:
                    st.warning(f"Track search failed: {e}")

            if found:
                st.session_state["pc_track_search_results"] = found
            else:
                st.session_state["pc_track_search_results"] = []
                st.warning("No tracks found. Try a different search term.")

        # Show search results in a scrollable container
        search_results = st.session_state.get("pc_track_search_results", [])
        if search_results:
            st.caption("Results — click to add:")
            already_selected = {t["key"] for t in st.session_state["pc_seed_track_objects"]}
            with st.container(height=280):
                for r in search_results:
                    is_added = r["key"] in already_selected
                    btn_label = f"✓ {r['label']}" if is_added else r["label"]
                    if st.button(btn_label, key=f"pc_add_{r['key']}", disabled=is_added, use_container_width=True):
                        st.session_state["pc_seed_track_objects"].append({
                            "key": r["key"],
                            "label": r["label"],
                            "short_label": r["short_label"],
                        })
                        st.rerun()

        # Sync to pc_seed_tracks for payload and preset saving
        st.session_state["pc_seed_tracks"] = ",".join(t["key"] for t in st.session_state["pc_seed_track_objects"])
        seed_track_keys_raw = st.session_state["pc_seed_tracks"]

    with col2:
        st.session_state.setdefault("pc_seed_playlists", "")
        seed_playlist_names_raw = st.text_input(
            "Seed playlist names (comma-separated)",
            placeholder="e.g., Dinner Party",
            key="pc_seed_playlists",
        )

    seed_track_keys = _parse_list(seed_track_keys_raw)
    seed_artist_names = _parse_list(seed_artist_names_raw)
    seed_playlist_names = _parse_list(seed_playlist_names_raw)
    seed_collection_names = _parse_list(seed_collection_names_raw)
    genre_seeds = _parse_list(genre_seeds_raw)
    include_collections = _parse_list(include_collections_raw)
    exclude_collections = _parse_list(exclude_collections_raw)
    exclude_genres = _parse_list(exclude_genres_raw)

    st.divider()
    st.warning(
        "Playlist Creator will create a **new playlist** in Plex but will not edit "
        "metadata or existing playlists."
    )
    payload = {
        "plex": {
            "url": cfg.plex_baseurl,
            "token": cfg.plex_token,
            "music_library": music_lib,
        },
        "playlist": {
            "exclude_played_days": int(exclude_days),
            "history_lookback_days": int(lookback_days),
            "max_tracks": int(max_tracks),
            "sonic_similar_limit": int(sonic_similar_limit),
            "deep_dive_target": int(deep_dive_target),
            "historical_ratio": float(historical_ratio),
            "exploit_weight": float(exploit_weight),
            "sonic_smoothing": 1 if sonic_smoothing else 0,

            # rating filters
            "min_rating": {
                "track": int(min_track),
                "album": int(min_album),
                "artist": int(min_artist),
            },
            "allow_unrated": 1 if allow_unrated else 0,

            # time periods / fallback
            "use_time_periods": 1 if use_time_periods else 0,
            "seed_fallback_mode": seed_fallback_mode.lower(),
            "seed_mode": seed_mode,

            "recency_bias": float(recency_bias),

            # play count filters
            "min_play_count": int(min_play_count),
            "max_play_count": int(max_play_count),

            # 💿 Year & duration filters (album-level year, track-level duration)
            "min_year": int(min_year),
            "max_year": int(max_year),
            "min_duration_sec": int(min_duration_sec),
            "max_duration_sec": int(max_duration_sec),

            # 👥 Artist / album caps
            "max_tracks_per_artist": int(max_tracks_per_artist),
            "max_tracks_per_album": int(max_tracks_per_album),

            # 📜 History filters
            "history_min_rating": int(history_min_rating),
            "history_max_play_count": int(history_max_play_count),

            # 🎯 Genre strictness & collections
            "genre_strict": 1 if genre_strict else 0,
            "allow_off_genre_fraction": float(off_genre_fraction),
            "include_collections": include_collections,
            "exclude_collections": exclude_collections,
            "exclude_genres": exclude_genres,

            # 🔥 Custom playlist title → naming + cover art
            "custom_title": custom_title.strip() or None,
            "cover_art_design": st.session_state.get("pc_coverart_select", "None"),
            "cover_art_color": st.session_state.get("pc_coverart_color_select", "#FF0000"),
            "cover_art_bg_color": st.session_state.get("pc_coverart_bg_color_select", "#000000"),

            # Seed lists
            "seed_track_keys": seed_track_keys,
            "seed_artist_names": seed_artist_names,
            "seed_playlist_names": seed_playlist_names,
            "seed_collection_names": seed_collection_names,
            "genre_seeds": genre_seeds,
        },
    }

    st.divider()

    # --- 3. SHOW RUN BUTTON ---
    run_btn = st.button("Generate Playlist", type="primary", key="pc_run")
    
    # Stop here if the user hasn't clicked Run
    if not run_btn:
        return

    # --- Execution Logic (Below this remains mostly the same) ---
    st.markdown("### Playlist Creator log")

    log_box = st.empty()
    log_lines = []

    env = os.environ.copy()
    env.update({
        "PLEX_BASEURL": cfg.plex_baseurl,
        "PLEX_URL": cfg.plex_baseurl,
        "PLEX_TOKEN": cfg.plex_token,
        "PYTHONIOENCODING": "utf-8",
        "PYTHONUTF8": "1",
    })


    try:
        proc = subprocess.Popen(
            ["python", PLAYLIST_CREATOR_SCRIPT],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            bufsize=1,
            env=env,
        )
        assert proc.stdout is not None
        assert proc.stdin is not None

        proc.stdin.write(json.dumps(payload))
        proc.stdin.close()

        for line in proc.stdout:
            log_lines.append(line.rstrip("\r\n"))
            tail = "\n".join(log_lines[-200:])
            log_box.code(tail or "…", language="bash")

        ret = proc.wait()
    except FileNotFoundError:
        st.error("Could not execute playlist_creator.py. Check that it's in Scripts/ and Python is on PATH.")
        return
    except Exception as e:
        st.error(f"Error while running Playlist Creator: {e}")
        return

    if ret == 0:
        st.success("Playlist Creator finished successfully. Check Plex for the new playlist.")
    else:
        st.error(f"Playlist Creator exited with code {ret}. Review the log above.")



# ---------------------------
# Compare tab
# ---------------------------

def ui_compare_tab():
    from datetime import datetime
    try:
        from zoneinfo import ZoneInfo
        tz = ZoneInfo("Europe/Zurich")
    except Exception:
        tz = None

    st.subheader("Compare Exported Metadata")
    st.caption(
        "Upload an **old** and **new** export CSV. \n"
        "Matches rows by **Track_ID / RatingKey** (preferred) or **Artist+Album+Track** (fallback)."
    )

    col1, col2 = st.columns(2)
    with col1:
        old_up = st.file_uploader("Upload OLD export CSV", type=["csv"], key="compare_old")
    with col2:
        new_up = st.file_uploader("Upload NEW export CSV", type=["csv"], key="compare_new")

    if old_up is None or new_up is None:
        st.info("Upload both files to enable comparison.")
        return

    try:
        old_df = read_csv_forgiving(old_up)
        new_df = read_csv_forgiving(new_up)
    except Exception as e:
        st.error(f"Could not read one of the CSVs: {e}")
        return

    with st.expander("Preview (first 25 rows)"):
        st.markdown("**OLD**")
        st.dataframe(old_df.head(25), use_container_width=True)
        st.markdown("**NEW**")
        st.dataframe(new_df.head(25), use_container_width=True)

    st.divider()

    # --- DYNAMIC COLUMN SELECTOR (CHECKLIST STYLE) ---
    # 1. Find columns that exist in BOTH files
    common_cols = [c for c in old_df.columns if c in new_df.columns]
    
    # 2. Exclude the ID columns from being compared against themselves (optional, but cleaner)
    ignored_keys = ["_key", "Track_ID", "RatingKey"]
    selectable_cols = [c for c in common_cols if c not in ignored_keys]

    st.markdown("### Select Columns to Compare")
    st.caption("Check the variables you want to include in the comparison report.")

    # --- Vertical Checklist Loop ---
    selected_vars = []
    
    for col_name in selectable_cols:
        # Start unchecked
        if st.checkbox(col_name, value=False, key=f"compare_chk_{col_name}"):
            selected_vars.append(col_name)
    # ------------------------------------

    st.divider()

    include_details = st.checkbox(
        "Include details (Old/Lost/Gained columns)",
        value=False,
        key="compare_details"
    )

    run = st.button("Run comparison", type="primary", key="compare_run")
    if not run:
        return
        
    if not selected_vars:
        st.error("Please select at least one column to compare.")
        return

    try:
        # Pass YOUR selected variables to the function
        result_df, summary = compare_exports_add_match_cols(
            old_df, new_df, 
            compare_vars=selected_vars, 
            include_details=include_details
        )
        st.success(f"Comparison complete using: **{summary.get('match_method', 'Unknown')}**")

        st.markdown("### Summary")
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("OLD rows", summary["old_rows"])
        m2.metric("NEW rows", summary["new_rows"])
        m3.metric("Matched keys", summary["matched_keys"])
        m4.metric("Unmatched NEW keys", summary["unmatched_new_keys"])

        st.markdown("### Match breakdown")
        for c in selected_vars:
            mc = f"{c}_Match"
            counts = summary.get(f"{mc}_counts", {})
            st.write(
                f"**{mc}** — yes: {counts.get('yes', 0):,} | "
                f"no: {counts.get('no', 0):,} | "
                f"not found: {counts.get('not found', 0):,}"
            )

        st.markdown("### Output preview (first 50 rows)")
        st.dataframe(result_df.head(50), use_container_width=True)

        now = datetime.now(tz) if tz else datetime.now()
        date_prefix = now.strftime("%Y_%m_%d")
        out_filename = f"{date_prefix} metadata_comparison_output.csv"
        out_path = os.path.join(APP_DIR, out_filename)

        try:
            result_df.to_csv(out_path, index=False, encoding="utf-8")
            st.info(f"Saved to app folder: `{out_path}`")
        except Exception as e:
            st.error(f"Could not save file to app folder: {e}")

        out_buf = io.BytesIO()
        result_df.to_csv(out_buf, index=False)
        st.download_button(
            f"Download {out_filename}",
            data=out_buf.getvalue(),
            file_name=out_filename,
            mime="text/csv",
        )

    except Exception as e:
        st.error(f"Comparison failed: {e}")

# ---------------------------------
# GALAXY / NETWORK VISUALIZATION TAB
# ---------------------------------
@st.cache_data(show_spinner=False)
def process_galaxy_data(csv_file):
    """
    Parses the Artist_Level_Info.csv, builds a 3D NetworkX graph,
    detects communities (clusters), and computes the 3D spring layout.
    Returns the dataframe enriched with x,y,z coordinates and cluster IDs.
    """
    # 1. Load Data
    try:
        df = pd.read_csv(csv_file)
    except Exception:
        # Fallback for forgiving read if standard fails
        df = read_csv_forgiving(csv_file)
    
    # Validation
    required_cols = ['Artist', 'Similar_Artists']
    if not all(col in df.columns for col in required_cols):
        return None, "CSV missing required columns: 'Artist' or 'Similar_Artists'"

    df['Similar_Artists'] = df['Similar_Artists'].fillna('')
    
    # 2. Build Graph
    G = nx.Graph()
    library_nodes = set(df['Artist'].unique())
    
    # Add Library Nodes
    for artist in library_nodes:
        G.add_node(artist, type='Library')

    # Add Edges & Missing Nodes
    for _, row in df.iterrows():
        source = row['Artist']
        similars = [s.strip() for s in row['Similar_Artists'].split(',') if s.strip()]
        for target in similars:
            if target not in library_nodes:
                G.add_node(target, type='Missing')
            G.add_edge(source, target)
            
    # 3. Detect Communities (Louvain) -> "Clusters"
    # Resolution < 1.0 = larger communities, > 1.0 = smaller/more communities
    try:
        partition = community_louvain.best_partition(G, resolution=1.2)
    except Exception:
        # Fallback if louvain fails or empty graph
        partition = {n: 0 for n in G.nodes()}

    # 4. Compute 3D Layout (Physics)
    # k controls node spacing. Smaller = tighter.
    pos = nx.spring_layout(G, dim=3, k=0.15, iterations=40, seed=42)

    # 5. Format for Plotly
    node_data = []
    for node in G.nodes():
        x, y, z = pos[node]
        cluster = partition[node]
        node_type = G.nodes[node]['type']
        
        node_data.append({
            "Artist": node,
            "x": x, "y": y, "z": z,
            "Cluster": str(cluster),
            "Type": node_type
        })
        
    final_df = pd.DataFrame(node_data)
    
    # Add Play Count or Recommendation Count metrics if available?
    # For now, we stick to the clean "Cluster" logic requested.
    
    return final_df, G

def ui_galaxy_tab():
    st.subheader("🌌 Plex Music Galaxy")
    
    if not HAS_GALAXY_DEPS:
        st.error("Missing dependencies. Please run: `pip install networkx plotly python-louvain`")
        return

    st.caption("Visualize your library as a 3D star map. Colors represent sonic clusters.")

    # 1. File Selection (Upload or Export Folder)
    # Check Exports folder for compatible files
    export_files = []
    if os.path.exists(EXPORTS_DIR):
        export_files = [f for f in os.listdir(EXPORTS_DIR) if "Artist_Level_Info" in f and f.endswith(".csv")]
    
    col1, col2 = st.columns([1, 1])
    with col1:
        input_method = st.radio("Input Source", ["Select from Exports", "Upload File"], horizontal=True)
    
    csv_source = None
    if input_method == "Select from Exports":
        if not export_files:
            st.info(f"No 'Artist_Level_Info' files found in {EXPORTS_DIR}. Please run an export first.")
        else:
            selected_file = st.selectbox("Select File", sorted(export_files, reverse=True))
            csv_source = os.path.join(EXPORTS_DIR, selected_file)
    else:
        uploaded_file = st.file_uploader("Upload 'Artist_Level_Info.csv'", type=["csv"])
        if uploaded_file:
            csv_source = uploaded_file

    if not csv_source:
        return

    # 2. Process Data
    with st.spinner("Computing galaxy layout (physics simulation)..."):
        try:
            plot_df, G = process_galaxy_data(csv_source)
            if plot_df is None: # Error case
                st.error(G) # G contains error message string here
                return
        except Exception as e:
            st.error(f"Error processing graph: {e}")
            return

    st.divider()

    # 3. Controls
    c_ctrl1, c_ctrl2 = st.columns([1, 2])
    with c_ctrl1:
        show_missing = st.toggle("Show Missing Artists (Red Nodes)", value=False)
        
    # Filter Data based on toggle
    if show_missing:
        # Show everything
        filtered_df = plot_df.copy()
    else:
        # Show only library nodes
        filtered_df = plot_df[plot_df['Type'] == 'Library'].copy()

    # Search / Focus
    # Only allow searching for nodes currently in the graph
    available = sorted(filtered_df['Artist'].unique())
    with c_ctrl2:
        target_artist = st.selectbox("🔭 Focus on Artist", options=available, index=0 if available else None)

    # 4. Plot Logic
    if target_artist and not filtered_df.empty:
        
        # Identify Neighbors
        if target_artist in G:
            # We get neighbors from the full graph G so connections exist even if hidden
            # But we only display them if they are in filtered_df
            raw_neighbors = list(G.neighbors(target_artist))
            visible_neighbors = set(raw_neighbors).intersection(set(filtered_df['Artist']))
        else:
            visible_neighbors = set()

        # Assign Display Types
        def assign_style(row):
            if row['Artist'] == target_artist:
                return "Focus", 20, 1.0  # Type, Size, Opacity
            elif row['Artist'] in visible_neighbors:
                return "Neighbor", 10, 0.9
            return "Background", 4, 0.2

        # Apply styles
        # Vectorized apply is messy with multiple returns, simple iteration is fast enough for <10k nodes
        styles = filtered_df.apply(assign_style, axis=1, result_type='expand')
        filtered_df[['display_type', 'pt_size', 'pt_opacity']] = styles

        # Color Logic
        # Library -> Cluster Color
        # Missing -> Red
        # We handle this by splitting traces.

        fig = go.Figure()

        # -- TRACE A: BACKGROUND (Library) --
        # Colored by cluster, small, faint
        bg_lib = filtered_df[(filtered_df['display_type'] == 'Background') & (filtered_df['Type'] == 'Library')]
        if not bg_lib.empty:
            # We iterate clusters to get distinct colors in legend/plot
            for cluster_id in sorted(bg_lib['Cluster'].unique()):
                clust_data = bg_lib[bg_lib['Cluster'] == cluster_id]
                fig.add_trace(go.Scatter3d(
                    x=clust_data['x'], y=clust_data['y'], z=clust_data['z'],
                    mode='markers',
                    marker=dict(size=4, opacity=0.3),
                    hovertext=clust_data['Artist'],
                    hoverinfo='text',
                    name=f'Cluster {cluster_id}',
                    legendgroup='Clusters'
                ))

        # -- TRACE B: BACKGROUND (Missing) --
        # Red, small, faint
        bg_miss = filtered_df[(filtered_df['display_type'] == 'Background') & (filtered_df['Type'] == 'Missing')]
        if not bg_miss.empty:
            fig.add_trace(go.Scatter3d(
                x=bg_miss['x'], y=bg_miss['y'], z=bg_miss['z'],
                mode='markers',
                marker=dict(size=3, color='#ff4b4b', opacity=0.2), # Standard Red
                hovertext=bg_miss['Artist'],
                hoverinfo='text',
                name='Missing Artists',
                legendgroup='Missing'
            ))

        # -- TRACE C: NEIGHBORS (Library + Missing) --
        # Larger, brighter. 
        # We want to maintain their color logic (Red vs Cluster) but boost opacity/size.
        neighbors = filtered_df[filtered_df['display_type'] == 'Neighbor']
        if not neighbors.empty:
            # We can use a trick: Plot all neighbors in one go, but define individual colors
            # Or split them. Splitting is cleaner for the 'Red' requirement.
            
            # Neighbor (Library)
            n_lib = neighbors[neighbors['Type'] == 'Library']
            if not n_lib.empty:
                 # To keep cluster colors, we rely on Plotly's default cycling match 
                 # OR we just make neighbors a distinct 'Highlight' color (e.g. White/Cyan).
                 # To match your R script: "Color is always by Cluster"
                 # Plotly Scatter3d doesn't easily map a column to color AND allow discrete clusters 
                 # without complex color_continuous_scale.
                 # Simplification: Neighbors get a bright generic color (Cyan) to stand out, 
                 # OR we iterate clusters again. Let's use Cyan for contrast.
                 fig.add_trace(go.Scatter3d(
                    x=n_lib['x'], y=n_lib['y'], z=n_lib['z'],
                    mode='markers+text',
                    marker=dict(size=8, color='#00d2ff', opacity=0.9), # Cyan
                    text=n_lib['Artist'], textposition="top center",
                    textfont=dict(size=10, color="white"),
                    name='Related (Library)'
                ))
            
            # Neighbor (Missing)
            n_miss = neighbors[neighbors['Type'] == 'Missing']
            if not n_miss.empty:
                 fig.add_trace(go.Scatter3d(
                    x=n_miss['x'], y=n_miss['y'], z=n_miss['z'],
                    mode='markers+text',
                    marker=dict(size=8, color='#ff4b4b', opacity=0.9, symbol='diamond'), # Red Diamond
                    text=n_miss['Artist'], textposition="top center",
                    textfont=dict(size=10, color="#ffcbcb"),
                    name='Related (Missing)'
                ))

        # -- TRACE D: FOCUS --
        focus = filtered_df[filtered_df['display_type'] == 'Focus']
        if not focus.empty:
            fig.add_trace(go.Scatter3d(
                x=focus['x'], y=focus['y'], z=focus['z'],
                mode='markers+text',
                marker=dict(size=20, color='white', line=dict(width=2, color='black')),
                text=focus['Artist'], textposition="top center",
                textfont=dict(size=14, color="yellow", family="Arial Black"),
                name='Selected'
            ))

        # Layout styling (No axis labels, dark theme)
        fig.update_layout(
            height=800,
            margin=dict(l=0, r=0, b=0, t=0),
            scene=dict(
                xaxis=dict(visible=False),
                yaxis=dict(visible=False),
                zaxis=dict(visible=False),
                bgcolor='#0e1117' # Dark Streamlit background match
            ),
            paper_bgcolor='#0e1117',
            legend=dict(itemsizing='constant', font=dict(color='white')),
        )

        st.plotly_chart(fig, use_container_width=True)

# ---------------------------
# Main
# ---------------------------
def main():
    st.set_page_config(layout="wide", page_title=APP_TITLE)

    # 1. Check for the password variable
    # If this is None or empty, we assume we are in "Trusted/Local" mode
    app_password = os.getenv("APP_PASSWORD")

    # 2. The Gatekeeper Logic
    # We only run this block if a password was actually found in the environment
    if app_password:
        if "authenticated" not in st.session_state:
            st.session_state["authenticated"] = False

        if not st.session_state["authenticated"]:
            st.sidebar.title("Login")
            # Use a key to keep the input stable
            pw = st.sidebar.text_input("Enter App Password", type="password", key="password_input")
            
            # Check password on button click
            if st.sidebar.button("Login"):
                if pw == app_password:
                    st.session_state["authenticated"] = True
                    st.rerun()
                else:
                    st.sidebar.error("Incorrect Password")
            
            st.warning("Protected Mode: Please login to access the music hub.")
            st.stop() # Stops the rest of the app from loading until logged in

    os.makedirs(EXPORTS_DIR, exist_ok=True) # make sure exports dir exists

    # 3. Main Application Load
    # If we get here, either no password was set, or the user successfully logged in.
    st.title(APP_TITLE)
    st.caption("Export music metadata, update metadata, and build intelligent playlists.")
    cfg = ui_sidebar_config()

    tab1, tab2, tab3, tab4, tab5, tab6, tab7 = st.tabs([
        "Export",
        "Update from CSV (Single Script)",
        "Update from CSV (Multiple Scripts)",
        "Compare Exported Metadata",
        "Playlist Creator",
        "Galaxy Explorer",
        "Artist Recommender"
    ])

    with tab1:
        ui_export_tab(cfg)
    with tab2:
        ui_update_tab(cfg)
    with tab3:
        ui_update_multi_tab(cfg)
    with tab4:
        ui_compare_tab()
    with tab5:
        ui_playlist_creator_tab(cfg)
    with tab6:
        # Initialize session state for this tab
        if "galaxy_launched" not in st.session_state:
            st.session_state["galaxy_launched"] = False

        # If not launched yet, show the button
        if not st.session_state["galaxy_launched"]:
            st.info("The Galaxy Explorer creates a 3D visualization of your music library. This requires significant processing power.")
            if st.button("Launch Galaxy Explorer", type="primary"):
                st.session_state["galaxy_launched"] = True
                st.rerun()
        
        # If launched, run the module
        else:
            plex_galaxy.run()
            # Optional: Add a 'Close' button to reset
            if st.button("Close Visualization"):
                st.session_state["galaxy_launched"] = False
                st.rerun()
    with tab7:
        st.subheader("Similar Artist Recommender")
        st.caption("Discover missing artists based on library similarity and listening intensity.")

        # 1. File Discovery
        export_files = []
        if os.path.exists(EXPORTS_DIR):
            export_files = [f for f in os.listdir(EXPORTS_DIR) if "Artist_Level_Info" in f and f.endswith(".csv")]
        
        if not export_files:
            st.info("Please run an Export first to generate recommendations.")
        else:
            selected_file = st.selectbox("Select Artist Metadata File", sorted(export_files, reverse=True), key="rec_file_select")
            
            if st.button("Generate Recommendations", type="primary"):
                file_path = os.path.join(EXPORTS_DIR, selected_file)
                input_df = read_csv_forgiving(file_path)
                
                with st.spinner("Analyzing library connections..."):
                    recs_df = artist_recommender.get_recommendations(input_df)
                
                st.success(f"Found {len(recs_df)} artists missing from your library.")

                # --- AUTO-SAVE LOGIC ---
                from datetime import datetime
                date_str = datetime.now().strftime("%Y_%m_%d")
                auto_filename = f"{date_str} Artist_Recommendations.csv"
                auto_save_path = os.path.join(EXPORTS_DIR, auto_filename)
                
                try:
                    recs_df.to_csv(auto_save_path, index=False, encoding="utf-8")
                    st.info(f"Automatically saved to: `{auto_save_path}`")
                except Exception as e:
                    st.error(f"Failed to auto-save file: {e}")
                # -----------------------

                # Display Results
                st.dataframe(
                    recs_df.head(50), 
                    use_container_width=True,
                    column_config={
                        "Priority_Score": st.column_config.NumberColumn("Priority Score", format="%.2f"),
                        "Related_Library_Artists_Total_Play_Count": "Total Plays of Peers"
                    }
                )

                # Manual Download Button
                csv_buffer = io.BytesIO()
                recs_df.to_csv(csv_buffer, index=False)
                st.download_button(
                    f"Download {auto_filename}",
                    data=csv_buffer.getvalue(),
                    file_name=auto_filename,
                    mime="text/csv"
                )


if __name__ == "__main__":
    main()

