import logging
import datetime

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from data.repository import (
    carregar_cadastros,
    carregar_orhafe_presencas,
    encerrar_orhafe_matricula,
    excluir_orhafe_coordenadora,
    excluir_orhafe_lider,
    excluir_orhafe_matricula,
    inativar_orhafe_secretaria,
    listar_orhafe_coordenadoras,
    listar_orhafe_lideres,
    listar_orhafe_matriculas,
    listar_orhafe_reunioes,
    listar_orhafe_secretarias,
    relatorio_orhafe_frequencia,
    relatorio_orhafe_visitantes,
    salvar_orhafe_chamada,
    salvar_orhafe_coordenadora,
    salvar_orhafe_lider,
    salvar_orhafe_matricula,
    salvar_orhafe_secretaria,
)
from utils.helpers import confirmar_exclusao, gerar_csv, normalizar_data_digitada, slug_da_sessao


CORES = {
    "azul": "#0F3D5E",
    "verde": "#1D9E75",
    "laranja": "#F59E0B",
    "vermelho": "#DC2626",
    "cinza": "#64748B",
    "roxo": "#7C3AED",
}
CONFIG_PLOTLY = {"displayModeBar": False, "responsive": True}


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


def _data_iso(valor):
    try:
        if isinstance(valor, datetime.date):
            return valor.isoformat()
        texto = str(valor or "").strip()
        if not texto:
            return ""
        for formato in ("%Y-%m-%d", "%d/%m/%Y"):
            try:
                return datetime.datetime.strptime(texto, formato).date().isoformat()
            except Exception:
                logging.exception("Erro ignorado silenciosamente")
        return datetime.date.fromisoformat(texto).isoformat()
    except Exception:
        return ""


def _filtrar_matriculas_validas_na_data(matriculas, data_referencia):
    if matriculas.empty:
        return matriculas

    data_ref = _data_iso(data_referencia)
    if not data_ref:
        return matriculas[matriculas["ativa"] == 1].copy()

    dados = matriculas.copy()
    if "data_inicio" not in dados.columns:
        dados["data_inicio"] = ""
    if "data_fim" not in dados.columns:
        dados["data_fim"] = ""
    inicio = dados["data_inicio"].apply(_data_iso)
    fim = dados["data_fim"].apply(_data_iso)

    validas = (inicio.eq("") | (inicio <= data_ref)) & (fim.eq("") | (fim >= data_ref))
    return dados[validas].copy()


def _pct(valor):
    try:
        return f"{float(valor):.1f}%"
    except Exception:
        return "0.0%"


def _moeda(valor):
    try:
        return f"R$ {float(valor):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except Exception:
        return "R$ 0,00"


def _membros_opcoes(slug):
    df = carregar_cadastros(slug)
    if df.empty:
        return {}, df
    membros = df[
        (df["tipo_cadastro"].astype(str).str.upper() == "MEMBRO")
        & (df["situacao"].astype(str).str.upper() == "ATIVO")
    ].copy()
    membros = membros.sort_values("nome")
    opcoes = {
        f'{int(row["id_cadastro"])} - {row["nome"]}': int(row["id_cadastro"])
        for _, row in membros.iterrows()
    }
    return opcoes, membros


def _lideres_opcoes(df_lideres):
    return {
        f'{int(row["id_lider"])} - {row["nome"]}': int(row["id_lider"])
        for _, row in df_lideres.iterrows()
    }


def _metricas_chamadas(reunioes):
    if reunioes.empty:
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Reunioes", 0)
        c2.metric("Presentes", 0)
        c3.metric("Visitantes", 0)
        c4.metric("Ofertas", _moeda(0))
        return
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Reunioes", int(reunioes["id_reuniao"].nunique()))
    c2.metric("Presentes", int(reunioes["presentes"].fillna(0).max()))
    c3.metric("Visitantes", int(reunioes["visitantes"].fillna(0).sum()))
    c4.metric("Ofertas", _moeda(reunioes["ofertas"].fillna(0).sum()))


def _grafico_reunioes(reunioes):
    if reunioes.empty:
        st.info("Sem reunioes no periodo selecionado.")
        return
    dados = reunioes.sort_values("data")
    fig = go.Figure()
    fig.add_trace(go.Bar(
        name="Presentes",
        x=dados["data"].apply(_fmt_data),
        y=dados["presentes"],
        marker_color=CORES["verde"],
        text=dados["presentes"],
        textposition="outside",
    ))
    fig.add_trace(go.Bar(
        name="Visitantes",
        x=dados["data"].apply(_fmt_data),
        y=dados["visitantes"],
        marker_color=CORES["laranja"],
        text=dados["visitantes"],
        textposition="outside",
    ))
    fig.update_layout(
        title="Participacao nas reunioes",
        barmode="group",
        height=430,
        margin=dict(t=60, b=60, l=20, r=20),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        yaxis=dict(gridcolor="#E2E8F0", fixedrange=True),
        xaxis=dict(fixedrange=True),
        legend=dict(orientation="h", y=1.12, x=0),
    )
    st.plotly_chart(fig, use_container_width=True, config=CONFIG_PLOTLY)


def _grafico_frequencia(freq):
    if freq.empty:
        st.info("Sem frequencia individual no periodo.")
        return
    dados = freq.copy()
    total = dados["presencas"] + dados["ausencias"]
    dados["frequencia_pct"] = (dados["presencas"] / total.where(total > 0, 1) * 100).round(1)
    dados = dados.sort_values("frequencia_pct")
    fig = go.Figure(go.Bar(
        name="Frequencia",
        x=dados["frequencia_pct"],
        y=dados["nome"],
        orientation="h",
        marker_color=CORES["azul"],
        text=[_pct(v) for v in dados["frequencia_pct"]],
        textposition="outside",
    ))
    fig.update_layout(
        title="Frequencia das matriculadas",
        height=max(360, 48 * len(dados)),
        margin=dict(t=60, b=40, l=20, r=35),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        xaxis=dict(range=[0, 105], title="Frequencia (%)", fixedrange=True),
        yaxis=dict(title="", fixedrange=True),
        showlegend=True,
        legend=dict(orientation="h", y=1.12, x=0),
    )
    st.plotly_chart(fig, use_container_width=True, config=CONFIG_PLOTLY)


def _contagens_pessoas_periodo(freq):
    if freq is None or freq.empty:
        return {
            "Matriculadas": 0,
            "Presentes": 0,
            "Ausentes": 0,
        }
    dados = freq.copy()
    dados["presencas"] = pd.to_numeric(dados["presencas"], errors="coerce").fillna(0)
    matriculadas = int(len(dados))
    presentes = int((dados["presencas"] > 0).sum())
    ausentes = max(matriculadas - presentes, 0)
    return {
        "Matriculadas": matriculadas,
        "Presentes": presentes,
        "Ausentes": ausentes,
    }


def _contar_visitantes_periodo(visitantes, lider=None):
    if visitantes is None or visitantes.empty:
        return 0
    dados = visitantes.copy()
    if lider is not None:
        dados = dados[
            dados["lider"].fillna("Sem lider").astype(str) == str(lider)
        ].copy()
    if dados.empty or "nome" not in dados.columns:
        return 0
    nomes = dados["nome"].fillna("").astype(str).str.strip().str.lower()
    return int(nomes[nomes.ne("")].nunique())


def _totais_reunioes(reunioes, freq=None, visitantes=None):
    if reunioes.empty:
        return {
            "Matriculadas": 0,
            "Presentes": 0,
            "Ausentes": 0,
            "Visitantes": 0,
            "Ofertas": 0.0,
            "Reunioes": 0,
        }
    contagens = _contagens_pessoas_periodo(freq)
    if contagens["Matriculadas"] == 0:
        contagens = {
            "Matriculadas": int(reunioes["matriculadas"].fillna(0).max()),
            "Presentes": int(reunioes["presentes"].fillna(0).max()),
            "Ausentes": int(reunioes["ausentes"].fillna(0).max()),
        }
    return {
        "Matriculadas": contagens["Matriculadas"],
        "Presentes": contagens["Presentes"],
        "Ausentes": contagens["Ausentes"],
        "Visitantes": _contar_visitantes_periodo(visitantes),
        "Ofertas": float(reunioes["ofertas"].fillna(0).sum()),
        "Reunioes": int(reunioes["id_reuniao"].nunique()),
    }


def _indicadores_grafico_resumo(reunioes, visitantes=None, lider=None):
    if reunioes.empty:
        return {
            "Presença média (%)": 0.0,
            "Ausência média (%)": 0.0,
            "Visitantes": 0,
            "Ofertas": 0.0,
        }

    matriculadas = pd.to_numeric(
        reunioes["matriculadas"], errors="coerce"
    ).fillna(0)
    presentes = pd.to_numeric(
        reunioes["presentes"], errors="coerce"
    ).fillna(0)
    ausentes = pd.to_numeric(
        reunioes["ausentes"], errors="coerce"
    ).fillna(0)

    media_matriculadas = float(matriculadas.mean()) if not matriculadas.empty else 0.0
    media_presentes = float(presentes.mean()) if not presentes.empty else 0.0
    media_ausentes = float(ausentes.mean()) if not ausentes.empty else 0.0

    if media_matriculadas > 0:
        presenca_pct = (media_presentes / media_matriculadas) * 100
        ausencia_pct = (media_ausentes / media_matriculadas) * 100
    else:
        presenca_pct = 0.0
        ausencia_pct = 0.0

    return {
        "Presença média (%)": round(presenca_pct, 1),
        "Ausência média (%)": round(ausencia_pct, 1),
        "Visitantes": _contar_visitantes_periodo(visitantes, lider),
        "Ofertas": float(reunioes["ofertas"].fillna(0).sum()),
    }


def _resumo_lideres(reunioes, visitantes=None):
    if reunioes.empty:
        return pd.DataFrame(
            columns=[
                "lider", "reunioes", "matriculadas", "presentes",
                "ausentes", "visitantes", "ofertas", "frequencia_pct",
            ]
        )
    resumo = reunioes.copy()
    resumo["lider"] = resumo["lider"].fillna("").replace("", "Sem lider")
    resumo = resumo.groupby("lider", as_index=False).agg(
        reunioes=("id_reuniao", "nunique"),
        matriculadas=("matriculadas", "max"),
        presentes=("presentes", "max"),
        ausentes=("ausentes", "max"),
        visitantes=("visitantes", "max"),
        ofertas=("ofertas", "sum"),
    )
    if visitantes is not None and not visitantes.empty:
        visitantes_lider = (
            visitantes.assign(
                lider=visitantes["lider"].fillna("Sem lider").astype(str),
                nome_norm=visitantes["nome"].fillna("").astype(str).str.strip().str.lower(),
            )
            .query("nome_norm != ''")
            .groupby("lider", as_index=False)["nome_norm"]
            .nunique()
            .rename(columns={"nome_norm": "visitantes"})
        )
        resumo = resumo.drop(columns=["visitantes"]).merge(
            visitantes_lider,
            on="lider",
            how="left",
        )
        resumo["visitantes"] = resumo["visitantes"].fillna(0).astype(int)
    total = resumo["presentes"] + resumo["ausentes"]
    resumo["frequencia_pct"] = (
        resumo["presentes"] / total.where(total > 0, 1) * 100
    ).round(1)
    return resumo.sort_values("lider")


def _grafico_totais_orhafe(titulo, dados):
    if not dados:
        st.info("Sem dados para gerar o grafico.")
        return
    df = pd.DataFrame(
        [{"Indicador": chave, "Total": valor} for chave, valor in dados.items()]
    )
    fig = go.Figure(go.Bar(
        name="Total",
        x=df["Indicador"],
        y=df["Total"],
        marker_color=[
            CORES["verde"], CORES["vermelho"],
            CORES["laranja"], CORES["roxo"],
        ][:len(df)],
        text=[
            _moeda(v)
            if str(k) == "Ofertas"
            else _pct(v)
            if "(%)" in str(k)
            else str(int(v))
            for k, v in dados.items()
        ],
        textposition="outside",
        hovertemplate="<b>%{x}</b><br>Total: %{text}<extra></extra>",
    ))
    fig.update_layout(
        title=titulo,
        height=430,
        margin=dict(t=60, b=80, l=25, r=25),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        xaxis=dict(fixedrange=True),
        yaxis=dict(fixedrange=True, gridcolor="#E2E8F0"),
        showlegend=False,
    )
    st.plotly_chart(fig, use_container_width=True, config=CONFIG_PLOTLY)


def _grafico_resumo_lideres(resumo):
    if resumo.empty:
        st.info("Sem dados por lider para o periodo selecionado.")
        return
    dados = resumo.sort_values("presentes", ascending=True)
    fig = go.Figure()
    fig.add_trace(go.Bar(
        name="Presentes",
        x=dados["presentes"],
        y=dados["lider"],
        orientation="h",
        marker_color=CORES["verde"],
        text=dados["presentes"],
        textposition="outside",
    ))
    fig.add_trace(go.Bar(
        name="Visitantes",
        x=dados["visitantes"],
        y=dados["lider"],
        orientation="h",
        marker_color=CORES["laranja"],
        text=dados["visitantes"],
        textposition="outside",
    ))
    fig.update_layout(
        title="Resumo por lider",
        barmode="group",
        height=max(360, 70 * len(dados)),
        margin=dict(t=60, b=40, l=20, r=35),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        xaxis=dict(fixedrange=True, gridcolor="#E2E8F0"),
        yaxis=dict(title="", fixedrange=True),
        showlegend=True,
        legend=dict(orientation="h", y=1.12, x=0),
    )
    st.plotly_chart(fig, use_container_width=True, config=CONFIG_PLOTLY)


def _render_coordenadoras(slug):
    coordenadoras = listar_orhafe_coordenadoras(slug)
    st.markdown(
        """
        <style>
        .orhafe-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px;margin:.35rem 0 1rem}
        .orhafe-card{border:1px solid #E2E8F0;border-radius:14px;padding:14px 16px;background:#fff;
            box-shadow:0 10px 28px rgba(15,61,94,.08)}
        .orhafe-card small{display:block;color:#64748B;margin-top:4px}
        @media(max-width:900px){.orhafe-grid{grid-template-columns:repeat(2,minmax(0,1fr))}}
        @media(max-width:560px){.orhafe-grid{grid-template-columns:1fr}}
        </style>
        """,
        unsafe_allow_html=True,
    )
    if coordenadoras.empty:
        st.warning("Cadastre as 4 coordenadoras fixas na aba Configuracoes.")
        return
    cards = []
    for _, row in coordenadoras.head(4).iterrows():
        cards.append(
            f"""<div class="orhafe-card">
                <b>{row["nome"]}</b>
                <small>{row.get("funcao", "") or "Coordenadora"}</small>
                <small>{row.get("telefone", "") or ""}</small>
            </div>"""
        )
    st.markdown(f'<div class="orhafe-grid">{"".join(cards)}</div>', unsafe_allow_html=True)


def _render_matriculas(slug):
    st.markdown("### Matriculas")
    st.caption("Matricule participantes buscando diretamente no cadastro de membros.")
    op_membros, df_membros = _membros_opcoes(slug)
    with st.form("form_orhafe_matricula"):
        if not op_membros:
            st.warning("Nao ha membros ativos disponiveis para matricula.")
            membro_label = None
        else:
            membro_label = st.selectbox("Membro", list(op_membros.keys()))
        c1, c2 = st.columns(2)
        data_inicio = c1.date_input("Data de inicio", value=_hoje(), format="DD/MM/YYYY")
        observacoes = c2.text_input("Observacoes")
        if st.form_submit_button("Matricular", type="primary"):
            if not membro_label:
                st.error("Selecione um membro.")
            else:
                id_cadastro = op_membros[membro_label]
                salvar_orhafe_matricula(
                    slug,
                    "",
                    id_cadastro=id_cadastro,
                    data_inicio=data_inicio.isoformat(),
                    observacoes=observacoes,
                )
                st.success("Matricula salva.")
                st.rerun()

    matriculas = listar_orhafe_matriculas(slug, incluir_inativas=True)
    if matriculas.empty:
        st.info("Nenhuma matricula cadastrada.")
        return
    exibir = matriculas.copy()
    exibir["situacao_matricula"] = exibir["ativa"].map({1: "Ativa", 0: "Encerrada"})
    exibir["data_inicio"] = exibir["data_inicio"].apply(_fmt_data)
    exibir["data_fim"] = exibir["data_fim"].apply(_fmt_data)
    st.dataframe(
        exibir[[
            "nome", "telefone", "funcao", "congregacao", "situacao_matricula",
            "data_inicio", "data_fim", "observacoes",
        ]],
        use_container_width=True,
        hide_index=True,
    )
    op_matriculas = {
        f'{int(row["id_matricula"])} - {row["nome"]}': row
        for _, row in matriculas.iterrows()
    }
    with st.expander("Editar matricula", expanded=False):
        selecionada = st.selectbox(
            "Matricula para editar",
            ["Selecione"] + list(op_matriculas.keys()),
            key="editar_matricula_orhafe",
        )
        if selecionada != "Selecione":
            row = op_matriculas[selecionada]
            with st.form(f"form_editar_matricula_orhafe_{int(row['id_matricula'])}"):
                c1, c2 = st.columns(2)
                nome = c1.text_input("Nome", value=row.get("nome", ""))
                telefone = c2.text_input("Telefone / WhatsApp", value=row.get("telefone", ""))
                data_inicio = st.text_input(
                    "Data de inicio",
                    value=str(row.get("data_inicio", "") or ""),
                    placeholder="Ex.: 26/06/2024 ou 26062024",
                )
                ativa = st.selectbox(
                    "Situacao",
                    ["Ativa", "Encerrada"],
                    index=0 if int(row.get("ativa", 1) or 0) == 1 else 1,
                )
                observacoes = st.text_area("Observacoes", value=row.get("observacoes", ""))
                if st.form_submit_button("Atualizar matricula", type="primary"):
                    salvar_orhafe_matricula(
                        slug,
                        nome,
                        id_cadastro=row.get("id_cadastro"),
                        telefone=telefone,
                        data_inicio=_data_iso(normalizar_data_digitada(data_inicio)),
                        observacoes=observacoes,
                        id_matricula=int(row["id_matricula"]),
                        ativa=ativa == "Ativa",
                    )
                    st.success("Matricula atualizada.")
                    st.rerun()

    ativas = matriculas[matriculas["ativa"] == 1]
    if not ativas.empty:
        op_ativas = [
            f'{int(row["id_matricula"])} - {row["nome"]}'
            for _, row in ativas.iterrows()
        ]

        with st.expander("Encerrar matricula", expanded=False):
            st.caption(
                "Use esta opção para remover a matriculada das próximas chamadas "
                "sem apagar o histórico de participação já registrado."
            )
            encerrar = st.selectbox(
                "Matrícula ativa",
                ["Selecione"] + op_ativas,
                key="orhafe_encerrar_matricula",
            )
            data_fim = st.date_input(
                "Data de encerramento",
                value=_hoje(),
                format="DD/MM/YYYY",
                key="orhafe_data_fim_matricula",
            )
            if encerrar != "Selecione" and confirmar_exclusao(
                f"encerrar_orhafe_{encerrar}",
                "Confirmar encerramento da matricula",
            ):
                encerrar_orhafe_matricula(
                    slug,
                    int(encerrar.split(" - ")[0]),
                    data_fim.isoformat(),
                )
                st.success(
                    "Matrícula encerrada. O histórico foi preservado e ela "
                    "não aparecerá nas próximas chamadas."
                )
                st.rerun()

        with st.expander("Excluir matricula sem historico", expanded=False):
            st.caption(
                "A exclusão definitiva só deve ser usada para cadastro lançado por engano. "
                "Se houver histórico, o sistema encerrará a matrícula em vez de apagar."
            )
            excluir = st.selectbox(
                "Matrícula para excluir",
                ["Selecione"] + op_ativas,
                key="orhafe_excluir_matricula",
            )
            if excluir != "Selecione" and confirmar_exclusao(
                f"excluir_orhafe_{excluir}",
                "Confirmar exclusao da matricula sem historico",
            ):
                removida = excluir_orhafe_matricula(
                    slug,
                    int(excluir.split(" - ")[0]),
                    _hoje().isoformat(),
                )
                st.success(
                    "Matrícula excluída."
                    if removida
                    else "A matrícula possui histórico e foi encerrada, sem apagar registros anteriores."
                )
                st.rerun()


def _render_chamada(slug):
    st.markdown("### Chamada do Círculo de Oração")
    lideres = listar_orhafe_lideres(slug)
    if lideres.empty:
        st.warning("Cadastre ate 5 lideres na aba Configuracoes antes de registrar chamada.")
        return
    chamadas_salvas = listar_orhafe_reunioes(slug)
    modo = st.radio(
        "Modo",
        ["Nova chamada", "Editar chamada salva"] if not chamadas_salvas.empty else ["Nova chamada"],
        horizontal=True,
    )
    reuniao_atual = None
    if modo == "Editar chamada salva":
        c_ini, c_fim = st.columns(2)
        editar_inicio = c_ini.date_input(
            "Data inicial para localizar chamada",
            value=_inicio_mes(),
            key="orhafe_edit_ini",
            format="DD/MM/YYYY",
        )
        editar_fim = c_fim.date_input(
            "Data final para localizar chamada",
            value=_hoje(),
            key="orhafe_edit_fim",
            format="DD/MM/YYYY",
        )
        if editar_inicio > editar_fim:
            st.error("A data inicial nao pode ser maior que a data final.")
            return
        chamadas_salvas = listar_orhafe_reunioes(
            slug,
            editar_inicio.isoformat(),
            editar_fim.isoformat(),
        )
        if chamadas_salvas.empty:
            st.info("Nenhuma chamada encontrada no periodo selecionado.")
            return
        op_reunioes = {
            f'{int(row["id_reuniao"])} - {_fmt_data(row["data"])} - {row.get("lider", "") or "sem lider"}': row
            for _, row in chamadas_salvas.iterrows()
        }
        labels_reunioes = list(op_reunioes.keys())
        chave_reuniao = "orhafe_editar_chamada"
        if st.session_state.get(chave_reuniao) not in labels_reunioes:
            st.session_state[chave_reuniao] = labels_reunioes[0]
        idx_atual = labels_reunioes.index(st.session_state[chave_reuniao])
        nav_ant, nav_sel, nav_seg = st.columns([1, 3, 1])
        if nav_ant.button(
            "Dia anterior",
            use_container_width=True,
            disabled=idx_atual >= len(labels_reunioes) - 1,
            key="orhafe_chamada_anterior",
        ):
            st.session_state[chave_reuniao] = labels_reunioes[idx_atual + 1]
        if nav_seg.button(
            "Dia seguinte",
            use_container_width=True,
            disabled=idx_atual <= 0,
            key="orhafe_chamada_seguinte",
        ):
            st.session_state[chave_reuniao] = labels_reunioes[idx_atual - 1]
        with nav_sel:
            reuniao_label = st.selectbox("Chamada salva", labels_reunioes, key=chave_reuniao)
        reuniao_atual = op_reunioes[reuniao_label]
        data_reuniao_original = datetime.date.fromisoformat(str(reuniao_atual["data"]))
        data_reuniao = st.date_input(
            "Data da reuniao",
            value=data_reuniao_original,
            key=f"orhafe_data_edit_{int(reuniao_atual['id_reuniao'])}",
            format="DD/MM/YYYY",
        )
    else:
        data_reuniao = st.date_input("Data da reuniao", value=_hoje(), format="DD/MM/YYYY")

    matriculas = listar_orhafe_matriculas(slug, incluir_inativas=True)
    if matriculas.empty:
        st.warning("Cadastre matriculas antes de registrar chamada.")
        return

    matriculas = _filtrar_matriculas_validas_na_data(matriculas, data_reuniao)
    if matriculas.empty:
        st.warning(
            "Nenhuma matricula estava ativa na data desta chamada. "
            "Verifique a data da reuniao ou a data de inicio das matriculas."
        )
        return

    lider_opcoes = _lideres_opcoes(lideres)
    lider_labels = list(lider_opcoes.keys())
    lider_index = 0
    if reuniao_atual is not None and reuniao_atual.get("id_lider"):
        for idx, label in enumerate(lider_labels):
            if lider_opcoes[label] == int(reuniao_atual["id_lider"]):
                lider_index = idx
                break

    presencas_salvas = {}
    visitantes_salvos = []
    tema_atual = ""
    obs_atual = ""
    ofertas_atual = 0.0
    if reuniao_atual is not None:
        tema_atual = reuniao_atual.get("tema", "")
        obs_atual = reuniao_atual.get("observacoes", "")
        ofertas_atual = float(reuniao_atual.get("ofertas", 0) or 0)
        df_pres = carregar_orhafe_presencas(slug, int(reuniao_atual["id_reuniao"]))
        for _, row in df_pres.iterrows():
            if int(row.get("visitante", 0) or 0):
                visitantes_salvos.append(row["nome"])
            elif row.get("id_matricula"):
                presencas_salvas[int(row["id_matricula"])] = bool(row["presente"])

    acao_presencas = st.radio(
        "Presenças da lista de chamada",
        ["Manter marcação atual", "Marcar todas", "Desmarcar todas"],
        horizontal=True,
        key=f"orhafe_acao_presencas_{data_reuniao.isoformat()}",
    )

    with st.form("form_orhafe_chamada"):
        c1, c2 = st.columns(2)
        lider_label = c1.selectbox("Lider da chamada", lider_labels, index=lider_index)
        tema = c2.text_input("Tema/assunto da oracao", value=tema_atual)
        ofertas = st.number_input(
            "Ofertas",
            min_value=0.0,
            step=1.0,
            value=ofertas_atual,
            format="%.2f",
        )
        obs = st.text_area("Observacoes", value=obs_atual)

        with st.expander("Lista de chamada", expanded=True):
            dados = matriculas[["id_matricula", "nome"]].copy()
            if acao_presencas == "Marcar todas":
                dados["presente"] = True
            elif acao_presencas == "Desmarcar todas":
                dados["presente"] = False
            else:
                dados["presente"] = dados["id_matricula"].apply(
                    lambda x: presencas_salvas.get(int(x), True)
                )
            editado = st.data_editor(
                dados,
                hide_index=True,
                use_container_width=True,
                key=f"orhafe_editor_chamada_{data_reuniao.isoformat()}_{acao_presencas}",
                disabled=["id_matricula", "nome"],
                column_config={
                    "id_matricula": st.column_config.NumberColumn("ID"),
                    "nome": st.column_config.TextColumn("Nome"),
                    "presente": st.column_config.CheckboxColumn("Presente"),
                },
            )

        with st.expander("Visitantes", expanded=False):
            st.caption("Informe uma visitante por linha e marque a coluna Visitante.")
            base_visitantes = pd.DataFrame(
                {
                    "nome": visitantes_salvos + ["", "", ""],
                    "visitante": [True] * len(visitantes_salvos) + [False, False, False],
                }
            )
            visitantes_edit = st.data_editor(
                base_visitantes,
                hide_index=True,
                use_container_width=True,
                num_rows="dynamic",
                column_config={
                    "nome": st.column_config.TextColumn("Nome da visitante"),
                    "visitante": st.column_config.CheckboxColumn("Visitante"),
                },
            )

        qtd_matriculadas = int(len(editado))
        qtd_presentes = int(editado["presente"].fillna(False).astype(bool).sum())
        qtd_ausentes = max(qtd_matriculadas - qtd_presentes, 0)
        qtd_visitantes = int(
            visitantes_edit[
                visitantes_edit["visitante"].fillna(False).astype(bool)
                & visitantes_edit["nome"].astype(str).str.strip().ne("")
            ].shape[0]
        )
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Matriculadas", qtd_matriculadas)
        m2.metric("Presentes", qtd_presentes)
        m3.metric("Ausentes", qtd_ausentes)
        m4.metric("Visitantes", qtd_visitantes)

        if st.form_submit_button("Salvar chamada", type="primary"):
            presencas = {
                int(row["id_matricula"]): bool(row["presente"])
                for _, row in editado.iterrows()
            }
            visitantes = visitantes_edit[
                visitantes_edit["visitante"].fillna(False).astype(bool)
            ]["nome"].astype(str).str.strip().tolist()
            salvar_orhafe_chamada(
                slug,
                data_reuniao.isoformat(),
                id_lider=lider_opcoes[lider_label],
                tema=tema,
                observacoes=obs,
                presencas=presencas,
                visitantes=visitantes,
                ofertas=ofertas,
                id_reuniao=int(reuniao_atual["id_reuniao"]) if reuniao_atual is not None else None,
            )
            st.success("Chamada salva.")
            st.rerun()


def _render_relatorios(slug):
    st.markdown("### Relatórios do Círculo de Oração")
    c1, c2 = st.columns(2)
    inicio = c1.date_input("Data inicial", value=_inicio_mes(), key="orhafe_rel_ini", format="DD/MM/YYYY")
    fim = c2.date_input("Data final", value=_hoje(), key="orhafe_rel_fim", format="DD/MM/YYYY")
    if inicio > fim:
        st.error("A data inicial nao pode ser maior que a data final.")
        return

    reunioes = listar_orhafe_reunioes(slug, inicio.isoformat(), fim.isoformat())
    freq = relatorio_orhafe_frequencia(slug, inicio.isoformat(), fim.isoformat())
    visitantes = relatorio_orhafe_visitantes(slug, inicio.isoformat(), fim.isoformat())
    st.markdown("#### Relatorio geral")
    if reunioes.empty:
        st.info("Nenhuma reuniao registrada no periodo selecionado.")
    else:
        totais = _totais_reunioes(reunioes, freq, visitantes)
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Total de reunioes", totais["Reunioes"])
        c2.metric("Presentes no periodo", totais["Presentes"])
        c3.metric("Ausentes no periodo", totais["Ausentes"])
        c4.metric("Total de visitantes", totais["Visitantes"])
        c5, c6 = st.columns(2)
        c5.metric("Matriculadas no periodo", totais["Matriculadas"])
        c6.metric("Total de ofertas", _moeda(totais["Ofertas"]))

        st.markdown("#### Gráfico geral do Círculo de Oração")
        _grafico_totais_orhafe(
            "Resumo geral do Círculo de Oração",
            _indicadores_grafico_resumo(reunioes, visitantes=visitantes),
        )

        st.markdown("#### Evolucao das reunioes")
        _grafico_reunioes(reunioes)

    st.markdown("#### Frequencia das matriculadas")
    _grafico_frequencia(freq)

    with st.expander("Reunioes registradas", expanded=False):
        if reunioes.empty:
            st.info("Nenhuma reuniao registrada no periodo.")
        else:
            exibir = reunioes.copy()
            exibir["data"] = exibir["data"].apply(_fmt_data)
            exibir["ofertas"] = exibir["ofertas"].apply(_moeda)
            exibir["frequencia"] = (
                exibir["presentes"].fillna(0)
                / exibir["matriculadas"].replace(0, 1).fillna(1)
                * 100
            ).round(1).apply(_pct)
            st.dataframe(
                exibir[[
                    "data", "lider", "tema", "matriculadas", "presentes",
                    "ausentes", "visitantes", "frequencia", "ofertas",
                    "observacoes",
                ]],
                use_container_width=True,
                hide_index=True,
            )
            st.download_button(
                "Baixar reunioes CSV",
                data=gerar_csv(reunioes),
                file_name="orhafe_reunioes.csv",
                mime="text/csv",
            )

    with st.expander("Relatorio individual por matriculada", expanded=False):
        if freq.empty:
            st.info("Sem dados individuais no periodo.")
        else:
            exibir = freq.copy()
            total = exibir["presencas"] + exibir["ausencias"]
            freq_numerica = (
                exibir["presencas"] / total.where(total > 0, 1) * 100
            ).round(1)
            exibir["frequencia_pct"] = freq_numerica.apply(_pct)
            exibir["acompanhamento"] = freq_numerica.apply(
                lambda v: "Acompanhar em oracao/visita" if v < 60 else "Regular"
            )
            st.dataframe(exibir, use_container_width=True, hide_index=True)
            st.download_button(
                "Baixar relatorio individual CSV",
                data=gerar_csv(freq),
                file_name="orhafe_frequencia.csv",
                mime="text/csv",
            )


def _render_configuracoes(slug):
    st.markdown("### Coordenadoras e lideres")
    coordenadoras = listar_orhafe_coordenadoras(slug, incluir_inativas=True)
    lideres = listar_orhafe_lideres(slug, incluir_inativos=True)
    op_membros, df_membros = _membros_opcoes(slug)

    with st.expander("Cadastrar coordenadora fixa", expanded=coordenadoras.empty):
        if len(coordenadoras[coordenadoras["ativa"] == 1]) >= 4:
            st.info("Ja existem 4 coordenadoras ativas. Inative ou edite uma antes de cadastrar outra.")
        with st.form("form_orhafe_coordenadora"):
            modo_coord = st.radio(
                "Origem da coordenadora",
                ["Cadastro de membros", "Inserir manualmente"],
                horizontal=True,
                key="modo_coord_orhafe",
            )
            id_cadastro_coord = None
            nome = ""
            telefone = ""
            funcao = "Coordenadora"
            if modo_coord == "Cadastro de membros":
                if not op_membros:
                    st.warning("Nao ha membros ativos disponiveis no cadastro.")
                else:
                    membro_label = st.selectbox(
                        "Coordenadora",
                        list(op_membros.keys()),
                        help="A lista traz somente membros ativos cadastrados.",
                    )
                    id_cadastro_coord = op_membros[membro_label]
                    row_membro = df_membros[
                        df_membros["id_cadastro"].astype(int) == int(id_cadastro_coord)
                    ].iloc[0]
                    c1, c2 = st.columns(2)
                    c1.text_input("Nome", value=row_membro.get("nome", ""), disabled=True)
                    c2.text_input("Telefone / WhatsApp", value=row_membro.get("telefone", ""), disabled=True)
                    funcao = row_membro.get("funcao", "") or "Coordenadora"
                    st.text_input("Funcao no cadastro", value=funcao, disabled=True)
            else:
                c1, c2 = st.columns(2)
                nome = c1.text_input("Nome da coordenadora")
                telefone = c2.text_input("Telefone / WhatsApp")
                funcao = st.text_input("Funcao", value="Coordenadora")
            ordem = st.number_input("Ordem", min_value=1, max_value=4, value=1, step=1)
            observacoes = st.text_area("Observacoes", key="obs_coord_orhafe")
            if st.form_submit_button("Salvar coordenadora", type="primary"):
                if len(coordenadoras[coordenadoras["ativa"] == 1]) >= 4:
                    st.error("O Círculo de Oração deve manter no máximo 4 coordenadoras ativas.")
                elif modo_coord == "Cadastro de membros" and not id_cadastro_coord:
                    st.error("Selecione uma coordenadora no cadastro de membros.")
                else:
                    salvar_orhafe_coordenadora(
                        slug,
                        nome,
                        id_cadastro=id_cadastro_coord,
                        telefone=telefone,
                        funcao=funcao,
                        ordem=ordem,
                        ativa=True,
                        observacoes=observacoes,
                    )
                    st.success("Coordenadora salva.")
                    st.rerun()

    if not coordenadoras.empty:
        st.markdown("#### Coordenadoras cadastradas")
        st.dataframe(
            coordenadoras[["id_cadastro", "nome", "telefone", "funcao", "ordem", "ativa", "observacoes"]],
            use_container_width=True,
            hide_index=True,
        )
        with st.expander("Editar ou excluir coordenadora", expanded=False):
            op_coord = {
                f'{int(row["id_coordenadora"])} - {row["nome"]}': row
                for _, row in coordenadoras.iterrows()
            }
            selecionada = st.selectbox(
                "Coordenadora",
                ["Selecione"] + list(op_coord.keys()),
                key="editar_coord_orhafe",
            )
            if selecionada != "Selecione":
                row = op_coord[selecionada]
                with st.form(f"form_editar_coord_orhafe_{int(row['id_coordenadora'])}"):
                    c1, c2 = st.columns(2)
                    nome = c1.text_input("Nome", value=row.get("nome", ""))
                    telefone = c2.text_input("Telefone / WhatsApp", value=row.get("telefone", ""))
                    c3, c4 = st.columns(2)
                    funcao = c3.text_input("Funcao", value=row.get("funcao", "Coordenadora"))
                    ordem = c4.number_input(
                        "Ordem",
                        min_value=1,
                        max_value=4,
                        value=max(1, min(int(row.get("ordem", 1) or 1), 4)),
                        step=1,
                    )
                    ativa = st.selectbox(
                        "Situacao",
                        ["Ativa", "Inativa"],
                        index=0 if int(row.get("ativa", 1) or 0) == 1 else 1,
                    )
                    observacoes = st.text_area("Observacoes", value=row.get("observacoes", ""))
                    if st.form_submit_button("Atualizar coordenadora", type="primary"):
                        salvar_orhafe_coordenadora(
                            slug,
                            nome,
                            id_cadastro=row.get("id_cadastro"),
                            telefone=telefone,
                            funcao=funcao,
                            ordem=ordem,
                            ativa=ativa == "Ativa",
                            observacoes=observacoes,
                            id_coordenadora=int(row["id_coordenadora"]),
                        )
                        st.success("Coordenadora atualizada.")
                        st.rerun()
                if confirmar_exclusao(
                    f"excluir_coord_orhafe_{int(row['id_coordenadora'])}",
                    "Excluir coordenadora selecionada",
                ):
                    excluir_orhafe_coordenadora(slug, int(row["id_coordenadora"]))
                    st.success("Coordenadora excluida.")
                    st.rerun()

    with st.expander("Cadastrar lider", expanded=lideres.empty):
        if len(lideres[lideres["ativo"] == 1]) >= 5:
            st.info("Ja existem 5 lideres ativos. Inative ou edite uma antes de cadastrar outro.")
        with st.form("form_orhafe_lider"):
            modo_lider = st.radio(
                "Origem da lider",
                ["Cadastro de membros", "Inserir manualmente"],
                horizontal=True,
                key="modo_lider_orhafe",
            )
            id_cadastro_lider = None
            nome = ""
            telefone = ""
            funcao = "Lider"
            if modo_lider == "Cadastro de membros":
                if not op_membros:
                    st.warning("Nao ha membros ativos disponiveis no cadastro.")
                else:
                    membro_label = st.selectbox(
                        "Lider",
                        list(op_membros.keys()),
                        help="A lista traz somente membros ativos cadastrados.",
                        key="lider_membro_orhafe",
                    )
                    id_cadastro_lider = op_membros[membro_label]
                    row_membro = df_membros[
                        df_membros["id_cadastro"].astype(int) == int(id_cadastro_lider)
                    ].iloc[0]
                    c1, c2 = st.columns(2)
                    c1.text_input("Nome", value=row_membro.get("nome", ""), disabled=True, key="lider_nome_auto")
                    c2.text_input(
                        "Telefone / WhatsApp",
                        value=row_membro.get("telefone", ""),
                        disabled=True,
                        key="lider_tel_auto",
                    )
                    funcao = row_membro.get("funcao", "") or "Lider"
                    st.text_input("Funcao no cadastro", value=funcao, disabled=True, key="lider_funcao_auto")
            else:
                c1, c2 = st.columns(2)
                nome = c1.text_input("Nome da lider")
                telefone = c2.text_input("Telefone / WhatsApp")
                funcao = st.text_input("Funcao", value="Lider")
            ordem = st.number_input("Ordem", min_value=1, max_value=5, value=1, step=1)
            observacoes = st.text_area("Observacoes", key="obs_lider_orhafe")
            if st.form_submit_button("Salvar lider", type="primary"):
                if len(lideres[lideres["ativo"] == 1]) >= 5:
                    st.error("O Círculo de Oração deve manter no máximo 5 líderes ativas.")
                elif modo_lider == "Cadastro de membros" and not id_cadastro_lider:
                    st.error("Selecione uma lider no cadastro de membros.")
                else:
                    salvar_orhafe_lider(
                        slug,
                        nome,
                        id_cadastro=id_cadastro_lider,
                        telefone=telefone,
                        funcao=funcao,
                        ordem=ordem,
                        ativo=True,
                        observacoes=observacoes,
                    )
                    st.success("Lider salva.")
                    st.rerun()

    if not lideres.empty:
        st.markdown("#### Lideres cadastradas")
        st.dataframe(
            lideres[["id_cadastro", "nome", "telefone", "funcao", "ordem", "ativo", "observacoes"]],
            use_container_width=True,
            hide_index=True,
        )
        with st.expander("Editar ou excluir lider", expanded=False):
            op_lider = {
                f'{int(row["id_lider"])} - {row["nome"]}': row
                for _, row in lideres.iterrows()
            }
            selecionada = st.selectbox(
                "Lider",
                ["Selecione"] + list(op_lider.keys()),
                key="editar_lider_orhafe",
            )
            if selecionada != "Selecione":
                row = op_lider[selecionada]
                with st.form(f"form_editar_lider_orhafe_{int(row['id_lider'])}"):
                    c1, c2 = st.columns(2)
                    nome = c1.text_input("Nome", value=row.get("nome", ""))
                    telefone = c2.text_input("Telefone / WhatsApp", value=row.get("telefone", ""))
                    c3, c4 = st.columns(2)
                    funcao = c3.text_input("Funcao", value=row.get("funcao", "Lider"))
                    ordem = c4.number_input(
                        "Ordem",
                        min_value=1,
                        max_value=5,
                        value=max(1, min(int(row.get("ordem", 1) or 1), 5)),
                        step=1,
                    )
                    ativo = st.selectbox(
                        "Situacao",
                        ["Ativa", "Inativa"],
                        index=0 if int(row.get("ativo", 1) or 0) == 1 else 1,
                    )
                    observacoes = st.text_area("Observacoes", value=row.get("observacoes", ""))
                    if st.form_submit_button("Atualizar lider", type="primary"):
                        salvar_orhafe_lider(
                            slug,
                            nome,
                            id_cadastro=row.get("id_cadastro"),
                            telefone=telefone,
                            funcao=funcao,
                            ordem=ordem,
                            ativo=ativo == "Ativa",
                            observacoes=observacoes,
                            id_lider=int(row["id_lider"]),
                        )
                        st.success("Lider atualizada.")
                        st.rerun()
                if confirmar_exclusao(
                    f"excluir_lider_orhafe_{int(row['id_lider'])}",
                    "Excluir ou inativar lider selecionada",
                ):
                    removida = excluir_orhafe_lider(slug, int(row["id_lider"]))
                    st.success("Lider excluida." if removida else "Lider inativada porque possui historico.")
                    st.rerun()


def _render_secretarias(slug):
    st.markdown("### Secretárias do Círculo de Oração")
    st.caption(
        "Secretaria de chamada acessa somente a chamada. "
        "Secretaria geral acessa todo o módulo Círculo de Oração."
    )
    op_membros, df_membros = _membros_opcoes(slug)
    with st.expander("Cadastrar secretaria", expanded=False):
        with st.form("form_orhafe_secretaria"):
            id_cadastro_secretaria = None
            nome = ""
            telefone = ""
            if not op_membros:
                st.warning("Nao ha membros ativos disponiveis no cadastro.")
            else:
                membro_label = st.selectbox(
                    "Secretaria",
                    list(op_membros.keys()),
                    help="A lista traz somente membros ativos cadastrados.",
                    key="secretaria_membro_orhafe",
                )
                id_cadastro_secretaria = op_membros[membro_label]
                row_membro = df_membros[
                    df_membros["id_cadastro"].astype(int) == int(id_cadastro_secretaria)
                ].iloc[0]
                c1, c2 = st.columns(2)
                c1.text_input("Nome", value=row_membro.get("nome", ""), disabled=True)
                c2.text_input(
                    "Telefone / WhatsApp",
                    value=row_membro.get("telefone", ""),
                    disabled=True,
                )
                nome = row_membro.get("nome", "")
                telefone = row_membro.get("telefone", "")
            usuario = st.text_input("Usuario")
            c3, c4 = st.columns(2)
            senha = c3.text_input("PIN de 4 digitos", type="password", max_chars=4)
            perfil_rotulo = c4.selectbox(
                "Perfil",
                ["Secretaria de chamada", "Secretaria geral"],
            )
            perfil = "geral" if perfil_rotulo == "Secretaria geral" else "chamada"
            email = st.text_input("E-mail", help="Opcional. O cadastro de membros atual nao possui e-mail.")
            observacoes = st.text_area("Observacoes")
            if st.form_submit_button("Salvar secretaria", type="primary"):
                try:
                    if not id_cadastro_secretaria:
                        st.error("Selecione uma secretaria no cadastro de membros.")
                        return
                    salvar_orhafe_secretaria(
                        slug,
                        nome,
                        usuario,
                        senha,
                        id_cadastro=id_cadastro_secretaria,
                        perfil=perfil,
                        telefone=telefone,
                        email=email,
                        situacao="Ativo",
                        observacoes=observacoes,
                    )
                    st.success("Secretaria cadastrada.")
                    st.rerun()
                except Exception as exc:
                    st.error(str(exc))

    df = listar_orhafe_secretarias(slug)
    if df.empty:
        st.info("Nenhuma secretária do Círculo de Oração cadastrada.")
        return

    exibir = df.copy()
    exibir["perfil"] = exibir["perfil"].map({
        "chamada": "Secretaria de chamada",
        "geral": "Secretaria geral",
    }).fillna(exibir["perfil"])
    st.dataframe(
        exibir[["id_cadastro", "nome", "usuario", "perfil", "telefone", "email", "situacao"]],
        use_container_width=True,
        hide_index=True,
    )

    opcoes = {
        f'{int(row["id_secretaria"])} - {row["nome"]} - {row["usuario"]}': row
        for _, row in df.iterrows()
    }
    selecionada = st.selectbox("Editar secretaria", ["Selecione"] + list(opcoes.keys()))
    if selecionada == "Selecione":
        return
    row = opcoes[selecionada]
    id_secretaria = int(row["id_secretaria"])
    with st.form(f"form_editar_secretaria_orhafe_{id_secretaria}"):
        c1, c2 = st.columns(2)
        nome = c1.text_input("Nome", value=row["nome"])
        usuario = c2.text_input("Usuario", value=row["usuario"])
        c3, c4 = st.columns(2)
        senha = c3.text_input("Novo PIN de 4 digitos", type="password", max_chars=4)
        perfil_rotulo = c4.selectbox(
            "Perfil",
            ["Secretaria de chamada", "Secretaria geral"],
            index=1 if row["perfil"] == "geral" else 0,
        )
        perfil = "geral" if perfil_rotulo == "Secretaria geral" else "chamada"
        c5, c6 = st.columns(2)
        telefone = c5.text_input("Telefone / WhatsApp", value=row.get("telefone", ""))
        email = c6.text_input("E-mail", value=row.get("email", ""))
        situacao = st.selectbox(
            "Situacao",
            ["Ativo", "Inativo"],
            index=0 if row.get("situacao") == "Ativo" else 1,
        )
        observacoes = st.text_area("Observacoes", value=row.get("observacoes", ""))
        if st.form_submit_button("Atualizar secretaria", type="primary"):
            try:
                salvar_orhafe_secretaria(
                    slug,
                    nome,
                    usuario,
                    senha,
                    id_cadastro=row.get("id_cadastro"),
                    perfil=perfil,
                    telefone=telefone,
                    email=email,
                    situacao=situacao,
                    observacoes=observacoes,
                    id_secretaria=id_secretaria,
                )
                st.success("Secretaria atualizada.")
                st.rerun()
            except Exception as exc:
                st.error(str(exc))

    if confirmar_exclusao(
        f"inativar_secretaria_orhafe_{id_secretaria}",
        "Inativar secretaria selecionada",
    ):
        inativar_orhafe_secretaria(slug, id_secretaria)
        st.success("Secretaria inativada.")
        st.rerun()


def render():
    st.subheader("Círculo de Oração")
    st.caption("Gestão de matrículas, chamadas, visitantes, líderes e relatórios do ministério de oração.")
    slug = slug_da_sessao()
    if not slug:
        st.error("Sessao invalida. Faca login novamente.")
        return

    _render_coordenadoras(slug)

    secretaria = st.session_state.get("secretaria_orhafe", {})
    modo = st.session_state.get("modo", "")
    if modo == "pastor_auxiliar":
        st.info("Acesso de Pastor Auxiliar: somente relatórios do Círculo de Oração.")
        _render_relatorios(slug)
        return
    if modo == "secretaria_orhafe" and isinstance(secretaria, dict):
        perfil = secretaria.get("perfil", "chamada")
        if perfil == "chamada":
            st.info("Acesso de secretária de chamada do Círculo de Oração.")
            _render_chamada(slug)
            return
        st.info("Acesso de secretária geral do Círculo de Oração.")

    abas = [
        "Chamada",
        "Matriculas",
        "Relatorios",
        "Coordenadoras e lideres",
    ]
    if modo != "secretaria_orhafe" or secretaria.get("perfil") == "geral":
        abas.append("Secretarias")

    tabs = st.tabs(abas)
    tab_chamada, tab_matriculas, tab_relatorios, tab_config = tabs[:4]
    with tab_chamada:
        _render_chamada(slug)
    with tab_matriculas:
        _render_matriculas(slug)
    with tab_relatorios:
        _render_relatorios(slug)
    with tab_config:
        _render_configuracoes(slug)
    if len(tabs) > 4:
        with tabs[4]:
            _render_secretarias(slug)
