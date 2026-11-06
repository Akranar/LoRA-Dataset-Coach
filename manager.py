"""
AI File Manager - Gestion visuelle des LoRAs et fichiers I/O ComfyUI.
Theme dark Catppuccin, sans dependances.
"""
import json
import os
import shutil
import subprocess
import sys
import threading
import urllib.request
from datetime import datetime
from pathlib import Path

import tkinter as tk
from tkinter import Tk, Frame, Label, Button, Entry, StringVar, Text, filedialog, messagebox, ttk

# PIL pour le preview live des photos analysees (optionnel)
try:
    from PIL import Image as PILImage, ImageTk as PILImageTk
    _HAS_PIL = True
except Exception:
    _HAS_PIL = False

# Path vers le python embeded de ComfyUI-future (qui a insightface)
COMFYUI_FUTURE_PY = r"C:\AI\ComfyUI-future\ComfyUI_windows_portable\python_embeded\python.exe"
OLLAMA_URL = "http://localhost:11434/api/generate"
OLLAMA_TAGS_URL = "http://localhost:11434/api/tags"

# Modeles proposes dans le dropdown (du plus rapide au plus precis)
PROMPT_MODELS = [
    ("gemma3:4b",     "Rapide (~3s) - Qualite correcte"),
    ("gemma4:latest", "Lent (~30s premier appel, ~10s ensuite) - Meilleure qualite"),
]

# System prompts par type de generation

# ============================================================
# Theme
# ============================================================
BG       = "#1e1e2e"   # base
BG2      = "#181825"   # mantle (dark)
CARD     = "#313244"   # surface0
CARD_HI  = "#45475a"   # surface1
TEXT     = "#cdd6f4"   # text
TEXT_DIM = "#a6adc8"   # subtext0
ACCENT   = "#89b4fa"   # blue
ACCENT2  = "#f5c2e7"   # pink
GREEN    = "#a6e3a1"
RED      = "#f38ba8"
ORANGE   = "#fab387"   # peach (warnings / grade C)
YELLOW   = "#f9e2af"

FONT_TITLE  = ("Segoe UI", 18, "bold")
FONT_H1     = ("Segoe UI", 13, "bold")
FONT_BODY   = ("Segoe UI", 10)
FONT_SMALL  = ("Segoe UI", 9)
FONT_MONO   = ("Consolas", 9)
FONT_EMOJI  = ("Segoe UI Emoji", 18)

# ============================================================
# Config
# ============================================================
# Config storage + model-path resolution now lives in ldc_config.py (shared
# with the CLI scripts: analyze_dataset.py, lora_evaluator.py, wd14_local.py,
# mask_generator_local.py) so the GUI and the subprocesses agree on one
# config.json and one path-resolution policy (env var -> config.json ->
# default). Re-exported here under the same names so every existing call
# site in this file keeps working unchanged.
sys.path.insert(0, str(Path(__file__).parent))
from ldc_config import CONFIG_FILE, DEFAULT_CONFIG, load_config, save_config




def open_in_explorer(path):
    p = Path(path)
    if not p.exists():
        messagebox.showerror("Error", f"Folder not found:\n{path}")
        return
    if sys.platform == "win32":
        os.startfile(str(p))


# ============================================================
# Widgets stylises
# ============================================================
def make_button(parent, text, command, primary=False, danger=False, width=None):
    if primary:
        bg, fg, ahover = ACCENT, BG, "#74c7ec"
    elif danger:
        bg, fg, ahover = RED, BG, "#eba0ac"
    else:
        bg, fg, ahover = CARD_HI, TEXT, "#585b70"
    b = Button(parent, text=text, command=command, font=FONT_BODY,
               bg=bg, fg=fg, activebackground=ahover, activeforeground=fg,
               relief="flat", padx=14, pady=7, cursor="hand2",
               borderwidth=0)
    if width:
        b.configure(width=width)
    return b


# ============================================================
# App
# ============================================================
class App:
    def __init__(self, root):
        self.root = root
        self.cfg = load_config()

        root.title("LoRA Dataset Coach")
        root.geometry("1180x780")
        root.configure(bg=BG)
        root.minsize(900, 600)

        # Chemin du Python ComfyUI (configurable, sinon valeur par defaut)
        self.comfyui_py = self.cfg.get("comfyui_python") or self.comfyui_py

        # Style ttk pour treeview dark
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("Dark.Treeview",
                        background=CARD, foreground=TEXT, fieldbackground=CARD,
                        rowheight=28, borderwidth=0, font=FONT_BODY)
        style.configure("Dark.Treeview.Heading",
                        background=BG2, foreground=ACCENT, font=FONT_H1,
                        relief="flat", borderwidth=0)
        style.map("Dark.Treeview", background=[("selected", ACCENT)],
                 foreground=[("selected", BG)])
        style.configure("Dark.TNotebook", background=BG, borderwidth=0)
        style.configure("Dark.TNotebook.Tab",
                        background=BG2, foreground=TEXT_DIM,
                        padding=[20, 8], font=FONT_BODY, borderwidth=0)
        style.map("Dark.TNotebook.Tab",
                 background=[("selected", CARD)],
                 foreground=[("selected", TEXT)])

        # Header
        header = Frame(root, bg=BG, pady=14, padx=20)
        header.pack(fill="x")
        Label(header, text="🧬  LoRA Dataset Coach",
              font=FONT_TITLE, fg=TEXT, bg=BG).pack(side="left")
        Label(header, text="Analyze · Prepare · Evaluate your LoRA datasets",
              font=FONT_BODY, fg=TEXT_DIM, bg=BG).pack(side="left", padx=15, pady=8)

        # Status bar (cree AVANT les tabs car ils l'utilisent pendant init)
        self.status_var = StringVar(value="Ready")
        status_bar = Frame(root, bg=BG2, padx=15, pady=6)
        status_bar.pack(fill="x", side="bottom")
        Label(status_bar, textvariable=self.status_var,
              font=FONT_SMALL, fg=TEXT_DIM, bg=BG2, anchor="w").pack(fill="x")

        # Notebook
        self.notebook = ttk.Notebook(root, style="Dark.TNotebook")
        self.notebook.pack(fill="both", expand=True, padx=15, pady=10)
        notebook = self.notebook

        self._build_analyzer_tab(notebook)
        self._build_trainer_tab(notebook)
        self._build_evaluator_tab(notebook)
        self._build_voice_tab(notebook)
        self._build_music_tab(notebook)
        self._build_config_tab(notebook)

    def select_tab(self, name):
        """Selectionne un tab par nom court."""
        mapping = {"analyzer": 0, "trainer": 1, "evaluator": 2, "voice": 3, "music": 4, "config": 5}
        if name in mapping:
            self.notebook.select(mapping[name])

    # =========================================================
    # ONGLET CREER LoRA — lance l'entrainement du dossier prepare
    # =========================================================
    def _build_trainer_tab(self, parent):
        frame = Frame(parent, bg=BG, padx=15, pady=12)
        parent.add(frame, text="  🏋 Create LoRA  ")
        self.train_proc = None
        self.train_runner = None
        self.train_vars = {}

        Label(frame, text="LoRA Creator", font=FONT_H1, fg=ACCENT2, bg=BG).pack(anchor="w")
        Label(frame, text="1. Analyze → 🧬 Prepare LoRA   2. Here: check the paths, start "
                          "training, follow progress   3. Send the checkpoints to "
                          "ComfyUI → batch-test in 📊 Evaluate: keep the best epoch.",
              font=FONT_SMALL, fg=TEXT_DIM, bg=BG, wraplength=1000, justify="left").pack(anchor="w", pady=(0, 8))

        row = Frame(frame, bg=CARD, padx=10, pady=8)
        row.pack(fill="x", pady=3)
        Label(row, text="📁 Prepared folder:", font=FONT_BODY, fg=TEXT, bg=CARD).pack(side="left")
        self.train_folder = StringVar(value="")
        tk.Entry(row, textvariable=self.train_folder, font=FONT_MONO, bg=BG2, fg=TEXT,
                 insertbackground=TEXT, relief="flat").pack(side="left", fill="x", expand=True,
                                                             ipady=5, padx=8)

        def pick():
            d = filedialog.askdirectory(title="Folder created by “Prepare LoRA”")
            if d:
                self.train_folder.set(d)
                self._train_load_folder()
        make_button(row, "📂", pick).pack(side="left")
        make_button(row, "↻", self._train_load_folder).pack(side="left", padx=4)

        self.train_info = Label(frame, text="Choose a prepared folder.", font=FONT_SMALL,
                                fg=TEXT_DIM, bg=BG, justify="left", anchor="w", wraplength=1000)
        self.train_info.pack(fill="x", pady=(2, 4))

        # Chemins editables (lignes "set" du .bat, ou ai-toolkit)
        self.train_paths_frame = Frame(frame, bg=CARD, padx=10, pady=6)
        self.train_paths_frame.pack(fill="x", pady=3)

        ctl = Frame(frame, bg=BG)
        ctl.pack(fill="x", pady=6)
        self.train_start_btn = Button(ctl, text="🏋 Start training", font=FONT_H1, bg=GREEN,
                                      fg=BG, relief="flat", padx=16, pady=6, command=self._train_start)
        self.train_start_btn.pack(side="left")
        self.train_stop_btn = Button(ctl, text="⏹ Stop", font=FONT_BODY, bg=RED, fg=BG,
                                     relief="flat", padx=12, pady=6, state="disabled",
                                     command=self._train_stop)
        self.train_stop_btn.pack(side="left", padx=8)
        self.train_send_btn = Button(ctl, text="📤 Checkpoints → ComfyUI → batch test", font=FONT_BODY,
                                     bg=ACCENT, fg=BG, relief="flat", padx=12, pady=6,
                                     command=self._train_send_checkpoints)
        self.train_send_btn.pack(side="right")

        self.train_status = Label(frame, text="⏸ Waiting", font=FONT_BODY, fg=TEXT_DIM, bg=BG,
                                  anchor="w")
        self.train_status.pack(fill="x")
        self.train_progress = ttk.Progressbar(frame, mode="determinate", maximum=100)
        self.train_progress.pack(fill="x", pady=2)

        body = Frame(frame, bg=BG)
        body.pack(fill="both", expand=True, pady=4)
        self.train_log = Text(body, bg=BG2, fg=TEXT, font=FONT_MONO, height=12, relief="flat",
                              wrap="none")
        self.train_log.pack(side="left", fill="both", expand=True)
        right = Frame(body, bg=CARD, padx=8, pady=6, width=300)
        right.pack(side="right", fill="y", padx=(8, 0))
        Label(right, text="💾 Checkpoints", font=FONT_BODY, fg=ACCENT, bg=CARD).pack(anchor="w")
        self.train_ckpt_list = tk.Listbox(right, bg=BG2, fg=TEXT, font=FONT_SMALL, relief="flat",
                                          width=38, height=9, selectmode="extended",
                                          exportselection=False)
        self.train_ckpt_list.pack(fill="both", expand=True)
        Label(right, text="Ctrl/Shift+click: multiple selection", font=FONT_SMALL,
              fg=TEXT_DIM, bg=CARD).pack(anchor="w")

        # Comparaison rapide : meme prompt + meme seed, 1 image par checkpoint selectionne
        # (vars partagees avec l'onglet Evaluer, construit apres)
        self.cmp_prompt = StringVar(value="close-up portrait photo of {trigger}, natural light, sharp focus")
        self.cmp_seed = tk.IntVar(value=1234)
        Label(right, text="🖼 Quick compare", font=FONT_BODY, fg=ACCENT, bg=CARD).pack(anchor="w", pady=(6, 0))
        tk.Entry(right, textvariable=self.cmp_prompt, font=FONT_SMALL, bg=BG2, fg=TEXT,
                 insertbackground=TEXT, relief="flat").pack(fill="x", pady=2)
        seed_row = Frame(right, bg=CARD)
        seed_row.pack(fill="x")
        Label(seed_row, text="Seed:", font=FONT_SMALL, fg=TEXT, bg=CARD).pack(side="left")
        tk.Entry(seed_row, textvariable=self.cmp_seed, font=FONT_SMALL, width=10, bg=BG2, fg=TEXT,
                 insertbackground=TEXT, relief="flat").pack(side="left", padx=4)
        self.train_cmp_btn = Button(right, text="🖼 1 image per selected checkpoint", font=FONT_SMALL,
                                    bg=ACCENT2, fg=BG, relief="flat", pady=4,
                                    command=self._train_quick_compare)
        self.train_cmp_btn.pack(fill="x", pady=(4, 0))

    def _train_log_write(self, text):
        self.train_log.insert("end", text)
        # Garde le log leger (les tqdm crachent des milliers de lignes)
        if int(self.train_log.index("end-1c").split(".")[0]) > 3000:
            self.train_log.delete("1.0", "1000.0")
        self.train_log.see("end")

    def _train_load_folder(self):
        import lora_trainer as lt
        folder = self.train_folder.get().strip()
        for w in self.train_paths_frame.winfo_children():
            w.destroy()
        self.train_vars = {}
        r = lt.detect_runner(folder) if folder else {"kind": None, "error": "No folder."}
        self.train_runner = r
        if not r.get("kind"):
            self.train_info.config(text=f"⚠️ {r.get('error')}", fg=YELLOW)
            self.train_start_btn.config(state="disabled")
            self._train_refresh_checkpoints()
            return
        self.train_start_btn.config(state="normal")

        def field(label, var, row_i, picker=None):
            Label(self.train_paths_frame, text=label, font=FONT_SMALL, fg=TEXT, bg=CARD,
                  width=16, anchor="w").grid(row=row_i, column=0, sticky="w")
            tk.Entry(self.train_paths_frame, textvariable=var, font=FONT_MONO, bg=BG2, fg=TEXT,
                     insertbackground=TEXT, relief="flat", width=95).grid(row=row_i, column=1,
                                                                        sticky="we", pady=1)
            if picker:
                make_button(self.train_paths_frame, "📂", lambda v=var: picker(v)).grid(row=row_i, column=2)

        if r["kind"] == "bat":
            vars_ = lt.read_bat_vars(r["file"])
            for i, (k, v) in enumerate(vars_.items()):
                var = StringVar(value=v)
                self.train_vars[k] = var
                picker = None if k == "MODEL_VERSION" else (
                    self._pick_folder if k.endswith("_DIR") else self._pick_file)
                field(k, var, i, picker)
            self.train_info.config(text=f"✅ musubi-tuner: {r['file'].name} — check the paths "
                                        f"below (saved into the .bat on launch).", fg=GREEN)
        else:
            for i, (k, lbl, picker) in enumerate((
                    ("aitoolkit_dir", "ai-toolkit dir", self._pick_folder),
                    ("aitoolkit_python", "python ai-toolkit", self._pick_file))):
                var = StringVar(value=self.cfg.get(k, ""))
                self.train_vars[k] = var
                field(lbl, var, i, picker)
            self.train_info.config(text=f"✅ ai-toolkit: {r['file'].name} — models are "
                                        f"downloaded from HuggingFace on first launch.", fg=GREEN)
        self._train_refresh_checkpoints()

    def _train_start(self):
        import lora_trainer as lt
        r = self.train_runner
        if not r or not r.get("kind"):
            return
        if self.train_proc and self.train_proc.poll() is None:
            messagebox.showwarning("Training", "A training run is already in progress.")
            return
        vals = {k: v.get().strip() for k, v in self.train_vars.items()}
        if r["kind"] == "bat":
            missing = lt.check_paths(vals)
            if missing and not messagebox.askyesno(
                    "Paths not found",
                    "These files/folders do not exist:\n" + "\n".join("• " + m for m in missing) +
                    "\n\nTraining will very likely fail. Launch anyway?"):
                return
            lt.write_bat_vars(r["file"], vals)
        else:
            self.cfg.update(vals)
            try:
                save_config(self.cfg)
            except Exception:
                pass
        try:
            cmd, cwd = lt.build_command(r, vals.get("aitoolkit_dir"), vals.get("aitoolkit_python"))
            self.train_proc = lt.start(cmd, cwd)
        except Exception as e:
            messagebox.showerror("Cannot launch", str(e))
            return
        self.train_log.delete("1.0", "end")
        self._train_log_write(f"$ {' '.join(cmd)}\n   (in {cwd})\n\n")
        self.train_start_btn.config(state="disabled")
        self.train_stop_btn.config(state="normal")
        self.train_progress.config(value=0)
        self.train_status.config(text="🏋 Training in progress…", fg=ACCENT)
        proc = self.train_proc

        def reader():
            state = {}
            for line in iter(proc.stdout.readline, ""):
                # tqdm reecrit sa ligne avec \r : on ne garde que le dernier etat
                last = line.replace("\r", "\n").rstrip("\n").split("\n")[-1]
                upd = lt.parse_progress(last)
                state.update(upd)
                self.root.after(0, lambda l=last, st=dict(state), u=bool(upd):
                                self._train_on_line(l, st, u))
            code = proc.wait()
            self.root.after(0, lambda: self._train_on_exit(code))
        threading.Thread(target=reader, daemon=True).start()
        self._train_poll_checkpoints()

    def _train_on_line(self, line, st, is_progress):
        if not is_progress or "%|" not in line:
            self._train_log_write(line + "\n")
        if "pct" in st:
            self.train_progress.config(value=st["pct"])
        parts = []
        if "epoch" in st:
            parts.append(f"epoch {st['epoch']}/{st['epochs']}")
        if "step" in st:
            parts.append(f"step {st['step']}/{st['total']}")
        if "loss" in st:
            parts.append(f"loss {st['loss']:.4f}")
        if parts:
            self.train_status.config(text="🏋 " + "  ·  ".join(parts), fg=ACCENT)

    def _train_on_exit(self, code):
        self.train_start_btn.config(state="normal")
        self.train_stop_btn.config(state="disabled")
        self._train_refresh_checkpoints()
        n = self.train_ckpt_list.size()
        if code == 0:
            self.train_progress.config(value=100)
            self.train_status.config(text=f"✅ Done — {n} checkpoint(s). Send them to batch test.",
                                     fg=GREEN)
        else:
            self.train_status.config(text=f"❌ Stopped (code {code}) — see the log below "
                                          f"({n} checkpoint(s) already produced)", fg=RED)

    def _train_stop(self):
        import lora_trainer as lt
        if self.train_proc and messagebox.askyesno("Stop", "Stop training? "
                                                   "Checkpoints already saved remain usable."):
            lt.stop(self.train_proc)

    def _train_refresh_checkpoints(self):
        import lora_trainer as lt
        self.train_ckpt_list.delete(0, "end")
        folder = self.train_folder.get().strip()
        for p in (lt.list_checkpoints(folder) if folder else []):
            self.train_ckpt_list.insert("end", p.name)

    def _train_poll_checkpoints(self):
        if self.train_proc and self.train_proc.poll() is None:
            self._train_refresh_checkpoints()
            self.root.after(10000, self._train_poll_checkpoints)

    def _train_send_checkpoints(self):
        import lora_trainer as lt
        folder = self.train_folder.get().strip()
        ckpts = lt.list_checkpoints(folder) if folder else []
        if not ckpts:
            messagebox.showinfo("Checkpoints", "No checkpoint in output/ yet.")
            return
        loras_dir = self.cfg.get("comfyui_loras_dir", "")
        if not Path(loras_dir).is_dir():
            d = filedialog.askdirectory(title="ComfyUI/models/loras folder")
            if not d:
                return
            loras_dir = d
            self.cfg["comfyui_loras_dir"] = d
            try:
                save_config(self.cfg)
            except Exception:
                pass
        run = Path(folder).name
        try:
            res = lt.publish_to_comfyui(ckpts, loras_dir, run)
        except Exception as e:
            messagebox.showerror("Cannot copy", str(e))
            return
        # Bascule vers l'evaluateur, filtre pre-rempli, liste rafraichie
        self.comfy_batch_filter.set(res["filter"])
        self._comfy_card_open(True)
        self.select_tab("evaluator")
        self._comfy_refresh_loras()
        messagebox.showinfo("Checkpoints sent",
                            f"{len(res['copied'])} checkpoint(s) copied to\n{res['dest']}\n\n"
                            "In 📊 Evaluate: fill in the real photos + the workflow, then "
                            "“📦 Test the batch and rank”.")

    # =========================================================
    # COMPARAISON RAPIDE (Creer LoRA + Evaluer) : meme prompt, meme seed,
    # 1 image par LoRA, le plus proche des photos reelles est designe
    # =========================================================
    def _ensure_comfy_settings(self):
        """Demande ce qui manque (workflow API, photos reelles) puis valide."""
        if not Path(self.comfy_wf.get().strip()).is_file():
            f = filedialog.askopenfilename(title="ComfyUI workflow exported in API format",
                                           filetypes=[("Workflow API", "*.json")])
            if not f:
                return None
            self.comfy_wf.set(f)
        if not Path(self.eval_ref_path.get().strip()).is_dir():
            d = filedialog.askdirectory(title="Folder of REAL subject photos (not training photos)")
            if not d:
                return None
            self.eval_ref_path.set(d)
        return self._comfy_check_inputs(need_lora=False)

    def _train_quick_compare(self):
        import comfyui_client as cc
        import lora_trainer as lt
        folder = self.train_folder.get().strip()
        ckpts = lt.list_checkpoints(folder) if folder else []
        sel = [ckpts[i] for i in self.train_ckpt_list.curselection() if i < len(ckpts)]
        if len(sel) < 2:
            messagebox.showinfo("Compare", "Select at least 2 checkpoints in the list "
                                               "(Ctrl+click or Shift+click).")
            return
        chk = self._ensure_comfy_settings()
        if not chk:
            return
        url, _ = chk
        loras_dir = self.cfg.get("comfyui_loras_dir", "")
        if not Path(loras_dir).is_dir():
            loras_dir = filedialog.askdirectory(title="ComfyUI/models/loras folder")
            if not loras_dir:
                return
            self.cfg["comfyui_loras_dir"] = loras_dir
        try:
            pub = lt.publish_to_comfyui(sel, loras_dir, Path(folder).name)
            installed = cc.filter_loras(cc.list_loras(url), pub["filter"])
        except Exception as e:
            messagebox.showerror("ComfyUI", str(e))
            return
        wanted = {p.name for p in sel}
        names = [l for l in installed if Path(l.replace("\\", "/")).name in wanted]
        if len(names) != len(sel):
            messagebox.showerror("ComfyUI", f"ComfyUI only sees {len(names)}/{len(sel)} checkpoints "
                                            f"in {pub['dest']}. Check the models/loras folder.")
            return
        self._quick_compare(names, self.train_status)

    def _eval_quick_compare(self):
        import comfyui_client as cc
        chk = self._ensure_comfy_settings()
        if not chk:
            return
        url, _ = chk
        try:
            loras = cc.list_loras(url)
        except Exception as e:
            messagebox.showerror("ComfyUI", f"Cannot reach ComfyUI at {url}:\n{e}")
            return
        pat = self.comfy_batch_filter.get().strip()
        if pat:
            loras = cc.filter_loras(loras, pat)
        # Choix des LoRA (pre-selection : ceux du filtre)
        dlg = tk.Toplevel(self.root)
        dlg.title("LoRAs to compare")
        dlg.configure(bg=BG)
        dlg.geometry("520x460")
        Label(dlg, text="Select the LoRAs to compare (Ctrl/Shift+click)", font=FONT_BODY,
              fg=TEXT, bg=BG).pack(anchor="w", padx=12, pady=(10, 4))
        lb = tk.Listbox(dlg, selectmode="extended", bg=BG2, fg=TEXT, font=FONT_SMALL,
                        relief="flat", exportselection=False)
        for l in loras:
            lb.insert("end", l)
        if pat:
            lb.select_set(0, "end")
        lb.pack(fill="both", expand=True, padx=12)

        def go():
            names = [loras[i] for i in lb.curselection()]
            if len(names) < 2:
                messagebox.showinfo("Compare", "Choose at least 2 LoRAs.", parent=dlg)
                return
            dlg.destroy()
            self._quick_compare(names, self.eval_phase)
        Button(dlg, text="🖼 Generate 1 image each", font=FONT_BODY, bg=ACCENT2, fg=BG,
               relief="flat", padx=12, pady=6, command=go).pack(pady=10)

    def _quick_compare(self, lora_names, status_label):
        """Genere 1 image par LoRA (meme prompt + seed) + temoin sans LoRA,
        mesure la ressemblance aux photos reelles, affiche la grille."""
        import comfyui_client as cc
        url = self.comfy_url.get().strip().rstrip("/")
        wf_path, ref = self.comfy_wf.get().strip(), self.eval_ref_path.get().strip()
        trigger = self.comfy_trigger.get().strip() or "ohwx"
        prompt = self.cmp_prompt.get().strip().replace("{trigger}", trigger) or trigger
        try:
            seed = int(self.cmp_seed.get())
        except Exception:
            seed = 1234
        strength = self.comfy_strength.get()
        base_dir = Path(self.eval_gen_path.get() or Path(wf_path).parent)
        out = base_dir / f"compare_{datetime.now():%Y%m%d_%H%M%S}"
        btns = [self.train_cmp_btn, self.comfy_cmp_btn]
        for b in btns:
            b.config(state="disabled")

        def say(text, color=ACCENT):
            self.root.after(0, lambda: status_label.config(text=text, fg=color))

        def worker():
            try:
                r = cc.generate_compare(wf_path, lora_names, prompt, seed, out, strength=strength,
                                        base_url=url,
                                        progress_cb=lambda c, t, n: say(f"🖼 ComfyUI {c}/{t} — {n}"))
                if not r["images"]:
                    say("❌ No image: " + " | ".join(r["errors"][:2]), RED)
                    return
                say("🔬 Measuring resemblance to the real photos…")
                ev = self._eval_run_once(str(out), ref, "")
                bev = (self._eval_run_once(str(out / "_baseline"), ref, "")
                       if r["baseline"] else None)
                if "error" in ev:
                    say(f"❌ Evaluator: {ev['error']}", RED)
                    return
                rows, base = cc.closest_lora(r["images"], ev,
                                             bev if bev and "error" not in bev else None)
                best = rows[0] if rows and rows[0]["sim"] is not None else None
                say((f"⭐ Closest: {Path(best['lora'].replace(chr(92), '/')).name} "
                     f"({best['sim']:.3f})") if best else "⚠️ No face detected",
                    GREEN if best else YELLOW)
                self.root.after(0, lambda: self._show_compare_window(
                    rows, base, r["baseline"], ref, prompt, seed, out, r["errors"]))
            except Exception as e:
                say(f"❌ {e}", RED)
            finally:
                self.root.after(0, lambda: [b.config(state="normal") for b in btns])
        threading.Thread(target=worker, daemon=True).start()

    def _show_compare_window(self, rows, base_sim, base_img, ref_folder, prompt, seed, out, errors):
        win = tk.Toplevel(self.root)
        win.title("Quick compare — same prompt, same seed")
        win.configure(bg=BG)
        Label(win, text=f"🖼 “{prompt}”  ·  seed {seed}", font=FONT_H1, fg=ACCENT2, bg=BG,
              wraplength=1100, justify="left").pack(anchor="w", padx=12, pady=(10, 0))
        Label(win, text="Resemblance = face similarity (InsightFace) to your REAL photos. "
                        "1 seed = quick indication; to decide on an epoch, use the batch test.",
              font=FONT_SMALL, fg=TEXT_DIM, bg=BG, wraplength=1100, justify="left").pack(anchor="w", padx=12)
        grid = Frame(win, bg=BG)
        grid.pack(padx=12, pady=10)
        win._photos = []  # garde les references (sinon Tk efface les images)
        best = rows[0] if rows and rows[0]["sim"] is not None else None
        exts = (".png", ".jpg", ".jpeg", ".webp")
        ref_img = next((p for p in sorted(Path(ref_folder).iterdir())
                        if p.suffix.lower() in exts), None) if Path(ref_folder).is_dir() else None

        cells = []
        if ref_img:
            cells.append(("📸 Real reference", str(ref_img), "", TEXT_DIM, False))
        if base_img:
            cells.append(("No LoRA (control)", base_img,
                          f"{base_sim:.3f}" if base_sim is not None else "no face", TEXT_DIM, False))
        for r in rows:
            name = Path(r["lora"].replace("\\", "/")).name
            if r["sim"] is None:
                txt, col = "❌ no face detected", RED
            else:
                gain = f"  ({r['sim'] - base_sim:+.3f} vs control)" if base_sim is not None else ""
                txt, col = f"{r['sim']:.3f}{gain}", (GREEN if r is best else TEXT)
            cells.append((("⭐ CLOSEST\n" if r is best else "") + name, r["image"], txt, col, r is best))

        # Jusqu'a 8 cases (= 6 LoRA) : 4 par ligne en 240 px ; au-dela, plus petit
        per_row, thumb = (4, 240) if len(cells) <= 8 else (6, 170)
        for i, (title, img_path, score, col, is_best) in enumerate(cells):
            cell = Frame(grid, bg=GREEN if is_best else CARD, padx=3, pady=3)
            cell.grid(row=i // per_row, column=i % per_row, padx=6, pady=6, sticky="n")
            inner = Frame(cell, bg=CARD, padx=6, pady=6)
            inner.pack()
            if _HAS_PIL:
                try:
                    pil = PILImage.open(img_path)
                    pil.thumbnail((thumb, thumb))
                    ph = PILImageTk.PhotoImage(pil)
                    win._photos.append(ph)
                    Label(inner, image=ph, bg=CARD).pack()
                except Exception:
                    Label(inner, text="(unreadable image)", fg=RED, bg=CARD, width=30, height=10).pack()
            Label(inner, text=title, font=FONT_SMALL, fg=GREEN if is_best else TEXT, bg=CARD,
                  wraplength=thumb, justify="center").pack(pady=(4, 0))
            if score:
                Label(inner, text=score, font=FONT_BODY, fg=col, bg=CARD).pack()
        foot = f"📁 {out}"
        if errors:
            foot += f"   ⚠️ {len(errors)} failed generation(s): " + " | ".join(errors[:2])
        Label(win, text=foot, font=FONT_SMALL, fg=TEXT_DIM, bg=BG, wraplength=1100,
              justify="left").pack(anchor="w", padx=12, pady=(0, 10))

    # ------------------ (removed: LoRAs / Outputs / Inputs / Prompt tabs) ------------------
    # ============================================================
    # ÉVALUATEUR LoRA POST-TRAIN (Lot E partie 1)
    # MirrorMetrics-inspired : R-FaceSim, Copycat, Black Hole
    # ============================================================
    def _build_evaluator_tab(self, parent):
        frame = Frame(parent, bg=BG, padx=15, pady=12)
        parent.add(frame, text="  📊 Evaluate LoRA  ")

        Label(frame, text="Post-training LoRA evaluator",
              font=FONT_H1, fg=ACCENT2, bg=BG).pack(anchor="w")
        Label(frame,
              text="Once your LoRA is trained, generate ~30 test images, "
                   "then provide them here along with real photos of the subject "
                   "(different from the training ones). We compute R-FaceSim, "
                   "Copycat, Black Hole — the 2026 standard (MirrorMetrics).",
              font=FONT_SMALL, fg=TEXT_DIM, bg=BG, wraplength=900,
              justify="left").pack(anchor="w", pady=(0, 10))

        # === Champs ===
        def pick_folder_for(var, msg=None):
            d = filedialog.askdirectory(initialdir=var.get())
            if d:
                var.set(d.replace("/", "\\"))

        # Generated folder
        gen_frame = Frame(frame, bg=CARD, padx=10, pady=8)
        gen_frame.pack(fill="x", pady=4)
        Label(gen_frame, text="🎲 Images generated by your LoRA:",
              font=FONT_BODY, fg=TEXT, bg=CARD).pack(side="left")
        self.eval_gen_path = StringVar(value=r"C:\AI\datasets\lora_test_output")
        tk.Entry(gen_frame, textvariable=self.eval_gen_path, font=FONT_MONO,
                  bg=BG2, fg=TEXT, insertbackground=TEXT, relief="flat"
                  ).pack(side="left", fill="x", expand=True, ipady=5, padx=8)
        make_button(gen_frame, "📂",
                     lambda: pick_folder_for(self.eval_gen_path)).pack(side="left")

        # Reference folder (REAL photos of subject)
        ref_frame = Frame(frame, bg=CARD, padx=10, pady=8)
        ref_frame.pack(fill="x", pady=4)
        Label(ref_frame, text="📸 REAL photos of the subject:",
              font=FONT_BODY, fg=TEXT, bg=CARD).pack(side="left")
        self.eval_ref_path = StringVar(value="")
        tk.Entry(ref_frame, textvariable=self.eval_ref_path, font=FONT_MONO,
                  bg=BG2, fg=TEXT, insertbackground=TEXT, relief="flat"
                  ).pack(side="left", fill="x", expand=True, ipady=5, padx=8)
        make_button(ref_frame, "📂",
                     lambda: pick_folder_for(self.eval_ref_path)).pack(side="left")
        Label(frame,
              text="   ⚠️ Must be different from the training photos (otherwise the score is inflated)",
              font=FONT_SMALL, fg=YELLOW, bg=BG).pack(anchor="w", padx=10, pady=(0, 4))

        # Training folder (optional)
        train_frame = Frame(frame, bg=CARD, padx=10, pady=8)
        train_frame.pack(fill="x", pady=4)
        Label(train_frame, text="🧬 Training dataset (optional, copycat check):",
              font=FONT_BODY, fg=TEXT, bg=CARD).pack(side="left")
        self.eval_train_path = StringVar(value="")
        tk.Entry(train_frame, textvariable=self.eval_train_path, font=FONT_MONO,
                  bg=BG2, fg=TEXT, insertbackground=TEXT, relief="flat"
                  ).pack(side="left", fill="x", expand=True, ipady=5, padx=8)
        make_button(train_frame, "📂",
                     lambda: pick_folder_for(self.eval_train_path)).pack(side="left")

        # === Generation automatique via ComfyUI local ===
        self._build_comfy_eval_card(frame)

        # Bouton lancer
        Button(frame, text="🚀 Evaluate the LoRA", font=FONT_H1, bg=ACCENT2, fg=BG,
               relief="flat", padx=20, pady=10, cursor="hand2",
               command=self._run_evaluator).pack(pady=12)

        # Progress
        self.eval_phase = Label(frame, text="⏸ Waiting",
                                 font=FONT_BODY, fg=TEXT_DIM, bg=BG)
        self.eval_phase.pack(anchor="w", pady=4)
        self.eval_progress = ttk.Progressbar(frame, mode="determinate",
                                              length=600, maximum=100)
        self.eval_progress.pack(fill="x", pady=2)

        # Verdict block
        self.eval_verdict_frame = Frame(frame, bg=CARD, padx=15, pady=10)
        # not packed yet

        # Détail tableau
        eval_tree_frame = Frame(frame, bg=BG)
        eval_tree_frame.pack(fill="both", expand=True, pady=8)
        cols = ("face", "rsim", "rsim_max", "near_ref", "near_train", "copycat")
        self.eval_tree = ttk.Treeview(eval_tree_frame, columns=cols, show="tree headings",
                                       height=14)
        self.eval_tree.heading("#0", text="Image")
        self.eval_tree.heading("face", text="Face")
        self.eval_tree.heading("rsim", text="R-FaceSim")
        self.eval_tree.heading("rsim_max", text="Max")
        self.eval_tree.heading("near_ref", text="Closest ref")
        self.eval_tree.heading("near_train", text="Closest train")
        self.eval_tree.heading("copycat", text="Copycat?")
        self.eval_tree.column("#0", width=180)
        self.eval_tree.column("face", width=70, anchor="center")
        self.eval_tree.column("rsim", width=80, anchor="center")
        self.eval_tree.column("rsim_max", width=70, anchor="center")
        self.eval_tree.column("near_ref", width=200, anchor="w")
        self.eval_tree.column("near_train", width=200, anchor="w")
        self.eval_tree.column("copycat", width=90, anchor="center")
        sb = ttk.Scrollbar(eval_tree_frame, orient="vertical",
                            command=self.eval_tree.yview)
        self.eval_tree.configure(yscrollcommand=sb.set)
        self.eval_tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self.eval_tree.tag_configure("ok", foreground=GREEN)
        self.eval_tree.tag_configure("warn", foreground=YELLOW)
        self.eval_tree.tag_configure("err", foreground=RED)

    def _build_comfy_eval_card(self, frame):
        """Carte : genere le jeu de test dans ComfyUI (avec LoRA + baseline sans LoRA)."""
        outer = Frame(frame, bg=CARD, padx=10, pady=6)
        outer.pack(fill="x", pady=4)
        # Repliee par defaut : depliee, elle pousse le verdict hors de la fenetre
        card = Frame(outer, bg=CARD)
        toggle = Button(outer, font=FONT_BODY, fg=ACCENT, bg=CARD, relief="flat", anchor="w",
                        activebackground=CARD, cursor="hand2")

        def set_open(opened):
            if opened:
                card.pack(fill="x", pady=(4, 0))
            else:
                card.pack_forget()
            toggle.config(text=("▾" if opened else "▸") +
                               " 🎨 Generate test images with local ComfyUI (optional)",
                          command=lambda: set_open(not opened))
        toggle.pack(fill="x")
        set_open(bool(self.cfg.get("comfyui_eval_workflow")))
        self._comfy_card_open = set_open

        self.comfy_url = StringVar(value=self.cfg.get("comfyui_url", "http://127.0.0.1:8188"))
        self.comfy_wf = StringVar(value=self.cfg.get("comfyui_eval_workflow", ""))
        self.comfy_lora = StringVar(value="")
        self.comfy_trigger = StringVar(value="ohwx")
        self.comfy_n = tk.IntVar(value=20)
        self.comfy_strength = tk.DoubleVar(value=1.0)
        self.comfy_baseline = tk.BooleanVar(value=True)

        def entry(parent, var, width):
            return tk.Entry(parent, textvariable=var, font=FONT_MONO, width=width, bg=BG2,
                            fg=TEXT, insertbackground=TEXT, relief="flat")

        Label(card, text="URL:", font=FONT_SMALL, fg=TEXT, bg=CARD).grid(row=1, column=0, sticky="w")
        entry(card, self.comfy_url, 24).grid(row=1, column=1, sticky="w", padx=4, pady=2)
        Label(card, text="Workflow (API format):", font=FONT_SMALL, fg=TEXT, bg=CARD).grid(row=1, column=2, sticky="e")
        entry(card, self.comfy_wf, 34).grid(row=1, column=3, sticky="we", padx=4)

        def pick_wf():
            f = filedialog.askopenfilename(title="ComfyUI workflow exported in API format",
                                           filetypes=[("Workflow API", "*.json")])
            if f:
                self.comfy_wf.set(f)
        make_button(card, "📂", pick_wf).grid(row=1, column=4, sticky="w")

        Label(card, text="LoRA:", font=FONT_SMALL, fg=TEXT, bg=CARD).grid(row=2, column=0, sticky="w")
        self.comfy_lora_combo = ttk.Combobox(card, textvariable=self.comfy_lora, width=34,
                                             state="readonly", font=FONT_SMALL)
        self.comfy_lora_combo.grid(row=2, column=1, columnspan=2, sticky="w", padx=4, pady=2)
        make_button(card, "🔄 List", self._comfy_refresh_loras).grid(row=2, column=3, sticky="w")

        opts = Frame(card, bg=CARD)
        opts.grid(row=3, column=0, columnspan=6, sticky="w", pady=(2, 0))
        Label(opts, text="Trigger:", font=FONT_SMALL, fg=TEXT, bg=CARD).pack(side="left")
        entry(opts, self.comfy_trigger, 12).pack(side="left", padx=(2, 10))
        Label(opts, text="Images:", font=FONT_SMALL, fg=TEXT, bg=CARD).pack(side="left")
        tk.Spinbox(opts, from_=5, to=100, textvariable=self.comfy_n, width=4,
                   font=FONT_SMALL).pack(side="left", padx=(2, 10))
        Label(opts, text="Strength:", font=FONT_SMALL, fg=TEXT, bg=CARD).pack(side="left")
        tk.Spinbox(opts, from_=0.1, to=2.0, increment=0.1, textvariable=self.comfy_strength,
                   width=4, font=FONT_SMALL).pack(side="left", padx=(2, 10))
        tk.Checkbutton(opts, text="Baseline A/B (same seeds, no LoRA)",
                       variable=self.comfy_baseline, font=FONT_SMALL, fg=TEXT, bg=CARD,
                       selectcolor=BG2, activebackground=CARD).pack(side="left", padx=4)
        self.comfy_gen_btn = Button(opts, text="🎨 Generate then evaluate", font=FONT_BODY,
                                    bg=ACCENT, fg=BG, relief="flat", padx=10,
                                    command=self._run_comfy_generation)
        self.comfy_gen_btn.pack(side="left", padx=8)

        # Test en LOT : tous les LoRA dont le nom contient le filtre (ex: checkpoints lin_1..4)
        self.comfy_batch_filter = StringVar(value="")
        batch = Frame(card, bg=CARD)
        batch.grid(row=5, column=0, columnspan=6, sticky="w", pady=(4, 0))
        Label(batch, text="📦 Batch — name contains:", font=FONT_SMALL, fg=TEXT, bg=CARD).pack(side="left")
        entry(batch, self.comfy_batch_filter, 22).pack(side="left", padx=(4, 8))
        self.comfy_batch_btn = Button(batch, text="📦 Test the batch and rank", font=FONT_BODY,
                                      bg=ACCENT2, fg=BG, relief="flat", padx=10,
                                      command=self._run_comfy_batch)
        self.comfy_batch_btn.pack(side="left")
        self.comfy_cmp_btn = Button(batch, text="🖼 Compare (1 image)", font=FONT_BODY,
                                    bg=CARD_HI, fg=TEXT, relief="flat", padx=8,
                                    command=self._eval_quick_compare)
        self.comfy_cmp_btn.pack(side="left", padx=6)
        Label(batch, text="  same prompts + same seeds for all, common baseline",
              font=FONT_SMALL, fg=TEXT_DIM, bg=CARD).pack(side="left")
        Label(card, text="   Workflow: ComfyUI > Workflow > Export (API). It must contain a "
                         "LoraLoader node and a SaveImage node; put {prompt} in the positive "
                         "text (otherwise it's detected via the sampler).",
              font=FONT_SMALL, fg=TEXT_DIM, bg=CARD, wraplength=880,
              justify="left").grid(row=4, column=0, columnspan=6, sticky="w")

    def _comfy_refresh_loras(self):
        import comfyui_client as cc
        url = self.comfy_url.get().strip().rstrip("/")
        def worker():
            try:
                loras = cc.list_loras(url)
                def done():
                    self.comfy_lora_combo.config(values=loras)
                    if loras and not self.comfy_lora.get():
                        self.comfy_lora.set(loras[0])
                    self.eval_phase.config(text=f"✅ ComfyUI: {len(loras)} LoRA(s) found", fg=GREEN)
                self.root.after(0, done)
            except Exception as e:
                self.root.after(0, lambda e=e: self.eval_phase.config(
                    text=f"❌ Cannot reach ComfyUI at {url} ({e})", fg=RED))
        threading.Thread(target=worker, daemon=True).start()

    def _run_comfy_generation(self):
        import comfyui_client as cc
        chk = self._comfy_check_inputs(need_lora=True)
        if not chk:
            return
        url, wf_path = chk
        lora = self.comfy_lora.get().strip()
        out = Path(self.eval_gen_path.get() or ".") / f"{cc.safe_dir_name(lora)}_{datetime.now():%Y%m%d_%H%M}"
        self.eval_gen_path.set(str(out))
        n, strength, base = self.comfy_n.get(), self.comfy_strength.get(), self.comfy_baseline.get()
        self.comfy_gen_btn.config(state="disabled")
        self.eval_progress.config(mode="determinate", value=0)

        def progress(cur, tot, name):
            self.root.after(0, lambda: (self.eval_progress.config(value=100 * cur / tot),
                                        self.eval_phase.config(text=f"🎨 ComfyUI {cur}/{tot} — {name}",
                                                               fg=ACCENT)))

        def worker():
            try:
                r = cc.generate_eval_set(wf_path, lora, self.comfy_trigger.get().strip() or "ohwx",
                                         out, n_images=n, strength=strength, with_baseline=base,
                                         base_url=url, progress_cb=progress)
            except Exception as e:
                self.root.after(0, lambda e=e: (self.comfy_gen_btn.config(state="normal"),
                                                self.eval_phase.config(text=f"❌ {e}", fg=RED)))
                return
            def done():
                self.comfy_gen_btn.config(state="normal")
                if not r["lora"]:
                    self.eval_phase.config(text="❌ No image generated: " +
                                           " | ".join(r["errors"][:2]), fg=RED)
                    return
                if r["errors"]:
                    messagebox.showwarning("ComfyUI", f"{len(r['errors'])} failed generation(s):\n" +
                                           "\n".join(r["errors"][:5]))
                self._run_evaluator()
            self.root.after(0, done)
        threading.Thread(target=worker, daemon=True).start()

    def _comfy_check_inputs(self, need_lora=True):
        """Validation commune generation simple / lot. Renvoie (url, wf_path) ou None."""
        import comfyui_client as cc
        url = self.comfy_url.get().strip().rstrip("/")
        wf_path = self.comfy_wf.get().strip()
        if not Path(wf_path).is_file():
            messagebox.showerror("Workflow", "Choose the ComfyUI workflow exported in API format.")
            return None
        if need_lora and not self.comfy_lora.get().strip():
            messagebox.showerror("LoRA", "Click “🔄 List” then choose the LoRA to evaluate.")
            return None
        if not Path(self.eval_ref_path.get()).is_dir():
            messagebox.showerror("Reference", "First provide the folder of REAL subject photos.")
            return None
        try:
            info = cc.inspect_workflow(cc.load_api_workflow(wf_path))
        except Exception as e:
            messagebox.showerror("Invalid workflow", str(e))
            return None
        if info["problems"]:
            messagebox.showerror("Unusable workflow", "\n".join("• " + p for p in info["problems"]))
            return None
        self.cfg["comfyui_url"], self.cfg["comfyui_eval_workflow"] = url, wf_path
        try:
            save_config(self.cfg)
        except Exception:
            pass
        return url, wf_path

    def _run_comfy_batch(self):
        import comfyui_client as cc
        chk = self._comfy_check_inputs(need_lora=False)
        if not chk:
            return
        url, wf_path = chk
        pattern = self.comfy_batch_filter.get().strip()
        if not pattern:
            messagebox.showerror("Batch", "Type part of the name shared by the LoRAs to compare (e.g. lin).")
            return
        try:
            loras = cc.filter_loras(cc.list_loras(url), pattern)
        except Exception as e:
            messagebox.showerror("ComfyUI", f"Cannot reach ComfyUI at {url}:\n{e}")
            return
        if len(loras) < 2:
            messagebox.showerror("Batch", f"{len(loras)} LoRA(s) contain “{pattern}”: at least 2 are needed "
                                        "for a ranking.")
            return
        n, base = self.comfy_n.get(), self.comfy_baseline.get()
        total = n * (len(loras) + (1 if base else 0))
        if not messagebox.askyesno(
                "Test the batch",
                f"{len(loras)} LoRA(s):\n" + "\n".join("  • " + l for l in loras[:15]) +
                ("\n  …" if len(loras) > 15 else "") +
                f"\n\n{total} generations total ({n} per LoRA"
                + (f" + {n} baseline" if base else "") + "). Proceed?"):
            return
        out = Path(self.eval_gen_path.get() or ".") / f"lot_{cc.safe_dir_name(pattern)}_{datetime.now():%Y%m%d_%H%M}"
        self.comfy_batch_btn.config(state="disabled")
        self.comfy_gen_btn.config(state="disabled")
        self.eval_progress.config(mode="determinate", value=0)
        ref, train = self.eval_ref_path.get(), self.eval_train_path.get().strip()

        def phase(text, pct=None):
            def f():
                self.eval_phase.config(text=text, fg=ACCENT)
                if pct is not None:
                    self.eval_progress.config(value=pct)
            self.root.after(0, f)

        def worker():
            try:
                r = cc.generate_batch(wf_path, loras, self.comfy_trigger.get().strip() or "ohwx",
                                      out, n_images=n, strength=self.comfy_strength.get(),
                                      with_baseline=base, base_url=url,
                                      progress_cb=lambda c, t, name: phase(
                                          f"🎨 ComfyUI {c}/{t} — {name}", 70 * c / t))
                results = {}
                targets = list(r["folders"].items())
                if r.get("baseline_folder") and Path(r["baseline_folder"]).is_dir():
                    targets.append(("_baseline", r["baseline_folder"]))
                for k, (name, folder) in enumerate(targets, 1):
                    phase(f"🔬 Evaluating {k}/{len(targets)} — {name}", 70 + 30 * k / len(targets))
                    results[name] = self._eval_run_once(folder, ref, "" if name == "_baseline" else train)
                rows = cc.rank_batch(results)
                (out / "classement.json").write_text(
                    json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
                self.root.after(0, lambda: self._show_batch_ranking(rows, out, r["errors"]))
            except Exception as e:
                self.root.after(0, lambda e=e: self.eval_phase.config(text=f"❌ {e}", fg=RED))
            finally:
                self.root.after(0, lambda: (self.comfy_batch_btn.config(state="normal"),
                                            self.comfy_gen_btn.config(state="normal")))
        threading.Thread(target=worker, daemon=True).start()

    def _show_batch_ranking(self, rows, out, errors):
        self.eval_progress.config(value=100)
        ok = [r for r in rows if "error" not in r]
        best = ok[0] if ok else None
        self.eval_phase.config(
            text=(f"🏆 Best: {best['lora']} ({best['grade']}, {best['score']}/100)" if best
                  else "❌ No LoRA evaluated"), fg=GREEN if best else RED)
        win = tk.Toplevel(self.root)
        win.title("Batch ranking")
        win.configure(bg=BG)
        win.geometry("980x460")
        Label(win, text="🏆 Batch ranking (same prompts, same seeds)", font=FONT_H1,
              fg=ACCENT2, bg=BG).pack(anchor="w", padx=15, pady=(12, 2))
        Label(win, text="Sort: verdict score (penalizes copycat and mode collapse), then identity "
                        "gain vs the no-LoRA baseline. The “best” isn't necessarily "
                        "the last epoch: beyond a point, the LoRA overfits.",
              font=FONT_SMALL, fg=TEXT_DIM, bg=BG, wraplength=940, justify="left").pack(anchor="w", padx=15)
        cols = ("rank", "grade", "score", "rsim", "gain", "std", "copycat")
        tree = ttk.Treeview(win, columns=cols, show="tree headings", height=14)
        for c, t, w in (("#0", "LoRA", 360), ("rank", "#", 40), ("grade", "Grade", 60),
                        ("score", "Score", 60), ("rsim", "R-FaceSim", 90), ("gain", "Gain vs base", 100),
                        ("std", "Std dev", 90), ("copycat", "Copycat", 70)):
            tree.heading(c, text=t)
            tree.column(c, width=w, anchor="w" if c == "#0" else "center")
        tree.tag_configure("best", foreground=GREEN)
        tree.tag_configure("bad", foreground=RED)
        fmt = lambda v, f="{:.3f}": "-" if v is None else f.format(v)
        for r in rows:
            if "error" in r:
                tree.insert("", "end", text=f"  {r['lora']}", values=("", "ERR", "", r["error"][:40], "", "", ""),
                            tags=("bad",))
                continue
            tag = "best" if r is best else ("bad" if r["copycat"] or (r["gain"] is not None and r["gain"] < 0.05) else "")
            tree.insert("", "end", text=("⭐ " if r is best else "   ") + r["lora"],
                        values=(r["rank"], r["grade"], r["score"], fmt(r["r_facesim_mean"]),
                                fmt(r["gain"], "{:+.3f}"), fmt(r["r_facesim_std"]), r["copycat"]),
                        tags=(tag,))
        tree.pack(fill="both", expand=True, padx=15, pady=8)
        foot = f"📁 Images + classement.json: {out}"
        if errors:
            foot += f"   ⚠️ {len(errors)} failed generation(s) (see classement.json)"
        Label(win, text=foot, font=FONT_SMALL, fg=TEXT_DIM, bg=BG, wraplength=940,
              justify="left").pack(anchor="w", padx=15, pady=(0, 10))

    def _run_evaluator(self):
        gen = self.eval_gen_path.get()
        ref = self.eval_ref_path.get()
        train = self.eval_train_path.get().strip()

        if not Path(gen).is_dir():
            messagebox.showerror("Error", f"Generated images folder not found:\n{gen}")
            return
        if not Path(ref).is_dir():
            messagebox.showerror("Error",
                f"Reference photos folder not found:\n{ref}\n\n"
                "You must provide REAL photos of the subject (not training photos)")
            return

        self.eval_phase.config(text="⚙ Loading insightface...", fg=ACCENT)
        self.eval_progress.config(value=0, mode="indeterminate")
        self.eval_progress.start(15)
        self.eval_tree.delete(*self.eval_tree.get_children())
        for w in self.eval_verdict_frame.winfo_children():
            w.destroy()
        self.eval_verdict_frame.pack_forget()

        threading.Thread(target=self._eval_subprocess,
                          args=(gen, ref, train), daemon=True).start()

    def _eval_subprocess(self, gen, ref, train):
        """Evalue le LoRA ; si un dossier _baseline/ (genere par ComfyUI, meme
        seeds, LoRA a 0) existe, l'evalue aussi et calcule le GAIN d'identite."""
        try:
            result = self._eval_run_once(gen, ref, train)
            base_dir = Path(gen) / "_baseline"
            if "error" not in result and base_dir.is_dir() and any(base_dir.iterdir()):
                self.root.after(0, lambda: self.eval_phase.config(
                    text="⚙ Evaluating the baseline (no LoRA)...", fg=ACCENT))
                base = self._eval_run_once(str(base_dir), ref, "")
                if "error" not in base:
                    lm = result.get("summary", {}).get("r_facesim_mean")
                    bm = base.get("summary", {}).get("r_facesim_mean")
                    result["baseline"] = {"r_facesim_mean": bm,
                                          "gain": round(lm - bm, 4) if lm is not None and bm is not None else None}
            self.root.after(0, lambda r=result: self._show_evaluator_result(r))
        except Exception as e:
            import traceback
            err = f"{e}\n\n{traceback.format_exc()[-500:]}"
            self.root.after(0, lambda e=err: messagebox.showerror("Evaluation error", e))

    def _eval_run_once(self, gen, ref, train):
        """Lance lora_evaluator.py en subprocess et renvoie son dict resultat."""
        import time as _time
        script = str(Path(__file__).parent / "lora_evaluator.py")
        cmd = [self.comfyui_py, script, gen, ref]
        if train:
            cmd.append(train)
        cmd.append(self.cfg.get("device", "auto"))  # auto/cuda/cpu
        proc = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding="utf-8", bufsize=1,
        )

        last_activity = [_time.time()]

        def read_progress():
            for raw in iter(proc.stderr.readline, ""):
                line = raw.strip()
                last_activity[0] = _time.time()
                if line.startswith("STEP "):
                    msg = line[5:]
                    self.root.after(0, lambda m=msg:
                        self.eval_phase.config(text=f"⚙ {m}", fg=ACCENT))
                elif line.startswith("PROGRESS "):
                    # PROGRESS REF 5/20 imagename
                    try:
                        parts = line.split(" ", 3)
                        kind = parts[1]
                        cur, tot = parts[2].split("/")
                        n = parts[3] if len(parts) > 3 else ""
                        self.root.after(0, lambda k=kind, c=cur, t=tot, n=n:
                            self.eval_phase.config(
                                text=f"⚙ Embedding {k} {c}/{t} — {n[:30]}", fg=ACCENT))
                    except Exception:
                        pass

        stdout_chunks = []
        def read_stdout():
            try:
                for chunk in iter(proc.stdout.readline, ""):
                    stdout_chunks.append(chunk)
            except Exception:
                pass

        t_err = threading.Thread(target=read_progress, daemon=True)
        t_out = threading.Thread(target=read_stdout, daemon=True)
        t_err.start(); t_out.start()

        # Watchdog d'inactivité (30 min de silence = bloqué)
        INACTIVITY_LIMIT = 1800
        killed = False
        while proc.poll() is None:
            _time.sleep(2)
            if _time.time() - last_activity[0] > INACTIVITY_LIMIT:
                killed = True
                try: proc.kill()
                except Exception: pass
                break
        t_out.join(timeout=5); t_err.join(timeout=5)

        if killed:
            return {"error": f"No activity for {INACTIVITY_LIMIT//60} min — stopped."}

        stdout = "".join(stdout_chunks)
        return json.loads(stdout.strip()) if stdout.strip() else {"error": "no output"}

    def _show_evaluator_result(self, data):
        self.eval_progress.stop()
        self.eval_progress.config(mode="determinate", value=100)
        if "error" in data:
            self.eval_phase.config(text=f"❌ {data['error']}", fg=RED)
            return

        s = data.get("summary", {})
        v = s.get("verdict", {})
        self.eval_phase.config(text=f"✅ Evaluation done — {s.get('n_generated', 0)} generated vs {s.get('n_reference', 0)} refs",
                                 fg=GREEN)

        # Bloc verdict
        grade = v.get("grade", "?")
        score = v.get("score", 0)
        desc = v.get("desc", "")
        advice = v.get("advice", "")
        issues = v.get("issues", [])
        color = {"A": GREEN, "B+": GREEN, "B": GREEN, "C": YELLOW,
                 "D": RED, "F": RED}.get(grade, TEXT)

        top = Frame(self.eval_verdict_frame, bg=CARD)
        top.pack(fill="x")
        Label(top, text=grade, font=("Segoe UI", 32, "bold"),
              fg=color, bg=CARD).pack(side="left", padx=(0, 15))
        right = Frame(top, bg=CARD)
        right.pack(side="left", fill="x", expand=True)
        Label(right, text=f"LoRA VERDICT: {desc}  ({score}/100)",
              font=FONT_H1, fg=color, bg=CARD, anchor="w").pack(fill="x")
        Label(right, text=f"R-FaceSim: mean {s.get('r_facesim_mean')} (std {s.get('r_facesim_std')}, min {s.get('r_facesim_min')}, max {s.get('r_facesim_max')})",
              font=FONT_BODY, fg=TEXT_DIM, bg=CARD, anchor="w").pack(fill="x")
        b = data.get("baseline")
        if b and b.get("gain") is not None:
            g = b["gain"]
            gcol = GREEN if g >= 0.15 else (YELLOW if g >= 0.05 else RED)
            Label(right, text=(f"ComfyUI A/B: without LoRA {b['r_facesim_mean']} → with LoRA "
                               f"{s.get('r_facesim_mean')}  = identity gain {g:+.3f}"
                               + ("" if g >= 0.05 else "  ⚠️ the LoRA adds almost nothing")),
                  font=FONT_BODY, fg=gcol, bg=CARD, anchor="w").pack(fill="x")
        if s.get("copycat_count", 0) > 0:
            Label(right, text=f"❌ {s['copycat_count']} copycat(s) detected (LoRA is copying instead of generalizing)",
                  font=FONT_BODY, fg=RED, bg=CARD, anchor="w").pack(fill="x")

        Label(self.eval_verdict_frame, text=f"💡 {advice}",
              font=FONT_BODY, fg=ACCENT, bg=CARD,
              anchor="w", wraplength=900, justify="left").pack(fill="x", pady=(6, 2))
        for issue in issues:
            Label(self.eval_verdict_frame, text=f"  ⚠️ {issue}",
                  font=FONT_SMALL, fg=YELLOW, bg=CARD,
                  anchor="w", wraplength=900, justify="left").pack(fill="x")

        # Black hole ranking
        bh = s.get("black_hole_top", [])
        if bh:
            Label(self.eval_verdict_frame, text="🕳 Black Hole Ranking (most-copied training images):",
                  font=FONT_H1, fg=ACCENT, bg=CARD, anchor="w").pack(fill="x", pady=(10, 4))
            for entry in bh[:5]:
                Label(self.eval_verdict_frame,
                      text=f"  • {entry['training_image']} attracts {entry['attributed_count']} gen(s) "
                           f"({entry['ratio']*100:.0f}%)",
                      font=FONT_SMALL, fg=TEXT_DIM if entry['ratio'] < 0.3 else YELLOW,
                      bg=CARD, anchor="w").pack(fill="x")

        # Verdict AU-DESSUS du tableau detail. (L'ancien before=eval_progress.master
        # visait le cadre de l'onglet, gere par le Notebook et non par pack :
        # TclError, et le tableau par image ne s'affichait jamais.)
        self.eval_verdict_frame.pack(fill="x", padx=10, pady=(0, 6),
                                       before=self.eval_tree.master)

        # Tableau detail
        for entry in data.get("per_image", []):
            name = entry.get("name", "?")
            face = "✅" if entry.get("has_face") else "❌"
            rsim = entry.get("r_facesim")
            rsim_str = f"{rsim:.3f}" if rsim is not None else "-"
            rsim_max = entry.get("r_facesim_max")
            rsim_max_str = f"{rsim_max:.3f}" if rsim_max is not None else "-"
            nref = entry.get("nearest_ref") or {}
            ntrain = entry.get("nearest_train") or {}
            near_ref_str = f"{nref.get('name', '-')} ({nref.get('sim', '-')})" if nref else "-"
            near_tr_str = f"{ntrain.get('name', '-')} ({ntrain.get('sim', '-')})" if ntrain else "-"
            copycat = "❌ OUI" if entry.get("copycat") else "✓"

            if not entry.get("has_face"):
                tag = "err"
            elif entry.get("copycat"):
                tag = "err"
            elif rsim is not None and rsim < 0.4:
                tag = "warn"
            else:
                tag = "ok"
            self.eval_tree.insert("", "end", text=f"  {name}",
                                    values=(face, rsim_str, rsim_max_str,
                                              near_ref_str, near_tr_str, copycat),
                                    tags=(tag,))

    # =========================================================
    # ONGLET VOIX — Dataset RVC (Applio)
    # =========================================================
    def _build_voice_tab(self, parent):
        frame = Frame(parent, bg=BG, padx=20, pady=15)
        parent.add(frame, text="  🎤 RVC Voice  ")

        Label(frame, text="🎤  Voice Dataset — RVC Training (Applio)",
              font=FONT_TITLE, fg=TEXT, bg=BG).pack(anchor="w", pady=(0, 4))
        Label(frame,
              text="Analyze your audio files for RVC training: mic quality, SNR, duration, diversity.",
              font=FONT_BODY, fg=TEXT_DIM, bg=BG).pack(anchor="w", pady=(0, 10))

        # Sélection dossier
        sel = Frame(frame, bg=BG)
        sel.pack(fill="x", pady=4)
        Label(sel, text="Audio folder:", font=FONT_BODY, fg=TEXT_DIM, bg=BG).pack(side="left")
        self.voice_folder = StringVar()
        Entry(sel, textvariable=self.voice_folder, font=FONT_MONO, bg=BG2, fg=TEXT,
              relief="flat", width=55).pack(side="left", padx=8)
        make_button(sel, "📂", lambda: self._pick_folder(self.voice_folder), width=4).pack(side="left")
        make_button(sel, "🔍 Analyze", self._run_voice_analysis, primary=True, width=12).pack(side="left", padx=8)

        # Barre de progression
        self.voice_progress_var = StringVar(value="")
        Label(frame, textvariable=self.voice_progress_var, font=FONT_SMALL, fg=TEXT_DIM, bg=BG,
              anchor="w").pack(fill="x", pady=(4, 0))

        # Résultats — tableau + résumé
        pane = Frame(frame, bg=BG)
        pane.pack(fill="both", expand=True, pady=8)

        # Colonne gauche : liste fichiers
        left = Frame(pane, bg=BG)
        left.pack(side="left", fill="both", expand=True)
        Label(left, text="Analyzed files", font=FONT_H1, fg=ACCENT, bg=BG).pack(anchor="w")
        cols = ("fichier", "durée", "SNR", "RMS", "SR", "note", "problèmes")
        col_labels = {"fichier": "File", "durée": "Duration", "note": "Grade", "problèmes": "Issues"}
        self.voice_tree = ttk.Treeview(left, columns=cols, show="headings",
                                        style="Dark.Treeview", height=14)
        for c, w in zip(cols, (200, 65, 65, 65, 75, 50, 280)):
            self.voice_tree.heading(c, text=col_labels.get(c, c)); self.voice_tree.column(c, width=w, anchor="center")
        self.voice_tree.column("fichier", anchor="w"); self.voice_tree.column("problèmes", anchor="w")
        self.voice_tree.pack(fill="both", expand=True)

        # Colonne droite : résumé + recommandations
        right = Frame(pane, bg=CARD, padx=12, pady=10, width=280)
        right.pack(side="right", fill="y", padx=(12, 0))
        right.pack_propagate(False)
        Label(right, text="Summary", font=FONT_H1, fg=ACCENT, bg=CARD).pack(anchor="w")
        self.voice_summary_text = Text(right, bg=CARD, fg=TEXT, font=FONT_SMALL,
                                        relief="flat", wrap="word", state="disabled", height=18)
        self.voice_summary_text.pack(fill="both", expand=True)

        # Actions
        act = Frame(frame, bg=BG)
        act.pack(fill="x", pady=(6, 0))
        make_button(act, "🚀 Open Applio", self._open_applio, width=16).pack(side="left", padx=4)
        Label(act, text="→ Train your RVC voice model in Applio",
              font=FONT_SMALL, fg=TEXT_DIM, bg=BG).pack(side="left")

    def _pick_folder(self, var):
        from tkinter import filedialog
        f = filedialog.askdirectory(title="Choose a folder")
        if f:
            var.set(f.replace("/", "\\"))

    def _run_voice_analysis(self):
        folder = self.voice_folder.get().strip()
        if not folder or not os.path.isdir(folder):
            messagebox.showwarning("Folder", "Choose a valid audio folder.")
            return
        self.voice_tree.delete(*self.voice_tree.get_children())
        self._set_voice_summary("⏳ Analyzing…")
        self.voice_progress_var.set("Starting…")

        def run():
            try:
                from analyze_voice import analyze_voice_folder
                GRADE_COLOR = {"A": GREEN, "B": ACCENT, "C": ORANGE, "D": RED, "F": "#ff0000"}

                def on_progress(i, total, name):
                    self.root.after(0, lambda: self.voice_progress_var.set(
                        f"[{i+1}/{total}] {name}"))

                def on_result(r):
                    tag = r["score"]
                    dur = f"{r['duration_s']:.1f}s" if r["duration_s"] else "?"
                    snr = f"{r['snr_db']} dB" if r["snr_db"] else "?"
                    rms = f"{r['rms_db']} dB" if r["rms_db"] else "?"
                    sr = f"{r['sample_rate']} Hz" if r["sample_rate"] else "?"
                    issues = " | ".join(r["issues"]) if r["issues"] else "✅ OK"
                    self.root.after(0, lambda: self.voice_tree.insert(
                        "", "end", values=(r["file"], dur, snr, rms, sr, tag, issues),
                        tags=(tag,)))
                    self.root.after(0, lambda: self.voice_tree.tag_configure(
                        tag, foreground=GRADE_COLOR.get(tag, TEXT)))

                summary = analyze_voice_folder(folder, on_progress, on_result)
                self.root.after(0, lambda: self._show_voice_summary(summary))
                self.root.after(0, lambda: self.voice_progress_var.set(
                    f"✅ {summary['total']} file(s) analyzed"))
            except ImportError as e:
                self.root.after(0, lambda e=e: self._set_voice_summary(
                    f"❌ Missing module: {e}\n\nInstall: pip install librosa soundfile"))

        threading.Thread(target=run, daemon=True).start()

    def _show_voice_summary(self, s):
        gc = s.get("grade_counts", {})
        txt = (
            f"📁 Files: {s['total']}\n"
            f"⏱ Total duration: {s['total_duration_min']} min\n"
            f"⌛ Avg. duration: {s['avg_duration_s']} s\n\n"
            f"Grades:\n"
            + "".join(f"  {g}: {gc.get(g,0)}\n" for g in "ABCDF")
            + f"\n🎯 Overall score: {s['overall_score']}\n"
            + ("✅ Ready for Applio\n" if s.get('rvc_ready') else "⚠️ Fix the issues first\n")
            + f"\n📋 Sample rates: {', '.join(str(x) for x in s.get('sample_rates', []))}\n\n"
            + "⚠️ Common issues:\n"
            + "\n".join(f"  • {i['issue']} ({i['count']}×)" for i in s.get('top_issues', []))
            + f"\n\n💡 Recommendation:\n{s.get('recommendation', '')}"
        )
        self._set_voice_summary(txt)

    def _set_voice_summary(self, txt):
        self.voice_summary_text.config(state="normal")
        self.voice_summary_text.delete("1.0", "end")
        self.voice_summary_text.insert("1.0", txt)
        self.voice_summary_text.config(state="disabled")

    def _open_applio(self):
        bat = r"C:\AI\Applio\run-applio.bat"
        if os.path.exists(bat):
            subprocess.Popen(["cmd", "/c", "start", "", bat], shell=False)
        else:
            messagebox.showinfo("Applio", f"Applio not found:\n{bat}")

    # =========================================================
    # ONGLET MUSIQUE — Dataset ACE-Step 1.5 LoRA
    # =========================================================
    def _build_music_tab(self, parent):
        frame = Frame(parent, bg=BG, padx=20, pady=15)
        parent.add(frame, text="  🎵 Music LoRA  ")

        Label(frame, text="🎵  Music Dataset — ACE-Step 1.5 LoRA",
              font=FONT_TITLE, fg=TEXT, bg=BG).pack(anchor="w", pady=(0, 4))
        Label(frame,
              text="Prepare your tracks for training an ACE-Step 1.5 music LoRA (style, artist…)",
              font=FONT_BODY, fg=TEXT_DIM, bg=BG).pack(anchor="w", pady=(0, 10))

        # Sélection dossier
        sel = Frame(frame, bg=BG)
        sel.pack(fill="x", pady=4)
        Label(sel, text="Tracks folder:", font=FONT_BODY, fg=TEXT_DIM, bg=BG).pack(side="left")
        self.music_folder = StringVar()
        Entry(sel, textvariable=self.music_folder, font=FONT_MONO, bg=BG2, fg=TEXT,
              relief="flat", width=50).pack(side="left", padx=8)
        make_button(sel, "📂", lambda: self._pick_folder(self.music_folder), width=4).pack(side="left")
        make_button(sel, "🔍 Analyze", self._run_music_analysis, primary=True, width=12).pack(side="left", padx=8)
        make_button(sel, "📝 Generate JSON", self._generate_music_json, width=14).pack(side="left", padx=4)

        # Info format
        info = Frame(frame, bg=BG2, padx=10, pady=6)
        info.pack(fill="x", pady=(0, 6))
        Label(info, text="📋 Expected ACE-Step format: song.mp3 + song.lyrics.txt + song.json {bpm, keyscale, caption, timesignature, language}",
              font=FONT_SMALL, fg=TEXT_DIM, bg=BG2, anchor="w").pack(fill="x")

        # Barre de progression
        self.music_progress_var = StringVar(value="")
        Label(frame, textvariable=self.music_progress_var, font=FONT_SMALL, fg=TEXT_DIM, bg=BG,
              anchor="w").pack(fill="x", pady=(2, 0))

        # Tableau
        pane = Frame(frame, bg=BG)
        pane.pack(fill="both", expand=True, pady=6)

        left = Frame(pane, bg=BG)
        left.pack(side="left", fill="both", expand=True)
        Label(left, text="Analyzed tracks", font=FONT_H1, fg=ACCENT, bg=BG).pack(anchor="w")
        cols = ("fichier", "durée", "paroles", "json", "BPM", "clé", "note", "problèmes")
        music_col_labels = {"fichier": "File", "durée": "Duration", "paroles": "Lyrics",
                             "clé": "Key", "note": "Grade", "problèmes": "Issues"}
        self.music_tree = ttk.Treeview(left, columns=cols, show="headings",
                                        style="Dark.Treeview", height=14)
        for c, w in zip(cols, (180, 65, 60, 50, 60, 90, 50, 240)):
            self.music_tree.heading(c, text=music_col_labels.get(c, c)); self.music_tree.column(c, width=w, anchor="center")
        self.music_tree.column("fichier", anchor="w"); self.music_tree.column("problèmes", anchor="w")
        self.music_tree.pack(fill="both", expand=True)

        right = Frame(pane, bg=CARD, padx=12, pady=10, width=280)
        right.pack(side="right", fill="y", padx=(12, 0))
        right.pack_propagate(False)
        Label(right, text="Summary", font=FONT_H1, fg=ACCENT, bg=CARD).pack(anchor="w")
        self.music_summary_text = Text(right, bg=CARD, fg=TEXT, font=FONT_SMALL,
                                        relief="flat", wrap="word", state="disabled", height=18)
        self.music_summary_text.pack(fill="both", expand=True)

        # Actions
        act = Frame(frame, bg=BG)
        act.pack(fill="x", pady=(4, 0))
        make_button(act, "🚀 Open ACE-Step", self._open_ace_step, width=18).pack(side="left", padx=4)
        Label(act, text="→ Launch the ACE-Step 1.5 UI → LoRA Training tab",
              font=FONT_SMALL, fg=TEXT_DIM, bg=BG).pack(side="left")

    def _run_music_analysis(self):
        folder = self.music_folder.get().strip()
        if not folder or not os.path.isdir(folder):
            messagebox.showwarning("Folder", "Choose a valid audio folder.")
            return
        self.music_tree.delete(*self.music_tree.get_children())
        self._set_music_summary("⏳ Analyzing…")
        self.music_progress_var.set("Starting…")

        def run():
            try:
                from analyze_music import analyze_music_folder
                GRADE_COLOR = {"A": GREEN, "B": ACCENT, "C": ORANGE, "D": RED, "F": "#ff0000"}

                def on_progress(i, total, name):
                    self.root.after(0, lambda: self.music_progress_var.set(
                        f"[{i+1}/{total}] {name}"))

                def on_result(r):
                    tag = r["score"]
                    dur = f"{r['duration_s']:.0f}s" if r["duration_s"] else "?"
                    bpm = str(r["meta"].get("bpm", "?")) if r["meta"].get("bpm") else "?"
                    key = r["meta"].get("keyscale", "?") or "?"
                    lyrics = "✅" if r["has_lyrics"] else "❌"
                    jsn = "✅" if r["has_json"] else "❌"
                    issues = " | ".join(r["issues"]) if r["issues"] else "✅ OK"
                    self.root.after(0, lambda: self.music_tree.insert(
                        "", "end", values=(r["file"], dur, lyrics, jsn, bpm, key, tag, issues),
                        tags=(tag,)))
                    self.root.after(0, lambda: self.music_tree.tag_configure(
                        tag, foreground=GRADE_COLOR.get(tag, TEXT)))

                summary = analyze_music_folder(folder, on_progress, on_result)
                self.root.after(0, lambda: self._show_music_summary(summary))
                self.root.after(0, lambda: self.music_progress_var.set(
                    f"✅ {summary['total']} track(s) analyzed"))
            except ImportError as e:
                self.root.after(0, lambda e=e: self._set_music_summary(
                    f"❌ Missing module: {e}\n\nInstall: pip install librosa soundfile mutagen"))

        threading.Thread(target=run, daemon=True).start()

    def _generate_music_json(self):
        folder = self.music_folder.get().strip()
        if not folder or not os.path.isdir(folder):
            messagebox.showwarning("Folder", "Choose a valid audio folder.")
            return
        try:
            from analyze_music import prepare_dataset
            generated = prepare_dataset(folder, generate_missing_json=True)
            if generated:
                messagebox.showinfo("JSON generated",
                    f"✅ {len(generated)} .json file(s) created.\n\nFill in the bpm, keyscale and caption fields before training.\n\nFirst file: {generated[0]}")
            else:
                messagebox.showinfo("JSON", "All tracks already have a .json.")
        except Exception as e:
            messagebox.showerror("Error", str(e))

    def _show_music_summary(self, s):
        gc = s.get("grade_counts", {})
        bpm_r = s.get("bpm_range")
        keys = s.get("unique_keys", [])
        txt = (
            f"📁 Tracks: {s['total']}\n"
            f"⏱ Total duration: {s['total_duration_min']} min\n"
            f"⌛ Avg. duration: {s['avg_duration_s']} s\n\n"
            f"Grades:\n"
            + "".join(f"  {g}: {gc.get(g,0)}\n" for g in "ABCDF")
            + f"\n🎯 Overall score: {s['overall_score']}\n"
            + ("✅ Ready for ACE-Step\n" if s.get('ace_step_ready') else "⚠️ Fix the issues\n")
            + f"\n📊 Diversity:\n"
            f"  BPM: {bpm_r[0]}–{bpm_r[1]}" if bpm_r else "  BPM: not provided"
        )
        if keys:
            txt += f"\n  Keys ({len(keys)}): {', '.join(keys[:6])}"
            if len(keys) > 6:
                txt += f"…+{len(keys)-6}"
        txt += (
            f"\n\n⚠️ Common issues:\n"
            + "\n".join(f"  • {i['issue']} ({i['count']}×)" for i in s.get('top_issues', []))
            + f"\n\n💡 Recommendation:\n{s.get('recommendation', '')}"
        )
        self._set_music_summary(txt)

    def _set_music_summary(self, txt):
        self.music_summary_text.config(state="normal")
        self.music_summary_text.delete("1.0", "end")
        self.music_summary_text.insert("1.0", txt)
        self.music_summary_text.config(state="disabled")

    def _open_ace_step(self):
        bat = r"C:\AI\ACE-Step-1.5\start_gradio_ui.bat"
        if os.path.exists(bat):
            subprocess.Popen(["cmd", "/c", "start", "", bat], shell=False)
        else:
            messagebox.showinfo("ACE-Step", f"ACE-Step not found:\n{bat}")

    def _build_config_tab(self, parent):
        frame = Frame(parent, bg=BG, padx=20, pady=20)
        parent.add(frame, text="  ⚙ Config  ")

        Label(frame, text="Configuration",
              font=FONT_H1, fg=TEXT, bg=BG).pack(anchor="w", pady=(0, 5))
        Label(frame, text="Adjust to match your install. Saved to config.json.",
              font=FONT_SMALL, fg=TEXT_DIM, bg=BG).pack(anchor="w", pady=(0, 20))

        self.entries = {}
        # key : (icon, label, desc, picker_type)  picker_type = "file" | "dir"
        labels = {
            "comfyui_python": ("🐍", "ComfyUI Python",
                                "ComfyUI's python.exe (has insightface + torch CUDA)", "file"),
            "datasets_dir":   ("📂", "Default datasets folder",
                                "Pre-filled in the analyzer", "dir"),
            "insightface_root": ("🧩", "Insightface models folder (antelopev2)",
                                "Leave empty to auto-detect (env var LDC_INSIGHTFACE_ROOT or ~/.insightface)", "dir"),
        }
        for key, (icon, label, desc, picker) in labels.items():
            card = Frame(frame, bg=CARD, padx=14, pady=12)
            card.pack(fill="x", pady=4)

            top_row = Frame(card, bg=CARD)
            top_row.pack(fill="x")
            Label(top_row, text=icon, font=FONT_EMOJI, fg=ACCENT2, bg=CARD).pack(side="left", padx=(0, 10))
            Label(top_row, text=label, font=FONT_H1, fg=TEXT, bg=CARD).pack(side="left")
            Label(top_row, text=desc, font=FONT_SMALL, fg=TEXT_DIM, bg=CARD).pack(side="left", padx=10)

            entry_row = Frame(card, bg=CARD)
            entry_row.pack(fill="x", pady=(8, 0))
            var = StringVar(value=self.cfg.get(key, ""))
            entry = tk.Entry(entry_row, textvariable=var, font=FONT_MONO,
                             bg=BG2, fg=TEXT, insertbackground=TEXT,
                             relief="flat", borderwidth=0)
            entry.pack(side="left", fill="x", expand=True, ipady=6, padx=(0, 6))
            if picker == "file":
                make_button(entry_row, "📂", lambda v=var: self._pick_file(v)).pack(side="left")
            else:
                make_button(entry_row, "📂", lambda v=var: self._pick_folder(v)).pack(side="left")
            self.entries[key] = var

        # ===== Sélecteur de device (CPU / GPU) =====
        dev_card = Frame(frame, bg=CARD, padx=14, pady=12)
        dev_card.pack(fill="x", pady=4)
        dev_top = Frame(dev_card, bg=CARD)
        dev_top.pack(fill="x")
        Label(dev_top, text="⚡", font=FONT_EMOJI, fg=ACCENT2, bg=CARD).pack(side="left", padx=(0, 10))
        Label(dev_top, text="Compute (device)", font=FONT_H1, fg=TEXT, bg=CARD).pack(side="left")
        Label(dev_top, text="auto = GPU if available (recommended)",
              font=FONT_SMALL, fg=TEXT_DIM, bg=CARD).pack(side="left", padx=10)

        dev_row = Frame(dev_card, bg=CARD)
        dev_row.pack(fill="x", pady=(8, 0))
        self.device_var = StringVar(value=self.cfg.get("device", "auto"))
        for val, lbl in (("auto", "Auto (GPU if available)"),
                          ("cuda", "Force GPU (CUDA)"),
                          ("cpu", "Force CPU")):
            tk.Radiobutton(dev_row, text=lbl, variable=self.device_var, value=val,
                            font=FONT_BODY, fg=TEXT, bg=CARD, selectcolor=BG2,
                            activebackground=CARD, activeforeground=TEXT).pack(side="left", padx=10)
        self.entries["device"] = self.device_var

        btn_row = Frame(frame, bg=BG)
        btn_row.pack(pady=25)
        make_button(btn_row, "💾 Save", self._save_cfg, primary=True).pack(side="left", padx=5)
        make_button(btn_row, "↺ Reset defaults", self._reset_cfg).pack(side="left", padx=5)

        # ===== Section MAJ logiciel =====
        Label(frame, text="Software update",
              font=FONT_H1, fg=TEXT, bg=BG).pack(anchor="w", pady=(30, 5))
        upd_card = Frame(frame, bg=CARD, padx=14, pady=12)
        upd_card.pack(fill="x", pady=4)

        # Lecture version locale
        try:
            sys.path.insert(0, str(Path(__file__).parent))
            from updater import get_current_version
            current_v = get_current_version()
        except Exception:
            current_v = "v0.0.0"

        ver_row = Frame(upd_card, bg=CARD)
        ver_row.pack(fill="x")
        Label(ver_row, text=f"📦 Local version: {current_v}",
              font=FONT_BODY, fg=TEXT, bg=CARD).pack(side="left")
        Label(ver_row, text="  ·  github.com/akalavol/LoRA-Dataset-Coach",
              font=FONT_SMALL, fg=TEXT_DIM, bg=CARD).pack(side="left")

        self.upd_status = Label(upd_card, text="", font=FONT_SMALL,
                                 fg=TEXT_DIM, bg=CARD, anchor="w",
                                 wraplength=900, justify="left")
        self.upd_status.pack(fill="x", pady=(8, 0))

        # Opt-in : desactive par defaut pour ne jamais ecraser des
        # modifications locales sans que l'utilisateur l'ait explicitement
        # demande. La garde reelle est dans updater.py (ldc_config.updates_enabled()).
        allow_update_var = tk.BooleanVar(value=bool(self.cfg.get("allow_self_update", False)))
        self.entries["allow_self_update"] = allow_update_var
        tk.Checkbutton(upd_card, text="Allow installing updates (can overwrite local files)",
                        variable=allow_update_var, font=FONT_BODY, fg=TEXT, bg=CARD,
                        selectcolor=BG2, activebackground=CARD,
                        activeforeground=TEXT).pack(anchor="w", pady=(6, 0))

        upd_btn_row = Frame(upd_card, bg=CARD)
        upd_btn_row.pack(fill="x", pady=(8, 0))
        make_button(upd_btn_row, "🔄 Check now",
                     self._check_for_updates, primary=True).pack(side="left", padx=5)
        self.upd_apply_btn = Button(upd_btn_row, text="⬇ Install update",
                                      font=FONT_BODY, bg=CARD_HI, fg=TEXT_DIM,
                                      relief="flat", padx=12, pady=6,
                                      state="disabled", cursor="hand2",
                                      command=self._apply_update)
        self.upd_apply_btn.pack(side="left", padx=5)

        # ===== Section CHANGELOG (Journal des nouveautés) =====
        Label(frame, text="Changelog",
              font=FONT_H1, fg=TEXT, bg=BG).pack(anchor="w", pady=(25, 5))
        Label(frame, text="All the changes, additions and fixes for each version.",
              font=FONT_SMALL, fg=TEXT_DIM, bg=BG).pack(anchor="w", pady=(0, 8))

        chg_card = Frame(frame, bg=CARD, padx=14, pady=12)
        chg_card.pack(fill="both", expand=True, pady=4)

        chg_header = Frame(chg_card, bg=CARD)
        chg_header.pack(fill="x", pady=(0, 6))
        Label(chg_header, text="📋 CHANGELOG.md", font=FONT_BODY,
              fg=ACCENT2, bg=CARD).pack(side="left")
        make_button(chg_header, "🔄 Reload",
                     self._load_changelog).pack(side="right", padx=4)
        make_button(chg_header, "🌐 View on GitHub",
                     lambda: self._open_url(
                         "https://github.com/akalavol/LoRA-Dataset-Coach/blob/main/CHANGELOG.md"
                     )).pack(side="right", padx=4)

        chg_scroll_frame = Frame(chg_card, bg=CARD)
        chg_scroll_frame.pack(fill="both", expand=True)
        self.changelog_text = Text(
            chg_scroll_frame, bg=BG2, fg=TEXT, font=FONT_MONO,
            relief="flat", padx=8, pady=8, wrap="word", height=18,
            insertbackground=TEXT,
        )
        chg_sb = ttk.Scrollbar(chg_scroll_frame, orient="vertical",
                                 command=self.changelog_text.yview)
        self.changelog_text.configure(yscrollcommand=chg_sb.set)
        self.changelog_text.pack(side="left", fill="both", expand=True)
        chg_sb.pack(side="right", fill="y")

        # Tags coloration markdown basique
        self.changelog_text.tag_configure("h1", foreground=ACCENT,
                                            font=("Segoe UI", 14, "bold"),
                                            spacing1=12, spacing3=4)
        self.changelog_text.tag_configure("h2", foreground=ACCENT2,
                                            font=("Segoe UI", 12, "bold"),
                                            spacing1=10, spacing3=4)
        self.changelog_text.tag_configure("h3", foreground=GREEN,
                                            font=("Segoe UI", 11, "bold"),
                                            spacing1=6, spacing3=2)
        self.changelog_text.tag_configure("bullet", foreground=TEXT_DIM)

        # Charge le contenu initial
        self._load_changelog()

    def _check_for_updates(self):
        self.upd_status.config(text="🔍 Checking…", fg=TEXT_DIM)
        self.upd_apply_btn.config(state="disabled", bg=CARD_HI, fg=TEXT_DIM)
        def worker():
            try:
                from updater import check_for_updates
                info = check_for_updates()
                self.root.after(0, lambda: self._on_update_check_done(info))
            except Exception as e:
                self.root.after(0, lambda e=e: self.upd_status.config(
                    text=f"❌ Error: {e}", fg=RED))
        threading.Thread(target=worker, daemon=True).start()

    def _on_update_check_done(self, info):
        if info.get("error"):
            self.upd_status.config(text=f"⚠️ {info['error']}", fg=YELLOW)
            return
        current = info.get("current", "?")
        latest = info.get("latest", "?")
        if info.get("update_available"):
            notes = (info.get("notes") or "")[:300]
            self.upd_status.config(
                text=f"✅ New version available: {latest} (you have {current})\n\n"
                     f"Notes:\n{notes}",
                fg=GREEN)
            self.upd_apply_btn.config(state="normal", bg=GREEN, fg=BG)
            self._pending_update_info = info
        else:
            self.upd_status.config(
                text=f"✅ You're up to date ({current}).", fg=GREEN)

    def _apply_update(self):
        info = getattr(self, "_pending_update_info", None)
        if not info:
            return
        is_git = info.get("is_git_install")
        msg = (f"Install {info['latest']}?\n\n"
               f"Method: {'git pull (recommended)' if is_git else 'Download zip + replace'}\n"
               f"A backup of the current .py files will be created in _backup_before_update/\n\n"
               f"The app will need to be restarted afterward.")
        if not messagebox.askyesno("Confirm update", msg):
            return

        self.upd_status.config(text="⏳ Updating…", fg=ACCENT)
        self.upd_apply_btn.config(state="disabled")
        def worker():
            try:
                from updater import apply_update_git, apply_update_zip
                if info.get("is_git_install"):
                    result = apply_update_git()
                else:
                    result = apply_update_zip(info["zipball_url"])
                self.root.after(0, lambda: self._on_update_applied(result))
            except Exception as e:
                self.root.after(0, lambda e=e: self.upd_status.config(
                    text=f"❌ Error: {e}", fg=RED))
        threading.Thread(target=worker, daemon=True).start()

    def _on_update_applied(self, result):
        if result.get("success"):
            self.upd_status.config(
                text=f"✅ {result['message']}\n\n"
                     f"➜ Close the app and relaunch run.bat to activate the new version.",
                fg=GREEN)
            messagebox.showinfo("Update OK",
                                  "Update applied. Close and relaunch the app.")
            # Auto-refresh changelog après update réussi
            try:
                self._load_changelog()
            except Exception:
                pass
        else:
            self.upd_status.config(text=f"❌ {result['message']}", fg=RED)
            self.upd_apply_btn.config(state="normal", bg=GREEN, fg=BG)

    def _open_url(self, url):
        try:
            import webbrowser
            webbrowser.open(url)
        except Exception as e:
            messagebox.showerror("Error", f"Cannot open the URL:\n{e}")

    def _load_changelog(self):
        """Charge CHANGELOG.md depuis le disque local, fallback sur GitHub."""
        if not hasattr(self, "changelog_text"):
            return
        chg_path = Path(__file__).parent / "CHANGELOG.md"
        content = ""
        if chg_path.is_file():
            try:
                content = chg_path.read_text(encoding="utf-8")
            except Exception:
                content = ""

        # Fallback : télécharge depuis GitHub si CHANGELOG.md manquant
        if not content:
            try:
                url = "https://raw.githubusercontent.com/akalavol/LoRA-Dataset-Coach/main/CHANGELOG.md"
                with urllib.request.urlopen(url, timeout=8) as resp:
                    content = resp.read().decode("utf-8")
            except Exception as e:
                content = f"Could not load CHANGELOG.md:\n{e}\n\n" \
                           f"Visit the GitHub repo directly."

        # Rendu markdown basique avec coloration
        self.changelog_text.config(state="normal")
        self.changelog_text.delete("1.0", "end")
        for line in content.splitlines():
            if line.startswith("# "):
                self.changelog_text.insert("end", line[2:] + "\n", "h1")
            elif line.startswith("## "):
                self.changelog_text.insert("end", line[3:] + "\n", "h2")
            elif line.startswith("### "):
                self.changelog_text.insert("end", line[4:] + "\n", "h3")
            elif line.startswith("- ") or line.startswith("  - "):
                self.changelog_text.insert("end", line + "\n", "bullet")
            else:
                self.changelog_text.insert("end", line + "\n")
        self.changelog_text.config(state="disabled")

    # ============================================================
    # ANALYZER : coherence dataset LoRA
    # ============================================================
    def _build_analyzer_tab(self, parent):
        frame = Frame(parent, bg=BG, padx=15, pady=12)
        parent.add(frame, text="  📊 Dataset Analyzer  ")

        Label(frame, text="LoRA Dataset Coherence Analyzer",
              font=FONT_H1, fg=ACCENT2, bg=BG).pack(anchor="w")
        Label(frame, text="Checks whether a folder of images is coherent for training a face LoRA: "
                          "same person, faces detected, resolutions, etc.",
              font=FONT_SMALL, fg=TEXT_DIM, bg=BG, wraplength=900, justify="left").pack(anchor="w", pady=(0, 10))

        # Selection dossier
        sel_frame = Frame(frame, bg=CARD, padx=10, pady=8)
        sel_frame.pack(fill="x", pady=4)
        Label(sel_frame, text="📂 Dataset folder:",
              font=FONT_BODY, fg=TEXT, bg=CARD).pack(side="left")
        self.analyzer_path = StringVar(value=self.cfg.get("datasets_dir", r"C:\AI\datasets"))
        entry = tk.Entry(sel_frame, textvariable=self.analyzer_path, font=FONT_MONO,
                         bg=BG2, fg=TEXT, insertbackground=TEXT, relief="flat")
        entry.pack(side="left", fill="x", expand=True, ipady=5, padx=8)
        make_button(sel_frame, "📂", lambda: self._pick_folder(self.analyzer_path)).pack(side="left", padx=4)
        make_button(sel_frame, "🔍 Analyze", self._run_analyzer, primary=True, width=14).pack(side="left", padx=4)
        self.analyzer_export_btn = Button(sel_frame, text="📄 Export PDF", font=FONT_BODY,
                                           bg=CARD_HI, fg=TEXT_DIM, relief="flat",
                                           padx=10, pady=6, cursor="hand2",
                                           state="disabled",
                                           command=self._export_analyzer_pdf)
        self.analyzer_export_btn.pack(side="left", padx=4)

        self.analyzer_move_btn = Button(sel_frame, text="🗑 Move rejects", font=FONT_BODY,
                                         bg=CARD_HI, fg=TEXT_DIM, relief="flat",
                                         padx=10, pady=6, cursor="hand2",
                                         state="disabled",
                                         command=self._move_rejected_photos)
        self.analyzer_move_btn.pack(side="left", padx=4)

        self.analyzer_upscale_btn = Button(sel_frame, text="🔧 Blurry → upscale", font=FONT_BODY,
                                            bg=CARD_HI, fg=TEXT_DIM, relief="flat",
                                            padx=10, pady=6, cursor="hand2",
                                            state="disabled",
                                            command=self._move_blurry_to_upscale)
        self.analyzer_upscale_btn.pack(side="left", padx=4)

        self.analyzer_kohya_btn = Button(sel_frame, text="🧬 Prepare Kohya", font=FONT_BODY,
                                          bg=CARD_HI, fg=TEXT_DIM, relief="flat",
                                          padx=10, pady=6, cursor="hand2",
                                          state="disabled",
                                          command=self._prepare_kohya)
        self.analyzer_kohya_btn.pack(side="left", padx=4)

        self.analyzer_mask_btn = Button(sel_frame, text="🎭 Subject masks", font=FONT_BODY,
                                         bg=CARD_HI, fg=TEXT_DIM, relief="flat",
                                         padx=10, pady=6, cursor="hand2",
                                         state="disabled",
                                         command=self._generate_subject_masks)
        self.analyzer_mask_btn.pack(side="left", padx=4)

        self.analyzer_gen_btn = Button(sel_frame, text="✨ Generate missing", font=FONT_BODY,
                                        bg=CARD_HI, fg=TEXT_DIM, relief="flat",
                                        padx=10, pady=6, cursor="hand2",
                                        state="disabled",
                                        command=self._generate_targeted_workflows)
        self.analyzer_gen_btn.pack(side="left", padx=4)

        # ===== Photo de reference (optionnelle) =====
        ref_frame = Frame(frame, bg=CARD, padx=10, pady=8)
        ref_frame.pack(fill="x", pady=4)
        Label(ref_frame, text="📷 Reference(s):",
              font=FONT_BODY, fg=TEXT, bg=CARD).pack(side="left")
        self.analyzer_ref_path = StringVar(value="")
        ref_entry = tk.Entry(ref_frame, textvariable=self.analyzer_ref_path, font=FONT_MONO,
                             bg=BG2, fg=TEXT, insertbackground=TEXT, relief="flat")
        ref_entry.pack(side="left", fill="x", expand=True, ipady=5, padx=8)
        make_button(ref_frame, "📄", self._pick_ref_image).pack(side="left", padx=2)   # 1 fichier
        make_button(ref_frame, "📁", self._pick_ref_folder).pack(side="left", padx=2)  # dossier de réfs
        make_button(ref_frame, "✕", lambda: (self.analyzer_ref_path.set(""),
                                              self._update_preview_ref(""))).pack(side="left", padx=2)
        Label(ref_frame, text="(optional — 1 photo OR 📁 a folder of 2-5 photos = more robust identity)",
              font=FONT_SMALL, fg=TEXT_DIM, bg=CARD).pack(side="left", padx=8)

        # ===== Mode captioner =====
        cap_frame = Frame(frame, bg=CARD, padx=10, pady=6)
        cap_frame.pack(fill="x", pady=4)
        Label(cap_frame, text="🏷 Captions:", font=FONT_BODY, fg=TEXT, bg=CARD).pack(side="left")
        self.captioner_mode = StringVar(value="none")
        for val, lbl, tip in (
            ("none",       "None (analysis only)", "No captioning - fastest, nothing written to disk"),
            ("wd14",       "WD14 tags",       "Booru tags SDXL/Kohya (~30 s, 330 MB)"),
            ("natural",    "Florence-2",      "Natural-language caption, fast but hallucinates on people"),
            ("joycaption", "JoyCaption ⭐",   "Long captions: FLUX.2/Qwen-Image/Z-Image/Wan/LTX-2 (slow, 4-8 GB)"),
            ("all",        "All",            "WD14 + Florence + JoyCaption (very slow, exhaustive)"),
        ):
            tk.Radiobutton(cap_frame, text=lbl, variable=self.captioner_mode, value=val,
                            font=FONT_BODY, fg=TEXT, bg=CARD, selectcolor=BG2,
                            activebackground=CARD, activeforeground=TEXT).pack(side="left", padx=6)
        Label(cap_frame, text="(WD14 for SDXL/Pony · JoyCaption for all 2025-26 models)",
              font=FONT_SMALL, fg=TEXT_DIM, bg=CARD).pack(side="left", padx=8)

        # ===== Options caption / artefacts (ligne separee) =====
        cap_opts_frame = Frame(frame, bg=CARD, padx=10, pady=6)
        cap_opts_frame.pack(fill="x", pady=4)
        self.write_captions_var = tk.BooleanVar(value=False)
        self.overwrite_captions_var = tk.BooleanVar(value=False)
        self.detect_artifacts_var = tk.BooleanVar(value=True)
        tk.Checkbutton(cap_opts_frame, text="Write caption files",
                        variable=self.write_captions_var,
                        font=FONT_BODY, fg=TEXT, bg=CARD, selectcolor=BG2,
                        activebackground=CARD, activeforeground=TEXT).pack(side="left", padx=6)
        tk.Checkbutton(cap_opts_frame, text="Overwrite existing captions",
                        variable=self.overwrite_captions_var,
                        font=FONT_BODY, fg=TEXT, bg=CARD, selectcolor=BG2,
                        activebackground=CARD, activeforeground=TEXT).pack(side="left", padx=6)
        tk.Checkbutton(cap_opts_frame, text="Detect anatomical artifacts (WD14, no files written)",
                        variable=self.detect_artifacts_var,
                        font=FONT_BODY, fg=TEXT, bg=CARD, selectcolor=BG2,
                        activebackground=CARD, activeforeground=TEXT).pack(side="left", padx=6)

        # Barre de progression + ligne phase + ETA
        progress_outer = Frame(frame, bg=BG)
        progress_outer.pack(fill="x", pady=(8, 4))

        # Ligne 1 : phase en cours
        self.analyzer_phase = Label(progress_outer, text="⏸ Waiting",
                                     font=FONT_BODY, fg=TEXT_DIM, bg=BG, anchor="w")
        self.analyzer_phase.pack(fill="x")

        # Ligne 2 : barre + pourcentage + ETA + fichier
        bar_row = Frame(progress_outer, bg=BG)
        bar_row.pack(fill="x", pady=(4, 0))

        self.analyzer_progress = ttk.Progressbar(bar_row, mode="determinate",
                                                  length=400, maximum=100)
        self.analyzer_progress.pack(side="left", fill="x", expand=True)

        self.analyzer_percent = Label(bar_row, text="0%",
                                       font=FONT_BODY, fg=ACCENT, bg=BG, width=6, anchor="e")
        self.analyzer_percent.pack(side="left", padx=(8, 4))

        self.analyzer_eta = Label(bar_row, text="",
                                   font=FONT_SMALL, fg=TEXT_DIM, bg=BG, width=18, anchor="w")
        self.analyzer_eta.pack(side="left", padx=4)

        # Ligne 3 : fichier en cours
        self.analyzer_status = Label(progress_outer, text="",
                                      font=FONT_SMALL, fg=TEXT_DIM, bg=BG, anchor="w")
        self.analyzer_status.pack(fill="x", pady=(2, 0))

        # ===== PREVIEW LIVE de la photo en cours d'analyse =====
        if _HAS_PIL:
            preview_row = Frame(frame, bg=BG)
            preview_row.pack(fill="x", pady=(8, 4))

            # Image courante (gauche)
            self.preview_current_frame = Frame(preview_row, bg=CARD, padx=6, pady=6)
            self.preview_current_frame.pack(side="left")
            Label(self.preview_current_frame, text="📷 Currently analyzing",
                  font=FONT_SMALL, fg=TEXT_DIM, bg=CARD).pack()
            self.preview_current_label = Label(self.preview_current_frame, bg=CARD,
                                                width=200, height=200)
            self.preview_current_label.pack(pady=2)
            self.preview_current_name = Label(self.preview_current_frame, text="",
                                               font=FONT_SMALL, fg=TEXT_DIM, bg=CARD,
                                               wraplength=200)
            self.preview_current_name.pack()

            # Image de reference (droite, si une ref est definie)
            self.preview_ref_frame = Frame(preview_row, bg=CARD, padx=6, pady=6)
            self.preview_ref_frame.pack(side="left", padx=12)
            Label(self.preview_ref_frame, text="📌 Reference",
                  font=FONT_SMALL, fg=TEXT_DIM, bg=CARD).pack()
            self.preview_ref_label = Label(self.preview_ref_frame, bg=CARD,
                                            width=200, height=200)
            self.preview_ref_label.pack(pady=2)
            self.preview_ref_name = Label(self.preview_ref_frame, text="(none)",
                                           font=FONT_SMALL, fg=TEXT_DIM, bg=CARD,
                                           wraplength=200)
            self.preview_ref_name.pack()

            # Verdict live de la photo courante (a droite des 2 previews)
            self.preview_verdict_frame = Frame(preview_row, bg=CARD, padx=12, pady=6)
            self.preview_verdict_frame.pack(side="left", fill="both", expand=True, padx=4)
            Label(self.preview_verdict_frame, text="🔎 Latest verdict",
                  font=FONT_SMALL, fg=TEXT_DIM, bg=CARD, anchor="w").pack(anchor="w")
            self.preview_verdict_text = Label(self.preview_verdict_frame, text="",
                                               font=FONT_BODY, fg=TEXT, bg=CARD,
                                               anchor="nw", justify="left", wraplength=400)
            self.preview_verdict_text.pack(anchor="nw", fill="both", expand=True, pady=4)

            # References vers les PhotoImages (Tk les garbage-collect sinon)
            self._preview_current_photo = None
            self._preview_ref_photo = None

        # Variables pour l'ETA
        self._analyzer_start_time = None
        self._analyzer_total = 0

        # Bloc verdict global (cache par defaut)
        self.analyzer_verdict_frame = Frame(frame, bg=CARD, padx=15, pady=10)
        # pas pack maintenant - apparait apres analyse

        # Resume
        self.analyzer_summary = Label(frame, text="(no analysis run yet)", font=FONT_BODY,
                                       fg=TEXT_DIM, bg=BG, justify="left")
        self.analyzer_summary.pack(anchor="w", pady=8)

        # Tableau resultats
        tree_frame = Frame(frame, bg=CARD)
        tree_frame.pack(fill="both", expand=True)
        self.analyzer_tree = ttk.Treeview(tree_frame,
                                          columns=("res", "sharp", "face", "size", "yaw", "expr", "sim", "body", "qual", "lora"),
                                          show="tree headings", style="Dark.Treeview")
        self.analyzer_tree.heading("#0", text="Image")
        self.analyzer_tree.heading("res", text="Res.")
        self.analyzer_tree.heading("sharp", text="Sharp.")
        self.analyzer_tree.heading("face", text="Face")
        self.analyzer_tree.heading("size", text="%face")
        self.analyzer_tree.heading("yaw", text="Pose°")
        self.analyzer_tree.heading("expr", text="Expression")
        self.analyzer_tree.heading("sim", text="F.sim")
        self.analyzer_tree.heading("body", text="B.sim")
        self.analyzer_tree.heading("qual", text="Quality")
        self.analyzer_tree.heading("lora", text="🧬 LoRA - reason")
        self.analyzer_tree.column("#0", width=160)
        self.analyzer_tree.column("res", width=75, anchor="center")
        self.analyzer_tree.column("sharp", width=50, anchor="e")
        self.analyzer_tree.column("face", width=35, anchor="center")
        self.analyzer_tree.column("size", width=55, anchor="e")
        self.analyzer_tree.column("yaw", width=50, anchor="e")
        self.analyzer_tree.column("expr", width=100, anchor="w")
        self.analyzer_tree.column("sim", width=50, anchor="e")
        self.analyzer_tree.column("body", width=50, anchor="e")
        self.analyzer_tree.column("qual", width=85)
        self.analyzer_tree.column("lora", width=230)
        sb = ttk.Scrollbar(tree_frame, orient="vertical", command=self.analyzer_tree.yview)
        self.analyzer_tree.configure(yscrollcommand=sb.set)
        self.analyzer_tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        # Tags couleur par verdict
        self.analyzer_tree.tag_configure("ok", foreground=GREEN)
        self.analyzer_tree.tag_configure("warn", foreground=YELLOW)
        self.analyzer_tree.tag_configure("err", foreground=RED)
        # Double-clic ouvre l'image en grand
        self.analyzer_tree.bind("<Double-1>", self._on_tree_double_click)
        # Clic simple : update le preview courant (rapide)
        self.analyzer_tree.bind("<<TreeviewSelect>>", self._on_tree_select)

        # === Zone d'erreur (cachee par defaut, apparait sur crash) ===
        self.analyzer_error_frame = Frame(frame, bg="#3a1f24", padx=10, pady=8)
        # NE PAS pack maintenant - on l'affiche seulement sur crash

        err_header = Frame(self.analyzer_error_frame, bg="#3a1f24")
        err_header.pack(fill="x")
        Label(err_header, text="❌ CRASH DETECTED", font=FONT_H1, fg=RED, bg="#3a1f24").pack(side="left")
        Button(err_header, text="📋 Copy", font=FONT_SMALL,
               bg=CARD_HI, fg=TEXT, relief="flat", padx=8, pady=2, cursor="hand2",
               command=self._copy_analyzer_error).pack(side="right", padx=4)
        Button(err_header, text="✕ Close", font=FONT_SMALL,
               bg=CARD_HI, fg=TEXT, relief="flat", padx=8, pady=2, cursor="hand2",
               command=lambda: self.analyzer_error_frame.pack_forget()).pack(side="right")

        # Text widget scrollable pour le traceback complet
        err_text_frame = Frame(self.analyzer_error_frame, bg="#3a1f24")
        err_text_frame.pack(fill="both", expand=True, pady=(6, 0))
        self.analyzer_error_text = Text(err_text_frame, height=8, font=FONT_MONO,
                                         bg=BG2, fg="#f5c2c7", insertbackground=TEXT,
                                         relief="flat", wrap="word", padx=8, pady=6)
        err_sb = ttk.Scrollbar(err_text_frame, orient="vertical", command=self.analyzer_error_text.yview)
        self.analyzer_error_text.configure(yscrollcommand=err_sb.set)
        self.analyzer_error_text.pack(side="left", fill="both", expand=True)
        err_sb.pack(side="right", fill="y")

    def _run_analyzer(self):
        folder = self.analyzer_path.get()
        if not Path(folder).is_dir():
            messagebox.showerror("Error", f"Folder not found:\n{folder}")
            return
        if not Path(self.comfyui_py).exists():
            messagebox.showerror("Error", f"ComfyUI-future Python not found:\n{self.comfyui_py}\n\n"
                                            "The analyzer needs insightface (installed in ComfyUI-future).")
            return

        # Référence(s) optionnelle(s) : 1 fichier OU un dossier de photos
        ref = self.analyzer_ref_path.get().strip()
        if ref and not (Path(ref).is_file() or Path(ref).is_dir()):
            messagebox.showerror("Error", f"Reference not found:\n{ref}\n\n"
                                            "Provide a photo OR a folder of photos, "
                                            "or leave it empty.")
            return
        # Affiche la ref dans le preview (au cas ou elle a ete tapee manuellement)
        self._update_preview_ref(ref)

        import time as _time
        cap_mode = self.captioner_mode.get() if hasattr(self, "captioner_mode") else "none"
        write_caps = self.write_captions_var.get() if hasattr(self, "write_captions_var") else False
        overwrite_caps = self.overwrite_captions_var.get() if hasattr(self, "overwrite_captions_var") else False
        detect_artifacts = self.detect_artifacts_var.get() if hasattr(self, "detect_artifacts_var") else True

        # Compte les images pour informer l'utilisateur en amont
        exts = (".png", ".jpg", ".jpeg", ".webp")
        try:
            n_imgs = sum(1 for f in Path(folder).iterdir()
                         if f.is_file() and f.suffix.lower() in exts)
        except Exception:
            n_imgs = 0

        # Avertissement si combinaison lente (JoyCaption sur CPU + beaucoup d'images)
        if cap_mode in ("joycaption", "all") and n_imgs >= 40:
            ok = messagebox.askyesno(
                "Potentially long analysis",
                f"{n_imgs} images with “{cap_mode}” captions.\n\n"
                f"⚙ Good news: natural-language captions (JoyCaption/Florence) "
                f"are only generated for photos judged viable — rejects "
                f"(blurry, wrong person, duplicates) are skipped.\n\n"
                f"JoyCaption is still SLOW on CPU (~2 min/image), fast on GPU "
                f"(~30 s/image). If many photos are viable, it can "
                f"still take a while without a GPU.\n\n"
                f"💡 Tip: set the device to GPU in ⚙ Config if you "
                f"haven't already.\n\n"
                f"Continue?"
            )
            if not ok:
                return

        self.analyzer_tree.delete(*self.analyzer_tree.get_children())
        self.analyzer_summary.config(text="", fg=TEXT_DIM)
        self.analyzer_progress.config(value=0, mode="indeterminate")
        self.analyzer_progress.start(15)
        self.analyzer_phase.config(text="⚙ Starting the analysis engine…", fg=ACCENT)
        self.analyzer_percent.config(text="")
        self.analyzer_eta.config(text="")
        self.analyzer_status.config(text="")
        self.analyzer_error_frame.pack_forget()  # Cache l'erreur si visible
        self.analyzer_error_text.delete("1.0", "end")
        self._analyzer_start_time = _time.time()
        self._analyzer_last_activity = _time.time()
        self._analyzer_total = 0
        self._analyzer_phase_label = "Starting the analysis engine"
        self._analyzer_running = True
        self._analyzer_stderr_buffer = []
        self.root.update_idletasks()

        # Démarre le ticker d'activité (montre que ça vit pendant le chargement)
        self._analyzer_tick()

        dev = self.cfg.get("device", "auto")
        threading.Thread(target=self._analyze_subprocess,
                          args=(folder, ref, cap_mode, dev,
                                write_caps, overwrite_caps, detect_artifacts),
                          daemon=True).start()

    def _analyzer_tick(self):
        """Tick chaque seconde : affiche le temps écoulé tant que l'analyse tourne
        et qu'on est encore en phase de chargement (avant la ligne TOTAL)."""
        import time as _time
        if not getattr(self, "_analyzer_running", False):
            return
        elapsed = int(_time.time() - self._analyzer_start_time)
        m, s = divmod(elapsed, 60)
        elapsed_str = f"{m}m{s:02d}s" if m else f"{s}s"

        # Tant qu'on n'a pas reçu TOTAL, on est en chargement modèles
        if self._analyzer_total == 0:
            since_activity = int(_time.time() - self._analyzer_last_activity)
            hint = ""
            if elapsed > 25:
                hint = "  (first run: downloading models, can take several minutes…)"
            self.analyzer_phase.config(
                text=f"⚙ {self._analyzer_phase_label} — {elapsed_str}{hint}", fg=ACCENT)
            # Indicateur d'activité du sous-processus
            if since_activity > 3:
                self.analyzer_status.config(
                    text=f"⏳ working… (last activity {since_activity}s ago)",
                    fg=TEXT_DIM)
            else:
                self.analyzer_status.config(text="⏳ loading…", fg=TEXT_DIM)
        # Reprogramme
        self.root.after(1000, self._analyzer_tick)

    def _analyze_subprocess(self, folder, ref="", cap_mode="none", device="auto",
                             write_captions=False, overwrite_captions=False,
                             detect_artifacts=True):
        import time as _time
        script = str(Path(__file__).parent / "analyze_dataset.py")
        try:
            cmd = [self.comfyui_py, script, folder, "full"]
            # argv: folder(1) full(2) ref(3) cap(4) device(5)
            #       write_captions(6) overwrite_captions(7) detect_artifacts(8)
            cmd.append(ref if ref else "")
            cmd.append(cap_mode)
            cmd.append(device)
            cmd.append("1" if write_captions else "0")
            cmd.append("1" if overwrite_captions else "0")
            cmd.append("1" if detect_artifacts else "0")
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, encoding="utf-8", bufsize=1
            )

            def fmt_eta(seconds):
                if seconds < 60:
                    return f"~{int(seconds)}s"
                m, s = divmod(int(seconds), 60)
                return f"~{m}m{s:02d}s"

            def read_progress():
                for raw_line in iter(proc.stderr.readline, ""):
                    line = raw_line.strip()
                    self._analyzer_stderr_buffer.append(raw_line)  # Capture TOUT pour crash report
                    self._analyzer_last_activity = _time.time()  # tout signe de vie compte
                    if line.startswith("TOTAL "):
                        total = int(line.split()[1])
                        self._analyzer_total = total  # coupe le mode "chargement" du ticker
                        self.root.after(0, lambda t=total: (
                            self.analyzer_progress.stop(),
                            self.analyzer_progress.config(mode="determinate", maximum=t, value=0),
                            self.analyzer_phase.config(text=f"🔍 Analyzing — {t} images", fg=ACCENT),
                            self.analyzer_percent.config(text="0%"),
                            self.analyzer_eta.config(text="")
                        ))
                    elif line.startswith("PROGRESS "):
                        try:
                            parts = line.split(" ", 2)
                            cur_total = parts[1].split("/")
                            cur = int(cur_total[0])
                            tot = int(cur_total[1])
                            name = parts[2] if len(parts) > 2 else ""
                            # Calcul ETA
                            elapsed = _time.time() - self._analyzer_start_time
                            pct = (cur / tot) * 100
                            if cur > 0 and elapsed > 1:
                                rate = cur / elapsed
                                remaining = (tot - cur) / rate if rate > 0 else 0
                                eta_str = f"⏱ {fmt_eta(remaining)} left"
                            else:
                                eta_str = "⏱ computing..."
                            self.root.after(0, lambda c=cur, t=tot, n=name, p=pct, e=eta_str: (
                                self.analyzer_progress.config(value=c),
                                self.analyzer_percent.config(text=f"{p:.0f}%"),
                                self.analyzer_eta.config(text=e),
                                self.analyzer_status.config(text=f"📷 {c}/{t} — {n[:50]}", fg=TEXT_DIM)
                            ))
                        except Exception:
                            pass
                    elif line.startswith("PREVIEW "):
                        # Path absolu de l'image en cours d'analyse
                        img_path = line[8:].strip()
                        self.root.after(0, lambda p=img_path: self._update_preview_current(p))
                    elif line.startswith("IMGINFO "):
                        # Mini-verdict JSON de l'image qu'on vient de finir
                        try:
                            mini = json.loads(line[8:])
                            self.root.after(0, lambda m=mini: self._update_preview_verdict(m))
                        except Exception:
                            pass
                    elif line.startswith("STEP "):
                        msg = line[5:]
                        # Mémorise pour le ticker (qui ajoute le temps écoulé)
                        self._analyzer_phase_label = msg
                        self.root.after(0, lambda m=msg: self.analyzer_phase.config(text=f"⚙ {m}", fg=ACCENT))
                    elif line.startswith("PROGRESS_DONE"):
                        self.root.after(0, lambda: (
                            self.analyzer_phase.config(text="⚙ Computing similarity...", fg=ACCENT),
                            self.analyzer_status.config(text="")
                        ))

            # Lit stdout dans son propre thread (sinon communicate() entre en
            # conflit avec read_progress() qui lit deja stderr)
            stdout_chunks = []
            def read_stdout():
                try:
                    for chunk in iter(proc.stdout.readline, ""):
                        stdout_chunks.append(chunk)
                except Exception:
                    pass

            t_err = threading.Thread(target=read_progress, daemon=True)
            t_out = threading.Thread(target=read_stdout, daemon=True)
            t_err.start()
            t_out.start()

            # Watchdog d'INACTIVITE plutot qu'un timeout total : on ne tue le
            # process QUE s'il ne donne plus aucun signe de vie pendant longtemps.
            # Une analyse JoyCaption de 200 photos sur CPU peut durer des heures,
            # mais elle emet en continu des lignes PROGRESS/PREVIEW.
            INACTIVITY_LIMIT = 1800  # 30 min de silence total = vraiment bloque
            killed_for_inactivity = False
            while proc.poll() is None:
                _time.sleep(2)
                silence = _time.time() - self._analyzer_last_activity
                if silence > INACTIVITY_LIMIT:
                    killed_for_inactivity = True
                    try:
                        proc.kill()
                    except Exception:
                        pass
                    break

            # Laisse les lecteurs finir de vider les pipes
            t_out.join(timeout=5)
            t_err.join(timeout=5)
            self._analyzer_running = False

            if killed_for_inactivity:
                full = "".join(self._analyzer_stderr_buffer)
                self.root.after(0, lambda: self._analyzer_done_error(
                    f"No activity for {INACTIVITY_LIMIT//60} min — process stopped. "
                    f"The model may be stuck downloading.", full))
                return

            stdout_data = "".join(stdout_chunks)

            if proc.returncode not in (0, None):
                full_stderr = "".join(self._analyzer_stderr_buffer)
                self.root.after(0, lambda: self._analyzer_done_error(
                    f"The Python script exited with code {proc.returncode}", full_stderr))
                return

            try:
                data = json.loads(stdout_data)
            except json.JSONDecodeError as e:
                full = "".join(self._analyzer_stderr_buffer) + "\n\n--- STDOUT (start) ---\n" + stdout_data[:3000]
                self.root.after(0, lambda e=e, full=full: self._analyzer_done_error(
                    f"Invalid JSON output: {e}", full))
                return
            if "error" in data:
                full = "".join(self._analyzer_stderr_buffer) + "\n\n--- ERROR ---\n" + str(data.get("error"))
                self.root.after(0, lambda: self._analyzer_done_error(str(data["error"]), full))
                return
            self.root.after(0, lambda: self._show_analyzer_result(data))
        except Exception as e:
            import traceback
            self._analyzer_running = False
            full = "".join(self._analyzer_stderr_buffer) + "\n\n--- GUI TRACEBACK ---\n" + traceback.format_exc()
            self.root.after(0, lambda e=e, full=full: self._analyzer_done_error(str(e), full))

    def _analyzer_done_error(self, msg, full_details=""):
        self._analyzer_running = False  # stoppe le ticker
        self.analyzer_progress.stop()
        self.analyzer_progress.config(mode="determinate", value=0)
        self.analyzer_phase.config(text=f"❌ Failed: {msg[:100]}", fg=RED)
        self.analyzer_percent.config(text="")
        self.analyzer_eta.config(text="")
        self.analyzer_status.config(text="")

        # Affiche la zone d'erreur scrollable avec le detail complet
        if full_details:
            self.analyzer_error_text.delete("1.0", "end")
            self.analyzer_error_text.insert("1.0", full_details)
            self.analyzer_error_text.see("end")  # Scroll vers le bas (souvent l'erreur)
            self.analyzer_error_frame.pack(fill="both", expand=False, pady=(8, 0), padx=10, before=self.analyzer_tree.master)

    def _copy_analyzer_error(self):
        text = self.analyzer_error_text.get("1.0", "end").strip()
        if text:
            self.root.clipboard_clear()
            self.root.clipboard_append(text)
            self.status_var.set("Error copied to clipboard")

    def _export_analyzer_pdf(self):
        """Genere un PDF paysage A4 du compte rendu de la derniere analyse."""
        data = getattr(self, "_last_analysis_data", None)
        if not data:
            messagebox.showinfo("Info", "Run an analysis first.")
            return

        # Nom par defaut base sur le dossier + date
        from pathlib import Path as _P
        folder = self.analyzer_path.get()
        default_name = f"rapport_dataset_{_P(folder).name}_{datetime.now():%Y%m%d_%H%M}.pdf"

        out = filedialog.asksaveasfilename(
            title="Save the PDF report",
            initialfile=default_name,
            defaultextension=".pdf",
            filetypes=[("PDF", "*.pdf")]
        )
        if not out:
            return

        try:
            # Import a la demande
            import sys as _sys
            _sys.path.insert(0, str(_P(__file__).parent))
            import export_pdf
            export_pdf.export(data, folder, out)
            self.status_var.set(f"PDF generated: {_P(out).name}")
            # Propose d'ouvrir
            if messagebox.askyesno("PDF generated", f"Report saved to:\n{out}\n\nOpen it now?"):
                os.startfile(out)
        except Exception as e:
            import traceback
            messagebox.showerror("PDF error",
                f"PDF generation failed:\n{e}\n\n{traceback.format_exc()[-400:]}")

    def _show_analyzer_result(self, data):
        import time as _time
        self._analyzer_running = False  # stoppe le ticker
        # Finalise la barre
        self.analyzer_progress.stop()
        try:
            maxv = int(self.analyzer_progress.cget("maximum"))
            self.analyzer_progress.config(mode="determinate", value=maxv)
        except Exception:
            self.analyzer_progress.config(value=100)

        # Calcul duree totale
        elapsed = _time.time() - (self._analyzer_start_time or _time.time())
        m, s = divmod(int(elapsed), 60)
        dur = f"{m}m{s:02d}s" if m else f"{s}s"
        n = data.get("summary", {}).get("total_images", 0)
        self.analyzer_phase.config(text=f"✅ Analysis done — {n} images in {dur}", fg=GREEN)
        self.analyzer_percent.config(text="100%")
        self.analyzer_eta.config(text="")
        self.analyzer_status.config(text="")

        # Garde les donnees + active les boutons
        self._last_analysis_data = data
        self.analyzer_export_btn.config(state="normal", bg=ACCENT, fg=BG)
        unusable = data.get("summary", {}).get("lora_unusable", 0)
        if unusable > 0:
            self.analyzer_move_btn.config(state="normal", bg=RED, fg=BG,
                                          text=f"🗑 Move rejects ({unusable})")
        else:
            self.analyzer_move_btn.config(state="disabled", bg=CARD_HI, fg=TEXT_DIM,
                                          text="🗑 No rejects to move")

        # Bouton upscale floues
        n_blurry = len(data.get("summary", {}).get("blurry_recoverable", []))
        if n_blurry > 0:
            self.analyzer_upscale_btn.config(state="normal", bg=YELLOW, fg=BG,
                                              text=f"🔧 Blurry → upscale ({n_blurry})")
        else:
            self.analyzer_upscale_btn.config(state="disabled", bg=CARD_HI, fg=TEXT_DIM,
                                              text="🔧 No recoverable blurry photo")

        # Bouton Kohya
        n_viable = data.get("summary", {}).get("lora_viable", 0)
        n_border = data.get("summary", {}).get("lora_borderline", 0)
        if n_viable + n_border >= 10:
            self.analyzer_kohya_btn.config(state="normal", bg=GREEN, fg=BG,
                                            text=f"🧬 Prepare Kohya ({n_viable + n_border} photos)")
        else:
            self.analyzer_kohya_btn.config(state="disabled", bg=CARD_HI, fg=TEXT_DIM,
                                            text="🧬 Not enough viable photos (min 10)")

        # Bouton masques (Lot D)
        if n_viable + n_border >= 1:
            self.analyzer_mask_btn.config(state="normal", bg=ACCENT2, fg=BG,
                                          text=f"🎭 Subject masks ({n_viable + n_border} photos)")
        else:
            self.analyzer_mask_btn.config(state="disabled", bg=CARD_HI, fg=TEXT_DIM,
                                          text="🎭 No viable image")

        # Bouton générer manques (Lot E)
        n_suggestions = len(data.get("summary", {}).get("next_to_generate", []))
        if n_suggestions > 0:
            self.analyzer_gen_btn.config(state="normal", bg=ACCENT, fg=BG,
                                         text=f"✨ Generate missing ({n_suggestions})")
        else:
            self.analyzer_gen_btn.config(state="disabled", bg=CARD_HI, fg=TEXT_DIM,
                                         text="✨ No gap detected")

        # Affiche le verdict global (avec infos ref + overfit + scores target + diversite)
        s = data.get("summary", {})
        self._show_verdict_block(s.get("verdict", {}),
                                  ref_info=s.get("reference"),
                                  ref_match=s.get("reference_match"),
                                  overfit_alerts=s.get("tag_overfit_alerts", []),
                                  top_tags=s.get("tag_frequency_top", []),
                                  target_scores=s.get("target_scores", {}),
                                  diversity=s.get("diversity", {}),
                                  ar_distribution=s.get("aspect_ratio_distribution", {}),
                                  distribution=s.get("distribution", {}),
                                  next_to_generate=s.get("next_to_generate", []))

        # Remplit le résumé du bas (avec la NOTE) + le tableau détaillé
        self._populate_results_table(data)

        # Enregistre automatiquement le rapport dans le dossier dataset
        self._autosave_report(data)

    def _autosave_report(self, data):
        """Sauve le rapport (JSON complet + résumé .txt lisible) dans le dataset.
        Évite de tout reperdre et permet de relire / partager l'analyse."""
        try:
            folder = Path(self.analyzer_path.get())
            if not folder.is_dir():
                return
            s = data.get("summary", {})
            verdict = s.get("verdict") or {}

            # 1) JSON complet (rechargeable)
            json_path = folder / "_analysis_report.json"
            json_path.write_text(
                json.dumps(data, ensure_ascii=False, indent=2),
                encoding="utf-8")

            # 2) Résumé .txt lisible
            lines = []
            lines.append("=" * 60)
            lines.append(f"LoRA ANALYSIS REPORT — {folder.name}")
            lines.append(f"Generated on {datetime.now():%Y-%m-%d %H:%M:%S}")
            lines.append("=" * 60)
            lines.append("")
            lines.append(f"OVERALL GRADE: {verdict.get('grade','?')} "
                         f"({verdict.get('grade_desc','')})")
            lines.append(f"  {s.get('lora_viable',0)} viable · "
                         f"{s.get('lora_borderline',0)} borderline · "
                         f"{s.get('lora_unusable',0)} to discard "
                         f"(out of {s.get('total_images',0)} images)")
            lines.append(f"  Face coherence: {s.get('overall_face_coherence','N/A')} · "
                         f"body: {s.get('overall_body_coherence','N/A')}")
            # Couverture des plans (types présents / manquants)
            dist = s.get("distribution") or {}
            if dist:
                ang = dist.get("angles", {})
                pln = dist.get("plans", {})
                expr = dist.get("expressions", {})
                lines.append("")
                lines.append("SHOT COVERAGE (viable):")
                lines.append(f"  Angles    : front {ang.get('front',0)} · "
                             f"3/4 {ang.get('three_quarter',0)} · profile {ang.get('profil',0)}")
                lines.append(f"  Framing   : close-up {pln.get('face_only',0)} · "
                             f"mid-body {pln.get('both',0)} · full body {pln.get('body_only',0)}")
                if expr:
                    lines.append("  Expressions: " +
                                 ", ".join(f"{k} ({v})" for k, v in sorted(expr.items(), key=lambda x:-x[1])))
            # Photos a generer
            n2g = s.get("next_to_generate") or []
            if n2g:
                lines.append("")
                lines.append("PHOTOS TO GENERATE TO FILL GAPS:")
                for sug in n2g:
                    lines.append(f"  + {sug}")
            if verdict.get("actions"):
                lines.append("")
                lines.append("ACTION PLAN:")
                for a in verdict["actions"]:
                    lines.append(f"  • {a}")
            # Meilleur target
            tscores = s.get("target_scores") or {}
            if tscores:
                lines.append("")
                lines.append("SCORES PER TARGET:")
                for fam, sc in tscores.items():
                    lines.append(f"  {sc.get('grade','?'):>3}  {sc.get('score',0):>3}/100  {fam}")
            lines.append("")
            lines.append("RECOMMENDATIONS:")
            for r in data.get("recommendations", []):
                lines.append(f"  {r}")
            lines.append("")
            lines.append("-" * 60)
            lines.append(f"{'IMAGE':<28} {'VIABLE':<10} REASON")
            lines.append("-" * 60)
            for img in data.get("images", []):
                lines.append(f"{img.get('name','?')[:27]:<28} "
                             f"{str(img.get('lora_viable','?')):<10} "
                             f"{img.get('lora_reason','')}")
            txt_path = folder / "_analysis_report.txt"
            txt_path.write_text("\n".join(lines), encoding="utf-8")

            self.status_var.set(f"📄 Report saved: {json_path.name} + {txt_path.name}")
        except Exception as e:
            # L'auto-save ne doit jamais faire planter l'affichage
            print(f"Auto-save report failed: {e}")

    def _show_verdict_block(self, verdict, ref_info=None, ref_match=None,
                              overfit_alerts=None, top_tags=None,
                              target_scores=None, diversity=None,
                              ar_distribution=None, distribution=None,
                              next_to_generate=None):
        # Vide le bloc precedent
        for w in self.analyzer_verdict_frame.winfo_children():
            w.destroy()

        if not verdict:
            self.analyzer_verdict_frame.pack_forget()
            return

        grade = verdict.get("grade", "?")
        desc = verdict.get("grade_desc", "")
        viable = verdict.get("viable_now", 0)
        after = verdict.get("after_cleanup", 0)
        target_min = verdict.get("target_min", 20)
        target_ideal = verdict.get("target_ideal", 30)
        actions = verdict.get("actions", [])

        # Couleur selon grade
        grade_color = {
            "A": GREEN, "B": GREEN, "B+": GREEN, "B-": YELLOW,
            "C": YELLOW, "D": RED, "F": RED,
        }.get(grade, TEXT)

        # Ligne 1 : grade enorme + description
        top = Frame(self.analyzer_verdict_frame, bg=CARD)
        top.pack(fill="x")
        Label(top, text=grade, font=("Segoe UI", 32, "bold"),
              fg=grade_color, bg=CARD).pack(side="left", padx=(0, 15))
        right = Frame(top, bg=CARD)
        right.pack(side="left", fill="x", expand=True)
        Label(right, text=f"DATASET VERDICT: {desc}",
              font=FONT_H1, fg=grade_color, bg=CARD, anchor="w").pack(fill="x")
        Label(right,
              text=f"{viable} viable photos now → {after} after cleanup  (target: {target_min}-{target_ideal})",
              font=FONT_BODY, fg=TEXT_DIM, bg=CARD, anchor="w").pack(fill="x")

        # Bloc reference (si presente)
        if ref_info and "error" not in (ref_info or {}):
            ref_box = Frame(self.analyzer_verdict_frame, bg=CARD)
            ref_box.pack(fill="x", pady=(8, 0))
            if ref_match:
                ok = ref_match.get("ok", 0)
                doubt = ref_match.get("doubt", 0)
                wrong = ref_match.get("wrong", 0)
                avg = ref_match.get("avg", 0)
                if wrong == 0 and doubt == 0:
                    color = GREEN
                    txt = f"📷 Ref: {ref_info.get('name', '?')}  →  ✅ {ok} photos match (avg {avg})"
                elif wrong == 0:
                    color = YELLOW
                    txt = f"📷 Ref: {ref_info.get('name', '?')}  →  💡 {ok} OK, {doubt} doubtful (avg {avg})"
                else:
                    color = RED
                    txt = f"📷 Ref: {ref_info.get('name', '?')}  →  ❌ {wrong} wrong person(s), {doubt} doubtful, {ok} OK"
                Label(ref_box, text=txt, font=FONT_BODY, fg=color, bg=CARD,
                      anchor="w", wraplength=900, justify="left").pack(fill="x")
        elif ref_info and "error" in ref_info:
            Label(self.analyzer_verdict_frame,
                  text=f"📷 Ref: ⚠️ {ref_info['error']}",
                  font=FONT_BODY, fg=YELLOW, bg=CARD,
                  anchor="w", wraplength=900, justify="left").pack(fill="x", pady=(8, 0))

        # ===== Alertes overfit (tags accessoires trop frequents) =====
        if overfit_alerts:
            Label(self.analyzer_verdict_frame, text="⚠️ Overfit risks:",
                  font=FONT_H1, fg=YELLOW, bg=CARD, anchor="w").pack(fill="x", pady=(10, 4))
            # Groupe par categorie pour affichage propre
            by_cat = {}
            for a in overfit_alerts:
                by_cat.setdefault(a["category"], []).append(a)
            for cat, alerts in by_cat.items():
                alerts.sort(key=lambda x: -x["count"])
                top = alerts[:3]
                txt = ", ".join(f"« {a['tag']} » ({int(a['ratio']*100)}%)" for a in top)
                color = RED if any(a["severity"] == "ALERTE" for a in top) else YELLOW
                Label(self.analyzer_verdict_frame,
                      text=f"  • {cat.capitalize()}: {txt}",
                      font=FONT_BODY, fg=color, bg=CARD,
                      anchor="w", wraplength=900, justify="left").pack(fill="x")

        # ===== SCORES PAR TARGET (7 familles) =====
        if target_scores:
            Label(self.analyzer_verdict_frame, text="🎯 Scores per target family:",
                  font=FONT_H1, fg=ACCENT, bg=CARD, anchor="w").pack(fill="x", pady=(10, 4))
            for fam, sc in target_scores.items():
                grade = sc.get("grade", "?")
                score = sc.get("score", 0)
                reason = sc.get("reason", "")
                color = {"A+": GREEN, "A": GREEN, "B+": GREEN, "B": YELLOW,
                         "C": YELLOW, "D": RED, "F": RED}.get(grade, TEXT)
                row = Frame(self.analyzer_verdict_frame, bg=CARD)
                row.pack(fill="x", pady=1)
                Label(row, text=f"  {grade}", font=("Segoe UI", 12, "bold"),
                      fg=color, bg=CARD, width=4).pack(side="left")
                Label(row, text=f"{score}/100", font=FONT_SMALL, fg=color, bg=CARD,
                      width=8).pack(side="left")
                Label(row, text=fam, font=FONT_BODY, fg=TEXT, bg=CARD,
                      width=35, anchor="w").pack(side="left")
                Label(row, text=reason[:80], font=FONT_SMALL, fg=TEXT_DIM, bg=CARD,
                      anchor="w").pack(side="left", fill="x", expand=True)

        # ===== DIVERSITE =====
        if diversity and diversity.get("overall_score") is not None:
            div_score = diversity["overall_score"]
            div_color = GREEN if div_score >= 70 else (YELLOW if div_score >= 50 else RED)
            div_row = Frame(self.analyzer_verdict_frame, bg=CARD)
            div_row.pack(fill="x", pady=(10, 2))
            Label(div_row, text=f"🌈 Diversity: {int(div_score)}/100",
                  font=FONT_H1, fg=div_color, bg=CARD).pack(side="left")
            Label(div_row, text=f"  ({diversity.get('verdict', '?')})",
                  font=FONT_BODY, fg=TEXT_DIM, bg=CARD).pack(side="left", padx=8)
            if diversity.get("clip_clusters"):
                Label(div_row,
                      text=f"  · {diversity['clip_clusters']} CLIP visual clusters",
                      font=FONT_SMALL, fg=TEXT_DIM, bg=CARD).pack(side="left", padx=8)

        # ===== AR DISTRIBUTION =====
        if ar_distribution and sum(ar_distribution.values()) > 0:
            total_ar = sum(ar_distribution.values())
            sq = ar_distribution.get("square", 0)
            po = ar_distribution.get("portrait", 0) + ar_distribution.get("tall_portrait", 0)
            la = ar_distribution.get("landscape", 0) + ar_distribution.get("wide_landscape", 0)
            ar_txt = (f"📐 Aspect ratio: "
                       f"⬜ {sq} square · 📱 {po} portrait · 🖼 {la} landscape")
            Label(self.analyzer_verdict_frame, text=ar_txt,
                  font=FONT_BODY, fg=TEXT, bg=CARD, anchor="w").pack(fill="x", pady=2)

        # ===== COUVERTURE DES PLANS (types de photos présents / manquants) =====
        if distribution:
            ang = distribution.get("angles", {})
            pln = distribution.get("plans", {})
            expr = distribution.get("expressions", {})
            n_viable_tot = max(1, sum(ang.values()) if ang else 0)

            Label(self.analyzer_verdict_frame,
                  text="📸 Dataset coverage (viable photos):",
                  font=FONT_H1, fg=ACCENT2, bg=CARD, anchor="w").pack(fill="x", pady=(12, 4))

            def cov_line(label, items, missing_msgs):
                """items = [(nom, count, seuil_ok)] ; missing_msgs = liste de manques."""
                row = Frame(self.analyzer_verdict_frame, bg=CARD)
                row.pack(fill="x", pady=1)
                Label(row, text=f"  {label}:", font=FONT_BODY, fg=TEXT_DIM, bg=CARD,
                      width=14, anchor="w").pack(side="left")
                for nom, cnt, ok in items:
                    color = GREEN if ok else (YELLOW if cnt > 0 else RED)
                    Label(row, text=f"{nom} {cnt}", font=FONT_BODY, fg=color, bg=CARD).pack(side="left", padx=6)
                if missing_msgs:
                    Label(row, text="  ❗ " + " · ".join(missing_msgs),
                          font=FONT_SMALL, fg=RED, bg=CARD, anchor="w").pack(side="left", padx=8)

            # --- Angles ---
            front = ang.get("front", 0); tq = ang.get("three_quarter", 0); prof = ang.get("profil", 0)
            miss_a = []
            if prof == 0:
                miss_a.append("no profile shot")
            if tq < 3:
                miss_a.append("few 3/4 shots")
            cov_line("Angles", [("front", front, front > 0),
                                 ("3/4", tq, tq >= 3),
                                 ("profile", prof, prof >= 2)], miss_a)

            # --- Cadrage ---
            fo = pln.get("face_only", 0); bo = pln.get("both", 0); bd = pln.get("body_only", 0)
            miss_p = []
            if bo == 0:
                miss_p.append("no mid-body shot")
            if bd == 0 and n_viable_tot >= 20:
                miss_p.append("no full-body shot")
            cov_line("Framing", [("close-up", fo, fo > 0),
                                  ("mid-body", bo, bo >= 3),
                                  ("full-body", bd, bd >= 1)], miss_p)

            # --- Expressions ---
            if expr:
                exp_items = sorted(expr.items(), key=lambda x: -x[1])
                exp_txt = ", ".join(f"{k} ({v})" for k, v in exp_items[:5])
                exp_color = GREEN if len(expr) >= 3 else YELLOW
                erow = Frame(self.analyzer_verdict_frame, bg=CARD)
                erow.pack(fill="x", pady=1)
                Label(erow, text="  Expressions:", font=FONT_BODY, fg=TEXT_DIM, bg=CARD,
                      width=14, anchor="w").pack(side="left")
                Label(erow, text=exp_txt, font=FONT_BODY, fg=exp_color, bg=CARD,
                      anchor="w", wraplength=700, justify="left").pack(side="left")
                if len(expr) < 3:
                    Label(erow, text="  ❗ not varied enough", font=FONT_SMALL, fg=RED, bg=CARD).pack(side="left", padx=8)

        # ===== À GÉNÉRER ENSUITE (manques concrets) =====
        if next_to_generate:
            Label(self.analyzer_verdict_frame, text="📷 Photos to generate to fill gaps:",
                  font=FONT_H1, fg=ACCENT, bg=CARD, anchor="w").pack(fill="x", pady=(10, 4))
            for sug in next_to_generate:
                Label(self.analyzer_verdict_frame, text=f"  ➕ {sug}",
                      font=FONT_BODY, fg=YELLOW, bg=CARD,
                      anchor="w", wraplength=900, justify="left").pack(fill="x")

        # Ligne finale : plan d'action global (cleanup, training…)
        if actions:
            Label(self.analyzer_verdict_frame, text="🎯 Action plan:",
                  font=FONT_H1, fg=ACCENT, bg=CARD, anchor="w").pack(fill="x", pady=(10, 4))
            for a in actions:
                Label(self.analyzer_verdict_frame, text=f"  • {a}",
                      font=FONT_BODY, fg=TEXT, bg=CARD,
                      anchor="w", wraplength=900, justify="left").pack(fill="x")

        # Pack au-dessus du resume
        self.analyzer_verdict_frame.pack(fill="x", padx=10, pady=(0, 6),
                                          before=self.analyzer_summary)

    def _generate_targeted_workflows(self):
        """Génère des workflows ComfyUI ciblés pour combler les manques détectés."""
        data = getattr(self, "_last_analysis_data", None)
        if not data:
            return
        suggestions = data.get("summary", {}).get("next_to_generate", [])
        if not suggestions:
            messagebox.showinfo("Nothing to do", "No gap detected.")
            return

        # Dossier de sortie
        default_out = Path(self.analyzer_path.get()).parent / "targeted_workflows"
        out = filedialog.askdirectory(
            initialdir=str(default_out.parent),
            title="Folder to export the targeted workflows to"
        )
        out_folder = Path(out) if out else default_out

        try:
            sys.path.insert(0, str(Path(__file__).parent))
            import prompt_generator
            written = prompt_generator.export_workflows_for_suggestions(
                suggestions=suggestions,
                output_folder=out_folder,
                base_persona_desc="",  # à enrichir : peut être lu depuis une config
                reference_image="reference_face_1024.png",
                checkpoint="RealVisXL_V5.0_fp16.safetensors",
            )
        except Exception as e:
            import traceback
            messagebox.showerror("Error", f"{e}\n\n{traceback.format_exc()[-300:]}")
            return

        msg = f"✅ {len(written)} workflow(s) exported to:\n{out_folder}\n\n"
        for w in written:
            msg += f"  • {w['category']} (x{w['count']}) → {Path(w['workflow_path']).name}\n"
        msg += "\n➜ Drag and drop a .json into ComfyUI to start generating.\n"
        msg += "➜ batch_size is already set to the requested count."
        messagebox.showinfo("Targeted workflows generated", msg)
        try:
            os.startfile(str(out_folder))
        except Exception:
            pass

    def _generate_subject_masks(self):
        """Genere des masques sujet (alpha BriaRMBG) a cote de chaque image viable.
        Format OneTrainer : <image>-masklabel.png noir/blanc."""
        data = getattr(self, "_last_analysis_data", None)
        if not data:
            return

        # Popup de config
        dlg = tk.Toplevel(self.root)
        dlg.title("Generate subject masks")
        dlg.configure(bg=BG)
        dlg.geometry("520x340")
        dlg.transient(self.root)
        dlg.grab_set()

        Label(dlg, text="🎭 Generate subject masks (OneTrainer)",
              font=FONT_H1, fg=ACCENT, bg=BG).pack(anchor="w", padx=20, pady=(15, 4))
        Label(dlg,
              text="Generates <image>-masklabel.png next to each viable photo.\n"
                   "OneTrainer focuses the loss on the subject (helps with varied/busy backgrounds).",
              font=FONT_SMALL, fg=TEXT_DIM, bg=BG, justify="left",
              wraplength=480).pack(anchor="w", padx=20, pady=(0, 12))

        # Threshold (binarisation)
        thresh_var = tk.DoubleVar(value=0.5)
        thresh_enabled = tk.BooleanVar(value=True)

        tk.Checkbutton(dlg, text="Binarize (recommended for OneTrainer: pure white subject, pure black background)",
                        variable=thresh_enabled, font=FONT_BODY, fg=TEXT, bg=BG,
                        selectcolor=CARD, activebackground=BG,
                        activeforeground=TEXT).pack(anchor="w", padx=20, pady=4)

        Label(dlg, text="Binarization threshold (0.3-0.7):",
              font=FONT_SMALL, fg=TEXT_DIM, bg=BG).pack(anchor="w", padx=20, pady=(8, 0))
        tk.Scale(dlg, from_=0.1, to=0.9, resolution=0.05,
                  orient="horizontal", variable=thresh_var,
                  bg=CARD, fg=TEXT, troughcolor=BG2,
                  highlightthickness=0, length=400).pack(anchor="w", padx=20)

        # Viable only
        viable_var = tk.BooleanVar(value=True)
        tk.Checkbutton(dlg, text="Viable/borderline photos only",
                        variable=viable_var, font=FONT_BODY, fg=TEXT, bg=BG,
                        selectcolor=CARD, activebackground=BG,
                        activeforeground=TEXT).pack(anchor="w", padx=20, pady=6)

        # Boutons
        btn_row = Frame(dlg, bg=BG)
        btn_row.pack(side="bottom", fill="x", padx=20, pady=15)

        def go():
            th = thresh_var.get() if thresh_enabled.get() else None
            viable_only = viable_var.get()
            dlg.destroy()
            self._launch_mask_generation(data, th, viable_only)

        Button(btn_row, text="Cancel", font=FONT_BODY, bg=CARD_HI, fg=TEXT,
               relief="flat", padx=20, pady=8, command=dlg.destroy).pack(side="right", padx=4)
        Button(btn_row, text="🚀 Generate", font=FONT_BODY, bg=ACCENT2, fg=BG,
               relief="flat", padx=20, pady=8, command=go).pack(side="right", padx=4)

    def _launch_mask_generation(self, data, threshold, viable_only):
        """Lance la generation en subprocess (besoin de torch + briarmbg = ComfyUI-future Python)."""
        # Liste des images cibles
        if viable_only:
            names = [img.get("name") for img in data.get("images", [])
                     if img.get("lora_viable") in ("yes", "borderline") and img.get("name")]
        else:
            names = [img.get("name") for img in data.get("images", []) if img.get("name")]
        if not names:
            messagebox.showinfo("Nothing to do", "No photo to process.")
            return

        folder = self.analyzer_path.get()
        self.status_var.set("Generating masks...")
        self.analyzer_mask_btn.config(state="disabled", text="🎭 Generating...")

        def worker():
            import time as _time
            script = str(Path(__file__).parent / "mask_generator_local.py")
            try:
                # On invoque le module via -c pour passer la liste de noms
                # mais le plus simple : on fait un petit driver inline
                import tempfile
                # Driver script avec args
                driver = (
                    "import sys, json\n"
                    f"sys.path.insert(0, r'{Path(__file__).parent}')\n"
                    "from mask_generator_local import generate_masks_for_folder\n"
                    "data = json.loads(sys.stdin.read())\n"
                    "result = generate_masks_for_folder(\n"
                    "    folder=data['folder'],\n"
                    "    viable_names=data['names'],\n"
                    "    threshold=data['threshold'],\n"
                    "    progress_cb=lambda c, t, n: print(f'PROGRESS {c}/{t} {n}', file=sys.stderr, flush=True)\n"
                    ")\n"
                    "print(json.dumps(result))\n"
                )
                payload = json.dumps({
                    "folder": folder,
                    "names": names,
                    "threshold": threshold,
                })

                proc = subprocess.Popen(
                    [self.comfyui_py, "-c", driver],
                    stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE, text=True, encoding="utf-8",
                )

                def read_stderr():
                    for line in iter(proc.stderr.readline, ""):
                        ln = line.strip()
                        if ln.startswith("PROGRESS "):
                            try:
                                parts = ln.split(" ", 2)
                                cur, tot = parts[1].split("/")
                                fname = parts[2] if len(parts) > 2 else ""
                                self.root.after(0, lambda c=cur, t=tot, n=fname:
                                    self.status_var.set(f"Mask {c}/{t} — {n[:40]}"))
                            except Exception:
                                pass
                        elif ln.startswith("STEP "):
                            self.root.after(0, lambda m=ln[5:]:
                                self.status_var.set(f"⚙ {m}"))

                t = threading.Thread(target=read_stderr, daemon=True)
                t.start()

                stdout, _ = proc.communicate(input=payload, timeout=900)
                result = json.loads(stdout.strip()) if stdout.strip() else {"errors": ["empty output"]}
                self.root.after(0, lambda r=result: self._on_mask_done(r))
            except Exception as e:
                import traceback
                err = f"{e}\n\n{traceback.format_exc()[-500:]}"
                self.root.after(0, lambda e=err: messagebox.showerror("Mask error", e))
                self.root.after(0, lambda: self.analyzer_mask_btn.config(
                    state="normal", text="🎭 Subject masks (retry)"))

        threading.Thread(target=worker, daemon=True).start()

    def _on_mask_done(self, result):
        written = result.get("written", 0)
        skipped = result.get("skipped", 0)
        errs = result.get("errors", [])
        total = result.get("total", written + skipped)
        msg = (f"✅ {written} mask(s) generated\n"
               f"⏭ {skipped} already existing\n"
               f"📁 Format: <image>-masklabel.png next to the photos\n\n"
               f"➜ Load the dataset in OneTrainer\n"
               f"➜ Concepts > Image augmentations > check \"masked training\"\n"
               f"➜ The LoRA will ignore the background during training (quality gain)")
        if errs:
            msg += f"\n\n⚠️ {len(errs)} error(s):\n" + "\n".join(errs[:3])
        messagebox.showinfo("Masks generated", msg)
        self.status_var.set(f"Masks: {written}/{total} generated")
        self.analyzer_mask_btn.config(
            state="normal", bg=ACCENT2, fg=BG,
            text=f"🎭 Subject masks ({written} OK)"
        )

    def _move_blurry_to_upscale(self):
        """Deplace les photos floues mais recuperables dans _a_upscaler/ avec un README."""
        data = getattr(self, "_last_analysis_data", None)
        if not data:
            return
        names = data.get("summary", {}).get("blurry_recoverable", []) or []
        if not names:
            messagebox.showinfo("Nothing to do", "No recoverable blurry photo.")
            return

        # Recupere les paths complets
        paths_by_name = {img["name"]: img["path"] for img in data.get("images", [])}
        to_move = [paths_by_name[n] for n in names if n in paths_by_name and Path(paths_by_name[n]).exists()]
        if not to_move:
            messagebox.showinfo("Nothing to do", "Photos not found (already moved?)")
            return

        source_folder = Path(self.analyzer_path.get())
        upscale_folder = source_folder / "_a_upscaler"

        if not messagebox.askyesno(
            "Move to upscale",
            f"Move {len(to_move)} blurry photo(s) to:\n{upscale_folder}\n\n"
            f"A README explaining how to upscale them in ComfyUI (SUPIR / UltraSharp) "
            f"will be created in the folder. Continue?"
        ):
            return

        upscale_folder.mkdir(exist_ok=True)
        moved = 0
        for src in to_move:
            try:
                src_p = Path(src)
                dst = upscale_folder / src_p.name
                if dst.exists():
                    dst = upscale_folder / f"{src_p.stem}_{moved}{src_p.suffix}"
                shutil.move(str(src_p), str(dst))
                # Deplace aussi le .txt caption s'il existe
                txt_src = src_p.with_suffix(".txt")
                if txt_src.exists():
                    try:
                        shutil.move(str(txt_src), str(dst.with_suffix(".txt")))
                    except Exception:
                        pass
                moved += 1
            except Exception as e:
                print(f"Move fail: {e}")

        # Ecrit le README
        readme_path = upscale_folder / "README.txt"
        readme_path.write_text(
            "BLURRY BUT RECOVERABLE PHOTOS (sharpness 50-100)\n"
            "=" * 60 + "\n\n"
            f"Generated on: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n"
            f"Count: {moved} photo(s)\n\n"
            "HOW TO SAVE THEM\n"
            "--------------------\n\n"
            "Option 1: SUPIR (best for faces)\n"
            "  1. Launch ComfyUI (via AI Launcher)\n"
            "  2. Load a SUPIR workflow (custom_nodes/ComfyUI-SUPIR)\n"
            "  3. LoadImage -> SUPIR Upscale (denoise ~0.3-0.4 to not change too much)\n"
            "  4. Save Image -> put back into the dataset after checking it\n\n"
            "Option 2: UltraSharp (fast, generic)\n"
            "  1. ComfyUI -> Load image -> Upscale Image (using Model)\n"
            "  2. Model: 4x-UltraSharp.pth (if installed in models/upscale_models/)\n"
            "  3. Resize to 1024x1024 if needed\n\n"
            "Option 3: Re-render with InstantID\n"
            "  If the photo has a clear face but average sharpness,\n"
            "  redo it via workflow 02 (InstantID dataset) with the same seed.\n\n"
            "AFTER UPSCALING\n"
            "-------------\n"
            "1. Check visually (no artifacts on the face)\n"
            "2. Put the good files back in the parent dataset folder\n"
            "3. Re-run the analysis (the cache will recognize the new versions)\n",
            encoding="utf-8"
        )

        messagebox.showinfo("Done",
                             f"✅ {moved} photo(s) moved to:\n{upscale_folder}\n\n"
                             f"A README.txt explains how to upscale them.")
        self.status_var.set(f"Moved {moved} photos to _a_upscaler/")
        self.analyzer_upscale_btn.config(state="disabled", bg=CARD_HI, fg=TEXT_DIM,
                                          text="🔧 Re-run the analysis")

    def _prepare_kohya(self):
        """Dialog de selection target + preparation LoRA multi-format."""
        data = getattr(self, "_last_analysis_data", None)
        if not data:
            return

        try:
            sys.path.insert(0, str(Path(__file__).parent))
            import lora_prep
        except Exception as e:
            messagebox.showerror("Error", f"lora_prep module not found:\n{e}")
            return

        # === Popup de selection target + nom + captioner ===
        dlg = tk.Toplevel(self.root)
        dlg.title("Prepare LoRA dataset")
        dlg.configure(bg=BG)
        dlg.geometry("640x640")
        dlg.transient(self.root)
        dlg.grab_set()

        Label(dlg, text="🧬 Prepare a LoRA dataset",
              font=FONT_H1, fg=ACCENT, bg=BG).pack(anchor="w", padx=20, pady=(15, 4))
        Label(dlg, text="Crop, resolution and config format adapt to the chosen target.",
              font=FONT_SMALL, fg=TEXT_DIM, bg=BG).pack(anchor="w", padx=20, pady=(0, 12))

        # Trigger word
        Label(dlg, text="Persona name (trigger word):",
              font=FONT_BODY, fg=TEXT, bg=BG).pack(anchor="w", padx=20)
        persona_var = StringVar(value="persona")
        persona_entry = tk.Entry(dlg, textvariable=persona_var, font=FONT_MONO,
                                  bg=CARD, fg=TEXT, insertbackground=TEXT, relief="flat")
        persona_entry.pack(fill="x", padx=20, ipady=5, pady=(2, 10))

        # Target (groupé par catégorie)
        Label(dlg, text="Trainer / target model:",
              font=FONT_BODY, fg=TEXT, bg=BG).pack(anchor="w", padx=20)
        target_var = StringVar(value="sdxl_kohya")
        # Construit la liste groupee : [--- Photo réaliste ---, sdxl_kohya, ...]
        targets_by_cat = {}
        for key, _ in lora_prep.list_targets():
            cat = lora_prep.get_target_category(key)
            targets_by_cat.setdefault(cat, []).append(key)
        cat_order = getattr(lora_prep, "CATEGORY_ORDER", ["image_photo", "image_anime", "video"])
        combo_values = []
        for cat in cat_order:
            if cat in targets_by_cat:
                combo_values.append(f"━━ {lora_prep.TARGET_CATEGORIES.get(cat, cat)} ━━")
                combo_values.extend(targets_by_cat[cat])
        # Reste (catégories inattendues)
        for cat, keys in targets_by_cat.items():
            if cat not in cat_order:
                combo_values.append(f"━━ {lora_prep.TARGET_CATEGORIES.get(cat, cat)} ━━")
                combo_values.extend(keys)
        target_combo = ttk.Combobox(dlg, textvariable=target_var, state="readonly",
                                     values=combo_values, font=FONT_BODY, height=20)
        target_combo.pack(fill="x", padx=20, pady=(2, 4))
        target_info = Label(dlg, text="", font=FONT_SMALL, fg=TEXT_DIM, bg=BG,
                             justify="left", wraplength=580)
        target_info.pack(anchor="w", padx=20, pady=(0, 4))
        # Modeles a la mode SANS export possible depuis des photos (evite de chercher en vain)
        not_exp = getattr(lora_prep, "NOT_EXPORTABLE", {})
        if not_exp:
            Label(dlg, text="No export available: " + ", ".join(not_exp) +
                            "  (details in each export's README)",
                  font=FONT_SMALL, fg=TEXT_DIM, bg=BG, justify="left",
                  wraplength=580).pack(anchor="w", padx=20, pady=(0, 12))

        def update_target_info(*_):
            sel = target_var.get()
            # Refuse les separateurs "━━ ... ━━"
            if sel.startswith("━━"):
                target_var.set("sdxl_kohya")
                sel = "sdxl_kohya"
            cfg = lora_prep.TARGETS.get(sel, {})
            label = cfg.get("label", "?")
            res = cfg.get("resolutions", [])
            cap = cfg.get("captioner", "?")
            q_prefix = cfg.get("quality_prefix")
            note = ""
            if cap == "natural":
                note = "  ⭐ JoyCaption recommended (re-run the analysis in 'joycaption' or 'all' mode)."
            if q_prefix:
                note += f"\n   🏷 Quality tags auto-added: “{q_prefix}”"
            if cfg.get("notes"):
                note += f"\n   ℹ {cfg['notes']}"
            target_info.config(
                text=(f"→ {label}\n"
                      f"   Resolution(s): {res}   |   Recommended captioner: {cap}\n"
                      f"   Doc: {cfg.get('trainer_doc_url', '')}{note}")
            )
        target_combo.bind("<<ComboboxSelected>>", update_target_info)
        update_target_info()

        # Viable only
        viable_var = tk.BooleanVar(value=True)
        tk.Checkbutton(dlg, text="Only include viable photos (recommended)",
                        variable=viable_var, font=FONT_BODY, fg=TEXT, bg=BG,
                        selectcolor=CARD, activebackground=BG,
                        activeforeground=TEXT).pack(anchor="w", padx=20, pady=4)

        # Masques sujet (Lot D)
        masks_var = tk.BooleanVar(value=False)
        tk.Checkbutton(dlg,
                        text="🎭 Also generate subject masks (OneTrainer masked training)",
                        variable=masks_var, font=FONT_BODY, fg=TEXT, bg=BG,
                        selectcolor=CARD, activebackground=BG,
                        activeforeground=TEXT).pack(anchor="w", padx=20, pady=4)
        Label(dlg, text="   (Recommended for OneTrainer — black background = ignored during training)",
              font=FONT_SMALL, fg=TEXT_DIM, bg=BG).pack(anchor="w", padx=20)

        # Overwrite existing captions (si on re-lance la prep sur le meme dossier)
        overwrite_captions_var = tk.BooleanVar(value=False)
        tk.Checkbutton(dlg, text="Overwrite existing captions",
                        variable=overwrite_captions_var, font=FONT_BODY, fg=TEXT, bg=BG,
                        selectcolor=CARD, activebackground=BG,
                        activeforeground=TEXT).pack(anchor="w", padx=20, pady=4)

        # Boutons
        btn_row = Frame(dlg, bg=BG)
        btn_row.pack(side="bottom", fill="x", padx=20, pady=15)

        def go():
            persona = persona_var.get().strip().replace(" ", "_")
            if not persona:
                messagebox.showwarning("Missing", "Provide a trigger word.", parent=dlg)
                return
            target = target_var.get()
            viable_only = viable_var.get()
            with_masks = masks_var.get()
            overwrite_captions = overwrite_captions_var.get()
            dlg.destroy()
            self._launch_lora_prep(data, persona, target, viable_only, with_masks,
                                    overwrite_captions)

        Button(btn_row, text="Cancel", font=FONT_BODY, bg=CARD_HI, fg=TEXT,
               relief="flat", padx=20, pady=8, command=dlg.destroy).pack(side="right", padx=4)
        Button(btn_row, text="🚀 Prepare", font=FONT_BODY, bg=GREEN, fg=BG,
               relief="flat", padx=20, pady=8, command=go).pack(side="right", padx=4)

    def _launch_lora_prep(self, data, persona, target, viable_only, with_masks=False,
                          overwrite_captions=False):
        import lora_prep
        cfg = lora_prep.TARGETS[target]

        # Dossier de sortie
        folder_prefix = "kohya" if "kohya" in target else target.split("_")[0]
        default_out = Path(self.analyzer_path.get()).parent / f"{folder_prefix}_{persona}"
        out = filedialog.askdirectory(
            initialdir=str(default_out.parent),
            title=f"Folder to create {folder_prefix}_{persona}/ in (cancel = default)"
        )
        out_folder = Path(out) / f"{folder_prefix}_{persona}" if out else default_out

        self.status_var.set(f"Preparing {cfg['label']}...")
        self.analyzer_kohya_btn.config(state="disabled", text="🧬 Preparing...")

        def progress_cb(cur, tot, name):
            self.root.after(0, lambda c=cur, t=tot, n=name:
                self.status_var.set(f"Prep: {c}/{t} — {n}"))

        def worker():
            try:
                result = lora_prep.prepare_lora_folder(
                    analysis_data=data,
                    source_folder=self.analyzer_path.get(),
                    output_folder=out_folder,
                    persona_name=persona,
                    target=target,
                    viable_only=viable_only,
                    progress_cb=progress_cb,
                    overwrite_captions=overwrite_captions,
                )
                # Si demande, genere aussi les masques sujet dans le dossier final
                if with_masks:
                    self.root.after(0, lambda: self.status_var.set("Generating subject masks…"))
                    images_subfolder = lora_prep.TARGETS[target].get("folder_naming") == "kohya"
                    rep = lora_prep.TARGETS[target].get("default_repeats") or 10
                    masks_target = out_folder / (f"{rep}_{persona}" if images_subfolder else "images")
                    try:
                        # Driver inline
                        driver = (
                            "import sys, json\n"
                            f"sys.path.insert(0, r'{Path(__file__).parent}')\n"
                            "from mask_generator_local import generate_masks_for_folder\n"
                            "data = json.loads(sys.stdin.read())\n"
                            "r = generate_masks_for_folder(folder=data['folder'], threshold=0.5,\n"
                            "    progress_cb=lambda c, t, n: print(f'PROGRESS {c}/{t} {n}', file=sys.stderr, flush=True))\n"
                            "print(json.dumps(r))\n"
                        )
                        payload = json.dumps({"folder": str(masks_target)})
                        proc = subprocess.Popen(
                            [self.comfyui_py, "-c", driver],
                            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, text=True, encoding="utf-8",
                        )
                        stdout, _ = proc.communicate(input=payload, timeout=600)
                        mask_result = json.loads(stdout.strip()) if stdout.strip() else {}
                        result["masks_generated"] = mask_result.get("written", 0)
                    except Exception as e:
                        result["masks_error"] = str(e)[:200]
                self.root.after(0, lambda r=result: self._on_kohya_done(r, out_folder))
            except Exception as e:
                import traceback
                err = f"{e}\n\n{traceback.format_exc()[-500:]}"
                self.root.after(0, lambda e=err: messagebox.showerror("Prep error", e))
                self.root.after(0, lambda: self.analyzer_kohya_btn.config(
                    state="normal", text="🧬 Prepare LoRA (retry)"))

        threading.Thread(target=worker, daemon=True).start()

    def _on_kohya_done(self, result, out_folder):
        written = result.get("written", 0)
        skipped = result.get("skipped", 0)
        errs = result.get("errors", [])
        tgt = result.get("target", "?")
        cfg_path = result.get("config_path")
        msg = (f"✅ {written} photo(s) prepared (crop + captions)\n"
               f"⏭ {skipped} excluded (not viable)\n\n"
               f"📁 {out_folder}\n"
               f"🎯 Target: {tgt}\n")
        if cfg_path:
            msg += f"⚙ Config: {Path(cfg_path).name}\n"
        masks_n = result.get("masks_generated")
        if masks_n is not None:
            msg += f"🎭 Subject masks: {masks_n} generated\n"
        if result.get("masks_error"):
            msg += f"⚠️ Mask error: {result['masks_error'][:100]}\n"
        msg += "\nRead README.txt for launch instructions."
        if errs:
            msg += f"\n\n⚠️ {len(errs)} error(s):\n" + "\n".join(errs[:3])
        messagebox.showinfo("LoRA dataset ready", msg)
        self.status_var.set(f"Prep done: {written} photos in {out_folder.name}/")
        self.analyzer_kohya_btn.config(
            state="normal", bg=GREEN, fg=BG,
            text=f"🧬 Prepare LoRA ({written} OK)"
        )
        # Enchaine : le dossier prepare est pre-rempli dans l'onglet Creer LoRA
        if hasattr(self, "train_folder"):
            self.train_folder.set(str(out_folder))
            self._train_load_folder()
        # Ouvre le dossier dans l'explorer
        try:
            os.startfile(str(out_folder))
        except Exception:
            pass

    def _move_rejected_photos(self):
        """Deplace toutes les photos marquees lora_viable='no' dans un sous-dossier."""
        data = getattr(self, "_last_analysis_data", None)
        if not data:
            return
        rejected = [img["path"] for img in data.get("images", [])
                    if img.get("lora_viable") == "no" and Path(img["path"]).exists()]
        if not rejected:
            messagebox.showinfo("Nothing to do", "No photo marked to discard.")
            return

        source_folder = Path(self.analyzer_path.get())
        reject_folder = source_folder / "_rejected"

        if not messagebox.askyesno(
            "Confirm move",
            f"Move {len(rejected)} photo(s) to:\n{reject_folder}\n\n"
            f"Files will be MOVED (not copied). Continue?"
        ):
            return

        reject_folder.mkdir(exist_ok=True)
        moved = 0
        errors = []
        for src in rejected:
            try:
                src_p = Path(src)
                dst = reject_folder / src_p.name
                # Si conflit, ajoute un suffixe
                if dst.exists():
                    dst = reject_folder / f"{src_p.stem}_{moved}{src_p.suffix}"
                shutil.move(str(src_p), str(dst))
                moved += 1
            except Exception as e:
                errors.append(f"{Path(src).name}: {e}")

        msg = f"✅ {moved} photo(s) moved to:\n{reject_folder}"
        if errors:
            msg += f"\n\n⚠️ {len(errors)} error(s):\n" + "\n".join(errors[:5])
        messagebox.showinfo("Move done", msg)
        self.status_var.set(f"Moved: {moved} photo(s) to _rejected/")
        self.analyzer_move_btn.config(state="disabled", bg=CARD_HI, fg=TEXT_DIM,
                                      text="🗑 Re-run the analysis")

    def _populate_results_table(self, data):
        """Remplit le résumé du bas (NOTE globale + stats + recommandations) et
        le tableau détaillé. Appelé à la fin de chaque analyse."""
        if "error" in data:
            self.analyzer_summary.config(text=f"❌ {data['error']}", fg=RED)
            return

        s = data.get("summary", {})
        recos = data.get("recommendations", [])
        verdict = s.get("verdict") or {}
        grade = verdict.get("grade", "?")
        grade_desc = verdict.get("grade_desc", "")
        body_coh = s.get('overall_body_coherence')
        dup_count = s.get('duplicates_count', 0)
        cap_count = s.get('captions_written', 0)
        ai_count = s.get('ai_classifier_count', 0)
        art_high = s.get('artifacts_high_count', 0)
        extra = ""
        if dup_count > 0:
            extra += f"  |  🔁 {dup_count} duplicates"
        if cap_count > 0:
            extra += f"  |  🏷 {cap_count} captions"
        if ai_count > 0:
            extra += f"  |  🤖 {ai_count} AI-detected"
        if art_high > 0:
            extra += f"  |  ❌ {art_high} severe artifacts"
        summary_text = (
            f"🏆 GRADE: {grade}  ({grade_desc})\n"
            f"📊 {s.get('total_images', 0)} images  |  "
            f"✅ {s.get('lora_viable', 0)} viable  |  "
            f"⚠️ {s.get('lora_borderline', 0)} borderline  |  "
            f"❌ {s.get('lora_unusable', 0)} to discard{extra}\n"
            f"Face coherence: {s.get('overall_face_coherence', 'N/A')}  |  "
            f"Body coherence: {body_coh if body_coh is not None else 'N/A'}\n\n"
            + "\n".join(recos)
        )
        self.analyzer_summary.config(text=summary_text, fg=TEXT)

        # Remplir le tableau
        for img in data.get("images", []):
            name = img.get("name", "?")
            res = f"{img.get('width', '?')}x{img.get('height', '?')}"
            sharp = f"{img.get('sharpness', 0):.0f}" if img.get("sharpness") is not None else "-"
            faces = str(img.get("face_count", "?"))
            prop = f"{img.get('face_proportion', 0):.1f}%" if img.get("face_proportion") else "-"
            yaw_val = img.get("face_yaw")
            yaw = f"{yaw_val:+.0f}" if yaw_val is not None else "-"
            expr = img.get("expression") or "-"
            sim_avg = img.get("face_similarity_avg")
            body_avg = img.get("body_similarity_avg")
            qual = img.get("quality_verdict", "-")
            view_type = img.get("view_type", "both")

            sim = f"{sim_avg:.2f}" if sim_avg is not None else "-"
            body = f"{body_avg:.2f}" if body_avg is not None else "NA"

            # === Tag = verdict viabilite LoRA en priorite ===
            viable = img.get("lora_viable", "yes")
            reason = img.get("lora_reason", "OK for LoRA")

            if viable == "no":
                tag = "err"
                lora_text = f"❌  {reason}"
            elif viable == "borderline":
                tag = "warn"
                lora_text = f"⚠  {reason}"
            else:
                tag = "ok"
                lora_text = f"✓  {reason}"

            self.analyzer_tree.insert("", "end", text=f"  {name}",
                                       values=(res, sharp, faces, prop, yaw, expr, sim, body, qual, lora_text),
                                       tags=(tag,))

    # ============================================================
    # Config helpers
    # ============================================================
    def _pick_folder(self, var):
        d = filedialog.askdirectory(initialdir=var.get())
        if d:
            var.set(d.replace("/", "\\"))

    def _pick_file(self, var):
        cur = var.get()
        initdir = str(Path(cur).parent) if cur and Path(cur).parent.exists() else None
        f = filedialog.askopenfilename(
            initialdir=initdir,
            title="Choose ComfyUI's python.exe",
            filetypes=[("Python executable", "python*.exe"), ("All", "*.*")],
        )
        if f:
            var.set(f.replace("/", "\\"))

    def _load_preview_image(self, path, max_size=200):
        """Charge une image en PhotoImage Tk en gardant le ratio. Retourne None si echec."""
        if not _HAS_PIL or not path or not Path(path).is_file():
            return None
        try:
            img = PILImage.open(path)
            img.thumbnail((max_size, max_size), PILImage.LANCZOS)
            return PILImageTk.PhotoImage(img)
        except Exception:
            return None

    def _update_preview_current(self, path):
        if not _HAS_PIL:
            return
        photo = self._load_preview_image(path, max_size=200)
        if photo is None:
            return
        # Garde une ref pour eviter le GC
        self._preview_current_photo = photo
        self.preview_current_label.config(image=photo, width=200, height=200)
        self.preview_current_name.config(text=Path(path).name)

    def _update_preview_ref(self, path):
        if not _HAS_PIL:
            return
        if not path:
            # Vide
            self.preview_ref_label.config(image="", width=200, height=200)
            self.preview_ref_name.config(text="(none)")
            self._preview_ref_photo = None
            return
        # Si c'est un DOSSIER : montre la 1re image + le nombre de réfs
        p = Path(path)
        label_txt = p.name
        thumb_path = path
        if p.is_dir():
            exts = (".png", ".jpg", ".jpeg", ".webp")
            imgs = sorted([f for f in p.iterdir()
                           if f.is_file() and f.suffix.lower() in exts])
            if imgs:
                thumb_path = str(imgs[0])
                label_txt = f"📁 {p.name} ({len(imgs)} refs)"
            else:
                self.preview_ref_name.config(text=f"📁 {p.name} (empty ⚠️)")
                self.preview_ref_label.config(image="", width=200, height=200)
                self._preview_ref_photo = None
                return
        photo = self._load_preview_image(thumb_path, max_size=200)
        if photo is None:
            self.preview_ref_name.config(text=f"⚠️ {label_txt}")
            return
        self._preview_ref_photo = photo
        self.preview_ref_label.config(image=photo, width=200, height=200)
        self.preview_ref_name.config(text=label_txt)

    def _tree_item_to_path(self, item_id):
        """Retrouve le path d'une ligne du tableau via son nom + dataset folder."""
        name = self.analyzer_tree.item(item_id, "text").strip()
        data = getattr(self, "_last_analysis_data", None)
        if not data:
            return None
        for img in data.get("images", []):
            if img.get("name") == name:
                return img.get("path")
        return None

    def _on_tree_select(self, event=None):
        """Clic simple sur une ligne -> met a jour le preview courant + verdict."""
        sel = self.analyzer_tree.selection()
        if not sel:
            return
        item_id = sel[0]
        path = self._tree_item_to_path(item_id)
        if not path:
            return
        # Met a jour le mini-verdict avec les infos completes de l'image
        data = self._last_analysis_data
        name = self.analyzer_tree.item(item_id, "text").strip()
        for img in data.get("images", []):
            if img.get("name") == name:
                mini = {
                    "name": img.get("name"),
                    "face_count": img.get("face_count"),
                    "face_proportion": img.get("face_proportion"),
                    "face_yaw": img.get("face_yaw"),
                    "sharpness": img.get("sharpness"),
                    "expression": img.get("expression"),
                    "ref_match": img.get("ref_match"),
                    "face_similarity_to_ref": img.get("face_similarity_to_ref"),
                    "quality_verdict": img.get("quality_verdict"),
                    "wd14_tags": (img.get("wd14_tags") or "")[:300],
                }
                self._update_preview_verdict(mini)
                break
        self._update_preview_current(path)

    def _on_tree_double_click(self, event=None):
        """Double-clic -> popup avec l'image en grand + tous les details."""
        sel = self.analyzer_tree.selection()
        if not sel:
            return
        item_id = sel[0]
        path = self._tree_item_to_path(item_id)
        if not path:
            return
        self._show_image_popup(path)

    def _show_image_popup(self, image_path):
        """Affiche une popup avec l'image en grand + toutes les metadonnees."""
        if not _HAS_PIL or not Path(image_path).is_file():
            return
        data = self._last_analysis_data or {}
        name = Path(image_path).name
        img_data = next((i for i in data.get("images", []) if i.get("name") == name), {})

        popup = tk.Toplevel(self.root)
        popup.title(f"📷 {name}")
        popup.configure(bg=BG)
        popup.geometry("1200x800")

        # Image a gauche
        left = Frame(popup, bg=BG, padx=12, pady=12)
        left.pack(side="left", fill="both", expand=True)
        try:
            pil = PILImage.open(image_path)
            pil.thumbnail((900, 750), PILImage.LANCZOS)
            photo = PILImageTk.PhotoImage(pil)
            lbl = Label(left, image=photo, bg=BG)
            lbl.image = photo  # garde la ref
            lbl.pack()
        except Exception as e:
            Label(left, text=f"Display error: {e}", fg=RED, bg=BG).pack()

        # Details a droite
        right = Frame(popup, bg=CARD, padx=14, pady=14, width=350)
        right.pack(side="right", fill="y")
        right.pack_propagate(False)

        Label(right, text=name, font=FONT_H1, fg=ACCENT, bg=CARD,
              wraplength=320, justify="left").pack(anchor="w", pady=(0, 8))

        def kv(label, val, color=TEXT):
            if val is None or val == "":
                return
            row = Frame(right, bg=CARD)
            row.pack(fill="x", pady=2)
            Label(row, text=f"{label}:", font=FONT_SMALL, fg=TEXT_DIM, bg=CARD,
                  width=18, anchor="w").pack(side="left")
            Label(row, text=str(val), font=FONT_BODY, fg=color, bg=CARD,
                  anchor="w", wraplength=200, justify="left").pack(side="left", fill="x", expand=True)

        viable = img_data.get("lora_viable", "?")
        v_color = {"yes": GREEN, "borderline": YELLOW, "no": RED}.get(viable, TEXT)
        kv("LoRA viability", viable.upper(), v_color)
        kv("Reason", img_data.get("lora_reason"))
        kv("", "")
        kv("Resolution", f"{img_data.get('width')}x{img_data.get('height')}")
        kv("Sharpness", img_data.get("sharpness"))
        kv("Brightness", img_data.get("brightness"))
        kv("Contrast", img_data.get("contrast"))
        kv("Quality", img_data.get("quality_verdict"))
        kv("", "")
        kv("Faces", img_data.get("face_count"))
        kv("% of frame", f"{img_data.get('face_proportion', 0):.1f}%" if img_data.get("face_proportion") else None)
        kv("Yaw (pose)", f"{img_data.get('face_yaw'):+.1f}°" if img_data.get("face_yaw") is not None else None)
        kv("Shot type", img_data.get("view_type"))
        kv("Expression", img_data.get("expression"))
        kv("Avg face sim", img_data.get("face_similarity_avg"))
        kv("Avg body sim", img_data.get("body_similarity_avg"))
        rm = img_data.get("ref_match")
        rm_color = {"OK": GREEN, "doubtful": YELLOW, "wrong person": RED}.get(rm, TEXT)
        kv("Reference match", f"{rm} (sim {img_data.get('face_similarity_to_ref')})" if rm else None, rm_color)
        if img_data.get("duplicate_of"):
            kv("Duplicate of", img_data["duplicate_of"], RED)
        if img_data.get("upscale_candidate"):
            kv("Upscale possible", "✓ (SUPIR/UltraSharp)", YELLOW)
        # Lot B : detection IA + artefacts
        ai_s = img_data.get("ai_score")
        if ai_s is not None:
            ai_color = RED if ai_s > 0.7 else (YELLOW if ai_s > 0.4 else GREEN)
            kv("AI-generated score", f"{ai_s:.2f} ({img_data.get('ai_label', '?')})", ai_color)
        art_s = img_data.get("artifacts_severity")
        if art_s and art_s != "none":
            art_color = {"high": RED, "medium": YELLOW, "low": TEXT}.get(art_s, TEXT)
            cats = img_data.get("artifacts_categories") or []
            kv("AI artifacts", f"{art_s.upper()} ({', '.join(cats)})", art_color)
        md_src = img_data.get("ai_metadata_sources")
        if md_src:
            kv("AI metadata", f"{', '.join(md_src)} ({img_data.get('ai_metadata_confidence', '?')})", TEXT_DIM)

        # ===== Captions EDITABLES (Lot D — éditeur inline) =====
        # Chaque caption a son propre Text + bouton Sauver qui réécrit le .txt
        for label, key, sidecar_ext, color in (
            ("🏷  WD14 tags",       "wd14_tags",       ".txt",     TEXT),
            ("🌿 Florence-2",       "natural_caption", ".nat.txt", TEXT_DIM),
            ("⭐ JoyCaption (2026)", "joycaption",      ".joy.txt", ACCENT),
        ):
            val = img_data.get(key)
            if not val:
                continue
            # Header avec label + bouton
            head = Frame(right, bg=CARD)
            head.pack(fill="x", pady=(10, 2))
            Label(head, text=label, font=FONT_SMALL, fg=color, bg=CARD,
                  anchor="w").pack(side="left")
            status_lbl = Label(head, text="", font=FONT_SMALL, fg=GREEN, bg=CARD)
            status_lbl.pack(side="right")

            # Zone editable
            t = Text(right, height=5, bg=BG, fg=TEXT, font=FONT_SMALL,
                     wrap="word", relief="flat", padx=6, pady=6,
                     insertbackground=TEXT)
            t.insert("1.0", val)
            t.pack(fill="x")

            # Bouton sauver
            def make_save_handler(text_widget=t, kk=key, ext=sidecar_ext,
                                   status_widget=status_lbl, img_name=name,
                                   img_path_str=str(image_path)):
                def save():
                    new_val = text_widget.get("1.0", "end").strip()
                    self._save_caption_edit(img_name, kk, ext, new_val, img_path_str)
                    status_widget.config(text="✅ saved", fg=GREEN)
                    # Reset le statut au bout de 2s
                    self.root.after(2000, lambda: status_widget.config(text=""))
                return save

            Button(right, text=f"💾 Save {sidecar_ext}", font=FONT_SMALL,
                   bg=CARD_HI, fg=TEXT, relief="flat", padx=8, pady=4,
                   cursor="hand2",
                   command=make_save_handler()).pack(anchor="e", pady=(2, 6))

        Button(right, text="Close (Esc)", font=FONT_BODY, bg=CARD_HI, fg=TEXT,
               relief="flat", padx=12, pady=6, command=popup.destroy).pack(pady=12)
        popup.bind("<Escape>", lambda e: popup.destroy())

    def _save_caption_edit(self, image_name, caption_key, sidecar_ext, new_value, image_path_str):
        """Sauve une caption editee : ecrit le .txt + maj cache + maj memoire."""
        image_path = Path(image_path_str)
        if not image_path.exists():
            messagebox.showwarning("Error", f"Image not found: {image_name}")
            return

        # 1) Reecrit le sidecar .txt / .nat.txt / .joy.txt
        sidecar = image_path.with_suffix(sidecar_ext)
        try:
            sidecar.write_text(new_value, encoding="utf-8")
        except Exception as e:
            messagebox.showerror("Error", f"Could not write {sidecar.name}:\n{e}")
            return

        # 2) Met a jour la donnee en memoire (pour les autres affichages)
        data = self._last_analysis_data
        if data:
            for img in data.get("images", []):
                if img.get("name") == image_name:
                    img[caption_key] = new_value
                    # Si on edite joycaption, met aussi a jour natural_caption
                    # (le fallback Flux/Wan utilise natural_caption)
                    if caption_key == "joycaption":
                        img["natural_caption"] = new_value
                    break

        # 3) Met a jour le cache pour que le prochain run ne reanalyse pas
        try:
            dataset_folder = Path(self.analyzer_path.get())
            cache_path = dataset_folder / ".analyzer_cache.json"
            if cache_path.is_file():
                cache = json.loads(cache_path.read_text(encoding="utf-8"))
                # Trouve l'entree par nom d'image
                for key, entry_data in cache.get("entries", {}).items():
                    if entry_data.get("entry", {}).get("name") == image_name:
                        entry_data["entry"][caption_key] = new_value
                        if caption_key == "joycaption":
                            entry_data["entry"]["natural_caption"] = new_value
                        break
                cache_path.write_text(json.dumps(cache, ensure_ascii=False, indent=1),
                                       encoding="utf-8")
        except Exception as e:
            print(f"Warning: could not update cache ({e})")

        self.status_var.set(f"Caption saved: {image_name} ({sidecar_ext})")

    def _update_preview_verdict(self, mini):
        """Affiche le mini-verdict de la derniere image analysee dans le panneau live."""
        if not _HAS_PIL:
            return
        lines = []
        # Visage
        fc = mini.get("face_count")
        if fc == 0:
            lines.append("👤 No face detected")
        elif fc == 1:
            prop = mini.get("face_proportion")
            yaw = mini.get("face_yaw")
            ystr = f", yaw {yaw:+.0f}°" if yaw is not None else ""
            pstr = f" ({prop:.1f}% of frame)" if prop else ""
            lines.append(f"👤 1 face{pstr}{ystr}")
        elif fc and fc > 1:
            lines.append(f"⚠️ {fc} faces detected")

        # Match a la reference
        sim_ref = mini.get("face_similarity_to_ref")
        rm = mini.get("ref_match")
        if rm is not None and sim_ref is not None:
            icon = {"OK": "✅", "doubtful": "⚠️", "wrong person": "❌"}.get(rm, "•")
            lines.append(f"{icon} Ref match: {rm} (sim {sim_ref:.2f})")

        # Qualite
        sharp = mini.get("sharpness")
        qv = mini.get("quality_verdict")
        if sharp is not None:
            sq = "✅" if sharp >= 200 else ("⚠️" if sharp >= 100 else "❌")
            lines.append(f"{sq} Sharpness {sharp:.0f}  →  {qv}")

        # Expression
        expr = mini.get("expression")
        if expr:
            lines.append(f"😶 Expression: {expr}")

        # Tags WD14
        tags = mini.get("wd14_tags")
        if tags:
            lines.append(f"🏷  {tags}")

        # JoyCaption (preferred quand disponible)
        joy = mini.get("joycaption")
        if joy:
            lines.append(f"⭐ {joy}")

        # Detection IA + artefacts (Lot B)
        ai_score = mini.get("ai_score")
        if ai_score is not None:
            icon = "🤖" if ai_score > 0.5 else "📷"
            lines.append(f"{icon} AI score: {ai_score:.2f} ({'AI-generated' if ai_score > 0.5 else 'photo'})")
        art_sev = mini.get("artifacts_severity")
        if art_sev and art_sev != "none":
            cats = mini.get("artifacts_categories") or []
            icon = {"high": "❌", "medium": "⚠️", "low": "💡"}.get(art_sev, "•")
            lines.append(f"{icon} Artifacts ({art_sev}): {', '.join(cats)}")
        md_sources = mini.get("ai_metadata_sources") or []
        if md_sources:
            lines.append(f"📋 AI metadata: {', '.join(md_sources)}")

        self.preview_verdict_text.config(text="\n".join(lines))

    def _pick_ref_image(self):
        # Demarre dans le dossier dataset si possible
        cur = self.analyzer_ref_path.get().strip()
        initdir = str(Path(cur).parent) if cur and Path(cur).exists() else self.analyzer_path.get()
        f = filedialog.askopenfilename(
            initialdir=initdir,
            title="Choose ONE reference photo (a clear face)",
            filetypes=[("Images", "*.png *.jpg *.jpeg *.webp"), ("All", "*.*")]
        )
        if f:
            self.analyzer_ref_path.set(f.replace("/", "\\"))
            self._update_preview_ref(f)

    def _pick_ref_folder(self):
        """Choisir un DOSSIER de références (plusieurs photos -> identité robuste)."""
        cur = self.analyzer_ref_path.get().strip()
        initdir = cur if cur and Path(cur).is_dir() else self.analyzer_path.get()
        d = filedialog.askdirectory(
            initialdir=initdir,
            title="Choose a folder of reference photos (2-5 photos of the person: face, 3/4, full body…)"
        )
        if d:
            self.analyzer_ref_path.set(d.replace("/", "\\"))
            self._update_preview_ref(d)

    def _save_cfg(self):
        for k, v in self.entries.items():
            self.cfg[k] = v.get()
        save_config(self.cfg)
        # Applique a chaud le nouveau chemin Python ComfyUI
        self.comfyui_py = self.cfg.get("comfyui_python") or COMFYUI_FUTURE_PY
        # Met a jour le dossier datasets par defaut dans l'analyseur (si vide)
        if hasattr(self, "analyzer_path") and self.cfg.get("datasets_dir"):
            if not self.analyzer_path.get().strip():
                self.analyzer_path.set(self.cfg["datasets_dir"])
        messagebox.showinfo("Saved", "Config saved.")

    def _reset_cfg(self):
        for k, v in DEFAULT_CONFIG.items():
            if k in self.entries:
                self.entries[k].set(v)


if __name__ == "__main__":
    cfg = load_config()
    # Pre-cree le dossier datasets par defaut s'il n'existe pas
    try:
        d = cfg.get("datasets_dir")
        if d:
            Path(d).mkdir(parents=True, exist_ok=True)
    except Exception:
        pass
    root = Tk()
    app = App(root)
    # Argument --tab <name> pour ouvrir directement sur un onglet
    if len(sys.argv) >= 3 and sys.argv[1] == "--tab":
        app.select_tab(sys.argv[2])
    root.mainloop()
