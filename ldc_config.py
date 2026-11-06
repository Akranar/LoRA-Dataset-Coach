"""Shared config + model-path resolution for LoRA-Dataset-Coach.

No GUI dependencies, so this can be imported from any of the CLI scripts
(analyze_dataset.py, lora_evaluator.py, wd14_local.py,
mask_generator_local.py) as well as from manager.py, and they all agree on
one config.json file and one path-resolution policy:

    1. an explicit function argument (if the caller passes one)
    2. an environment variable
    3. a key in config.json (editable from the GUI Settings tab)
    4. a reasonable cross-platform default

Usage::

    from ldc_config import find_insightface_root, not_found_message
    root, tried = find_insightface_root()
    if root is None:
        return {"error": not_found_message("insightface antelopev2", tried)}
"""
import json
import os
from pathlib import Path

CONFIG_FILE = Path(__file__).parent / "config.json"

DEFAULT_CONFIG = {
    # Path to the ComfyUI python_embeded.exe that has insightface + torch CUDA
    "comfyui_python": r"C:\AI\ComfyUI-future\ComfyUI_windows_portable\python_embeded\python.exe",
    # Default folder pre-filled in the analyzer
    "datasets_dir": "C:\\AI\\datasets",
    # Compute device: "auto" (GPU si dispo) | "cuda" | "cpu"
    "device": "auto",
    # ComfyUI local (evaluateur : generation automatique du jeu de test)
    "comfyui_url": "http://127.0.0.1:8188",
    "comfyui_eval_workflow": "",
    # Createur de LoRA (entrainement) + envoi des checkpoints a ComfyUI
    "aitoolkit_dir": r"C:\AI\ai-toolkit",
    "aitoolkit_python": r"C:\AI\ai-toolkit\venv\Scripts\python.exe",
    "comfyui_loras_dir": r"C:\AI\ComfyUI-future\ComfyUI_windows_portable\ComfyUI\models\loras",
    # Model folders - empty string = auto-detect (env var / default location).
    # Editable from the GUI Settings tab.
    "insightface_root": "",
    "wd14_model_dir": "",
    "rmbg_model_dir": "",
    # Root folder substituted into lora_prep.py's generated training configs
    # in place of the author's personal "C:/AI" paths. Empty = an obvious
    # placeholder is used instead so you notice it in the generated files.
    "training_models_root": "",
    # Self-updater: disabled by default so it can never silently overwrite
    # local modifications. See updater.py / ldc_config.updates_enabled().
    "allow_self_update": False,
}


def load_config():
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            for k, v in DEFAULT_CONFIG.items():
                cfg.setdefault(k, v)
            return cfg
        except Exception:
            pass
    return dict(DEFAULT_CONFIG)


def save_config(cfg):
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)


def updates_enabled():
    """True only if the user explicitly opted into the self-updater."""
    return bool(load_config().get("allow_self_update", False))


def _search_model_root(env_var, config_key, default_candidates, required_subpath):
    """Looks for a model folder containing `required_subpath` (a list of path
    parts, e.g. ["models", "antelopev2"]).

    Order: env var -> config.json key -> each of default_candidates (list of
    (label, path) tuples). Returns (found_root_or_None, tried_descriptions).
    """
    tried = []

    env_val = os.environ.get(env_var)
    if env_val:
        tried.append(f"{env_var} env var: {env_val}")
        if os.path.isdir(os.path.join(env_val, *required_subpath)):
            return env_val, tried

    cfg_val = load_config().get(config_key)
    if cfg_val:
        tried.append(f'config.json["{config_key}"]: {cfg_val}')
        if os.path.isdir(os.path.join(cfg_val, *required_subpath)):
            return cfg_val, tried

    for label, cand in default_candidates:
        tried.append(f"{label}: {cand}")
        if os.path.isdir(os.path.join(cand, *required_subpath)):
            return cand, tried

    return None, tried


def find_insightface_root():
    """Looks for the insightface `antelopev2` model folder.

    Returns (root_or_None, tried_descriptions). `root/models/antelopev2`
    must exist for a candidate to be accepted (insightface's own layout).
    """
    default = os.path.join(os.path.expanduser("~"), ".insightface")
    return _search_model_root(
        "LDC_INSIGHTFACE_ROOT", "insightface_root",
        [("default location (~/.insightface)", default)],
        ["models", "antelopev2"],
    )


def find_wd14_model_dir(model_name="wd-v1-4-moat-tagger-v2"):
    """Looks for an existing WD14 tagger model (.onnx + .csv).

    Returns (dir_or_None, tried_descriptions). If nothing is found, callers
    should download the model into the cross-platform cache dir below
    (``default_wd14_download_dir()``) rather than into a hardcoded path.
    """
    default = os.path.join(os.path.expanduser("~"), ".cache", "ldc", "wd14")
    return _search_file_dir(
        "LDC_WD14_MODEL_DIR", "wd14_model_dir",
        [("default cache (~/.cache/ldc/wd14)", default)],
        [f"{model_name}.onnx", f"{model_name}.csv"],
    )


def default_wd14_download_dir():
    env_val = os.environ.get("LDC_WD14_MODEL_DIR")
    if env_val:
        return env_val
    cfg_val = load_config().get("wd14_model_dir")
    if cfg_val:
        return cfg_val
    return os.path.join(os.path.expanduser("~"), ".cache", "ldc", "wd14")


def find_rmbg_model_dir():
    """Looks for an installed ComfyUI-BRIA_AI-RMBG custom node folder (the
    one containing briarmbg.py - this is a Python module, not just model
    weights, so there is no generic cache dir to auto-download it into;
    the user has to point at an existing install)."""
    return _search_file_dir(
        "LDC_RMBG_MODEL_DIR", "rmbg_model_dir", [], ["briarmbg.py"],
    )


def _search_file_dir(env_var, config_key, default_candidates, required_files):
    """Like _search_model_root but checks for files (not a subfolder)
    directly inside each candidate directory."""
    tried = []

    def _has_all(d):
        return all(os.path.isfile(os.path.join(d, fn)) for fn in required_files)

    env_val = os.environ.get(env_var)
    if env_val:
        tried.append(f"{env_var} env var: {env_val}")
        if _has_all(env_val):
            return env_val, tried

    cfg_val = load_config().get(config_key)
    if cfg_val:
        tried.append(f'config.json["{config_key}"]: {cfg_val}')
        if _has_all(cfg_val):
            return cfg_val, tried

    for label, cand in default_candidates:
        tried.append(f"{label}: {cand}")
        if _has_all(cand):
            return cand, tried

    return None, tried


def not_found_message(what, tried):
    """Builds a clear English error message naming every location checked
    and how to fix it."""
    lines = [f"Could not find the {what} model files."]
    lines.append("Looked in:")
    for t in tried:
        lines.append(f"  - {t}")
    lines.append("")
    lines.append("To fix this, do one of:")
    lines.append("  1. Set the corresponding LDC_*_ROOT/LDC_*_DIR environment variable.")
    lines.append("  2. Set it in config.json, or in the GUI's Settings tab.")
    lines.append("  3. Place the model files at the default location shown above.")
    return "\n".join(lines)
