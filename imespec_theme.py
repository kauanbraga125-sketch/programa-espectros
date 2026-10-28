"""A compact, consistent desktop theme shared by the IMESPEC workspaces."""

from tkinter import ttk, font as tkfont

PALETTE = {
    "app_bg": "#F2F5FA",
    "surface": "#FFFFFF",
    "surface_alt": "#F8FAFD",
    "sidebar": "#101D34",
    "sidebar_hover": "#1B2C48",
    "sidebar_active": "#2463EB",
    "text": "#152540",
    "muted": "#65758C",
    "border": "#DFE6F0",
    "primary": "#2463EB",
    "primary_hover": "#1B4FC4",
    "success": "#0B8A71",
    "warning": "#B96C09",
    "danger": "#C63F46",
    "invalid": "#E5EAF1",
}


def apply_theme(root):
    families = {f.casefold() for f in tkfont.families(root)}
    family = next(
        (
            f
            for f in ("Segoe UI", "Inter", "Arial", "DejaVu Sans", "Liberation Sans")
            if f.casefold() in families
        ),
        "TkDefaultFont",
    )
    for name in ("TkDefaultFont", "TkTextFont", "TkMenuFont", "TkHeadingFont"):
        if family != "TkDefaultFont":
            tkfont.nametofont(name).configure(family=family, size=10)
    root.option_add("*TCombobox*Listbox.background", "white")
    root.option_add("*TCombobox*Listbox.selectBackground", "#DFEAFE")
    root.option_add("*TCombobox*Listbox.selectForeground", PALETTE["text"])
    s = ttk.Style(root)
    s.theme_use("clam")
    s.configure(
        ".",
        font=(family, 10),
        background=PALETTE["surface"],
        foreground=PALETTE["text"],
        bordercolor=PALETTE["border"],
    )
    for name in ("TFrame", "Surface.TFrame", "WorkspaceHeader.TFrame"):
        s.configure(name, background=PALETTE["surface"])
    s.configure("Workspace.TFrame", background=PALETTE["app_bg"])
    s.configure(
        "TLabel", background="white", foreground=PALETTE["text"], font=(family, 10)
    )
    s.configure("Muted.TLabel", foreground=PALETTE["muted"])
    s.configure("Caption.TLabel", font=(family, 9), foreground=PALETTE["muted"])
    s.configure("Section.TLabel", font=(family, 10, "bold"))
    s.configure("Title.TLabel", font=(family, 17, "bold"))
    s.configure(
        "TButton",
        padding=(12, 8),
        background="#F7F9FC",
        borderwidth=1,
        relief="flat",
        bordercolor=PALETTE["border"],
        lightcolor=PALETTE["border"],
        darkcolor=PALETTE["border"],
        focusthickness=1,
        focuscolor=PALETTE["primary"],
    )
    s.map(
        "TButton",
        background=[("pressed", "#E0E8F5"), ("active", "#ECF1F9")],
        foreground=[("disabled", "#94A3B8")],
    )
    s.configure(
        "Accent.TButton",
        background=PALETTE["primary"],
        foreground="white",
        borderwidth=0,
        padding=(13, 8),
        font=(family, 10, "bold"),
    )
    s.map(
        "Accent.TButton",
        background=[
            ("disabled", "#A8BDE8"),
            ("pressed", "#183F99"),
            ("active", PALETTE["primary_hover"]),
        ],
        foreground=[("disabled", "white")],
    )
    s.configure("Ghost.TButton", background="white", foreground=PALETTE["primary"])
    s.configure("Danger.TButton", foreground=PALETTE["danger"])
    s.configure(
        "TEntry",
        padding=7,
        fieldbackground="white",
        borderwidth=1,
        bordercolor=PALETTE["border"],
        lightcolor=PALETTE["border"],
        darkcolor=PALETTE["border"],
    )
    s.map("TEntry", bordercolor=[("focus", PALETTE["primary"])])
    s.configure(
        "TCombobox",
        padding=6,
        fieldbackground="white",
        background="#F2F5FA",
        borderwidth=1,
        arrowsize=13,
        lightcolor=PALETTE["border"],
        darkcolor=PALETTE["border"],
    )
    s.map(
        "TCombobox",
        fieldbackground=[("readonly", "white")],
        selectbackground=[("readonly", "white")],
        selectforeground=[("readonly", PALETTE["text"])],
        bordercolor=[("focus", PALETTE["primary"])],
    )
    s.configure("TCheckbutton", background="white", padding=(0, 3))
    s.map("TCheckbutton", background=[("active", "white")])
    s.configure("TRadiobutton", background="white", padding=(0, 3))
    s.configure("TLabelframe", background="white", relief="solid", borderwidth=1)
    s.configure("TLabelframe.Label", background="white", font=(family, 10, "bold"))
    s.configure(
        "TNotebook",
        background=PALETTE["app_bg"],
        borderwidth=0,
        tabmargins=(0, 0, 0, 0),
    )
    s.configure(
        "TNotebook.Tab",
        background=PALETTE["app_bg"],
        padding=(16, 10),
        borderwidth=0,
        font=(family, 10),
        foreground=PALETTE["muted"],
    )
    s.map(
        "TNotebook.Tab",
        background=[("selected", "white"), ("active", "#E8EFFA")],
        foreground=[("selected", PALETTE["primary"]), ("active", PALETTE["text"])],
    )
    s.configure(
        "Treeview",
        rowheight=29,
        fieldbackground="white",
        background="white",
        borderwidth=0,
        font=(family, 9),
    )
    s.configure(
        "Treeview.Heading",
        background="#F2F5FA",
        font=(family, 9, "bold"),
        relief="flat",
        padding=(7, 8),
        borderwidth=0,
    )
    s.map(
        "Treeview",
        background=[("selected", "#E6EFFF")],
        foreground=[("selected", PALETTE["primary"])],
    )
    for orient in ("Vertical", "Horizontal"):
        s.configure(
            f"{orient}.TScrollbar",
            background="#C9D4E4",
            troughcolor="#F2F5FA",
            borderwidth=0,
            arrowsize=11,
            arrowcolor=PALETTE["muted"],
        )
    return family
