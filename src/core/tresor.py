"""Profilablage: verschlüsselt, signiert, mit Sicherung (Releaseplan E4).

**Mit offenem Visier.** Das hier ist eine *Bremsschwelle*, keine
Sicherheitsmaßnahme. Der Schlüssel steht drei Zeilen weiter unten im Klartext
und muss das auch — das Spiel liest die Datei ohne Rückfrage, also wird der
Schlüssel mitgeliefert, und was mitgeliefert wird, lässt sich herausholen.
Echter Schutz ginge nur serverseitig mit Benutzerkonten; bei kosmetischen
Belohnungen in einem kostenlosen Spiel wäre das der falsche Aufwand. Was diese
Datei erreicht: wer sich zwanzig Siege schenken will, muss es wollen, und nicht
nur eine Zahl in einer offenen JSON-Datei überschreiben.

Der Behälter bleibt **Text**. Ein Profil ist nach dem Umstellen weiterhin eine
JSON-Datei mit lesbaren Feldnamen, nur der Inhalt ist ein Base64-Block. Das ist
kein Zufall: eine Datei, die plötzlich binär ist, lässt sich weder in einem
Fehlerbericht zeigen noch in der Versionsverwaltung ansehen.

Drei Dinge sind getrennt und sollen es bleiben:

* **Verschlüsseln** — XOR gegen einen SHA-256-Strom. Kein Blockchiffre-Aufbau,
  keine Bibliothek, kein Eintrag in ``requirements.txt``.
* **Signieren** — HMAC-SHA256 über den Geheimtext (encrypt-then-MAC). Damit
  fällt jede Änderung auf, statt sich als Zahlensalat zu entladen.
* **Sichern** — vor jedem Schreiben wandert die vorherige Fassung nach
  ``<name>.bak``, aber nur, wenn sie heil war. Sonst überschriebe eine kaputte
  Datei die letzte gute Sicherung, und genau die soll sie retten.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets

#: Kennung des Behälterformats. Steht im Klartext in der Datei, damit ein
#: Klartextprofil von vorher am fehlenden Feld erkennbar bleibt.
FORMAT = "rp1"

#: Der Schlüssel. Er liegt hier offen, und er sagt selbst, was er ist.
_SCHLUESSEL = b"2D-Racing-Game/Profil/v1 - Bremsschwelle, kein Schutz"

#: Steht unverschlüsselt in jeder Datei. Wer sie öffnet, soll nicht raten
#: müssen, was er da vor sich hat.
HINWEIS = ("Verschluesselt und signiert, damit Zaehler nicht aus Versehen oder "
           "nebenbei verstellt werden. Der Schluessel liegt im Spiel - das ist "
           "eine Bremsschwelle, kein Schutz. Sicherung: profile.bak")

_NONCE_LAENGE = 16


# ---------------------------------------------------------------------------
# Kern
# ---------------------------------------------------------------------------
def _strom(laenge: int, nonce: bytes) -> bytes:
    """Schlüsselstrom aus SHA-256, blockweise durchgezählt."""
    teile, z = [], 0
    erzeugt = 0
    while erzeugt < laenge:
        teile.append(hashlib.sha256(
            _SCHLUESSEL + b"|strom|" + nonce + z.to_bytes(4, "big")).digest())
        erzeugt += 32
        z += 1
    return b"".join(teile)[:laenge]


def _signieren(nonce: bytes, geheim: bytes) -> str:
    """HMAC über den **Geheimtext** — encrypt-then-MAC.

    Andersherum (erst signieren, dann verschlüsseln) müsste zum Prüfen erst
    entschlüsselt werden, also müsste fremder Inhalt verarbeitet werden, bevor
    feststeht, ob er echt ist. Die Reihenfolge ist der ganze Trick daran.
    """
    return hmac.new(_SCHLUESSEL + b"|sig|", nonce + geheim,
                    hashlib.sha256).hexdigest()


def packen(klartext: str) -> str:
    """Klartext in den Behälter (ein JSON-Text) legen."""
    nonce = secrets.token_bytes(_NONCE_LAENGE)
    roh = klartext.encode("utf-8")
    geheim = bytes(a ^ b for a, b in zip(roh, _strom(len(roh), nonce)))
    return json.dumps({
        "format": FORMAT,
        "hinweis": HINWEIS,
        "nonce": nonce.hex(),
        "sig": _signieren(nonce, geheim),
        "data": base64.b64encode(geheim).decode("ascii"),
    }, indent=2, ensure_ascii=False)


def ist_behaelter(text: str) -> bool:
    """Ob *text* wie eine verschlüsselte Ablage aussieht (ungeprüft)."""
    try:
        return json.loads(text).get("format") == FORMAT
    except Exception:
        return False


def entpacken(text: str) -> str | None:
    """Behälter zurück in Klartext. ``None``, wenn irgendetwas nicht stimmt.

    Ein Rückgabewert statt einer Ausnahme: der Aufrufer soll auf die Sicherung
    ausweichen können, und das ist kein Ausnahmefall, sondern der vorgesehene
    zweite Versuch.
    """
    try:
        d = json.loads(text)
        if not isinstance(d, dict) or d.get("format") != FORMAT:
            return None
        nonce = bytes.fromhex(str(d["nonce"]))
        geheim = base64.b64decode(str(d["data"]).encode("ascii"), validate=True)
        # Zeitkonstant vergleichen. Hier bringt das nichts (die Datei liegt auf
        # derselben Platte wie der Angreifer), es ist aber die Gewohnheit, die
        # man beibehalten will, wenn dieselbe Stelle einmal übers Netz geht.
        if not hmac.compare_digest(_signieren(nonce, geheim), str(d["sig"])):
            return None
        return bytes(a ^ b for a, b in
                     zip(geheim, _strom(len(geheim), nonce))).decode("utf-8")
    except Exception:
        return None


def _heil(text: str) -> bool:
    """Ob *text* ein brauchbares Profil enthält — verschlüsselt oder Klartext.

    Klartext zählt mit, weil ein Profil von vor der Umstellung genauso
    sicherungswürdig ist wie ein neues.
    """
    if ist_behaelter(text):
        klar = entpacken(text)
    else:
        klar = text
    if klar is None:
        return False
    try:
        return isinstance(json.loads(klar), dict)
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Dateien
# ---------------------------------------------------------------------------
def bak_pfad(pfad: str) -> str:
    return os.path.splitext(pfad)[0] + ".bak"


def _datei_lesen(pfad: str) -> str | None:
    try:
        with open(pfad, encoding="utf-8") as f:
            return f.read()
    except Exception:
        return None


def lesen(pfad: str) -> str | None:
    """Klartext aus *pfad*, notfalls aus der Sicherung. ``None``: nichts da.

    Reihenfolge: Hauptdatei entschlüsseln — klappt das nicht, ist sie vielleicht
    noch Klartext von vor der Umstellung (dann wird sie übernommen) — und erst
    wenn auch das nichts ergibt, kommt ``.bak`` an die Reihe. Verloren ist dann
    höchstens die letzte Änderung statt allem.
    """
    for kandidat in (pfad, bak_pfad(pfad)):
        text = _datei_lesen(kandidat)
        if text is None:
            continue
        if ist_behaelter(text):
            klar = entpacken(text)
            if klar is not None:
                return klar
            continue          # beschädigt oder verbogen: nächste Datei
        if _heil(text):
            return text       # Klartext von vor der Umstellung
    return None


def schreiben(pfad: str, klartext: str) -> None:
    """*klartext* verschlüsselt ablegen, die vorherige Fassung sichern.

    Geschrieben wird erst daneben und dann umbenannt: ``os.replace`` ist auf
    allen unterstützten Systemen unteilbar, ein direktes Überschreiben nicht.
    Ein Absturz mitten im Schreiben hinterlässt sonst eine halbe Datei — und
    halbe Dateien sind genau das, wogegen die Sicherung nicht mehr hilft, wenn
    sie schon überschrieben wurde.
    """
    behaelter = packen(klartext)
    tmp = pfad + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(behaelter)
        f.flush()
        try:
            os.fsync(f.fileno())
        except OSError:
            pass              # nicht jedes Dateisystem kann das
    alt = _datei_lesen(pfad)
    if alt is not None and _heil(alt):
        try:
            with open(bak_pfad(pfad), "w", encoding="utf-8") as f:
                f.write(alt)
        except OSError:
            pass              # ohne Sicherung weiterzuschreiben ist besser als
            #                   gar nicht zu speichern
    os.replace(tmp, pfad)
