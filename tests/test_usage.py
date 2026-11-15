import json
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.rapoo_vt7.usage import (
    CONFIRM_SECONDS,
    HISTORY_LIMIT,
    JUMP_POINTS,
    MIN_SESSION_SECONDS,
    UsageTracker,
    format_duration,
)


class FakeClock:
    """Relógio controlado (epoch) para testes determinísticos."""

    def __init__(self, start=1000.0):
        self.t = start

    def __call__(self):
        return self.t

    def advance(self, delta):
        self.t += delta


class TrackerCase(unittest.TestCase):
    def setUp(self):
        self._dir = tempfile.TemporaryDirectory()
        self.path = os.path.join(self._dir.name, "usage.json")
        self.clock = FakeClock()
        self.tracker = UsageTracker(path=self.path, clock=self.clock)

    def tearDown(self):
        self._dir.cleanup()

    def new_tracker(self):
        return UsageTracker(path=self.path, clock=self.clock)


class FormatDurationTest(unittest.TestCase):
    def test_none_e_invalido(self):
        self.assertIsNone(format_duration(None))
        self.assertIsNone(format_duration("x"))

    def test_minutos_horas_e_dias(self):
        cases = [
            (0, "0 min"),
            (59, "0 min"),
            (60, "1 min"),
            (3599, "59 min"),
            (3600, "1 h 00 min"),
            (7320, "2 h 02 min"),
            (86399, "23 h 59 min"),
            (86400, "1 d 0 h"),
            (3 * 86400 + 4 * 3600 + 59 * 60, "3 d 4 h"),
        ]
        for seconds, expected in cases:
            self.assertEqual(format_duration(seconds), expected, seconds)

    def test_negativo_vira_zero(self):
        self.assertEqual(format_duration(-50), "0 min")


class SessionLifecycleTest(TrackerCase):
    def test_primeira_leitura_em_descarga_abre_sessao(self):
        self.assertTrue(self.tracker.observe(False, 87))
        self.assertIsNotNone(self.tracker.since)
        self.clock.advance(3600)
        self.assertEqual(self.tracker.elapsed(), 3600.0)

    def test_sessao_sobrevive_ao_reinicio_do_app(self):
        self.tracker.observe(False, 87, now=1000.0)
        self.clock.advance(3 * 86400)
        reloaded = self.new_tracker()
        self.assertEqual(reloaded.since, 1000.0)
        self.assertEqual(reloaded.elapsed(), 3 * 86400)

    def test_carga_confirmada_encerra_sessao(self):
        self.tracker.observe(False, 90, now=1000.0)
        self.tracker.observe(True, 40, now=2000.0)
        self.assertIsNotNone(self.tracker.since)  # ainda pendente
        self.tracker.observe(True, 41, now=2000.0 + CONFIRM_SECONDS)
        self.assertIsNone(self.tracker.since)
        last = self.tracker.last_session()
        self.assertEqual(last["start"], 1000.0)
        # O fim é a PRIMEIRA leitura de carga, não a confirmação.
        self.assertEqual(last["end"], 2000.0)
        self.assertTrue(last["complete"])
        self.assertEqual(last["percent_end"], 90)

    def test_leitura_isolada_de_carga_nao_encerra(self):
        self.tracker.observe(False, 90, now=1000.0)
        self.tracker.observe(True, 89, now=2000.0)
        # Voltou a descarregar antes da confirmação: pico descartado.
        self.tracker.observe(False, 89, now=2030.0)
        self.assertEqual(self.tracker.since, 1000.0)
        self.assertIsNone(self.tracker.last_session())
        self.assertFalse(self.tracker.is_charging())

    def test_carga_sem_sessao_aberta_nao_cria_historico(self):
        self.assertFalse(self.tracker.observe(True, 60, now=1000.0))
        self.assertIsNone(self.tracker.since)
        self.assertIsNone(self.tracker.last_session())

    def test_sessao_curta_encerra_mas_nao_entra_no_historico(self):
        self.tracker.observe(False, 90, now=1000.0)
        self.tracker.observe(True, 90, now=1000.0 + MIN_SESSION_SECONDS / 2)
        self.tracker.observe(True, 90, now=2000.0)
        self.assertIsNone(self.tracker.since)
        self.assertEqual(self.tracker.history(), [])

    def test_tempo_congela_no_inicio_da_carga(self):
        self.tracker.observe(False, 90, now=1000.0)
        self.tracker.observe(True, 90, now=2000.0)
        self.clock.advance(5000)
        # Carga ainda não confirmada, mas o "sem recarregar" parou em 2000.
        self.assertEqual(self.tracker.elapsed(), 1000.0)

    def test_reset_descarta_sessao_atual_e_reinicia(self):
        self.tracker.observe(False, 30, now=1000.0)
        self.tracker.reset(now=5000.0)
        self.assertEqual(self.tracker.since, 5000.0)
        self.assertEqual(self.tracker.history(), [])


class PercentJumpTest(TrackerCase):
    def test_salto_de_porcentagem_nao_zera_contagem(self):
        self.tracker.observe(False, 40, now=1000.0)
        self.tracker.observe(False, 40 + JUMP_POINTS + 1, now=2000.0)
        self.assertEqual(self.tracker.since, 1000.0)
        self.assertEqual(self.tracker.recalibrations, 1)
        self.assertEqual(self.tracker.elapsed(now=2000.0), 1000.0)

    def test_salto_pequeno_nao_conta(self):
        self.tracker.observe(False, 40, now=1000.0)
        self.assertTrue(
            not self.tracker.observe(False, 40 + JUMP_POINTS, now=2000.0)
        )
        self.assertEqual(self.tracker.recalibrations, 0)

    def test_oscilacao_no_limite_conta_uma_vez(self):
        for index, pct in enumerate((40, 46, 45, 46, 44, 45)):
            self.tracker.observe(False, pct, now=1000.0 + index)
        self.assertEqual(self.tracker.recalibrations, 1)

    def test_salto_persistido_no_reinicio(self):
        self.tracker.observe(False, 40, now=1000.0)
        self.tracker.observe(False, 70, now=2000.0)
        self.assertEqual(self.new_tracker().recalibrations, 1)

    def test_porcentagem_ausente_ou_invalida(self):
        self.tracker.observe(False, None, now=1000.0)
        self.tracker.observe(False, 250, now=2000.0)
        self.tracker.observe(False, -3, now=3000.0)
        self.assertEqual(self.tracker.since, 1000.0)
        self.assertEqual(self.tracker.recalibrations, 0)


class HistoryTest(TrackerCase):
    def _close_session(self, start, end, percent=50):
        tracker = self.tracker
        tracker.observe(False, 90, now=start)
        tracker.observe(True, 90, now=end)
        tracker.observe(True, 90, now=end + CONFIRM_SECONDS + 1)

    def test_media_ignora_sessoes_incompletas(self):
        self._close_session(0, 86400)
        self._close_session(100000, 100000 + 2 * 86400)
        self.assertEqual(self.tracker.average_session(), 1.5 * 86400)

    def test_historico_limitado(self):
        limit = 3
        tracker = UsageTracker(
            path=self.path, clock=self.clock, history=limit
        )
        for index in range(limit + 2):
            start = index * 100000.0
            tracker.observe(False, 90, now=start)
            tracker.observe(True, 90, now=start + 86400)
            tracker.observe(
                True, 90, now=start + 86400 + CONFIRM_SECONDS + 1
            )
        self.assertEqual(len(tracker.history()), limit)
        self.assertEqual(
            tracker.history()[-1]["start"], (limit + 1) * 100000.0
        )

    def test_arquivo_corrompido_e_ignorado(self):
        with open(self.path, "w", encoding="utf-8") as handle:
            handle.write("{nao-e-json")
        tracker = self.new_tracker()
        self.assertIsNone(tracker.since)
        tracker.observe(False, 50, now=1000.0)
        self.assertEqual(tracker.since, 1000.0)

    def test_historico_invalido_na_leitura(self):
        with open(self.path, "w", encoding="utf-8") as handle:
            json.dump(
                {
                    "since": "x",
                    "history": [
                        {"start": 10, "end": 5},
                        {"start": 10, "end": 20},
                        "lixo",
                        {"start": None, "end": 3},
                    ],
                },
                handle,
            )
        tracker = self.new_tracker()
        self.assertIsNone(tracker.since)
        self.assertEqual(len(tracker.history()), 1)
        self.assertEqual(tracker.history()[0]["start"], 10.0)

    def test_sem_arquivo_tmp_apos_salvar(self):
        self.tracker.observe(False, 50, now=1000.0)
        self.assertFalse(os.path.exists(self.path + ".tmp"))
        self.assertTrue(os.path.exists(self.path))


class RefreshUsageTest(unittest.TestCase):
    """Integração com `RapooApp._refresh_usage` (sem GTK real)."""

    def _app(self, charging=False, elapsed=3 * 86400, lang="pt_BR"):
        from src.rapoo_vt7 import main

        app = main.RapooApp.__new__(main.RapooApp)
        app._usage = mock.Mock()
        app._usage.elapsed.return_value = elapsed
        app._usage.is_charging.return_value = charging
        app._usage.since = 1000.0
        app._usage.last_session.return_value = {"start": 0, "end": 86400}
        app._window = mock.Mock()
        app._window._lang = lang
        app._tray = mock.Mock()
        app._refresh_usage()
        return app

    def test_texto_do_tempo_sem_recarregar(self):
        app = self._app()
        text, tooltip = app._window.set_usage.call_args[0]
        self.assertEqual(text, "Sem recarregar há 3 d 0 h")
        self.assertIn("Iniciada em", tooltip)
        app._tray.set_usage.assert_called_once_with(text)

    def test_tooltip_mostra_a_media(self):
        app = self._app()
        app._usage.average_session.return_value = 2 * 86400
        app._usage_last = None
        app._refresh_usage()
        tooltip = app._window.set_usage.call_args[0][1]
        self.assertIn("média 2 d 0 h", tooltip)

    def test_idioma_ingles(self):
        app = self._app(lang="en")
        text = app._window.set_usage.call_args[0][0]
        self.assertEqual(text, "Not recharged for 3 d 0 h")

    def test_carregando_mostra_a_ultima_sessao(self):
        app = self._app(charging=True)
        text = app._window.set_usage.call_args[0][0]
        self.assertEqual(text, "Carregando agora · última sessão 1 d 0 h")

    def test_sem_sessao_mostra_texto_neutro(self):
        app = self._app(elapsed=None)
        text = app._window.set_usage.call_args[0][0]
        self.assertEqual(text, "Sem recarregar: --")

    def test_sem_tracker_nao_levanta(self):
        from src.rapoo_vt7 import main

        app = main.RapooApp.__new__(main.RapooApp)
        app._window = mock.Mock()
        app._window._lang = "pt_BR"
        app._refresh_usage()  # sem `_usage`: no-op silencioso

    def test_reset_zera_a_contagem(self):
        from src.rapoo_vt7 import main

        app = main.RapooApp.__new__(main.RapooApp)
        app._usage = mock.Mock()
        app._usage.last_session.return_value = None
        app._usage.elapsed.return_value = None
        app._usage.since = None
        app._window = mock.Mock()
        app._window._lang = "pt_BR"
        app._tray = mock.Mock()
        app._on_reset_usage()
        app._usage.reset.assert_called_once_with()

    def test_cabo_usb_conta_como_carga(self):
        from src.rapoo_vt7 import main

        app = main.RapooApp.__new__(main.RapooApp)
        app._usage = mock.Mock()
        app._usage.elapsed.return_value = None
        app._usage.is_charging.return_value = False
        app._usage.since = None
        app._usage.last_session.return_value = None
        app._window = mock.Mock()
        app._window._lang = "pt_BR"
        app._tray = mock.Mock()
        app._observe_usage(False, 100, mode=2)
        app._usage.observe.assert_called_once_with(True, 100)
        self.assertTrue(app._usage_charging)

    def test_wireless_nao_inventa_carga(self):
        from src.rapoo_vt7 import main

        app = main.RapooApp.__new__(main.RapooApp)
        app._usage = mock.Mock()
        app._usage.elapsed.return_value = None
        app._usage.is_charging.return_value = False
        app._usage.since = None
        app._usage.last_session.return_value = None
        app._window = mock.Mock()
        app._window._lang = "pt_BR"
        app._tray = mock.Mock()
        app._observe_usage(False, 80, mode=0)
        app._usage.observe.assert_called_once_with(False, 80)
        self.assertFalse(app._usage_charging)

    def test_tick_mantem_o_timeout_vivo(self):
        from src.rapoo_vt7 import main

        app = main.RapooApp.__new__(main.RapooApp)
        app._refresh_usage = mock.Mock()
        self.assertTrue(app._tick_usage())
        app._refresh_usage.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
