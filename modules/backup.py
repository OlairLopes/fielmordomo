"""Backup manual seguro da congregacao autenticada."""

import datetime
import logging

import pandas as pd
import streamlit as st

from data.repository import (
    TAMANHO_MAXIMO_ARQUIVOS_ZIP,
    TAMANHO_MAXIMO_ZIP,
    carregar_cadastros,
    carregar_lancamentos,
    exportar_backup_igreja,
    restaurar_backup_igreja,
)
from utils.backup_scheduler import HORA_EXECUCAO, listar_backups_automaticos
from utils.helpers import formatar_moeda, slug_da_sessao, solicitar_autorizacao
from utils.planos import obter_plano, tem_backup_automatico


LOGGER = logging.getLogger(__name__)


def _sk(nome, slug):
    return f"backup_{nome}_{slug}"


def _nome_backup(slug):
    agora = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"backup_{slug}_{agora}.zip"


def _limpar_cache_dados():
    prefixos = ("df_", "lote_", "nl_counter_", "dashboard_")
    for chave in list(st.session_state.keys()):
        if chave.startswith(prefixos):
            st.session_state.pop(chave, None)


def _gerar_backup(slug):
    try:
        dados = exportar_backup_igreja(slug)
    except Exception:
        LOGGER.exception("Nao foi possivel exportar backup da igreja %s.", slug)
        st.error("Nao foi possivel gerar o backup. Consulte o log do sistema.")
        return
    st.session_state[_sk("download_dados", slug)] = dados
    st.session_state[_sk("download_nome", slug)] = _nome_backup(slug)
    st.toast("Backup gerado com sucesso.")


def _render_download(slug):
    st.markdown("#### Gerar backup")
    st.caption(
        "O ZIP inclui uma copia consistente do banco SQLite e arquivos CSV para conferencia."
    )
    if st.button("Gerar backup completo", type="primary", key=_sk("gerar", slug)):
        _gerar_backup(slug)
    dados = st.session_state.get(_sk("download_dados", slug))
    nome = st.session_state.get(_sk("download_nome", slug))
    if dados and nome:
        st.download_button(
            "Baixar arquivo ZIP",
            data=dados,
            file_name=nome,
            mime="application/zip",
            key=_sk("baixar", slug),
        )
        st.caption(f"Arquivo pronto: {nome} ({len(dados) / 1024:.1f} KB)")


def _guardar_upload(slug, arquivo):
    dados = arquivo.getvalue()
    limite = TAMANHO_MAXIMO_ZIP if arquivo.name.lower().endswith(".zip") else TAMANHO_MAXIMO_ARQUIVOS_ZIP
    if not dados:
        st.error("O arquivo enviado esta vazio.")
        return
    if len(dados) > limite:
        st.error("O arquivo enviado excede o limite permitido.")
        return
    st.session_state[_sk("upload_nome", slug)] = arquivo.name
    st.session_state[_sk("upload_dados", slug)] = dados


def _restaurar_upload(slug):
    nome = st.session_state.get(_sk("upload_nome", slug), "")
    dados = st.session_state.get(_sk("upload_dados", slug), b"")
    if not nome or not dados:
        st.error("Envie um arquivo de backup antes de restaurar.")
        return
    try:
        restaurar_backup_igreja(slug, dados, nome)
    except ValueError as ex:
        st.error(str(ex))
        return
    except Exception:
        LOGGER.exception("Nao foi possivel restaurar backup da igreja %s.", slug)
        st.error("Nao foi possivel restaurar o backup. Consulte o log do sistema.")
        return
    _limpar_cache_dados()
    st.session_state.pop(_sk("upload_nome", slug), None)
    st.session_state.pop(_sk("upload_dados", slug), None)
    st.success("Backup restaurado com sucesso. Os dados foram recarregados.")


def _render_restauracao(slug):
    st.markdown("#### Restaurar backup")
    st.warning(
        "A restauracao substitui os dados atuais desta congregacao. "
        "O sistema cria uma copia preventiva antes da substituicao."
    )
    arquivo = st.file_uploader(
        "Selecione um backup ZIP ou banco SQLite",
        type=["zip", "db"],
        key=_sk("arquivo", slug),
    )
    if arquivo is not None:
        _guardar_upload(slug, arquivo)
    nome = st.session_state.get(_sk("upload_nome", slug))
    dados = st.session_state.get(_sk("upload_dados", slug))
    if nome and dados:
        st.info(f"Arquivo carregado: {nome} ({len(dados) / 1024:.1f} KB)")
    confirmar = st.checkbox(
        "Confirmo que desejo substituir os dados atuais desta congregacao.",
        key=_sk("confirmar", slug),
    )
    if not solicitar_autorizacao(_sk("restaurar", slug), "restaurar o backup"):
        return
    if st.button(
        "Restaurar arquivo validado",
        type="primary",
        key=_sk("executar_restauracao", slug),
        disabled=not confirmar,
    ):
        _restaurar_upload(slug)


def _render_resumo(slug):
    cadastros = carregar_cadastros(slug)
    lancamentos = carregar_lancamentos(slug)
    membros = fornecedores = 0
    if not cadastros.empty and "tipo_cadastro" in cadastros.columns:
        tipos = cadastros["tipo_cadastro"].fillna("").astype(str).str.strip().str.upper()
        membros = int((tipos == "MEMBRO").sum())
        fornecedores = int((tipos == "FORNECEDOR").sum())
    entradas = saidas = 0.0
    if not lancamentos.empty and {"tipo", "valor"}.issubset(lancamentos.columns):
        tipos = lancamentos["tipo"].fillna("").astype(str).str.strip().str.upper()
        valores = pd.to_numeric(lancamentos["valor"], errors="coerce").fillna(0.0)
        entradas = float(valores[tipos == "ENTRADA"].sum())
        saidas = float(valores[tipos == "SAIDA"].sum())
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Membros", membros)
    c2.metric("Fornecedores", fornecedores)
    c3.metric("Lancamentos", len(lancamentos))
    c4.metric("Resultado registrado", formatar_moeda(entradas - saidas))


def _render_backup_automatico(slug, plano):
    p_info = obter_plano(plano)
    if not tem_backup_automatico(plano):
        st.caption(
            f"O plano {p_info['nome']} possui backup manual. "
            "Backups automaticos diarios estao disponiveis nos planos Profissional e Premium."
        )
        return

    st.markdown("#### Backup automatico")
    backups = listar_backups_automaticos(slug)
    if not backups:
        st.info(
            f"Seu plano inclui backup automatico diario (gerado por volta das "
            f"{HORA_EXECUCAO}h, horario de Brasilia). Ainda nao foi gerado o "
            "primeiro backup automatico desta igreja."
        )
        return

    ultimo_ts, _ = backups[0]
    st.success(
        f"Backup automatico ativo. Ultimo backup: "
        f"{ultimo_ts.strftime('%d/%m/%Y %H:%M')} (horario de Brasilia)."
    )
    with st.expander(f"Backups automaticos recentes ({len(backups)})", expanded=False):
        for ts, arquivo in backups:
            c_data, c_baixar = st.columns([3, 1])
            c_data.caption(ts.strftime("%d/%m/%Y %H:%M"))
            c_baixar.download_button(
                "Baixar",
                data=arquivo.read_bytes(),
                file_name=arquivo.name,
                mime="application/zip",
                key=_sk(f"baixar_auto_{arquivo.stem}", slug),
            )


def render():
    slug = slug_da_sessao()
    if not slug:
        st.error("Sessao invalida. Faca login novamente.")
        return
    igreja = st.session_state.get("igreja", {})
    plano = igreja.get("plano", "basico") if isinstance(igreja, dict) else "basico"
    st.subheader("💾 Backup de dados")
    st.caption("Exporte ou restaure os dados isolados desta congregacao.")
    _render_resumo(slug)
    st.divider()
    _render_download(slug)
    st.divider()
    _render_restauracao(slug)
    st.divider()
    _render_backup_automatico(slug, plano)
