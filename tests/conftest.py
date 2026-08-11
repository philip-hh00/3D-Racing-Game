"""Gemeinsame Testeinrichtung.

pygame wird einmal für den gesamten Testlauf hochgefahren und **nicht** zwischen
den Modulen beendet. Grund: ``theme`` hält einen Cache erzeugter Font-Objekte.
Ein ``pygame.quit()`` macht die ungültig, der Cache merkt das aber nicht — das
nächste Modul erbt dann tote Fonts und scheitert mit
"Invalid font (font module quit since font created)".

Im Spiel tritt das nie auf, dort läuft pygame vom Start bis zum Beenden durch.
Deshalb wird hier die Testumgebung angepasst und nicht der Cache im Spielcode.
"""
from __future__ import annotations

import os

import pytest

# Vor dem pygame-Import setzen: ohne Fenster und ohne Tonausgabe testen.
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")


@pytest.fixture(scope="session", autouse=True)
def pygame_umgebung():
    import pygame
    pygame.init()
    pygame.display.set_mode((1920, 1080))
    yield
    # Bewusst kein pygame.quit(): der Prozess endet ohnehin gleich, und ein
    # Beenden mitten im Lauf zieht anderen Modulen den Font-Cache weg.


@pytest.fixture(scope="session", autouse=True)
def kein_serveranruf():
    """Kein Test ruft beim echten Relay an.

    ``OnlineLobbyPage.enter`` startet ``server_info.fetch_info_async`` — einen
    echten Netzfaden, der die Antwort in eine **modulweite** Variable schreibt.
    Wer danach die Info-Seite zeichnet, sieht die Ankuendigungen des Servers.

    Damit haengt das Ergebnis daran, ob die Maschine ins Netz kommt. Genau das
    ist am 07.08.2026 passiert: auf dem Entwicklungsrechner (hinter einem
    Proxy) kamen keine Ankuendigungen an und die Testsuite war gruen, auf dem
    Bauknecht kamen welche an und zwei Layouttests fielen. Ein Test, der bei
    Netz anders ausgeht als ohne, blockiert Releases nach Wetterlage.

    Wer Ankuendigungen braucht, setzt sie selbst — ``_cached`` oder
    ``get_cached`` mit ``monkeypatch``. Das ist ohnehin die einzige Art, sie
    vorhersagbar zu haben.
    """
    from src.net import server_info

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(server_info, "fetch_info_async", lambda: None)
        mp.setattr(server_info, "fetch_info", lambda timeout=4.0: None)
        mp.setattr(server_info, "_cached", None, raising=False)
        yield


@pytest.fixture(scope="session", autouse=True)
def eigenes_profil(tmp_path_factory):
    """Kein Test schreibt jemals in ``data/settings/profile.json``.

    Das ist keine Vorsichtsmaßnahme, sondern eine Lehre: der Testlauf hat die
    echte Datei schon zweimal überschrieben. Beim ersten Mal landete eine
    Lackierung darin (30.07.2026), beim zweiten Mal wurde sie auf Vorgabewerte
    zurückgesetzt — Benutzername und fünf Bestzeiten weg (02.08.2026). Beide
    Male, weil ein Test einen Weg auslöste, der am Ende ``profile.save()`` ruft;
    beim zweiten Mal war es die neue Statistik, die nach jedem Zielankommen
    sichert.

    Einzelne Tests abzusichern hilft nicht: der Aufruf steckt tief im Spielcode,
    und der nächste Test, der ein Rennen zu Ende fahren lässt, weiß nichts
    davon. Deshalb wird für den **ganzen Lauf** umgelenkt, und das geladene
    Profil verworfen, damit auch nichts aus der echten Datei in die Tests
    sickert.

    Umgelenkt wird das **Verzeichnis für beschreibbare Nutzerdaten**, nicht der
    Profilpfad selbst: so greifen die feineren Umlenkungen einzelner Tests
    weiterhin, und nebenbei landen auch Ghosts und übernommene Strecken im
    tmp-Verzeichnis statt im Arbeitsbaum.
    """
    from src.core import paths, profile

    ordner = tmp_path_factory.mktemp("nutzerdaten")
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(paths, "user_data_dir", lambda: ordner)
        mp.setattr(profile, "_current", None, raising=False)
        yield ordner
