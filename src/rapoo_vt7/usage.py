"""Tempo sem recarregar — medido pelo app, não pelo mouse.

O firmware do VT7 **não** expõe timestamp nem contador de carga: só o estado
instantâneo (`status` 0 inválido / 1 descarregando / 2 carregando) e a
porcentagem. Este módulo reconstrói a duração da sessão de uso a partir das
transições observadas enquanto o app está rodando:

- a primeira leitura em descarga abre a sessão;
- "carregando" só encerra a sessão depois de **confirmado** (duas leituras
  separadas por `CONFIRM_SECONDS`), para que um byte de status isolado não
  zere dias de contagem;
- a variação de % **nunca** abre nem encerra sessão: o medidor do mouse
  recalibra ao desligar/religar e a leitura pode subir sem ter havido recarga
  (o salto só é contabilizado como diagnóstico em `recalibrations`);
- o estado vive em disco, então remover o dongle, fechar o app ou reiniciar o
  PC **não** zera a contagem.

Limite assumido: a carga só é vista com o app rodando. Se o mouse carregar com
o PC desligado, a sessão só termina na primeira leitura de "carregando" — o
fim gravado é essa leitura, não o instante real do início da carga.
"""

import json
import os
import time

DEFAULT_PATH = os.path.expanduser("~/.config/rapoo-vt7/usage.json")

# Duas leituras de "carregando" separadas por este intervalo confirmam a
# recarga (histerese contra um byte de status isolado).
CONFIRM_SECONDS = 60.0

# Sessões mais curtas que isto não entram no histórico (evita poluir a média
# com o mouse que só encostou na dock e voltou).
MIN_SESSION_SECONDS = 60.0

HISTORY_LIMIT = 10

# Salto de % para cima durante a descarga: não é recarga (recalibração do
# medidor), apenas registro de diagnóstico.
JUMP_POINTS = 5

_EMPTY_STATE = {
    "since": None,  # início da sessão atual (epoch) ou None
    "since_percent": None,  # % na abertura da sessão
    "last_percent": None,  # última % em descarga
    "max_percent": None,  # maior % da sessão (diagnóstico de recalibração)
    "last_seen": None,  # última atualização em descarga (epoch)
    "charge_seen": None,  # 1ª leitura de "carregando" pendente de confirmação
    "recalibrations": 0,  # saltos de % para cima em descarga (diagnóstico)
    "history": [],  # sessões encerradas
}


def _number(value):
    """Aceita apenas números finitos (int/float); None para o resto."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if value != value or value in (float("inf"), float("-inf")):
        return None
    return float(value)


def _percent(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    value = int(value)
    return value if 0 <= value <= 100 else None


def format_duration(seconds):
    """Duração compacta: "3 d 7 h", "7 h 12 min", "42 min".

    None/inválido -> None (o chamador decide o texto de "sem dados").
    """
    if seconds is None:
        return None
    try:
        total = int(max(0, float(seconds)))
    except (TypeError, ValueError):
        return None
    days, rest = divmod(total, 86400)
    hours, rest = divmod(rest, 3600)
    minutes = rest // 60
    if days:
        return "%d d %d h" % (days, hours)
    if hours:
        return "%d h %02d min" % (hours, minutes)
    return "%d min" % minutes


class UsageTracker:
    """Conta há quanto tempo o mouse está fora da carga.

    `clock` é injetável nos testes (epoch em segundos). `path` permite isolar
    o arquivo de estado; o padrão fica em `~/.config/rapoo-vt7/usage.json`.
    """

    def __init__(self, path=None, clock=time.time, confirm=CONFIRM_SECONDS,
                 history=HISTORY_LIMIT):
        self._path = path or DEFAULT_PATH
        self._clock = clock
        self._confirm = float(confirm)
        self._history_limit = max(0, int(history))
        self._state = self._load()

    # --- leitura do estado ---

    @property
    def path(self):
        return self._path

    @property
    def since(self):
        return self._state["since"]

    @property
    def recalibrations(self):
        return self._state["recalibrations"]

    def is_charging(self):
        """Informa se há uma carga pendente de confirmação em andamento."""
        return self._state["charge_seen"] is not None

    def elapsed(self, now=None):
        """Segundos desde o início da sessão atual (None sem sessão).

        Com uma carga pendente a contagem congela no instante em que a carga
        foi vista pela primeira vez — o tempo "sem recarregar" terminou ali.
        """
        start = self._state["since"]
        if start is None:
            return None
        now = self._now(now)
        end = self._state["charge_seen"]
        if end is None:
            end = now
        return max(0.0, end - start)

    def history(self):
        """Sessões encerradas, da mais antiga para a mais recente."""
        return [dict(entry) for entry in self._state["history"]]

    def last_session(self):
        if not self._state["history"]:
            return None
        return dict(self._state["history"][-1])

    def average_session(self):
        """Média das sessões completas do histórico (None sem dados)."""
        durations = [
            entry["end"] - entry["start"]
            for entry in self._state["history"]
            if entry.get("complete")
        ]
        if not durations:
            return None
        return sum(durations) / len(durations)

    # --- atualização ---

    def observe(self, charging, percent=None, now=None):
        """Registra uma leitura de bateria. Devolve True se o estado mudou de
        forma persistente (sessão aberta/encerrada ou recalibração anotada).

        `charging` é o status do report 7 / 0xAA já normalizado em bool; uma
        leitura inválida não deve chegar aqui (o `BatteryMonitor` filtra).
        """
        now = self._now(now)
        pct = _percent(percent)
        dirty = False
        if charging:
            dirty = self._observe_charging(now)
        else:
            dirty = self._observe_discharging(now, pct)
        if dirty:
            self._save()
        return dirty

    def reset(self, now=None):
        """Marca "recarregado agora": descarta a sessão atual (sem histórico) e
        abre uma nova contagem a partir deste instante.

        Serve de escape quando a recarga aconteceu sem o app rodando (PC
        desligado) — a única situação que a medição não consegue ver.
        """
        now = self._now(now)
        self._state["since"] = now
        self._state["since_percent"] = self._state["last_percent"]
        self._state["max_percent"] = self._state["last_percent"]
        self._state["last_seen"] = now
        self._state["charge_seen"] = None
        self._save()

    def _now(self, now):
        return self._clock() if now is None else float(now)

    def _observe_charging(self, now):
        if self._state["since"] is None:
            # Já estava carregando quando a observação começou: não há sessão
            # aberta para encerrar.
            return False
        seen = self._state["charge_seen"]
        if seen is None:
            self._state["charge_seen"] = now
            return True
        if now - seen < self._confirm:
            return False
        self._close(seen, self._state["last_percent"])
        return True

    def _observe_discharging(self, now, pct):
        dirty = False
        if self._state["charge_seen"] is not None:
            # Leitura de carga isolada (não confirmada): descarta.
            self._state["charge_seen"] = None
            dirty = True
        if self._state["since"] is None:
            self._state["since"] = now
            self._state["since_percent"] = pct
            self._state["max_percent"] = pct
            dirty = True
        elif pct is not None:
            # Compara com o MAIOR valor já visto na sessão (não com a última
            # leitura) para que a oscilação em torno de um limite não infle o
            # diagnóstico.
            peak = self._state["max_percent"]
            if peak is None or pct > peak:
                if peak is not None and pct > peak + JUMP_POINTS:
                    # Recalibração do medidor (desligar/religar sobe a
                    # leitura): NUNCA zera a sessão, só fica registrado.
                    self._state["recalibrations"] += 1
                    dirty = True
                self._state["max_percent"] = pct
        if pct is not None:
            self._state["last_percent"] = pct
        self._state["last_seen"] = now
        return dirty

    def _close(self, end, pct):
        """Encerra a sessão atual gravando-a no histórico (se longa o
        suficiente) e deixa o estado sem sessão."""
        start = self._state["since"]
        self._state["since"] = None
        self._state["since_percent"] = None
        self._state["max_percent"] = None
        self._state["charge_seen"] = None
        if start is None:
            return
        duration = max(0.0, end - start)
        if duration < MIN_SESSION_SECONDS or self._history_limit == 0:
            return
        self._state["history"].append(
            {
                "start": start,
                "end": end,
                "percent_end": pct,
                "complete": True,
            }
        )
        self._state["history"] = self._state["history"][-self._history_limit:]

    # --- persistência ---

    def _load(self):
        state = dict(_EMPTY_STATE)
        state["history"] = []
        try:
            with open(self._path, encoding="utf-8") as handle:
                data = json.load(handle)
        except (OSError, ValueError):
            return state
        if not isinstance(data, dict):
            return state
        for key in ("since", "last_seen", "charge_seen"):
            value = _number(data.get(key))
            if value is not None:
                state[key] = value
        for key in ("since_percent", "last_percent", "max_percent"):
            state[key] = _percent(data.get(key))
        recalibrations = data.get("recalibrations")
        if isinstance(recalibrations, int) and recalibrations >= 0:
            state["recalibrations"] = recalibrations
        history = data.get("history")
        if isinstance(history, list):
            state["history"] = [
                entry
                for entry in (self._clean_entry(item) for item in history)
                if entry is not None
            ][-self._history_limit:]
        return state

    @staticmethod
    def _clean_entry(item):
        if not isinstance(item, dict):
            return None
        start = _number(item.get("start"))
        end = _number(item.get("end"))
        if start is None or end is None or end < start:
            return None
        return {
            "start": start,
            "end": end,
            "percent_end": _percent(item.get("percent_end")),
            "complete": bool(item.get("complete", True)),
        }

    def _save(self):
        """Gravação atômica (tmp + replace); falha de I/O é silenciosa, como em
        `config.py` — a medição é acessório e nunca deve derrubar o app."""
        try:
            directory = os.path.dirname(self._path)
            if directory:
                os.makedirs(directory, exist_ok=True)
            temp = self._path + ".tmp"
            with open(temp, "w", encoding="utf-8") as handle:
                json.dump(self._state, handle, ensure_ascii=False, indent=2)
            os.replace(temp, self._path)
        except OSError:
            pass
