"""Der echte Relay-Server in einem eigenen Ereignisfaden, für Netztests.

Diese Klasse stand am 06.08.2026 **dreimal** wortgleich in den Testdateien
(``test_relais_absicherung``, ``test_block_g_online``, ``test_lack_online``) —
und dreimal mit demselben Fehler beim Herunterfahren. Deshalb liegt sie jetzt
hier: ein Ort, eine Begründung.

**Der Fehler.** ``stop()`` rief ``loop.stop()``. Damit hört der Ereignisfaden
mitten in der Arbeit auf, und die ``_handle_tcp``-Coroutinen der noch offenen
Verbindungen bleiben **mittendrin** stehen. Aufgeräumt hat sie irgendwann der
Müllsammler — im Hauptfaden, wo sie beim Abwickeln ihres ``finally`` noch
``_on_disconnect`` aufriefen. Das schrieb in ``srv._wache`` und
``srv._registry``, also in die Globalen des **nächsten** Tests, der längst
frische angelegt hatte.

Sichtbar war das die ganze Zeit: 26 ``PytestUnraisableExceptionWarning`` je
vollem Lauf, alle mit „There is no current event loop in thread 'MainThread'".
Gekostet hat es einen sprunghaften Fehlschlag in
``test_die_gesamtgrenze_gilt_auch_hinter_einem_tunnel`` — dort zählt der Test
offene Verbindungen, und ein fremdes ``_on_disconnect`` drückte den Zähler unter
die Grenze, sodass eine Verbindung angenommen wurde, die abgewiesen gehörte.

Für eine Testsuite, die ab jetzt Releases freigibt, ist genau das das
Schlimmste: ein Fehlschlag, der nichts über den Code aussagt und Releases
zufällig blockiert.

**Die Behebung.** Der Server wartet auf ein Ereignis statt auf ein Future, das
nie fertig wird. ``stop()`` setzt es, bricht die offenen Verbindungen ordentlich
ab, schließt den Ereignisfaden und **wartet auf den Faden**. Erst danach steht
fest, dass nichts mehr in die Globalen des nächsten Tests schreibt.
"""
from __future__ import annotations

import asyncio
import threading


class Relay:
    """Startet ``server.server`` auf einem freien Port im Hintergrund."""

    def __init__(self) -> None:
        # Erst hier, nicht oben: die Testdateien haengen ``server/`` selbst in
        # den Suchpfad und importieren das Modul als ``server``. Beim Laden
        # dieser Datei steht der Pfad noch nicht zwangslaeufig.
        import server as srv
        self._srv = srv
        self.port = 0
        self._loop = asyncio.new_event_loop()
        self._bereit = threading.Event()
        self._halt: asyncio.Event | None = None
        self._faden = threading.Thread(target=self._laufen, daemon=True)

    def _laufen(self) -> None:
        asyncio.set_event_loop(self._loop)

        async def start():
            self._halt = asyncio.Event()
            server = await asyncio.start_server(
                self._srv._handle_tcp, "127.0.0.1", 0)
            self.port = server.sockets[0].getsockname()[1]
            self._bereit.set()
            async with server:
                await self._halt.wait()

        try:
            self._loop.run_until_complete(start())
        except Exception:
            self._bereit.set()
        finally:
            self._aufraeumen()

    def _aufraeumen(self) -> None:
        """Offene Verbindungen abbrechen, bevor der Faden endet."""
        try:
            offen = [t for t in asyncio.all_tasks(self._loop) if not t.done()]
            for t in offen:
                t.cancel()
            if offen:
                self._loop.run_until_complete(
                    asyncio.gather(*offen, return_exceptions=True))
            self._loop.run_until_complete(self._loop.shutdown_asyncgens())
        except Exception:
            pass
        finally:
            self._loop.close()

    def start(self) -> None:
        self._faden.start()
        assert self._bereit.wait(5.0), "Relay ist nicht hochgekommen"

    def stop(self) -> None:
        if self._halt is not None:
            self._loop.call_soon_threadsafe(self._halt.set)
        self._faden.join(5.0)
        assert not self._faden.is_alive(), "Relay laeuft noch"
