"""Cadastro de tesoureiros da congregacao autenticada."""

import datetime
import logging

import pandas as pd
import streamlit as st

from data.models import Tesoureiro
from data.repository import (
    atualizar_tesoureiro,
    carregar_tesoureiros,
    inserir_tesoureiro,
    validar_nova_senha,
)
from utils.helpers import slug_da_sessao, solicitar_autorizacao


LOGGER = logging.getLogger(__name__)


def _cache_key(slug):
    return f"df_tesoureiros_{slug}"


def _carregar(slug):
    chave = _cache_key(slug)
    if chave not in st.session_state:
        st.session_state[chave] = carregar_tesoureiros(slug)
    return st.session_state[chave]


def _invalidar(slug):
    st.session_state.pop(_cache_key(slug), None)


def _data_iso(valor):
    if valor is None:
        return ""
    if isinstance(valor, datetime.date):
        return valor.isoformat()
    return str(valor or "")


def _data_input(valor, padrao=None):
    try:
        return datetime.date.fromisoformat(str(valor))
    except (TypeError, ValueError):
        return padrao


def _cpf_mascarado(cpf):
    digitos = "".join(c for c in str(cpf or "") if c.isdigit())
    if len(digitos) != 11:
        return ""
    return f"***.{digitos[3:6]}.{digitos[6:9]}-**"


def _formatar_data(valor):
    try:
        return datetime.date.fromisoformat(str(valor)).strftime("%d/%m/%Y")
    except (TypeError, ValueError):
        return ""


def _salvar(slug, tesoureiro, atualizar=False):
    erros = tesoureiro.validar()
    if erros:
        for erro in erros:
            st.error(erro)
        return False
    try:
        if atualizar:
            atualizar_tesoureiro(slug, tesoureiro)
        else:
            inserir_tesoureiro(slug, tesoureiro)
    except ValueError as ex:
        st.error(str(ex))
        return False
    except Exception:
        LOGGER.exception("Falha ao salvar tesoureiro da congregacao %s.", slug)
        st.error("Nao foi possivel salvar o tesoureiro. Consulte o log do sistema.")
        return False
    _invalidar(slug)
    st.toast("Cadastro de tesoureiro salvo.")
    return True


def _form_novo(slug):
    with st.expander("Cadastrar tesoureiro", expanded=False):
        with st.form("form_novo_tesoureiro", clear_on_submit=True):
            st.caption("O CPF identifica o responsavel e nao sera exibido integralmente na listagem.")
            nome = st.text_input("Nome completo *")
            cpf = st.text_input("CPF *", placeholder="000.000.000-00")
            usuario = st.text_input(
                "Usuario de acesso *",
                placeholder="ex: tesouraria.central",
                help="Use letras minusculas, numeros, ponto, hifen ou sublinhado.",
            )
            senha = st.text_input("Senha inicial *", type="password")
            confirma_senha = st.text_input("Confirmar senha inicial *", type="password")
            c1, c2 = st.columns(2)
            with c1:
                telefone = st.text_input("Telefone")
                data_inicio = st.date_input(
                    "Inicio da atuacao *", value=datetime.date.today(), format="DD/MM/YYYY"
                )
            with c2:
                email = st.text_input("E-mail")
                principal = st.checkbox("Responsavel principal")
            observacoes = st.text_area("Observacoes")
            if st.form_submit_button("Cadastrar", type="primary"):
                erros_senha = validar_nova_senha(senha)
                if senha != confirma_senha:
                    erros_senha.append("Senha e confirmacao nao coincidem.")
                if erros_senha:
                    for erro in dict.fromkeys(erros_senha):
                        st.error(erro)
                    return
                tesoureiro = Tesoureiro(
                    nome=nome,
                    cpf=cpf,
                    usuario=usuario,
                    senha=senha,
                    telefone=telefone,
                    email=email,
                    data_inicio=_data_iso(data_inicio),
                    situacao="Ativo",
                    principal=principal,
                    observacoes=observacoes,
                )
                if _salvar(slug, tesoureiro):
                    st.rerun()


def _tabela_resumo(df):
    tabela = df.copy()
    tabela["CPF"] = tabela["cpf"].map(_cpf_mascarado)
    tabela["Principal"] = tabela["principal"].map(lambda valor: "Sim" if bool(valor) else "Nao")
    tabela["Inicio"] = tabela["data_inicio"].map(_formatar_data)
    tabela["Fim"] = tabela["data_fim"].map(_formatar_data)
    tabela = tabela.rename(columns={
        "nome": "Nome",
        "usuario": "Usuario",
        "telefone": "Telefone",
        "email": "E-mail",
        "situacao": "Situacao",
    })
    return tabela[["Nome", "Usuario", "CPF", "Telefone", "E-mail", "Inicio", "Fim", "Situacao", "Principal"]]


def _form_editar(slug, df):
    if df.empty:
        return
    opcoes = {
        f"{int(row['id_tesoureiro'])} | {row['nome']} | {row['situacao']}": row
        for _, row in df.iterrows()
    }
    selecionado = st.selectbox("Selecionar tesoureiro para editar", list(opcoes))
    row = opcoes[selecionado]
    id_tesoureiro = int(row["id_tesoureiro"])
    situacao_atual = str(row["situacao"])
    with st.form(f"form_editar_tesoureiro_{id_tesoureiro}"):
        st.caption("Para preservar o historico, encerre a atuacao em vez de excluir o registro.")
        nome = st.text_input("Nome completo *", value=str(row["nome"] or ""))
        cpf = st.text_input("CPF *", value=str(row["cpf"] or ""))
        usuario = st.text_input("Usuario de acesso *", value=str(row["usuario"] or ""))
        senha = st.text_input(
            "Nova senha",
            type="password",
            help="Deixe em branco para manter a senha atual.",
        )
        confirma_senha = st.text_input("Confirmar nova senha", type="password")
        c1, c2 = st.columns(2)
        with c1:
            telefone = st.text_input("Telefone", value=str(row["telefone"] or ""))
            data_inicio = st.date_input(
                "Inicio da atuacao *",
                value=_data_input(row["data_inicio"], datetime.date.today()),
                format="DD/MM/YYYY",
            )
        with c2:
            email = st.text_input("E-mail", value=str(row["email"] or ""))
            situacao = st.selectbox(
                "Situacao", ["Ativo", "Inativo"],
                index=0 if situacao_atual == "Ativo" else 1,
            )
        data_fim = st.date_input(
            "Fim da atuacao",
            value=_data_input(row["data_fim"]),
            format="DD/MM/YYYY",
            help="Obrigatorio ao encerrar a atuacao.",
        )
        principal = st.checkbox(
            "Responsavel principal",
            value=bool(row["principal"]),
            disabled=situacao == "Inativo",
        )
        observacoes = st.text_area("Observacoes", value=str(row["observacoes"] or ""))
        if st.form_submit_button("Salvar alteracoes", type="primary"):
            erros_senha = validar_nova_senha(senha) if senha else []
            if senha != confirma_senha:
                erros_senha.append("Senha e confirmacao nao coincidem.")
            if erros_senha:
                for erro in dict.fromkeys(erros_senha):
                    st.error(erro)
                return
            tesoureiro = Tesoureiro(
                id_tesoureiro=id_tesoureiro,
                nome=nome,
                cpf=cpf,
                usuario=usuario,
                senha=senha,
                telefone=telefone,
                email=email,
                data_inicio=_data_iso(data_inicio),
                data_fim=_data_iso(data_fim),
                situacao=situacao,
                principal=principal if situacao == "Ativo" else False,
                observacoes=observacoes,
            )
            if _salvar(slug, tesoureiro, atualizar=True):
                st.rerun()


def render():
    slug = slug_da_sessao()
    if not slug:
        st.error("Sessao invalida. Faca login novamente.")
        return
    st.subheader("💼 Tesoureiros")
    if not solicitar_autorizacao(
        "gerenciar_tesoureiros",
        "gerenciar acessos de tesoureiros",
    ):
        st.caption("Confirme a senha principal da igreja para administrar credenciais.")
        return
    st.caption(
        "Cadastre credenciais para os responsaveis financeiros. Tesoureiros ativos "
        "podem entrar no sistema somente para registrar lancamentos."
    )
    df = _carregar(slug)
    ativos = int((df["situacao"] == "Ativo").sum()) if not df.empty else 0
    principais = int(((df["situacao"] == "Ativo") & (df["principal"] == 1)).sum()) if not df.empty else 0
    c1, c2, c3 = st.columns(3)
    c1.metric("Tesoureiros cadastrados", len(df))
    c2.metric("Ativos", ativos)
    c3.metric("Responsavel principal", "Definido" if principais else "Pendente")
    if ativos and not principais:
        st.warning("Defina um responsavel principal ativo para esta congregacao.")
    _form_novo(slug)
    st.markdown("#### Responsaveis cadastrados")
    if df.empty:
        st.info("Nenhum tesoureiro cadastrado.")
        return
    st.dataframe(_tabela_resumo(df), use_container_width=True, hide_index=True)
    st.markdown("#### Editar ou encerrar atuacao")
    _form_editar(slug, df)
