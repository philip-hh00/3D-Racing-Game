"""Namen, die zur Laufzeit nicht da sind (06.08.2026).

Dreimal derselbe Absturz, dreimal erst beim Spieler gefunden:

* 05.08.2026, Streckeneditor: ``NameError: name 'theme' is not defined``
* 05.08.2026, Pausemenü: dieselbe Ursache aus der anderen Richtung
* 06.08.2026, Fahrzeug-Labor: ``theme.ZEIGER`` in ``_draw_params``

Das Muster ist jedes Mal gleich. Zwei Methoden einer Datei holen sich ``theme``
mit einem **lokalen** Import, die dritte verlässt sich darauf, dass er im Modul
steht — tut er aber nicht. Solange die dritte Methode nicht läuft, fällt nichts
auf; sie läuft dann beim Spieler.

Weder ein Importtest noch die Testabdeckung fangen das: die Datei importiert
sauber, und getroffen wird nur der Zweig, der die Zeile ausführt. Gesucht wird
deshalb hier **statisch** — ein Name, der in einer Funktion benutzt, aber weder
dort noch im Modul gebunden wird, ist ein Absturz auf Abruf.

Absichtlich eng gehalten: geprüft werden nur ``name.attribut``-Zugriffe, also
das, was nach einem vergessenen Modulimport aussieht. Verschachtelte Funktionen,
die Namen aus ihrer Umgebung mitnehmen, sind der häufigste falsche Alarm und
werden deshalb mitsamt ihrer Umgebung aufgelöst.
"""
from __future__ import annotations

import ast
import builtins
import os

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_BUILTINS = frozenset(dir(builtins))


def _argument_namen(args: ast.arguments) -> set[str]:
    namen = {a.arg for a in args.posonlyargs + args.args + args.kwonlyargs}
    if args.vararg:
        namen.add(args.vararg.arg)
    if args.kwarg:
        namen.add(args.kwarg.arg)
    return namen


def _gebundene_namen(knoten: ast.AST, mit_argumenten: bool = False) -> set[str]:
    """Alle Namen, die *knoten* in seinem eigenen Namensraum bindet.

    Gesammelt wird über den ganzen Teilbaum — Schleifenziele, ``with … as``,
    ``except … as``, bedingte Importe, Komprehensionen, allesamt Bindungen.
    **Nicht** hinein geht es in verschachtelte Funktionen und Klassen: deren
    lokale Namen gehören ihnen allein, nach außen dringt nur ihr eigener.

    Komprehensionsziele haben in Python streng genommen ihren eigenen
    Namensraum und wären hier zu großzügig gerechnet. Das ist Absicht: ein
    falscher Alarm kostet mehr als ein übersehener Fall, und dieser Test
    stellt nicht die Namensauflösung nach, sondern sucht ein bestimmtes Muster.
    """
    namen: set[str] = set()
    if mit_argumenten and isinstance(knoten, (ast.FunctionDef, ast.AsyncFunctionDef,
                                              ast.Lambda)):
        namen |= _argument_namen(knoten.args)

    stapel: list[ast.AST] = list(ast.iter_child_nodes(knoten))
    while stapel:
        kind = stapel.pop()
        if isinstance(kind, ast.Lambda):
            continue                      # eigener Namensraum, bindet nichts nach außen
        if isinstance(kind, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            namen.add(kind.name)          # nur der Name, nicht der Inhalt
            continue
        if isinstance(kind, ast.Import):
            namen.update(a.asname or a.name.split(".")[0] for a in kind.names)
        elif isinstance(kind, ast.ImportFrom):
            namen.update(a.asname or a.name for a in kind.names)
        elif isinstance(kind, ast.Name) and isinstance(kind.ctx, ast.Store):
            namen.add(kind.id)
        elif isinstance(kind, ast.ExceptHandler) and kind.name:
            namen.add(kind.name)
        elif isinstance(kind, (ast.Global, ast.Nonlocal)):
            namen.update(kind.names)
        stapel.extend(ast.iter_child_nodes(kind))
    return namen


def _freie_zugriffe(pfad: str) -> list[tuple[int, str, str, str]]:
    """(Zeile, Funktion, Name, Attribut) je Zugriff ohne erreichbare Bindung."""
    with open(pfad, encoding="utf-8") as fh:
        baum = ast.parse(fh.read(), pfad)

    funde: list[tuple[int, str, str, str]] = []

    def besuchen(knoten: ast.AST, sichtbar: frozenset[str], name: str) -> None:
        """*knoten* mit eigenem Namensraum prüfen.

        Verschachtelte Definitionen bekommen ihren eigenen Durchgang und werden
        hier übersprungen — sonst würden ihre lokalen Namen dem äußeren Rahmen
        zugerechnet, und der äußere Rahmen ihren.
        """
        eigen = sichtbar | _gebundene_namen(knoten, mit_argumenten=True)
        stapel: list[ast.AST] = list(ast.iter_child_nodes(knoten))
        while stapel:
            kind = stapel.pop()
            if isinstance(kind, ast.Lambda):
                besuchen(kind, frozenset(eigen), name)
                continue
            if isinstance(kind, (ast.FunctionDef, ast.AsyncFunctionDef,
                                 ast.ClassDef)):
                besuchen(kind, frozenset(eigen),
                         f"{name}.{kind.name}" if name else kind.name)
                continue
            if (isinstance(kind, ast.Attribute)
                    and isinstance(kind.value, ast.Name)
                    and kind.value.id not in eigen):
                funde.append((kind.lineno, name, kind.value.id, kind.attr))
            stapel.extend(ast.iter_child_nodes(kind))

    oben = frozenset(_gebundene_namen(baum) | _BUILTINS | {"__file__", "__name__"})
    for kind in baum.body:
        if isinstance(kind, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            besuchen(kind, oben, kind.name)
    return funde


def _quelldateien() -> list[str]:
    dateien = []
    for wurzel, ordner, namen in os.walk(os.path.join(_ROOT, "src")):
        ordner[:] = [o for o in ordner if o != "__pycache__"]
        dateien.extend(os.path.join(wurzel, n) for n in namen if n.endswith(".py"))
    return sorted(dateien)


def test_kein_zugriff_auf_einen_ungebundenen_namen():
    """Der eigentliche Test: dreimal war es ``theme``, beim vierten Mal wäre es
    etwas anderes."""
    funde = []
    for pfad in _quelldateien():
        for zeile, funktion, name, attribut in _freie_zugriffe(pfad):
            kurz = os.path.relpath(pfad, _ROOT)
            funde.append(f"{kurz}:{zeile}  {funktion}()  ->  {name}.{attribut}")
    assert not funde, ("Namen ohne Bindung — das sind Abstürze auf Abruf:\n  "
                       + "\n  ".join(funde))


def test_der_test_findet_den_absturz_vom_06_08():
    """Ohne diese Gegenprobe wäre der Test oben auch dann grün, wenn er gar
    nichts mehr prüft."""
    import tempfile
    quelle = (
        "import pygame\n"
        "\n"
        "class Seite:\n"
        "    def zeichnen(self):\n"
        "        from src.ui import theme\n"
        "        theme.text(self)\n"
        "\n"
        "    def _draw_params(self):\n"
        "        return f'{theme.ZEIGER} '\n"      # genau der Fund vom 06.08.
    )
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False,
                                     encoding="utf-8") as fh:
        fh.write(quelle)
        pfad = fh.name
    try:
        funde = _freie_zugriffe(pfad)
    finally:
        os.unlink(pfad)
    assert [(f[1], f[2], f[3]) for f in funde] == [
        ("Seite._draw_params", "theme", "ZEIGER")]


def test_der_test_meldet_keinen_falschen_alarm_bei_verschachtelten_funktionen():
    """Der häufigste falsche Alarm: eine innere Funktion greift auf einen Namen
    der äußeren zu. Das läuft, und der Test darf es nicht anschwärzen."""
    import tempfile
    quelle = (
        "def zeichnen(screen):\n"
        "    innen = screen.get_rect()\n"
        "    def y_von(wert):\n"
        "        return innen.height * wert\n"
        "    try:\n"
        "        import numpy\n"
        "    except ImportError:\n"
        "        numpy = None\n"
        "    def summe(x):\n"
        "        return numpy.sum(x)\n"
        "    return y_von(0.5), summe\n"
    )
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False,
                                     encoding="utf-8") as fh:
        fh.write(quelle)
        pfad = fh.name
    try:
        assert _freie_zugriffe(pfad) == []
    finally:
        os.unlink(pfad)
