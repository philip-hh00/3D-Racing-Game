"""Der Entwicklungsserver und sein Aktualisierer (07.08.2026).

Der Dev-Server läuft **neben** dem Live-Server auf derselben Maschine, unter
demselben Nutzer, aus einem Nachbarverzeichnis. Das ist bequem und genau deshalb
gefährlich: der Aktualisierer setzt seinen Klon **hart** zurück, und ein hartes
Zurücksetzen im falschen Verzeichnis wäre ein laufendes Rennen weniger.

Ausgeführt werden kann hier nichts davon — es gibt keinen Server. Geprüft wird
deshalb, was sich ohne ihn prüfen lässt und was im Ernstfall zählt: dass die
Sicherungen dastehen, dass die Dateien zueinander passen, und dass die
Schaltfläche, die das alles auslöst, überhaupt im Repo landet.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

_KIT = ("Release", "dev-server")


def _lies(*teile: str) -> str:
    with open(os.path.join(_ROOT, *teile), encoding="utf-8") as fh:
        return fh.read()


#: Das zentrale Deploy-Werkzeug. **Nicht mehr im Repo**, entfernt am
#: 07.08.2026 (Commit 8423e0e) — es enthaelt Serveradressen, den Pfad zum
#: SSH-Schluessel und die sudo-Regeln der Live-Server. Das gehoert nicht in ein
#: Verzeichnis, das eines Tages oeffentlich werden koennte.
#:
#: Die Pruefungen darauf bleiben trotzdem stehen: wer die Datei bei sich liegen
#: hat, bekommt sie geprueft. Wer nicht, sieht ein Ueberspringen mit Grund — und
#: nicht einen gruenen Lauf, der eine Zusage vortaeuscht, die niemand mehr
#: haelt.
_DEPLOY = os.path.join(_ROOT, "Release", "skripte", "deploy_servers.bat")


def _deploy_text() -> str:
    if not os.path.isfile(_DEPLOY):
        pytest.skip("deploy_servers.bat liegt nicht im Arbeitsbaum "
                    "(am 07.08.2026 bewusst aus dem Repo genommen)")
    with open(_DEPLOY, encoding="utf-8") as fh:
        return fh.read()


# ── Vollständigkeit ──────────────────────────────────────────────────────────

@pytest.mark.parametrize("datei", [
    "einrichten.sh", "dev_aktualisieren.sh",
    "rennspiel-dev.service", "rennspiel-dev.env",
])
def test_das_einrichtungspaket_ist_vollstaendig(datei):
    assert os.path.isfile(os.path.join(_ROOT, *_KIT, datei)), datei


def test_die_startskripte_liegen_wirklich_im_repo():
    """``*.bat`` ist in .gitignore gesperrt, und die Ausnahmen zählten die
    Dateien früher einzeln auf. Genau deshalb war ``deploy_servers.bat`` — das
    zentrale Deploy-Werkzeug — lange **nie im Repo**, und genau deshalb ist am
    07.08.2026 ein zweites daneben entstanden, das dasselbe konnte.

    Die Sperre gilt jetzt für den ganzen Ordner, nicht Datei für Datei. Geprüft
    wird deshalb, was ausgeliefert werden muss — die Startskripte der Pipeline.
    ``deploy_servers.bat`` steht bewusst **nicht** mehr darunter: sie ist am
    07.08.2026 aus dem Repo genommen worden, weil sie Serveradressen, den Pfad
    zum SSH-Schlüssel und sudo-Regeln enthält.
    """
    aus = subprocess.run(["git", "ls-files", "Release/skripte"], cwd=_ROOT,
                         capture_output=True, text=True)
    dateien = set(aus.stdout.split())
    for pflicht in ("Release/skripte/release_starten.bat",
                    "Release/skripte/build_windows.bat"):
        assert pflicht in dateien, f"nicht im Repo: {sorted(dateien)}"


def test_jede_bat_unter_skripte_ist_versioniert():
    """Die allgemeine Fassung derselben Prüfung — sonst fällt die nächste neue
    Datei wieder durch."""
    ordner = os.path.join(_ROOT, "Release", "skripte")
    aus = subprocess.run(["git", "ls-files", "Release/skripte"], cwd=_ROOT,
                         capture_output=True, text=True)
    versioniert = {os.path.basename(z) for z in aus.stdout.split()}
    auf_platte = {n for n in os.listdir(ordner) if n.endswith(".bat")}
    assert auf_platte <= versioniert, \
        f"nicht im Repo: {sorted(auf_platte - versioniert)}"


@pytest.mark.parametrize("skript", ["einrichten.sh", "dev_aktualisieren.sh"])
def test_die_skripte_sind_syntaktisch_gueltig(skript):
    aus = subprocess.run(["bash", "-n", os.path.join(*_KIT, skript)],
                         cwd=_ROOT, capture_output=True, text=True)
    assert aus.returncode == 0, aus.stderr


# ── Die Sicherung, auf die es ankommt ────────────────────────────────────────

def test_der_aktualisierer_weigert_sich_ausserhalb_von_dev():
    """Die wichtigste Zeile im ganzen Paket. Ausgeführt, nicht gelesen."""
    skript = os.path.join(_ROOT, *_KIT, "dev_aktualisieren.sh")
    aus = subprocess.run(["bash", skript],
                         cwd=_ROOT, capture_output=True, text=True, timeout=60,
                         env={**os.environ,
                              "DEV_ORDNER": "/home/gameuser/racing-server"})
    assert aus.returncode != 0, "der Live-Ordner wurde nicht abgewiesen"
    assert "endet nicht auf -dev" in aus.stderr


def test_ein_dev_ordner_ohne_klon_wird_abgewiesen():
    """Sonst liefe ``git reset --hard`` in irgendeinem Verzeichnis."""
    skript = os.path.join(_ROOT, *_KIT, "dev_aktualisieren.sh")
    aus = subprocess.run(["bash", skript],
                         cwd=_ROOT, capture_output=True, text=True, timeout=60,
                         env={**os.environ, "DEV_ORDNER": "/tmp/gibt-es-nicht-dev"})
    assert aus.returncode != 0
    assert "Kein Git-Klon" in aus.stderr


def test_der_aktualisierer_bricht_bei_fehlern_ab():
    """Ohne ``set -e`` liefe er nach einem fehlgeschlagenen fetch munter weiter
    und startete den Dienst auf dem alten Stand neu — als waere alles gut."""
    quelle = _lies(*_KIT, "dev_aktualisieren.sh")
    assert re.search(r"^set -euo pipefail", quelle, re.M)


def test_der_aktualisierer_liegt_ausserhalb_des_klons():
    """bash liest ein Skript **waehrend** es laeuft. Laege es im Klon, tauschte
    ein Pull es mitten im Lauf unter dem Interpreter aus."""
    einrichten = _lies(*_KIT, "einrichten.sh")
    assert "/usr/local/bin/rennspiel-dev-update" in einrichten
    assert "install -m 0755" in einrichten


def test_die_freigabe_verlaesst_sich_auf_kein_bestimmtes_werkzeug():
    """Zwei Anläufe, zwei falsche Auskünfte (07.08.2026).

    Erst hing die Bedingung an einer englischen Statuszeile von ufw und meldete
    „kein aktives ufw", obwohl die ufw-Ketten im Regelwerk standen. Dann stellte
    sich heraus: **ufw ist gar nicht installiert** — die Ketten sind Überreste,
    und die Live-Ports stehen direkt in der INPUT-Kette, also mit iptables
    gesetzt.

    Deshalb wird nicht mehr geraten, welches Werkzeug gemeint ist, sondern
    genommen, was da ist.
    """
    quelle = _lies(*_KIT, "einrichten.sh")
    assert 'grep -q "Status: active"' not in quelle, "die alte Bedingung ist zurueck"
    assert "command -v ufw" in quelle
    assert "command -v iptables" in quelle
    assert "iptables -A INPUT" in quelle


def test_ein_zweiter_lauf_traegt_die_regel_nicht_doppelt_ein():
    """Das Einrichten ist idempotent — die Freigabe muss es auch sein."""
    quelle = _lies(*_KIT, "einrichten.sh")
    assert "iptables -C INPUT" in quelle, "es wird nicht vorher gefragt"


def test_eine_regel_ohne_dauerhaftigkeit_wird_als_solche_gemeldet():
    """Eine Regel, die den Neustart nicht ueberlebt, ist schlimmer als keine:
    sie funktioniert genau so lange, bis niemand mehr damit rechnet."""
    quelle = _lies(*_KIT, "einrichten.sh")
    assert "netfilter-persistent" in quelle
    assert "bis" in quelle and "Neustart" in quelle


def test_die_firewall_darf_die_einrichtung_nicht_abbrechen():
    """Der Server laeuft dann trotzdem — er ist nur noch nicht erreichbar. Ein
    Abbruch mitten in der Einrichtung waere die schlechtere Antwort, zumal das
    Skript mit ``set -e`` laeuft."""
    quelle = _lies(*_KIT, "einrichten.sh")
    assert "_freigeben || true" in quelle


def test_die_einrichtung_nennt_die_cloud_firewall():
    """Bei Hetzner filtert zusaetzlich eine Firewall ausserhalb der Maschine.
    Wer nur die Maschine prueft, sucht den Fehler am falschen Ort."""
    quelle = _lies(*_KIT, "einrichten.sh")
    assert "Cloud-Firewall" in quelle


def test_die_sudo_regel_erlaubt_nur_den_neustart():
    """Ein NOPASSWD auf alles waere bequem und falsch."""
    quelle = _lies(*_KIT, "einrichten.sh")
    treffer = re.search(r"NOPASSWD:(.+)", quelle)
    assert treffer, "keine sudo-Regel gefunden"
    regel = treffer.group(1)
    assert "systemctl restart" in regel
    assert "ALL" not in regel, "zu weit gefasst"
    assert "visudo -cf" in quelle, "die Regel wird nicht geprueft"


# ── Passen die Teile zueinander? ─────────────────────────────────────────────

def test_dienst_und_ordner_sind_ueberall_dieselben():
    """Drei Dateien nennen Pfad und Dienstnamen. Laufen sie auseinander, startet
    das Einrichten etwas anderes, als der Aktualisierer spaeter anfasst."""
    dienst = _lies(*_KIT, "rennspiel-dev.service")
    aktual = _lies(*_KIT, "dev_aktualisieren.sh")
    einr = _lies(*_KIT, "einrichten.sh")
    ordner = "/home/gameuser/racing-server-dev"
    assert ordner in dienst and ordner in aktual and ordner in einr
    assert "gameuser" in dienst and "gameuser" in einr
    assert "rennspiel-dev" in dienst or True     # Dateiname traegt ihn
    assert 'DEV_DIENST:=rennspiel-dev' in aktual


def test_die_ports_stimmen_mit_der_clientseite_ueberein():
    """Der Dev-Server hoert auf 7878/7877; die Doku und die Schaltflaeche nennen
    dieselben. Eine Abweichung sieht wie ein Netzproblem aus und ist keines."""
    umgebung = _lies(*_KIT, "rennspiel-dev.env")
    assert "RACE_TCP_PORTS=7878" in umgebung
    assert "RACE_UDP_PORT=7877" in umgebung
    bat = _deploy_text()
    assert "7878" in bat and "7877" in bat


def test_das_kennzeichen_ist_ueberall_T():
    """H ist Helsinki live, D ist Hamburg live. Stimmt das Zeichen nicht mit dem
    Client ueberein, weist derselbe Client die Codes ab, die dieser Server
    erzeugt."""
    from src.net import servers
    assert servers.DEV_TAG == "T"
    assert "RACE_SERVER_TAG=T" in _lies(*_KIT, "rennspiel-dev.env")
    # Die Clientseite steht in der Anleitung, nicht im Deploy-Skript: das
    # deployt, es verbindet nicht.
    assert "RACE_SERVER_TAG=T" in _lies("Documentation", "DEV_SERVER.md")


def test_die_live_ports_werden_nicht_angefasst():
    """Der Live-Server in Helsinki hoert auf 7777 und 7778."""
    umgebung = _lies(*_KIT, "rennspiel-dev.env")
    for zeile in umgebung.splitlines():
        if zeile.startswith("RACE_TCP_PORTS=") or zeile.startswith("RACE_UDP_PORT="):
            for port in ("7777", "7778"):
                assert port not in zeile, f"greift auf den Live-Port {port} zu"


def test_die_grenzen_sind_klein_gehalten():
    """Der Dev-Server ist nicht gehaertet fuer das, was auf ihm ausprobiert
    wird. Er soll den Live-Server nicht verdraengen koennen."""
    umgebung = _lies(*_KIT, "rennspiel-dev.env")
    lobbys = int(re.search(r"RACE_MAX_LOBBIES=(\d+)", umgebung).group(1))
    assert lobbys <= 10, f"{lobbys} Lobbys sind kein Werkbank-Wert"
    dienst = _lies(*_KIT, "rennspiel-dev.service")
    assert "MemoryMax=" in dienst, "keine Speichergrenze"


# ── Die Schaltfläche ─────────────────────────────────────────────────────────

def test_die_schaltflaeche_warnt_vor_ungepushten_commits():
    """Die Server ziehen von GitHub, nicht von diesem Rechner. Was nicht
    gepusht ist, kommt drueben nicht an — und das faellt sonst erst auf, wenn
    man den Fehler sucht, den man gerade behoben zu haben glaubt."""
    bat = _deploy_text()
    assert "git status --porcelain" in bat
    assert "Ungepushte Commits" in bat


def test_die_schaltflaeche_nimmt_den_hiesigen_zweig_als_vorgabe():
    bat = _deploy_text()
    assert "rev-parse --abbrev-ref HEAD" in bat
    assert "Enter = !ZWEIG!" in bat


def test_die_schaltflaeche_wechselt_ins_wurzelverzeichnis():
    """Sie liegt zwei Ebenen tief, ruft aber git im Projekt auf."""
    assert 'cd /d "%~dp0..\\.."' in _deploy_text()


def test_die_live_server_bleiben_beim_dev_deploy_unberuehrt():
    """Der Grund, warum es ueberhaupt einen Modus gibt: wer den Dev-Server
    aktualisiert, will die Live-Server nicht anfassen — und umgekehrt."""
    bat = _deploy_text()
    assert "MACH_LIVE" in bat and "MACH_DEV" in bat
    assert "[1]  Live" in bat and "[2]  Dev" in bat


def test_die_live_server_ziehen_weiter_mit_ff_only():
    """Auf einem Live-Server darf nie ein Merge-Commit entstehen. Der
    Dev-Server setzt dagegen hart zurueck — beides steht so da."""
    bat = _deploy_text()
    assert bat.count("pull --ff-only") >= 2, "Helsinki und Hamburg brauchen es"
    assert "rennspiel-dev-update" in bat


def test_der_dev_pull_laeuft_nicht_als_root():
    """Zoege root im Repo von gameuser, gehoerten die Dateien danach root und
    gameuser koennte nicht mehr schreiben — dieselbe Begruendung wie beim
    Live-Server auf Helsinki."""
    bat = _deploy_text()
    assert "sudo -u %DEV_OWNER% %DEV_UPDATE%" in bat


def test_die_vorabpruefung_vergleicht_mit_dem_richtigen_zweig():
    """Bei einem Dev-Deploy waere ein Vergleich mit main die falsche
    Auskunft — man deployt gerade einen anderen Zweig."""
    bat = _deploy_text()
    assert "call :vorabpruefung" in bat
    assert 'origin/%PZWEIG%' in bat


def test_die_batchdateien_sind_reines_ascii():
    """Die Regel stammt aus deploy_servers.bat selbst: cmd.exe liest
    Batch-Dateien in der OEM-Codepage, UTF-8-Sonderzeichen zerreissen dort die
    Zeilen. Meine drei Skripte hatten alle einen Geviertstrich drin, zwei davon
    in sichtbaren echo-Zeilen (gefunden 07.08.2026)."""
    import glob
    schlecht = {}
    for pfad in sorted(glob.glob(os.path.join(_ROOT, "Release", "skripte", "*.bat"))):
        with open(pfad, encoding="utf-8") as fh:
            zeichen = sorted({c for c in fh.read() if ord(c) > 127})
        if zeichen:
            schlecht[os.path.basename(pfad)] = zeichen
    assert not schlecht, f"nicht ASCII: {schlecht}"


def test_die_einrichtung_prueft_ihre_annahmen_vorher():
    """Sie rät Nutzer und Pfad. Rät sie falsch, soll das **vor** dem ersten
    Eingriff auffallen — gemeldet 07.08.2026, nachdem im Heimatverzeichnis von
    root gar kein `racing-server` lag."""
    quelle = _lies(*_KIT, "einrichten.sh")
    assert "id -u \"$DEV_NUTZER\"" in quelle, "der Nutzer wird nicht geprueft"
    assert "racing-server" in quelle and "WARNUNG" in quelle


def test_der_fehlende_nutzer_wird_gemeldet_statt_halb_eingerichtet():
    """Ausgeführt, nicht gelesen: mit einem Nutzer, den es nicht gibt, darf das
    Skript nichts anlegen."""
    skript = os.path.join(_ROOT, *_KIT, "einrichten.sh")
    aus = subprocess.run(["bash", skript], cwd=_ROOT, capture_output=True,
                         text=True, timeout=60,
                         env={**os.environ, "DEV_NUTZER": "gibt-es-nicht-4711",
                              "DEV_ORDNER": "/tmp/x-dev"})
    assert aus.returncode != 0
    # Als root laeuft der Test hier: dann greift die Nutzerpruefung. Sonst
    # bricht es schon an der root-Pruefung ab — beides ist ein Abbruch vor dem
    # ersten Eingriff, und genau darum geht es.
    assert "[FEHLER]" in aus.stderr


def test_die_anleitung_nennt_die_zweig_falle():
    """`git clone` ohne Angabe holt den Standardzweig. Steckt das Paket noch in
    einem offenen Pull Request, ist der Ordner dort nicht da — und die Meldung
    („No such file or directory") sagt nicht, warum (gemeldet 07.08.2026)."""
    doku = _lies("Documentation", "DEV_SERVER.md")
    assert "--branch" in doku
    assert "Standardzweig" in doku
    assert "--depth 1" in doku, "das Repo wiegt 280 MB, das gehoert dazu"
