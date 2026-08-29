import datetime
import json
import urllib.request

import pandas as pd
import streamlit as st

from data.repository import (
    carregar_cadastros,
    excluir_visitante_culto,
    listar_visitantes_cultos,
    salvar_visitante_culto,
)
from utils.helpers import confirmar_exclusao, gerar_csv, slug_da_sessao


ESTADOS_BR = [
    "AC", "AL", "AP", "AM", "BA", "CE", "DF", "ES", "GO", "MA", "MT",
    "MS", "MG", "PA", "PB", "PR", "PE", "PI", "RJ", "RN", "RS", "RO",
    "RR", "SC", "SP", "SE", "TO",
]

DEPARTAMENTOS_CULTO = [
    "Conscientização Missionária",
    "Consagração",
    "Culto de Ensino",
    "Culto Ministério de Homens",
    "Culto Ministério Família",
    "Culto Ministério Infantil",
    "Culto Ministério Jovens",
    "Culto Ministério Missões",
    "Culto Ministério Mulheres",
    "Dia com Deus",
    "Encontro Unificado",
    "Escola Bíblica",
    "Fraternal",
    "Outros",
    "Vigília",
]


IGREJAS_ORIGEM = [
    "Assembleia de Deus",
    "Presbiteriana",
    "Presbiteriana Renovada",
    "Batista",
    "Batista Renovada",
    "Igreja Catolica",
    "Igreja CIMADSETA",
    "Igreja Apostolica Fonte da Vida",
    "Igreja Crista Evangelica",
    "Tabernaculo da Fe",
    "Congregacao Crista no Brasil",
    "Igreja Universal do Reino de Deus",
    "Igreja do Evangelho Quadrangular",
    "Igreja Missao Outras",
    "Outros",
]

CONGREGACOES_VISITANTES = [
    "Setor Central",
    "Jardim de Deus",
    "Jardim Arimateia",
    "Jardim Emilia",
    "Jardim Floresta",
    "Minacu Norte",
    "Nova Jerusalem",
    "Galileia",
    "Distrito Cana Brava",
    "Marajoara",
    "AD Serrinha",
    "Vila Nova",
    "Vila de Furnas",
    "Vila Manchester",
    "Vila Uniao",
    "Rua Dezoito",
    "Monte Sinai",
    "Outros",
]


def _hoje():
    return datetime.date.today()


def _inicio_mes():
    hoje = _hoje()
    return hoje.replace(day=1)


def _fmt_data(valor):
    try:
        return datetime.date.fromisoformat(str(valor)).strftime("%d/%m/%Y")
    except Exception:
        return str(valor or "")


def _sim_nao(valor):
    return "Sim" if bool(valor) else "Não"



@st.cache_data(ttl=86400, show_spinner=False)
def _cidades_por_estado(uf):
    uf = str(uf or "").strip().upper()
    if not uf or uf == "SELECIONE":
        return ["Outros"]
    try:
        url = f"https://servicodados.ibge.gov.br/api/v1/localidades/estados/{uf}/municipios"
        with urllib.request.urlopen(url, timeout=8) as resposta:
            dados = json.loads(resposta.read().decode("utf-8"))
        cidades = sorted(
            str(item.get("nome", "")).strip()
            for item in dados
            if str(item.get("nome", "")).strip()
        )
        return cidades + ["Outros"] if cidades else ["Outros"]
    except Exception:
        if uf == "GO":
            return ["Minaçu", "Outros"]
        return ["Outros"]


@st.cache_data(ttl=300, show_spinner=False)
def _congregacoes_membros(slug):
    try:
        df = carregar_cadastros(slug)
    except Exception:
        return []
    if df is None or df.empty or "congregacao" not in df.columns:
        return []
    if "tipo_cadastro" in df.columns:
        df = df[df["tipo_cadastro"].fillna("").astype(str).str.strip().str.upper() == "MEMBRO"]
    if "situacao" in df.columns:
        df = df[df["situacao"].fillna("").astype(str).str.strip().str.upper() == "ATIVO"]
    congregacoes = (
        df["congregacao"]
        .fillna("")
        .astype(str)
        .str.strip()
    )
    return sorted({c for c in congregacoes if c})


def _totais(df):
    if df.empty:
        return {
            "visitantes": 0,
            "crentes": 0,
            "nao_crentes": 0,
            "apresentar": 0,
            "oracao": 0,
        }
    return {
        "visitantes": int(len(df)),
        "crentes": int((df["tipo_visitante"] == "Crente").sum()),
        "nao_crentes": int((df["tipo_visitante"] == "Nao crente").sum()),
        "apresentar": int(df["deseja_ser_apresentado"].fillna(0).astype(int).sum()),
        "oracao": int(df["deseja_oracao_final"].fillna(0).astype(int).sum()),
    }


def _render_formulario(slug):
    st.markdown("### Registrar visitante")
    st.caption("Registre visitantes recebidos nos cultos e departamentos da igreja.")

    nonce = st.session_state.get("visitante_form_nonce", 0)

    c1, c2 = st.columns(2)
    c1.text_input(
        "Identificador da igreja",
        value=slug,
        disabled=True,
        key=f"visitante_slug_{nonce}",
    )
    data = c2.date_input("Data", value=_hoje(), key=f"visitante_data_{nonce}", format="DD/MM/YYYY")

    departamento_opcao = st.selectbox(
        "Departamento na direcao do culto",
        DEPARTAMENTOS_CULTO,
        index=0,
        key=f"visitante_departamento_{nonce}",
    )
    departamento = departamento_opcao
    if departamento_opcao == "Outros":
        departamento = st.text_input(
            "Informe o departamento",
            placeholder="Ex.: Ministerio de louvor, familia, adolescentes...",
            key=f"visitante_departamento_outros_{nonce}",
        )

    nome_visitante = st.text_input("Nome do visitante", key=f"visitante_nome_{nonce}")

    crente = st.radio(
        "Tipo de visitante: e crente?",
        ["Sim", "Nao"],
        horizontal=True,
        key=f"visitante_crente_{nonce}",
    )
    tipo_visitante = "Crente" if crente == "Sim" else "Nao crente"

    igreja_origem = ""
    cidade = ""
    estado = ""
    congregacao = ""
    denominacao = ""

    if tipo_visitante == "Crente":
        st.markdown("#### Dados da igreja de origem")
        c3, c4, c5 = st.columns([2, 1.4, 1])
        igreja_origem_opcao = c3.selectbox(
            "De qual igreja?",
            IGREJAS_ORIGEM,
            index=0,
            key=f"visitante_igreja_origem_select_{nonce}",
        )
        igreja_origem = igreja_origem_opcao
        if igreja_origem_opcao == "Outros":
            igreja_origem = st.text_input(
                "Informe a igreja",
                placeholder="Digite o nome da igreja",
                key=f"visitante_igreja_origem_outros_{nonce}",
            )
        estado_opcao = c5.selectbox(
            "Qual estado?",
            ["Selecione"] + ESTADOS_BR,
            index=ESTADOS_BR.index("GO") + 1,
            key=f"visitante_estado_{nonce}",
        )
        estado = "" if estado_opcao == "Selecione" else estado_opcao
        cidades = _cidades_por_estado(estado)
        cidade_index = cidades.index("Minaçu") if "Minaçu" in cidades else 0
        cidade_opcao = c4.selectbox(
            "Qual cidade?",
            cidades,
            index=cidade_index,
            key=f"visitante_cidade_{estado or 'sem_uf'}_{nonce}",
        )
        cidade = cidade_opcao
        if cidade_opcao == "Outros":
            cidade = st.text_input(
                "Informe a cidade",
                placeholder="Digite o nome da cidade",
                key=f"visitante_cidade_outros_{nonce}",
            )
        if (
            igreja_origem_opcao == "Assembleia de Deus"
            and estado == "GO"
            and cidade == "Minaçu"
        ):
            opcoes_congregacao = ["Selecione"] + CONGREGACOES_VISITANTES
            congregacao_opcao = st.selectbox(
                "Congregacao",
                opcoes_congregacao,
                key=f"visitante_congregacao_select_{nonce}",
            )
            if congregacao_opcao == "Outros":
                congregacao = st.text_input(
                    "Informe a congregacao",
                    placeholder="Digite o nome da congregacao",
                    key=f"visitante_congregacao_outros_{nonce}",
                )
            elif congregacao_opcao != "Selecione":
                congregacao = congregacao_opcao
    else:
        denominacao = st.text_input(
            "Pertence a qual denominacao?",
            placeholder="Ex.: Catolica, Assembleia de Deus, sem denominacao...",
            key=f"visitante_denominacao_{nonce}",
        )

    c6, c7 = st.columns(2)
    deseja_ser_apresentado = c6.checkbox(
        "Deseja ser apresentado?",
        key=f"visitante_apresentar_{nonce}",
    )
    deseja_oracao_final = c7.checkbox(
        "Deseja receber oracao ao final do culto?",
        key=f"visitante_oracao_{nonce}",
    )
    observacoes = st.text_area(
        "Observacoes",
        placeholder="Opcional",
        key=f"visitante_obs_{nonce}",
    )

    b1, b2 = st.columns([1, 1])
    salvar = b1.button(
        "Salvar visitante",
        type="primary",
        use_container_width=True,
        key=f"visitante_salvar_{nonce}",
    )
    novo = b2.button(
        "Novo cadastro",
        use_container_width=True,
        key=f"visitante_novo_{nonce}",
    )

    if novo:
        st.session_state["visitante_form_nonce"] = nonce + 1
        st.rerun()

    if salvar:
        try:
            salvar_visitante_culto(
                slug,
                data.isoformat(),
                departamento,
                nome_visitante,
                tipo_visitante,
                igreja_origem,
                cidade,
                estado,
                denominacao,
                deseja_ser_apresentado,
                deseja_oracao_final,
                observacoes,
                congregacao=congregacao,
            )
            st.success("Visitante registrado com sucesso.")
            st.session_state["visitante_form_nonce"] = nonce + 1
            st.rerun()
        except Exception as exc:
            st.error(str(exc))

def _render_consulta(slug):
    st.markdown("### Visitantes registrados")
    c1, c2, c3 = st.columns(3)
    inicio = c1.date_input("Data inicial", value=_inicio_mes(), key="visitantes_ini", format="DD/MM/YYYY")
    fim = c2.date_input("Data final", value=_hoje(), key="visitantes_fim", format="DD/MM/YYYY")
    departamento = c3.text_input("Filtrar departamento", placeholder="Opcional")
    if inicio > fim:
        st.error("A data inicial não pode ser maior que a data final.")
        return

    df = listar_visitantes_cultos(
        slug,
        inicio.isoformat(),
        fim.isoformat(),
        departamento.strip(),
    )
    totais = _totais(df)
    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric("Visitantes", totais["visitantes"])
    m2.metric("Crentes", totais["crentes"])
    m3.metric("Não crentes", totais["nao_crentes"])
    m4.metric("Apresentar", totais["apresentar"])
    m5.metric("Oração final", totais["oracao"])

    if df.empty:
        st.info("Nenhum visitante encontrado no período selecionado.")
        return

    exibir = df.copy()
    exibir["data"] = exibir["data"].apply(_fmt_data)
    exibir["deseja_ser_apresentado"] = exibir["deseja_ser_apresentado"].apply(_sim_nao)
    exibir["deseja_oracao_final"] = exibir["deseja_oracao_final"].apply(_sim_nao)
    st.dataframe(
        exibir[[
            "data", "departamento", "nome_visitante", "tipo_visitante",
            "igreja_origem", "cidade", "estado", "congregacao", "denominacao",
            "deseja_ser_apresentado", "deseja_oracao_final", "observacoes",
        ]],
        use_container_width=True,
        hide_index=True,
    )
    st.download_button(
        "Baixar visitantes CSV",
        data=gerar_csv(df),
        file_name="visitantes_cultos.csv",
        mime="text/csv",
    )

    excluir = st.selectbox(
        "Excluir registro",
        ["Selecione"] + [
            f'{int(row["id_visitante"])} - {_fmt_data(row["data"])} - {row["nome_visitante"]}'
            for _, row in df.iterrows()
        ],
    )
    if excluir != "Selecione" and confirmar_exclusao(
        f"excluir_visitante_{excluir}",
        "Excluir registro selecionado",
    ):
        excluir_visitante_culto(slug, int(excluir.split(" - ")[0]))
        st.success("Registro excluído.")
        st.rerun()


def render():
    st.subheader("🤝 Registro de Visitantes")
    slug = slug_da_sessao()
    if not slug:
        st.error("Sessão inválida. Faça login novamente.")
        return

    tab_form, tab_consulta = st.tabs(["Registrar visitante", "Consultar registros"])
    with tab_form:
        _render_formulario(slug)
    with tab_consulta:
        _render_consulta(slug)
