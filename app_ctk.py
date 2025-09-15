# -*- coding: utf-8 -*-
from __future__ import annotations
import os, io, time, threading, queue, json, hashlib
from datetime import datetime

import customtkinter as ctk
from PIL import Image, ImageTk, ImageDraw
import requests

# ====== CONFIG IMPORTS (your existing files) ======
from config import (
    CAP_LEFT, CAP_TOP, CAP_WIDTH, CAP_HEIGHT,
    OCR_LANG, OCR_OEM, OCR_PSM, TESSERACT_CMD,
    PROVIDER, MODEL, PROMPT, LLM_TEMP,
    DISCORD_WEBHOOK, LOG_DIR,
    OPENAI_API_KEY, ANTHROPIC_API_KEY, GEMINI_API_KEY,
    PROMPTS as CONFIG_PROMPTS, PROVIDERS as CONFIG_PROVIDERS
)
from llm_client import LLMClient
    # must provide .complete(text, prompt, temperature)
from ocr import set_tesseract_cmd, grab_image, ocr_image

try:
    import keyboard as kb  # global hotkeys for hide/show
except Exception:
    kb = None

# ====== FULL MATTE BLACK PALETTE ======
K_BG        = "#090909"   # global background
K_BG_ALT    = "#0B0B0C"
K_PANEL     = "#0D0E11"   # panels
K_PANEL2    = "#111318"   # inner panels
K_BORDER    = "#22242A"
K_FG        = "#E9ECFF"   # text
K_MUTED     = "#9AA2C0"   # secondary text
K_ACCENT    = "#5AB0FF"   # neon cold blue
K_ACCENT_2  = "#7A6CFF"   # neon violet

ctk.set_appearance_mode("dark")  # ensure dark

PROMPTS_FILE  = "prompts.json"

def sha1_bytes(b: bytes) -> str:
    return hashlib.sha1(b).hexdigest()

def ensure_dir(p: str):
    os.makedirs(p, exist_ok=True)

# --- Small capture icon for the snipping button ---
def make_capture_icon(size=20, fg=K_FG):
    s = size
    img = Image.new("RGBA", (s, s), (0,0,0,0))
    d = ImageDraw.Draw(img)
    # camera body (rounded rectangle)
    d.rounded_rectangle([1,1,s-2,s-2], radius=5, outline=fg, width=2)
    # lens
    d.ellipse([int(s*0.30), int(s*0.30), int(s*0.70), int(s*0.70)], outline=fg, width=2)
    # status dot
    d.ellipse([int(s*0.15), int(s*0.15), int(s*0.25), int(s*0.25)], fill=fg)
    return ctk.CTkImage(light_image=img, dark_image=img, size=(s, s))

# ====== PROMPTS ======
def load_prompts() -> dict[str, str]:
    data = {}
    if isinstance(CONFIG_PROMPTS, dict):
        data.update(CONFIG_PROMPTS)
    if os.path.exists(PROMPTS_FILE):
        try:
            with open(PROMPTS_FILE, "r", encoding="utf-8") as f:
                extra = json.load(f)
                if isinstance(extra, dict):
                    data.update(extra)
        except Exception:
            pass
    if not data:
        data = {
            "Default (General Reasoning)": "You are a logic expert. Analyze the OCR text and return ONLY the text of the correct choice.",
            "TOEIC (Reading)": "Act like a TOEIC grader. Given OCR (question + choices), return ONLY the letter and text of the correct choice. If ambiguous, pick the most plausible.",
            "Numeric Aptitude (Math/Logic)": "Solve mentally step-by-step but return ONLY the exact option among the choices.",
            "Data Sufficiency": "Evaluate (1) alone, (2) alone, and (1)&(2) together. Return ONLY the correct option."
        }
    return data

def save_prompts(prompts: dict[str, str]):
    with open(PROMPTS_FILE, "w", encoding="utf-8") as f:
        json.dump(prompts, f, ensure_ascii=False, indent=2)

def merged_providers():
    prov_map = {name: list(models) for (name, models) in CONFIG_PROVIDERS}
    prov_map.setdefault("OpenAI", []).extend(["gpt-4o", "gpt-4o-mini", "o3-mini", "gpt-4.1-mini"])
    prov_map.setdefault("Anthropic", []).extend(["claude-3.5-sonnet", "claude-3-opus", "claude-3-haiku"])
    prov_map.setdefault("Gemini", []).extend(["gemini-1.5-pro", "gemini-1.5-flash"])
    for k in prov_map:
        prov_map[k] = sorted(set(prov_map[k]))
    return [(k, prov_map[k]) for k in sorted(prov_map.keys())]

# ====== Fullscreen snipping overlay ======
class RegionOverlay(ctk.CTkToplevel):
    """Fullscreen overlay to draw a region with the mouse (Snipping Tool style)."""
    def __init__(self, master, on_done):
        super().__init__(master)
        self.on_done = on_done
        # semi-transparent black
        self.configure(fg_color="#000000")
        self.attributes("-alpha", 0.25)
        self.attributes("-topmost", True)
        self.overrideredirect(True)
        self.geometry(f"{self.winfo_screenwidth()}x{self.winfo_screenheight()}+0+0")

        # IMPORTANT: use a valid color for Tk
        self.canvas = ctk.CTkCanvas(self, bg="#000000", highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)
        self.start = None
        self.cur = None

        self.bind("<ButtonPress-1>", self._on_press)
        self.bind("<B1-Motion>", self._on_motion)
        self.bind("<ButtonRelease-1>", self._on_release)
        self.bind("<Escape>", lambda e: self._cancel())

        # small hint label
        self.hint = ctk.CTkLabel(
            self,
            text="Click & drag to select • Esc to cancel",
            text_color=K_FG, fg_color="transparent",
            font=ctk.CTkFont(size=16, weight="bold")
        )
        self.hint.place(relx=0.5, rely=0.03, anchor="n")

    def _on_press(self, e):
        self.start = (e.x, e.y)
        self.cur = (e.x, e.y)
        self._redraw()

    def _on_motion(self, e):
        self.cur = (e.x, e.y)
        self._redraw()

    def _on_release(self, e):
        if not (self.start and self.cur):
            self._cancel(); return
        x1, y1 = self.start
        x2, y2 = self.cur
        left, top = min(x1, x2), min(y1, y2)
        width, height = abs(x2 - x1), abs(y2 - y1)
        self.destroy()
        if width >= 10 and height >= 10:
            self.on_done(left, top, width, height)

    def _redraw(self):
        self.canvas.delete("all")
        if not (self.start and self.cur):
            return
        x1, y1 = self.start
        x2, y2 = self.cur
        left, top = min(x1, x2), min(y1, y2)
        right, bottom = max(x1, x2), max(y1, y2)
        # neon multi-layer frame
        for w, color in ((3, K_ACCENT), (1, K_ACCENT_2)):
            self.canvas.create_rectangle(left, top, right, bottom, outline=color, width=w)

    def _cancel(self):
        self.destroy()

# ====== APP ======
class OCRQCMApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        # --- Window ---
        self.title("OCR QCM – CTk Neon")
        self.geometry("1288x770")
        self.minsize(1120, 660)
        self.configure(fg_color=K_BG)
        self.wm_attributes("-alpha", 0.995)

        # --- State ---
        self.capture_zone = {"left": CAP_LEFT, "top": CAP_TOP, "width": CAP_WIDTH, "height": CAP_HEIGHT}
        self.cooldown_s = 1.5
        self.last_hash = None
        self.last_capture_ts = 0.0
        self.webhook_url = DISCORD_WEBHOOK
        self.log_dir = LOG_DIR
        ensure_dir(self.log_dir)

        self.prompts = load_prompts()
        self.providers = merged_providers()

        default_provider = PROVIDER if PROVIDER in dict(self.providers) else "OpenAI"
        default_prompt   = PROMPT if PROMPT in self.prompts else list(self.prompts.keys())[0]

        # AI
        self.provider_var    = ctk.StringVar(value=default_provider)
        self.model_var       = ctk.StringVar(value=MODEL)
        self.prompt_key_var  = ctk.StringVar(value=default_prompt)
        self.temperature_var = ctk.DoubleVar(value=float(LLM_TEMP))

        # API keys (masked)
        self.key_openai    = ctk.StringVar(value=OPENAI_API_KEY or "")
        self.key_anthropic = ctk.StringVar(value=ANTHROPIC_API_KEY or "")
        self.key_gemini    = ctk.StringVar(value=GEMINI_API_KEY or "")

        # Telegram
        self.telegram_token = ctk.StringVar(value=os.getenv("TELEGRAM_BOT_TOKEN", ""))
        self.telegram_chat  = ctk.StringVar(value=os.getenv("TELEGRAM_CHAT_ID", ""))

        # OCR params
        self.var_lang     = ctk.StringVar(value=OCR_LANG)
        self.var_oem      = ctk.StringVar(value=str(OCR_OEM))
        self.var_psm      = ctk.StringVar(value=str(OCR_PSM))
        self.var_cooldown = ctk.DoubleVar(value=1.5)

        # Outputs (in Settings → Outputs)
        self.do_copy_clipboard = ctk.BooleanVar(value=True)
        self.do_auto_save      = ctk.BooleanVar(value=True)
        self.do_send_discord   = ctk.BooleanVar(value=bool(self.webhook_url))
        self.do_send_telegram  = ctk.BooleanVar(value=False)

        # UI queue
        self.q_ui = queue.Queue()

        # Tesseract
        if TESSERACT_CMD:
            set_tesseract_cmd(TESSERACT_CMD)

        # ---- Create icons BEFORE building UI (fixes your crash) ----
        self.icons = {"capture": make_capture_icon(18, fg=K_FG)}

        # Build UI
        self._build_ui()
        self._bind_hotkeys()
        self.after(16, self._drain_ui_queue)

    # ====== UI helpers ======
    def _frame(self, parent, pad=8):
        f = ctk.CTkFrame(parent, fg_color=K_PANEL, border_color=K_BORDER, border_width=1, corner_radius=10)
        if pad: f.pack_propagate(False)
        return f

    def _subframe(self, parent):
        return ctk.CTkFrame(parent, fg_color=K_PANEL2, border_color=K_BORDER, border_width=1, corner_radius=8)

    def _label(self, parent, text, small=False, muted=False):
        return ctk.CTkLabel(parent, text=text, fg_color="transparent",
                            text_color=(K_MUTED if muted else K_FG),
                            font=ctk.CTkFont(size=(12 if small else 13)))

    def _title(self, parent, text):
        return ctk.CTkLabel(parent, text=text, fg_color=K_BG_ALT, text_color=K_FG,
                            font=ctk.CTkFont(size=14, weight="bold"))

    def _button(self, parent, text, command, accent=True, image=None):
        return ctk.CTkButton(
            parent, text=text, command=command, image=image, compound="left",
            fg_color=(K_ACCENT if accent else K_BG_ALT),
            hover_color=K_ACCENT_2 if accent else K_BG_ALT,
            text_color=("#0B0B0C" if accent else K_FG),
            border_color=K_BORDER, border_width=1, corner_radius=8
        )

    def _entry(self, parent, var, width=90, secret=False):
        e = ctk.CTkEntry(parent, width=width, textvariable=var,
                         fg_color=K_BG_ALT, border_color=K_BORDER, text_color=K_FG)
        if secret: e.configure(show="•")
        return e

    def _secret_row(self, parent, label, var, width=520):
        row = self._subframe(parent); row.pack(fill="x", padx=8, pady=6)
        self._label(row, label, muted=True).pack(side="left", padx=8)
        entry = self._entry(row, var, width=width, secret=True); entry.pack(side="left", padx=8)
        state = {"showing": False}
        def toggle():
            state["showing"] = not state["showing"]
            entry.configure(show="" if state["showing"] else "•")
            btn.configure(text=("🙈 Hide" if state["showing"] else "👁 Show"))
        btn = self._button(row, "👁 Show", toggle, accent=False); btn.pack(side="left", padx=6)
        return row

    def _textbox(self, parent, **kw):
        return ctk.CTkTextbox(parent, wrap="word",
                              fg_color=K_BG_ALT, text_color=K_FG,
                              border_color=K_BORDER, border_width=1, **kw)

    def _optionmenu(self, parent, values, variable, command=None, width=160):
        return ctk.CTkOptionMenu(parent, values=values, variable=variable, command=command,
                                 width=width, fg_color=K_BG_ALT, button_color=K_ACCENT,
                                 button_hover_color=K_ACCENT, dropdown_fg_color=K_BG_ALT,
                                 dropdown_text_color=K_FG, text_color=K_FG)

    def _slider(self, parent, var, width=160):
        return ctk.CTkSlider(parent, from_=0.0, to=2.0, number_of_steps=20,
                             width=width, variable=var, fg_color=K_BG_ALT, progress_color=K_ACCENT)

    # ====== Build UI ======
    def _build_ui(self):
        # Tabs
        self.tabview = ctk.CTkTabview(self, fg_color=K_BG, segmented_button_fg_color=K_BG_ALT,
                                      segmented_button_selected_color=K_ACCENT, text_color=K_FG)
        self.tabview.pack(fill="both", expand=True, padx=10, pady=10)
        for name in ("Capture", "AI", "Results & Logs", "Settings"):
            self.tabview.add(name)

        self._build_tab_capture(self.tabview.tab("Capture"))
        self._build_tab_ai(self.tabview.tab("AI"))
        self._build_tab_logs(self.tabview.tab("Results & Logs"))
        self._build_tab_settings(self.tabview.tab("Settings"))

        # Status bar
        self.status_var = ctk.StringVar(value="Ready.")
        status = ctk.CTkFrame(self, fg_color=K_BG_ALT, border_color=K_BORDER, border_width=1)
        status.pack(side="bottom", fill="x", padx=10, pady=(0,10))
        ctk.CTkLabel(status, textvariable=self.status_var, fg_color="transparent", text_color=K_MUTED).pack(anchor="center", pady=4)

    def _build_tab_capture(self, parent):
        # Top: region + capture
        top = self._frame(parent); top.pack(fill="x", padx=8, pady=8)
        self._title(top, "Region & Capture").pack(anchor="w", padx=8, pady=(8,6))

        row = self._subframe(top); row.pack(fill="x", padx=8, pady=8)
        # Inputs L, T, W, H
        self.var_l = ctk.IntVar(value=self.capture_zone["left"])
        self.var_t = ctk.IntVar(value=self.capture_zone["top"])
        self.var_w = ctk.IntVar(value=self.capture_zone["width"])
        self.var_h = ctk.IntVar(value=self.capture_zone["height"])
        for lbl, var in (("L", self.var_l), ("T", self.var_t), ("W", self.var_w), ("H", self.var_h)):
            self._label(row, lbl, small=True, muted=True).pack(side="left", padx=(8,4))
            self._entry(row, var, width=80).pack(side="left", padx=(0,8))

        # Snipping overlay button with icon
        self._button(
            row, "Define region (draw)", self._open_region_overlay,
            accent=False, image=self.icons.get("capture")
        ).pack(side="left", padx=8)
        self._button(row, "Capture (F2)", self.capture_once).pack(side="right", padx=8)

        # Middle: Preview + OCR text
        mid = self._frame(parent); mid.pack(fill="both", expand=True, padx=8, pady=6)
        self._title(mid, "Preview & OCR").pack(anchor="w", padx=8, pady=(8,6))

        grid = self._subframe(mid); grid.pack(fill="both", expand=True, padx=8, pady=(0,8))
        grid.grid_columnconfigure(0, weight=1)
        grid.grid_columnconfigure(1, weight=1)
        grid.grid_rowconfigure(0, weight=1)

        self.preview = ctk.CTkLabel(grid, text="Capture preview", fg_color=K_PANEL2,
                                    text_color=K_MUTED, width=540, height=360, anchor="n")
        self.preview.grid(row=0, column=0, sticky="nsew", padx=8, pady=8)

        self.txt_ocr = self._textbox(grid)
        self.txt_ocr.grid(row=0, column=1, sticky="nsew", padx=8, pady=8)

        # Bottom: OCR params
        bot = self._frame(parent); bot.pack(fill="x", padx=8, pady=8)
        self._title(bot, "OCR Parameters").pack(anchor="w", padx=8, pady=(8,6))
        row2 = self._subframe(bot); row2.pack(fill="x", padx=8, pady=8)
        for lbl, var, w in (("Lang", self.var_lang, 100),
                            ("OEM", self.var_oem, 80),
                            ("PSM", self.var_psm, 80),
                            ("Cooldown (s)", self.var_cooldown, 120)):
            self._label(row2, lbl, small=True, muted=True).pack(side="left", padx=(8,4))
            self._entry(row2, var, width=w).pack(side="left", padx=(0,10))

    def _build_tab_ai(self, parent):
        # Line 1: provider / model / prompt / temp / stealth
        top = self._frame(parent); top.pack(fill="x", padx=8, pady=8)
        self._title(top, "AI Engine & Prompt").pack(anchor="w", padx=8, pady=(8,6))

        row = self._subframe(top); row.pack(fill="x", padx=8, pady=8)
        self._optionmenu(row, [p[0] for p in self.providers], self.provider_var,
                         command=lambda *_: self._refresh_models_for_provider()).pack(side="left", padx=6)
        self.cmb_model = self._optionmenu(row, [self.model_var.get()], self.model_var, width=220)
        self.cmb_model.pack(side="left", padx=6)

        self.cmb_prompt = self._optionmenu(row, list(self.prompts.keys()), self.prompt_key_var,
                                           command=lambda *_: self._load_prompt_to_editor(), width=260)
        self.cmb_prompt.pack(side="left", padx=6)

        self._label(row, "Temp", small=True, muted=True).pack(side="left", padx=(12,6))
        self._slider(row, self.temperature_var, 180).pack(side="left", padx=6)

        self._button(row, "Show (Ctrl+Shift+S)", self.show_window, accent=False).pack(side="right", padx=6)
        self._button(row, "Hide (Ctrl+Shift+H)", self.hide_window, accent=False).pack(side="right", padx=6)

        # Line 2: actions
        btn_bar = self._subframe(parent); btn_bar.pack(fill="x", padx=8, pady=6)
        self._button(btn_bar, "Test AI call", self._test_ai_call).pack(side="left", padx=6, pady=8)
        self._button(btn_bar, "Solve (OCR → AI)", self.solve_flow).pack(side="left", padx=6, pady=8)

        # Prompt editor
        editor = self._frame(parent); editor.pack(fill="both", expand=True, padx=8, pady=8)
        head = self._subframe(editor); head.pack(fill="x", padx=8, pady=(8,0))
        self._label(head, "Prompt name", small=True, muted=True).pack(side="left", padx=(8,4))
        self.prompt_name_var = ctk.StringVar(value=self.prompt_key_var.get())
        self._entry(head, self.prompt_name_var, width=360).pack(side="left", padx=8)
        self._button(head, "New", self._prompt_new, accent=False).pack(side="left", padx=4)
        self._button(head, "Save", self._prompt_save, accent=False).pack(side="left", padx=4)
        self._button(head, "Delete", self._prompt_delete, accent=False).pack(side="left", padx=4)

        self.txt_prompt = self._textbox(editor)
        self.txt_prompt.pack(fill="both", expand=True, padx=10, pady=10)
        self._load_prompt_to_editor()

        # AI answer
        out = self._frame(parent); out.pack(fill="both", expand=True, padx=8, pady=8)
        self._title(out, "AI Answer").pack(anchor="w", padx=8, pady=(8,6))
        self.txt_ai = self._textbox(out, height=140)
        self.txt_ai.pack(fill="both", expand=True, padx=8, pady=8)

    def _build_tab_logs(self, parent):
        self._title(parent, "Logs").pack(anchor="w", padx=16, pady=(8,6))
        self.txt_log = self._textbox(parent, height=260)
        self.txt_log.pack(fill="both", expand=True, padx=8, pady=8)

    def _build_tab_settings(self, parent):
        # Tesseract
        t1 = self._frame(parent); t1.pack(fill="x", padx=8, pady=8)
        self._title(t1, "Tesseract").pack(anchor="w", padx=8, pady=(8,6))
        row = self._subframe(t1); row.pack(fill="x", padx=8, pady=8)
        self._label(row, "tesseract.exe path", small=True, muted=True).pack(side="left", padx=(8,4))
        self.var_tesseract = ctk.StringVar(value=TESSERACT_CMD)
        self._entry(row, self.var_tesseract, width=520).pack(side="left", padx=8)
        self._button(row, "Browse…", self._pick_tesseract, accent=False).pack(side="left", padx=6)

        # API keys
        t2 = self._frame(parent); t2.pack(fill="x", padx=8, pady=8)
        self._title(t2, "API Keys (hidden)").pack(anchor="w", padx=8, pady=(8,6))
        self._secret_row(t2, "OpenAI", self.key_openai)
        self._secret_row(t2, "Anthropic", self.key_anthropic)
        self._secret_row(t2, "Gemini", self.key_gemini)

        # Outputs (clipboard / save / Discord / Telegram)
        t3 = self._frame(parent); t3.pack(fill="x", padx=8, pady=8)
        self._title(t3, "Outputs").pack(anchor="w", padx=8, pady=(8,6))

        toggles = self._subframe(t3); toggles.pack(fill="x", padx=8, pady=(8,0))
        ctk.CTkCheckBox(toggles, text="Copy AI answer to clipboard",
                        variable=self.do_copy_clipboard, fg_color=K_ACCENT,
                        border_color=K_BORDER, text_color=K_FG).pack(side="left", padx=6, pady=6)
        ctk.CTkCheckBox(toggles, text="Auto-save answer to disk",
                        variable=self.do_auto_save, fg_color=K_ACCENT,
                        border_color=K_BORDER, text_color=K_FG).pack(side="left", padx=6, pady=6)

        # Discord settings
        disc = self._subframe(t3); disc.pack(fill="x", padx=8, pady=8)
        ctk.CTkCheckBox(disc, text="Send to Discord webhook",
                        variable=self.do_send_discord, fg_color=K_ACCENT,
                        border_color=K_BORDER, text_color=K_FG).pack(side="left", padx=6)
        self._label(disc, "Webhook", small=True, muted=True).pack(side="left", padx=(16,4))
        self.var_webhook = ctk.StringVar(value=self.webhook_url)
        self._entry(disc, self.var_webhook, width=520).pack(side="left", padx=8)
        self._button(disc, "Test Discord", self._test_discord, accent=False).pack(side="left", padx=6)

        # Telegram settings
        tg = self._subframe(t3); tg.pack(fill="x", padx=8, pady=(8,8))
        ctk.CTkCheckBox(tg, text="Send to Telegram",
                        variable=self.do_send_telegram, fg_color=K_ACCENT,
                        border_color=K_BORDER, text_color=K_FG).pack(side="left", padx=6)
        self._label(tg, "Bot Token", small=True, muted=True).pack(side="left", padx=(16,4))
        self._entry(tg, self.telegram_token, width=360, secret=True).pack(side="left", padx=(0,8))
        self._label(tg, "Chat ID", small=True, muted=True).pack(side="left", padx=(8,4))
        self._entry(tg, self.telegram_chat, width=220).pack(side="left", padx=(0,8))
        self._button(tg, "Test Telegram", self._test_telegram, accent=False).pack(side="left", padx=6)

    # ====== Hotkeys & Stealth ======
    def _bind_hotkeys(self):
        self.bind("<F2>", lambda e: self.capture_once())
        if kb:
            try:
                kb.add_hotkey("ctrl+shift+h", self.hide_window)
                kb.add_hotkey("ctrl+shift+s", self.show_window)
                kb.add_hotkey("f2", self.capture_once)
                kb.add_hotkey("ctrl+shift+x", self._panic_hide)  # panic: hide and clear
            except Exception:
                pass

    def hide_window(self): self.withdraw()
    def show_window(self): self.deiconify(); self.lift()
    def _panic_hide(self):
        self.hide_window()
        try:
            self.preview.configure(image=None, text="")
            self.txt_ocr.delete("1.0", "end")
            self.txt_ai.delete("1.0", "end")
            self.status_var.set("Hidden.")
        except Exception:
            pass

    # ====== Region overlay ======
    def _open_region_overlay(self, auto_capture=True):
        def done(l, t, w, h):
            self.var_l.set(l); self.var_t.set(t); self.var_w.set(w); self.var_h.set(h)
            self.status_var.set(f"Region set: L={l} T={t} W={w} H={h}")
            if auto_capture:
                self.capture_once()

        # hide main window so the overlay covers fully
        self.withdraw()
        # start overlay once the window is hidden
        def after_hide():
            RegionOverlay(self, on_done=lambda L,T,W,H: (self.show_window(), done(L,T,W,H)))
        self.after(120, after_hide)

    # ====== Prompt editor ======
    def _load_prompt_to_editor(self):
        key = self.prompt_key_var.get()
        text = self.prompts.get(key, "")
        self.txt_prompt.delete("1.0", "end"); self.txt_prompt.insert("1.0", text)
        self.prompt_name_var.set(key)

    def _prompt_new(self):
        base = "New Prompt"
        name = base; i = 1
        while name in self.prompts:
            i += 1; name = f"{base} {i}"
        self.prompts[name] = "Write your prompt here…"
        self._refresh_prompt_menu(select=name); self._load_prompt_to_editor()

    def _prompt_save(self):
        name = self.prompt_name_var.get().strip()
        if not name:
            self.status_var.set("Prompt name is empty."); return
        text = self.txt_prompt.get("1.0", "end").strip()
        self.prompts[name] = text
        save_prompts(self.prompts)
        self._refresh_prompt_menu(select=name)
        self.status_var.set(f"Prompt “{name}” saved.")

    def _prompt_delete(self):
        name = self.prompt_key_var.get()
        if name in self.prompts:
            del self.prompts[name]
            save_prompts(self.prompts)
            new_key = list(self.prompts.keys())[0] if self.prompts else ""
            self._refresh_prompt_menu(select=new_key)
            if new_key: self._load_prompt_to_editor()
            self.status_var.set(f"Prompt “{name}” deleted.")

    def _refresh_prompt_menu(self, select: str | None = None):
        keys = list(self.prompts.keys()) or [""]
        self.cmb_prompt.configure(values=keys)
        if select and select in keys:
            self.prompt_key_var.set(select)
        elif self.prompt_key_var.get() not in keys:
            self.prompt_key_var.set(keys[0])

    # ====== Logic ======
    def _refresh_models_for_provider(self, *_):
        prov = self.provider_var.get()
        for p, models in self.providers:
            if p == prov:
                self.cmb_model.configure(values=models)
                if self.model_var.get() not in models:
                    self.model_var.set(models[0])
                break

    def capture_once(self, *_evt):
        self.status_var.set("Capturing…")
        threading.Thread(target=self._capture_thread, daemon=True).start()

    def _capture_thread(self):
        try:
            self.capture_zone = {
                "left": int(self.var_l.get()),
                "top": int(self.var_t.get()),
                "width": int(self.var_w.get()),
                "height": int(self.var_h.get()),
            }
            img = grab_image(**self.capture_zone)
            im_small = img.copy(); im_small.thumbnail((960, 540))
            buf_small = io.BytesIO(); im_small.save(buf_small, format="PNG")
            small_bytes = buf_small.getvalue()

            text = ocr_image(img, lang=self.var_lang.get(),
                             oem=str(self.var_oem.get()), psm=str(self.var_psm.get()))

            self.q_ui.put(("preview", small_bytes))
            self.q_ui.put(("ocr_text", text))
            self.q_ui.put(("status", f"Capture OK ({len(text)} chars)"))
        except Exception as e:
            self.q_ui.put(("error", f"OCR/Capture error: {e}"))

    def _build_llm(self) -> LLMClient | None:
        prov = self.provider_var.get()
        model = self.model_var.get()
        key_map = {
            "OpenAI": self.key_openai.get().strip(),
            "Anthropic": self.key_anthropic.get().strip(),
            "Gemini": self.key_gemini.get().strip(),
        }
        key = key_map.get(prov, "")
        if not key:
            self.q_ui.put(("status", f"Missing API key for {prov}."))
            return None
        try:
            return LLMClient(prov, model, key)
        except Exception as e:
            self.q_ui.put(("error", f"LLM init failed: {e}"))
            return None

    def _test_ai_call(self):
        def run():
            txt = self.txt_ocr.get("1.0", "end-1c").strip() or "A = 2, B = 3. Sum? A)3 B)4 C)5"
            llm = self._build_llm()
            if not llm: return
            self.q_ui.put(("status", "Calling AI…"))
            try:
                prompt = self.prompts.get(self.prompt_key_var.get(), "")
                ans = llm.complete(txt, prompt, temperature=float(self.temperature_var.get()))
                self._post_answer(ans, txt, img_bytes=None)
            except Exception as e:
                self.q_ui.put(("error", f"AI error: {e}"))
        threading.Thread(target=run, daemon=True).start()

    def solve_flow(self):
        def run():
            # Ensure OCR first
            self._capture_thread()
            t0 = time.time()
            while time.time() - t0 < 2.0 and self.txt_ocr.get("1.0", "end-1c") == "":
                time.sleep(0.05)
            txt = self.txt_ocr.get("1.0", "end-1c").strip()
            if not txt:
                self.q_ui.put(("status", "No OCR text.")); return
            # AI
            llm = self._build_llm()
            if not llm: return
            self.q_ui.put(("status", "Solving via AI…"))
            try:
                prompt = self.prompts.get(self.prompt_key_var.get(), "")
                ans = llm.complete(txt, prompt, temperature=float(self.temperature_var.get()))
                self._post_answer(ans, txt, img_bytes=None)
            except Exception as e:
                self.q_ui.put(("error", f"AI error: {e}"))
        threading.Thread(target=run, daemon=True).start()

    def _post_answer(self, ans: str, ocr_text: str, img_bytes: bytes | None):
        self.q_ui.put(("ai_text", ans))
        self.q_ui.put(("status", "AI answer received."))
        # Post-processing (Settings → Outputs)
        if self.do_copy_clipboard.get():
            try: self.clipboard_clear(); self.clipboard_append(ans)
            except Exception: pass
        if self.do_auto_save.get(): self._append_log(ans, ocr_text)
        if self.do_send_discord.get() and self.var_webhook.get().strip():
            try:
                content = f"**AI Answer ({self.provider_var.get()} / {self.model_var.get()} / {self.prompt_key_var.get()})**\n>>> {ans}"
                files = {}
                if img_bytes:
                    files["file"] = ("capture.png", img_bytes, "image/png")
                r = requests.post(self.var_webhook.get().strip(), data={"content": content}, files=files, timeout=10)
                if r.status_code >= 300: raise RuntimeError(f"HTTP {r.status_code}: {r.text[:200]}")
                self.txt_log.insert("1.0", "Sent to Discord.\n")
            except Exception as e:
                self.txt_log.insert("1.0", f"Discord failed: {e}\n")
        if self.do_send_telegram.get() and self.telegram_token.get().strip() and self.telegram_chat.get().strip():
            try: self._send_telegram_message(ans)
            except Exception as e: self.txt_log.insert("1.0", f"Telegram failed: {e}\n")

    # ====== UI Queue drain ======
    def _drain_ui_queue(self):
        try:
            while True:
                kind, payload = self.q_ui.get_nowait()
                if kind == "preview":
                    img = Image.open(io.BytesIO(payload))
                    self._preview_imgtk = ImageTk.PhotoImage(img)
                    self.preview.configure(image=self._preview_imgtk, text="")
                elif kind == "ocr_text":
                    self.txt_ocr.delete("1.0", "end"); self.txt_ocr.insert("1.0", payload)
                elif kind == "ai_text":
                    self.txt_ai.delete("1.0", "end"); self.txt_ai.insert("1.0", payload)
                elif kind == "status":
                    self.status_var.set(str(payload))
                elif kind == "error":
                    self.status_var.set(str(payload))
        except queue.Empty:
            pass
        self.after(33, self._drain_ui_queue)

    # ====== Logs & Misc ======
    def _append_log(self, answer: str, ocr_text: str):
        ensure_dir(self.log_dir)
        p = os.path.join(self.log_dir, f"result_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt")
        with open(p, "w", encoding="utf-8") as f:
            f.write(f"=== {datetime.now()} | {self.provider_var.get()} | {self.model_var.get()} | {self.prompt_key_var.get()} ===\n")
            f.write("--- OCR ---\n"); f.write(ocr_text + "\n")
            f.write("--- ANSWER ---\n"); f.write((answer or "") + "\n")
        self.txt_log.insert("1.0", f"Log written: {p}\n")

    def _pick_tesseract(self):
        from tkinter import filedialog
        p = filedialog.askopenfilename(title="Select tesseract.exe")
        if p: self.var_tesseract.set(p)

    # ====== Discord / Telegram tests ======
    def _test_discord(self):
        try:
            r = requests.post(self.var_webhook.get().strip(), data={"content": "Test from OCR QCM – CTk Neon ✅"}, timeout=10)
            if r.status_code >= 300: raise RuntimeError(f"HTTP {r.status_code}: {r.text[:200]}")
            self.status_var.set("Discord OK.")
        except Exception as e:
            self.status_var.set(f"Discord failed: {e}")

    def _test_telegram(self):
        try:
            self._send_telegram_message("Test from OCR QCM – CTk Neon ✅")
            self.status_var.set("Telegram OK.")
        except Exception as e:
            self.status_var.set(f"Telegram failed: {e}")

    def _send_telegram_message(self, text: str):
        token = self.telegram_token.get().strip()
        chat  = self.telegram_chat.get().strip()
        if not token or not chat:
            raise RuntimeError("Please set bot token and chat id.")
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        r = requests.post(url, json={"chat_id": chat, "text": text, "parse_mode": "Markdown"}, timeout=10)
        if r.status_code >= 300:
            raise RuntimeError(f"Telegram HTTP {r.status_code}: {r.text[:200]}")

# ====== main ======
if __name__ == "__main__":
    app = OCRQCMApp()
    app.mainloop()
