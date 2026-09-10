"""Agendador de backup automatico em background para planos que o incluem.

Roda como uma thread daemon dentro do proprio processo do Streamlit (o
render.yaml do projeto sobe um unico servico web, sem worker separado).
A thread e iniciada uma unica vez por processo, verifica periodicamente se
ja passou do horario configurado e, se ainda nao rodou no dia, gera um
backup por igreja elegivel.
"""

import datetime
import logging
import threading
import time
from pathlib import Path

from data.repository import DATA_DIR, exportar_backup_igreja, listar_igrejas
from utils.planos import tem_backup_automatico

LOGGER = logging.getLogger(__name__)

TZ_BRASILIA = datetime.timezone(datetime.timedelta(hours=-3))
HORA_EXECUCAO = 3
INTERVALO_VERIFICACAO_SEGUNDOS = 1800
RETENCAO_BACKUPS = 7

AUTO_BACKUP_DIR = DATA_DIR / "backups_automaticos"
_MARCADOR_ULTIMA_EXECUCAO = AUTO_BACKUP_DIR / ".ultima_execucao"

_lock = threading.Lock()
_iniciado = False


def _agora_brasilia():
    return datetime.datetime.now(TZ_BRASILIA)


def _ler_ultima_execucao():
    try:
        texto = _MARCADOR_ULTIMA_EXECUCAO.read_text(encoding="utf-8").strip()
        return datetime.date.fromisoformat(texto)
    except Exception:
        return None


def _gravar_ultima_execucao(data):
    AUTO_BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    _MARCADOR_ULTIMA_EXECUCAO.write_text(data.isoformat(), encoding="utf-8")


def _pasta_igreja(slug):
    return AUTO_BACKUP_DIR / slug


def _aplicar_retencao(pasta):
    arquivos = sorted(pasta.glob("backup_*.zip"))
    for arquivo in arquivos[:-RETENCAO_BACKUPS]:
        try:
            arquivo.unlink()
        except OSError:
            LOGGER.exception("Falha ao remover backup automatico antigo: %s", arquivo)


def listar_backups_automaticos(slug):
    """Retorna [(datetime, Path), ...] dos backups automaticos da igreja, mais recente primeiro."""
    pasta = _pasta_igreja(slug)
    if not pasta.exists():
        return []
    resultado = []
    for arquivo in pasta.glob("backup_*.zip"):
        try:
            ts = datetime.datetime.strptime(arquivo.stem, "backup_%Y%m%d_%H%M%S")
            ts = ts.replace(tzinfo=TZ_BRASILIA)
        except ValueError:
            continue
        resultado.append((ts, arquivo))
    resultado.sort(key=lambda par: par[0], reverse=True)
    return resultado


def executar_ciclo_backup_automatico():
    """Gera backup automatico para cada igreja ativa com plano habilitado.

    Retorna {slug: "ok"} ou {slug: "erro: <motivo>"} por igreja, para que
    falhas possam ser auditadas em vez de descartadas silenciosamente.
    """
    resultado = {}
    try:
        df_igrejas = listar_igrejas()
    except Exception:
        LOGGER.exception("Nao foi possivel listar igrejas para o backup automatico.")
        return resultado

    if df_igrejas.empty:
        return resultado

    elegiveis = df_igrejas[
        df_igrejas["ativa"].fillna(0).astype(int).eq(1)
        & df_igrejas["plano"].apply(tem_backup_automatico)
    ]

    for _, linha in elegiveis.iterrows():
        slug = str(linha["slug"])
        try:
            dados = exportar_backup_igreja(slug)
            pasta = _pasta_igreja(slug)
            pasta.mkdir(parents=True, exist_ok=True)
            ts = _agora_brasilia().strftime("%Y%m%d_%H%M%S")
            (pasta / f"backup_{ts}.zip").write_bytes(dados)
            _aplicar_retencao(pasta)
            resultado[slug] = "ok"
        except Exception as exc:
            LOGGER.exception("Falha no backup automatico da igreja %s.", slug)
            resultado[slug] = f"erro: {exc}"

    falhas = {s: r for s, r in resultado.items() if r != "ok"}
    if falhas:
        LOGGER.error(
            "Backup automatico concluido com falhas em %d de %d igreja(s): %s",
            len(falhas), len(resultado), falhas,
        )
    elif resultado:
        LOGGER.info("Backup automatico concluido para %d igreja(s).", len(resultado))
    return resultado


def _loop_agendador():
    while True:
        try:
            agora = _agora_brasilia()
            if agora.hour >= HORA_EXECUCAO and _ler_ultima_execucao() != agora.date():
                executar_ciclo_backup_automatico()
                _gravar_ultima_execucao(agora.date())
        except Exception:
            LOGGER.exception("Erro no loop do agendador de backup automatico.")
        time.sleep(INTERVALO_VERIFICACAO_SEGUNDOS)


def iniciar_agendador_backup():
    """Inicia a thread do agendador uma unica vez por processo (idempotente)."""
    global _iniciado
    with _lock:
        if _iniciado:
            return
        _iniciado = True
        threading.Thread(
            target=_loop_agendador, daemon=True, name="backup-automatico",
        ).start()
        LOGGER.info("Agendador de backup automatico iniciado (execucao diaria as %dh, horario de Brasilia).", HORA_EXECUCAO)
