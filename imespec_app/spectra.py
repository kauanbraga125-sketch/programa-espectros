"""Read-only spectra, reversible display offsets and portable project files.

No Qt, Tk, fitting, normalization, smoothing or baseline subtraction lives in
this module. A displayed curve is exactly raw intensity + a recorded constant.
The optional reference alignment uses the nearest measured point, matching the
teacher's existing ``distribuir`` convention without mutating its inputs.
"""

from dataclasses import dataclass, field
from pathlib import Path
import hashlib
import json
import math
import os
import re
import tempfile
import uuid

import numpy as np

COLORS = (
    "#2563EB",
    "#0891B2",
    "#059669",
    "#CA8A04",
    "#EA580C",
    "#DC2626",
    "#9333EA",
    "#475569",
)
TEMP_RE = re.compile(r"(?<![A-Za-z0-9])(\d+(?:[.,_]\d+)?)\s*K(?=$|[^A-Za-z0-9])", re.I)


def temperature_from_name(name):
    """Only infer an explicit number followed by K; never a laser or exposure."""
    matches = TEMP_RE.findall(Path(name).stem)
    if not matches:
        return None
    number = float(matches[-1].replace(",", ".").replace("_", "."))
    return number if math.isfinite(number) and number >= 0 else None


def natural_key(value):
    return [
        (0, float(p)) if re.fullmatch(r"\d+(?:\.\d+)?", p) else (1, p)
        for p in re.split(r"(\d+(?:\.\d+)?)", str(value).casefold())
        if p
    ]


@dataclass
class Spectrum:
    x: np.ndarray
    y: np.ndarray
    name: str
    source: str = ""
    temperature: float | None = None
    color: str = COLORS[0]
    visible: bool = True
    label: str = ""
    uid: str = field(default_factory=lambda: uuid.uuid4().hex)

    def __post_init__(self):
        x = np.array(self.x, dtype=np.float64, copy=True)
        y = np.array(self.y, dtype=np.float64, copy=True)
        if x.ndim != 1 or y.shape != x.shape or x.size < 2:
            raise ValueError(
                "Cada espectro precisa de pelo menos dois pares de valores X e Y."
            )
        if not np.isfinite(x).all() or not np.isfinite(y).all():
            raise ValueError("O espectro contém NaN ou valores infinitos.")
        dx = np.diff(x)
        if not (np.all(dx > 0) or np.all(dx < 0)):
            raise ValueError(
                "O eixo Raman precisa ser crescente ou decrescente, sem valores repetidos."
            )
        # Keep the original sample order, including descending acquisitions.
        x.setflags(write=False)
        y.setflags(write=False)
        self.x, self.y = x, y
        self.name = str(self.name)
        self.label = str(self.label)
        if self.temperature is not None:
            self.temperature = float(self.temperature)
            if not math.isfinite(self.temperature) or self.temperature < 0:
                raise ValueError(
                    "A temperatura precisa ser um número finito maior ou igual a zero."
                )
        if not re.fullmatch(r"#[0-9a-fA-F]{6}", self.color):
            raise ValueError("A cor do espectro é inválida.")

    @property
    def title(self):
        if self.label:
            return self.label
        if self.temperature is not None:
            suffix = " · volta" if "volta" in self.name.casefold() else ""
            return f"{self.temperature:g} K{suffix}"
        return Path(self.name).stem

    @property
    def bounds(self):
        return float(self.x.min()), float(self.x.max())

    @property
    def fingerprint(self):
        digest = hashlib.sha256()
        digest.update(self.x.tobytes())
        digest.update(self.y.tobytes())
        return digest.hexdigest()


def _numeric_line(line):
    raw = line.strip()
    if not raw or raw.startswith(("#", "//", "%")):
        return None
    if "\t" in raw:
        parts, decimal = raw.split("\t"), True
    elif ";" in raw:
        parts, decimal = raw.split(";"), True
    elif "," in raw and len(raw.split()) == 2:
        parts, decimal = raw.split(), True
    elif "," in raw:
        parts, decimal = raw.split(","), False
    else:
        parts, decimal = raw.split(), False
    if len(parts) < 2:
        return None
    try:
        values = [
            float(
                p.strip().strip('"').replace("−", "-").replace(",", ".")
                if decimal
                else p.strip().strip('"').replace("−", "-")
            )
            for p in parts
        ]
    except ValueError:
        return None
    return values


def read_spectrum(path, color=COLORS[0]):
    """Read the longest contiguous table; reject maps and malformed tables.

    Headers before/after the table are allowed. Numeric rows with NaN/Inf or
    varying column counts are retained and rejected, rather than silently
    cutting away a damaged portion of the spectrum.
    """
    path = Path(path)
    raw = path.read_bytes()
    if b"\x00" in raw:
        raise ValueError(
            "Arquivo binário. Exporte o espectro como TXT ou CSV com duas colunas."
        )
    for encoding in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            text = raw.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    blocks, current = [], []
    for line in text.splitlines():
        values = _numeric_line(line)
        if values is None:
            if current:
                blocks.append(current)
                current = []
        else:
            current.append(values)
    if current:
        blocks.append(current)
    if not blocks or len(max(blocks, key=len)) < 2:
        raise ValueError(
            "Não foi encontrada uma tabela espectral com pelo menos duas linhas."
        )
    block = max(blocks, key=len)
    sizes = {len(row) for row in block}
    if sizes != {2}:
        raise ValueError(
            "Use duas colunas: Raman shift e intensidade. Para arquivos de mapa, abra Raman Map."
        )
    data = np.asarray(block, dtype=np.float64)
    return Spectrum(
        data[:, 0],
        data[:, 1],
        path.name,
        str(path.resolve()),
        temperature_from_name(path.name),
        color,
    )


def spectral_groups(spectra):
    """Group overlapping spectral windows; never join or interpolate samples.

    Membership uses interval overlap. Windows joined by a short overlap remain
    distinct curves, and the UI warns when their measured ranges differ.
    """
    groups = []
    for spectrum in sorted(spectra, key=lambda s: s.bounds[0]):
        lo, hi = spectrum.bounds
        if groups and lo <= groups[-1][1]:
            groups[-1][1] = max(hi, groups[-1][1])
            groups[-1][2].append(spectrum.uid)
        else:
            groups.append([lo, hi, [spectrum.uid]])
    return groups


def common_range(spectra):
    if not spectra:
        return None
    lo, hi = max(s.bounds[0] for s in spectra), min(s.bounds[1] for s in spectra)
    return (lo, hi) if lo < hi else None


def sort_by_temperature(spectra):
    # Stable sort preserves the measured order for repeated temperatures.
    return sorted(
        spectra,
        key=lambda s: (
            s.temperature is None,
            s.temperature if s.temperature is not None else math.inf,
        ),
    )


def automatic_spacing(spectra, align=False, xref=None):
    if not spectra:
        return 1.0
    ys = [np.array(s.y, copy=True) for s in spectra]
    if align:
        shifts = reference_shifts(spectra, xref)
        ys = [y + shift for y, shift in zip(ys, shifts)]
    span = max(float(np.ptp(y)) for y in ys)
    if not math.isfinite(span):
        raise ValueError(
            "A amplitude dos dados é grande demais para calcular o espaçamento."
        )
    span = span or max(abs(float(ys[0][0])) * 0.05, 1.0)
    needed = max(
        (float(ys[i - 1].max() - ys[i].min()) for i in range(1, len(ys))), default=span
    )
    value = max(0.0, needed) + 0.12 * span
    if not math.isfinite(value):
        raise ValueError("O espaçamento calculado não é finito.")
    return value


def reference_shifts(spectra, xref):
    bounds = common_range(spectra)
    if bounds is None:
        raise ValueError(
            "As curvas visíveis não possuem uma faixa Raman comum para o alinhamento."
        )
    if xref is None or not math.isfinite(xref) or not bounds[0] <= xref <= bounds[1]:
        raise ValueError(
            f"Escolha a referência entre {bounds[0]:g} e {bounds[1]:g} cm⁻¹."
        )
    levels = [float(s.y[np.argmin(np.abs(s.x - xref))]) for s in spectra]
    return [levels[0] - value for value in levels]


def display_curves(spectra, mode="cascade", spacing=None, align=False, xref=None):
    """Return (spectrum, plotted_y, additive_shift); inputs remain read-only."""
    if mode not in ("overlay", "cascade", "waterfall"):
        raise ValueError("Modo de visualização desconhecido.")
    if not spectra:
        return []
    alignment = (
        reference_shifts(spectra, xref)
        if align and mode != "overlay"
        else [0.0] * len(spectra)
    )
    if spacing is None:
        spacing = automatic_spacing(spectra, align and mode != "overlay", xref)
    spacing = float(spacing)
    if not math.isfinite(spacing) or spacing < 0:
        raise ValueError(
            "O espaçamento deve ser um número finito maior ou igual a zero."
        )
    result = []
    for index, spectrum in enumerate(spectra):
        shift = alignment[index] + (index * spacing if mode == "cascade" else 0.0)
        with np.errstate(over="ignore", invalid="ignore"):
            displayed = spectrum.y + shift
        if not np.isfinite(displayed).all():
            raise ValueError(
                "O deslocamento excedeu o limite numérico. Reduza o espaçamento."
            )
        result.append((spectrum, displayed, shift))
    return result


DEFAULT_SETTINGS = {
    "mode": "cascade",
    "automatic": True,
    "spacing": 1.0,
    "align": False,
    "xref": None,
    "labels": True,
    "linewidth": 1.2,
    "temperature_axis": True,
}


def validate_settings(settings):
    result = dict(DEFAULT_SETTINGS)
    result.update({k: v for k, v in settings.items() if k in result})
    if result["mode"] not in ("overlay", "cascade", "waterfall"):
        raise ValueError("Modo de visualização inválido no projeto.")
    for key in ("automatic", "align", "labels", "temperature_axis"):
        if type(result[key]) is not bool:
            raise ValueError(f"Opção inválida no projeto: {key}.")
    for key in ("spacing", "linewidth"):
        result[key] = float(result[key])
        if (
            not math.isfinite(result[key])
            or result[key] < 0
            or (key == "linewidth" and not 0.1 <= result[key] <= 10)
        ):
            raise ValueError(f"Valor inválido no projeto: {key}.")
    if result["xref"] is not None:
        result["xref"] = float(result["xref"])
        if not math.isfinite(result["xref"]):
            raise ValueError("Referência Raman inválida no projeto.")
    return result


def save_project(path, spectra, settings):
    """Self-contained project; replacing a saved project is atomic."""
    document = {
        "format": "IMESPEC",
        "schema": 1,
        "version": "1.4.1",
        "units": {"x": "cm^-1", "y": "a.u.", "temperature": "K"},
        "settings": validate_settings(settings),
        "spectra": [],
    }
    for s in spectra:
        document["spectra"].append(
            {
                "uid": s.uid,
                "name": s.name,
                "source": s.source,
                "temperature": s.temperature,
                "color": s.color,
                "visible": s.visible,
                "label": s.label,
                "sha256_xy": s.fingerprint,
                "x": s.x.tolist(),
                "y": s.y.tolist(),
            }
        )
    path = Path(path)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent, suffix=".tmp", delete=False
        ) as stream:
            temporary = stream.name
            json.dump(
                document,
                stream,
                ensure_ascii=False,
                allow_nan=False,
                separators=(",", ":"),
            )
        os.replace(temporary, path)
    finally:
        if temporary and os.path.exists(temporary):
            os.unlink(temporary)


def load_project(path):
    path = Path(path)
    if path.stat().st_size > 200 * 1024 * 1024:
        raise ValueError("O projeto ultrapassa o limite de 200 MB desta versão.")
    document = json.loads(path.read_text(encoding="utf-8"))
    if document.get("format") != "IMESPEC" or document.get("schema") != 1:
        raise ValueError("Formato de projeto IMESPEC não reconhecido.")
    if document.get("units") != {"x": "cm^-1", "y": "a.u.", "temperature": "K"}:
        raise ValueError("As unidades do projeto não são compatíveis com esta versão.")
    settings = validate_settings(document["settings"])
    spectra, ids = [], set()
    for row in document["spectra"]:
        if row["uid"] in ids or type(row["visible"]) is not bool:
            raise ValueError("A lista de espectros do projeto é inválida.")
        s = Spectrum(
            row["x"],
            row["y"],
            row["name"],
            row.get("source", ""),
            row["temperature"],
            row["color"],
            row["visible"],
            row["label"],
            row["uid"],
        )
        if s.fingerprint != row["sha256_xy"]:
            raise ValueError(
                f"Os dados do espectro {s.name} não correspondem à verificação de integridade."
            )
        spectra.append(s)
        ids.add(s.uid)
    if not spectra:
        raise ValueError("O projeto não contém espectros.")
    return spectra, settings
