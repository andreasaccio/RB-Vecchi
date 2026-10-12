"""PDF minimo, senza dipendenze: pagine A4 con testo (Helvetica e Helvetica-Bold
in WinAnsiEncoding, quindi accenti italiani ed euro), linee e rettangoli.

Le coordinate partono dall'angolo in alto a sinistra e crescono verso il basso;
la conversione nel sistema PDF (origine in basso a sinistra) è fatta qui.
"""
from __future__ import annotations

from datetime import datetime, timezone

A4 = (595.28, 841.89)

# Larghezze dei glifi (1/1000 di em) dalle metriche standard Adobe, ASCII 32-126.
_HELV = (
    "278 278 355 556 556 889 667 191 333 333 389 584 278 333 278 278 "
    "556 556 556 556 556 556 556 556 556 556 278 278 584 584 584 556 "
    "1015 667 667 722 722 667 611 778 722 278 500 667 556 833 722 778 "
    "667 778 722 667 611 722 667 944 667 667 611 278 278 278 469 556 "
    "333 556 556 500 556 556 278 556 556 222 222 500 222 833 556 556 "
    "556 556 333 500 278 556 500 722 500 500 500 334 260 334 584"
)
_HELV_BOLD = (
    "278 333 474 556 556 889 722 238 333 333 389 584 278 333 278 278 "
    "556 556 556 556 556 556 556 556 556 556 333 333 584 584 584 611 "
    "975 722 722 722 722 667 611 778 722 278 556 722 611 833 722 778 "
    "667 778 722 667 611 722 667 944 667 667 611 333 278 333 584 556 "
    "333 556 611 556 611 556 333 611 611 278 278 556 278 889 611 611 "
    "611 611 389 556 333 611 556 778 556 556 500 389 280 389 584"
)
LARGHEZZE = {
    False: dict(zip(range(32, 127), map(int, _HELV.split()))),
    True: dict(zip(range(32, 127), map(int, _HELV_BOLD.split()))),
}
# Caratteri non ASCII usati nei documenti: lettera base o larghezza nota.
_EQUIVALENTI = {"à": "a", "è": "e", "é": "e", "ì": "i", "ò": "o", "ù": "u",
                "À": "A", "È": "E", "É": "E", "Ì": "I", "Ò": "O", "Ù": "U"}
_SPECIALI = {"€": 556, "·": 278, "–": 556, "—": 1000, "’": 222, "×": 584}


def larghezza(testo: str, corpo: float, grassetto: bool = False) -> float:
    tabella = LARGHEZZE[grassetto]
    totale = 0
    for ch in testo:
        ch = _EQUIVALENTI.get(ch, ch)
        if ord(ch) in tabella:
            totale += tabella[ord(ch)]
        else:
            totale += _SPECIALI.get(ch, 556)
    return totale * corpo / 1000


def _stringa(testo: str) -> bytes:
    grezzo = testo.encode("cp1252", errors="replace")
    return grezzo.replace(b"\\", b"\\\\").replace(b"(", b"\\(").replace(b")", b"\\)")


def _n(x: float) -> str:
    return f"{x:.2f}".rstrip("0").rstrip(".") or "0"


def _colore(rgb: tuple[float, float, float]) -> str:
    return " ".join(_n(c) for c in rgb)


class Documento:
    def __init__(self, titolo: str, larghezza_pagina: float = A4[0],
                 altezza_pagina: float = A4[1]) -> None:
        self.titolo = titolo
        self.w, self.h = larghezza_pagina, altezza_pagina
        self.pagine: list[list[bytes]] = []
        self.nuova_pagina()

    def nuova_pagina(self) -> None:
        self.ops: list[bytes] = []
        self.pagine.append(self.ops)

    def testo(self, x: float, y: float, testo: str, corpo: float = 10,
              grassetto: bool = False, colore=(0.07, 0.09, 0.15), allinea: str = "sinistra") -> None:
        """y è la linea di base del testo, misurata dall'alto."""
        if allinea == "destra":
            x -= larghezza(testo, corpo, grassetto)
        elif allinea == "centro":
            x -= larghezza(testo, corpo, grassetto) / 2
        font = "F2" if grassetto else "F1"
        self.ops.append(
            f"BT /{font} {_n(corpo)} Tf {_colore(colore)} rg {_n(x)} {_n(self.h - y)} Td (".encode()
            + _stringa(testo) + b") Tj ET")

    def linea(self, x1: float, y1: float, x2: float, y2: float, spessore: float = 0.5,
              colore=(0.85, 0.87, 0.9)) -> None:
        self.ops.append(
            f"{_colore(colore)} RG {_n(spessore)} w {_n(x1)} {_n(self.h - y1)} m "
            f"{_n(x2)} {_n(self.h - y2)} l S".encode())

    def rettangolo(self, x: float, y: float, w: float, h: float, riempimento=None,
                   bordo=None, spessore: float = 0.5) -> None:
        """(x, y) è l'angolo in alto a sinistra."""
        base = f"{_n(x)} {_n(self.h - y - h)} {_n(w)} {_n(h)} re"
        if riempimento is not None:
            self.ops.append(f"{_colore(riempimento)} rg {base} f".encode())
        if bordo is not None:
            self.ops.append(f"{_colore(bordo)} RG {_n(spessore)} w {base} S".encode())

    def bytes(self) -> bytes:
        oggetti: list[bytes] = []

        def aggiungi(corpo: bytes) -> int:
            oggetti.append(corpo)
            return len(oggetti)

        catalogo = aggiungi(b"")                       # riempito alla fine
        pagine = aggiungi(b"")
        f1 = aggiungi(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica "
                      b"/Encoding /WinAnsiEncoding >>")
        f2 = aggiungi(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold "
                      b"/Encoding /WinAnsiEncoding >>")
        figli = []
        for ops in self.pagine:
            contenuto = b"\n".join(ops)
            flusso = aggiungi(b"<< /Length %d >>\nstream\n" % len(contenuto)
                              + contenuto + b"\nendstream")
            figli.append(aggiungi(
                f"<< /Type /Page /Parent {pagine} 0 R /MediaBox [0 0 {_n(self.w)} {_n(self.h)}] "
                f"/Resources << /Font << /F1 {f1} 0 R /F2 {f2} 0 R >> >> "
                f"/Contents {flusso} 0 R >>".encode()))
        oggetti[catalogo - 1] = f"<< /Type /Catalog /Pages {pagine} 0 R >>".encode()
        oggetti[pagine - 1] = (f"<< /Type /Pages /Count {len(figli)} /Kids ["
                               + " ".join(f"{n} 0 R" for n in figli) + "] >>").encode()
        adesso = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%SZ")
        # Le stringhe del dizionario Info non sono in WinAnsi: UTF-16BE con BOM.
        titolo = ("feff" + self.titolo.encode("utf-16-be").hex()).encode()
        info = aggiungi(b"<< /Title <" + titolo + b"> /Producer (RB-Vecchi) "
                        + f"/CreationDate (D:{adesso}) >>".encode())

        out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
        posizioni = []
        for i, corpo in enumerate(oggetti, start=1):
            posizioni.append(len(out))
            out += b"%d 0 obj\n" % i + corpo + b"\nendobj\n"
        xref = len(out)
        out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(oggetti) + 1)
        for pos in posizioni:
            out += b"%010d 00000 n \n" % pos
        out += (b"trailer\n<< /Size %d /Root %d 0 R /Info %d 0 R >>\nstartxref\n%d\n%%%%EOF\n"
                % (len(oggetti) + 1, catalogo, info, xref))
        return bytes(out)
