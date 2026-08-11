"""Release-Manager (Dev-Tool).

Bearbeitet in einem Schritt:
  - src/core/version.py   (VERSION-Zeile, gilt fuer den NAECHSTEN Build)
  - server/live_config.json (required_version + Ankuendigungen)

Nach dem Speichern muss live_config.json manuell auf den Relay-Server
hochgeladen werden - dieses Tool tut das nicht selbst.

Aufruf: python tools/release_gui.py
"""
from __future__ import annotations

import json
import os
import re
import tkinter as tk
from datetime import date
from tkinter import messagebox, ttk

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VERSION_PATH = os.path.join(ROOT, "src", "core", "version.py")
LIVE_CONFIG_PATH = os.path.join(ROOT, "server", "live_config.json")


def load_version() -> str:
    try:
        with open(VERSION_PATH, "r", encoding="utf-8") as f:
            src = f.read()
        m = re.search(r'^VERSION\s*=\s*"([^"]+)"', src, re.M)
        return m.group(1) if m else ""
    except Exception:
        return ""


def load_announcements() -> list[dict]:
    try:
        with open(LIVE_CONFIG_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        return list(data.get("announcements", []))
    except Exception:
        return []


def slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug[:30]


class ReleaseGUI:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        root.title("Release-Manager")
        root.geometry("760x640")

        self.announcements = load_announcements()
        self.selected_index: int | None = None

        top = ttk.Frame(root, padding=8)
        top.pack(fill="x")
        ttk.Label(top, text="Spielversion:").pack(side="left")
        self.version_var = tk.StringVar(value=load_version())
        ttk.Entry(top, textvariable=self.version_var, width=20).pack(side="left", padx=6)

        mid = ttk.Frame(root, padding=8)
        mid.pack(fill="both", expand=True)

        left = ttk.Frame(mid)
        left.pack(side="left", fill="y", padx=(0, 8))
        ttk.Label(left, text="Ankündigungen:").pack(anchor="w")
        self.listbox = tk.Listbox(left, width=40, height=20)
        self.listbox.pack(fill="y", expand=True)
        self.listbox.bind("<<ListboxSelect>>", self.on_select)
        btns = ttk.Frame(left)
        btns.pack(fill="x", pady=4)
        ttk.Button(btns, text="Neu", command=self.on_new).pack(side="left")
        ttk.Button(btns, text="Löschen", command=self.on_delete).pack(side="left", padx=4)

        right = ttk.Frame(mid)
        right.pack(side="left", fill="both", expand=True)

        ttk.Label(right, text="Datum:").grid(row=0, column=0, sticky="w")
        self.date_var = tk.StringVar()
        ttk.Entry(right, textvariable=self.date_var, width=20).grid(row=0, column=1, sticky="w", pady=2)

        ttk.Label(right, text="Titel (DE):").grid(row=1, column=0, sticky="w")
        self.title_de_var = tk.StringVar()
        ttk.Entry(right, textvariable=self.title_de_var, width=50).grid(row=1, column=1, sticky="we", pady=2)

        ttk.Label(right, text="Titel (EN):").grid(row=2, column=0, sticky="w")
        self.title_en_var = tk.StringVar()
        ttk.Entry(right, textvariable=self.title_en_var, width=50).grid(row=2, column=1, sticky="we", pady=2)

        ttk.Label(right, text="Text (DE):").grid(row=3, column=0, sticky="nw")
        self.text_de = tk.Text(right, height=4, width=50)
        self.text_de.grid(row=3, column=1, sticky="we", pady=2)

        ttk.Label(right, text="Text (EN):").grid(row=4, column=0, sticky="nw")
        self.text_en = tk.Text(right, height=4, width=50)
        self.text_en.grid(row=4, column=1, sticky="we", pady=2)

        ttk.Button(right, text="Übernehmen", command=self.on_apply).grid(row=5, column=1, sticky="w", pady=8)

        right.columnconfigure(1, weight=1)

        bottom = ttk.Frame(root, padding=8)
        bottom.pack(fill="x")
        ttk.Button(bottom, text="Speichern", command=self.on_save).pack(side="left")
        self.status_var = tk.StringVar(value="")
        self.status_label = ttk.Label(bottom, textvariable=self.status_var)
        self.status_label.pack(side="left", padx=10)

        self.refresh_listbox()

    def refresh_listbox(self) -> None:
        self.listbox.delete(0, tk.END)
        for ann in self.announcements:
            title_de = ann.get("title", {}).get("de", "")
            self.listbox.insert(tk.END, f"{ann.get('date', '')}  {title_de}")

    def clear_editor(self) -> None:
        self.date_var.set(date.today().isoformat())
        self.title_de_var.set("")
        self.title_en_var.set("")
        self.text_de.delete("1.0", tk.END)
        self.text_en.delete("1.0", tk.END)

    def load_into_editor(self, ann: dict) -> None:
        self.date_var.set(ann.get("date", ""))
        self.title_de_var.set(ann.get("title", {}).get("de", ""))
        self.title_en_var.set(ann.get("title", {}).get("en", ""))
        self.text_de.delete("1.0", tk.END)
        self.text_de.insert("1.0", ann.get("text", {}).get("de", ""))
        self.text_en.delete("1.0", tk.END)
        self.text_en.insert("1.0", ann.get("text", {}).get("en", ""))

    def on_select(self, _event=None) -> None:
        sel = self.listbox.curselection()
        if not sel:
            return
        self.selected_index = sel[0]
        self.load_into_editor(self.announcements[self.selected_index])

    def on_new(self) -> None:
        self.selected_index = None
        self.listbox.selection_clear(0, tk.END)
        self.clear_editor()

    def on_delete(self) -> None:
        if self.selected_index is None:
            return
        if not messagebox.askyesno(
            "Löschen bestätigen",
            "Diese Ankündigung löschen? Clients sehen sie danach nicht mehr.",
        ):
            return
        del self.announcements[self.selected_index]
        self.selected_index = None
        self.refresh_listbox()
        self.clear_editor()

    def on_apply(self) -> None:
        d = self.date_var.get().strip()
        title_de = self.title_de_var.get().strip()
        title_en = self.title_en_var.get().strip()
        text_de = self.text_de.get("1.0", tk.END).strip()
        text_en = self.text_en.get("1.0", tk.END).strip()

        if self.selected_index is None:
            ann_id = f"{d}-{slugify(title_de)}"
            ann = {
                "id": ann_id,
                "date": d,
                "title": {"de": title_de, "en": title_en},
                "text": {"de": text_de, "en": text_en},
            }
            self.announcements.append(ann)
            self.selected_index = len(self.announcements) - 1
        else:
            ann = self.announcements[self.selected_index]
            ann["date"] = d
            ann["title"] = {"de": title_de, "en": title_en}
            ann["text"] = {"de": text_de, "en": text_en}

        self.refresh_listbox()
        self.listbox.selection_clear(0, tk.END)
        self.listbox.selection_set(self.selected_index)

    def on_save(self) -> None:
        v = self.version_var.get().strip()
        if not v:
            self.status_var.set("Fehler: Version darf nicht leer sein.")
            self.status_label.configure(foreground="red")
            return

        try:
            with open(VERSION_PATH, "r", encoding="utf-8") as f:
                src = f.read()
            new_src = re.sub(
                r'^VERSION\s*=\s*"[^"]*"',
                f'VERSION = "{v}"',
                src,
                count=1,
                flags=re.M,
            )
            with open(VERSION_PATH, "w", encoding="utf-8") as f:
                f.write(new_src)

            with open(LIVE_CONFIG_PATH, "w", encoding="utf-8") as f:
                json.dump(
                    {"required_version": v, "announcements": self.announcements},
                    f,
                    indent=2,
                    ensure_ascii=False,
                )
        except Exception as exc:
            self.status_var.set(f"Fehler beim Speichern: {exc}")
            self.status_label.configure(foreground="red")
            return

        self.status_var.set(
            "Gespeichert. live_config.json jetzt auf den Server hochladen — "
            "version.py gilt für den nächsten Build."
        )
        self.status_label.configure(foreground="green")


def main() -> None:
    root = tk.Tk()
    ReleaseGUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()
