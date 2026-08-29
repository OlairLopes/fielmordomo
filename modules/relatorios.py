import datetime
import io
import logging

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from data.repository import (
    PLANO_LEITURA_PADRAO,
    carregar_cadastros,
    carregar_lancamentos,
    listar_confirmacoes_leitura_biblica,
    listar_planos_leitura_biblica,
    obter_leitura_do_dia,
    obter_logo_igreja,
    resumo_leitores_biblia,
)
from modules.leitura_biblica import render_importar_leitores
from report_exports import AZUL, gerar_excel_relatorio, gerar_pdf_relatorio
from utils.helpers import formatar_moeda, gerar_csv, slug_da_sessao


LOGGER = logging.getLogger(__name__)
COLUNAS_LANCAMENTOS = {
    "id_lancamento", "data", "tipo", "categoria", "valor",
}
COLUNAS_TEXTO = [
    "tipo", "categoria", "subcategoria", "descricao", "forma_pagamento",
    "nome_cadastro", "tipo_cadastro", "lote_id",
]
CORES = {
    "entrada": "#1D9E75",
    "saida": "#D85A30",
}
CONFIG_PLOTLY = {
    "displayModeBar": False,
    "displaylogo": False,
    "responsive": True,
    "scrollZoom": False,
    "doubleClick": False,
}


def _texto(serie):
    return serie.fillna("").astype(str).str.strip()


def _normalizar_lancamentos(df):
    df = df.copy()
    ausentes = sorted(COLUNAS_LANCAMENTOS - set(df.columns))
    if ausentes:
        return df, ausentes, 0, 0

    for coluna in COLUNAS_TEXTO:
        if coluna not in df.columns:
            df[coluna] = ""
        df[coluna] = _texto(df[coluna])

    if "id_cadastro" not in df.columns:
        df["id_cadastro"] = pd.NA

    datas_originais = _texto(df["data"])
    valores_originais = _texto(df["valor"])
    df["data"] = pd.to_datetime(df["data"], errors="coerce")
    valores = pd.to_numeric(df["valor"], errors="coerce")
    datas_invalidas = int((datas_originais.ne("") & df["data"].isna()).sum())
    valores_invalidos = int((valores_originais.ne("") & valores.isna()).sum())
    df["valor"] = valores.fillna(0.0)
    df["tipo_norm"] = _texto(df["tipo"]).str.upper()
    df["categoria_norm"] = _texto(df["categoria"]).str.upper()
    df["subcategoria"] = _texto(df["subcategoria"])
    df["mes_ref"] = df["data"].dt.to_period("M")
    return df, ausentes, datas_invalidas, valores_invalidos


def _opcoes_vinculos(cad):
    colunas = {"id_cadastro", "nome", "tipo_cadastro"}
    if cad.empty or not colunas.issubset(cad.columns):
        return {"Todos": None}

    registros = cad.copy()
    registros["nome"] = _texto(registros["nome"])
    registros["tipo_cadastro"] = _texto(registros["tipo_cadastro"])
    registros = registros[registros["nome"].ne("")]
    registros = registros.drop_duplicates("id_cadastro").sort_values(
        ["tipo_cadastro", "nome"]
    )

    opcoes = {"Todos": None}
    for _, row in registros.iterrows():
        try:
            id_cadastro = int(row["id_cadastro"])
        except (TypeError, ValueError):
            continue
        rotulo = f"{id_cadastro} | {row['tipo_cadastro']} | {row['nome']}"
        opcoes[rotulo] = id_cadastro
    return opcoes


def _resumo_por(df, coluna, rotulo):
    if df.empty:
        return pd.DataFrame(columns=[rotulo, "Quantidade", "Valor total"])
    base = df.copy()
    base[coluna] = _texto(base[coluna]).replace("", "Nao informado")
    resumo = (
        base.groupby(coluna, dropna=False)
        .agg(Quantidade=("id_lancamento", "count"), Valor=("valor", "sum"))
        .reset_index()
        .sort_values("Valor", ascending=False)
        .rename(columns={coluna: rotulo, "Valor": "Valor total"})
    )
    return resumo


def _formatar_resumo(df):
    exibicao = df.copy()
    if "Valor total" in exibicao.columns:
        exibicao["Valor total"] = exibicao["Valor total"].apply(formatar_moeda)
    return exibicao


def _grafico_barras_mensal(mensal):
    fig = go.Figure()
    for coluna, cor in (("Entradas", CORES["entrada"]), ("Saidas", CORES["saida"])):
        valores = mensal[coluna].tolist()
        fig.add_trace(go.Bar(
            name=coluna,
            x=mensal.index.tolist(),
            y=valores,
            marker_color=cor,
            text=[formatar_moeda(valor) if valor else "" for valor in valores],
            textposition="outside",
            cliponaxis=False,
            customdata=[formatar_moeda(valor) for valor in valores],
            hovertemplate=f"<b>{coluna}</b><br>Mes: %{{x}}<br>%{{customdata}}<extra></extra>",
        ))
    fig.update_layout(
        autosize=True,
        barmode="group",
        height=440,
        margin=dict(l=20, r=20, t=20, b=20),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=1.02,
            xanchor="left",
            x=0,
        ),
        dragmode=False,
        xaxis=dict(title="Mes", showgrid=False, fixedrange=True),
        yaxis=dict(title="Valor (R$)", gridcolor="rgba(148,163,184,0.22)", fixedrange=True),
    )
    return fig


def _detalhes_exibicao(df):
    colunas = [
        "id_lancamento", "data", "tipo", "categoria", "subcategoria",
        "descricao", "forma_pagamento", "nome_cadastro", "tipo_cadastro",
        "lote_id", "valor",
    ]
    detalhes = df[[col for col in colunas if col in df.columns]].copy()
    if "data" in detalhes.columns:
        detalhes["data"] = detalhes["data"].dt.strftime("%d/%m/%Y").fillna("")
    if "valor" in detalhes.columns:
        detalhes["valor"] = detalhes["valor"].apply(formatar_moeda)
    return detalhes.rename(columns={
        "id_lancamento": "ID",
        "data": "Data",
        "tipo": "Tipo",
        "categoria": "Categoria",
        "subcategoria": "Subcategoria",
        "descricao": "Descricao",
        "forma_pagamento": "Pagamento",
        "nome_cadastro": "Vinculado a",
        "tipo_cadastro": "Tipo vinculo",
        "lote_id": "Lote",
        "valor": "Valor",
    })


def _detalhes_exportacao(df):
    detalhes = df.copy()
    detalhes["data"] = detalhes["data"].dt.strftime("%d/%m/%Y").fillna("")
    remover = ["tipo_norm", "categoria_norm", "mes_ref"]
    return detalhes.drop(columns=[c for c in remover if c in detalhes.columns])


def _aplicar_filtros(df, periodo, tipo, categoria, subcategoria, id_cadastro, lote_id):
    inicio, fim = periodo
    filtrado = df[
        df["data"].between(pd.Timestamp(inicio), pd.Timestamp(fim), inclusive="both")
    ].copy()
    if tipo != "Todos":
        filtrado = filtrado[filtrado["tipo"] == tipo]
    if categoria != "Todas":
        filtrado = filtrado[filtrado["categoria"] == categoria]
    if subcategoria != "Todas":
        filtrado = filtrado[filtrado["subcategoria"] == subcategoria]
    if id_cadastro is not None:
        ids = pd.to_numeric(filtrado["id_cadastro"], errors="coerce")
        filtrado = filtrado[ids == id_cadastro]
    if lote_id != "Todos":
        filtrado = filtrado[filtrado["lote_id"] == lote_id]
    return filtrado


def _injetar_css():
    st.markdown("""
    <style>
    .rel-filtros {
        background:#F8FAFC;
        border:1px solid #E2E8F0;
        border-radius:14px;
        margin:4px 0 14px;
        padding:14px 16px 8px;
    }
    .rel-filtros strong { color:#0F172A;font-size:1rem; }
    .rel-filtros span {
        color:#64748B;
        display:block;
        font-size:.78rem;
        margin-top:3px;
    }
    .stPlotlyChart, [data-testid="stPlotlyChart"] {
        background:#FFFFFF;
        border:1px solid #E2E8F0;
        border-radius:14px;
        box-shadow:0 10px 24px rgba(15,23,42,.14);
        box-sizing:border-box;
        max-width:100%;
        min-width:0;
        overflow:hidden;
        padding:10px;
        width:100%;
    }
    [data-testid="stPlotlyChart"] > div,
    [data-testid="stPlotlyChart"] .js-plotly-plot,
    [data-testid="stPlotlyChart"] .plot-container,
    [data-testid="stPlotlyChart"] .svg-container {
        box-sizing:border-box;
        max-width:100%!important;
        min-width:0!important;
        width:100%!important;
    }
    @media (max-width:640px) {
        .stPlotlyChart, [data-testid="stPlotlyChart"] {
            border-radius:10px;
            box-shadow:0 6px 16px rgba(15,23,42,.12);
            padding:4px;
        }
    }
    </style>
    """, unsafe_allow_html=True)


def _periodo_por_atualizacao(atalho, data_min, data_max, hoje):
    fim = min(max(hoje, data_min), data_max)
    if atalho == "Mes atual":
        inicio = max(data_min, fim.replace(day=1))
    elif atalho == "Ultimos 30 dias":
        inicio = max(data_min, fim - datetime.timedelta(days=29))
    elif atalho == "Ano atual":
        inicio = max(data_min, datetime.date(fim.year, 1, 1))
    else:
        return None
    return inicio, fim


def render():
    _injetar_css()
    slug = slug_da_sessao()
    igreja = st.session_state.get("igreja", {})
    if not isinstance(igreja, dict):
        igreja = {}
    st.subheader("📈 Relatórios")

    tab_financeiro, tab_leitura = st.tabs(["Financeiro", "Plano de Leitura"])
    with tab_financeiro:
        _render_financeiro(slug, igreja)
    with tab_leitura:
        _render_leitura_biblica(slug)


def _render_financeiro(slug, igreja):
    df_bruto = carregar_lancamentos(slug)
    cad = carregar_cadastros(slug)
    if df_bruto.empty:
        st.info("Ainda nao ha lancamentos.")
        return

    df, ausentes, datas_invalidas, valores_invalidos = _normalizar_lancamentos(df_bruto)
    if ausentes:
        st.error("Relatorio indisponivel. Colunas ausentes: " + ", ".join(ausentes))
        return

    if datas_invalidas or valores_invalidos:
        st.warning(
            "Existem registros antigos com dados invalidos: "
            f"{datas_invalidas} data(s) e {valores_invalidos} valor(es). "
            "Esses registros devem ser revisados."
        )

    datas_validas = df["data"].dropna()
    if datas_validas.empty:
        st.error("Nao existem datas validas para gerar o relatorio.")
        return

    hoje = datetime.date.today()
    data_min = datas_validas.min().date()
    data_max = max(hoje, datas_validas.max().date())
    fim_padrao = min(max(hoje, data_min), data_max)
    inicio_padrao = max(data_min, fim_padrao.replace(day=1))

    st.markdown(
        '<div class="rel-filtros"><strong>Filtros do relatorio</strong>'
        '<span>Defina o periodo e refine os lancamentos exibidos nas abas e exportacoes.</span></div>',
        unsafe_allow_html=True,
    )

    atalho = st.radio(
        "Periodo rapido",
        ["Mes atual", "Ultimos 30 dias", "Ano atual", "Personalizado"],
        horizontal=True,
        key="rel_periodo_atalho",
    )
    periodo_rapido = _periodo_por_atualizacao(atalho, data_min, data_max, hoje)
    if periodo_rapido:
        st.session_state["rel_inicio"] = periodo_rapido[0]
        st.session_state["rel_fim"] = periodo_rapido[1]
    else:
        st.session_state.setdefault("rel_inicio", inicio_padrao)
        st.session_state.setdefault("rel_fim", fim_padrao)

    f1, f2 = st.columns(2)
    with f1:
        inicio = st.date_input(
            "Data inicial",
            min_value=data_min,
            max_value=data_max,
            format="DD/MM/YYYY",
            key="rel_inicio",
        )
    with f2:
        fim = st.date_input(
            "Data final",
            min_value=data_min,
            max_value=data_max,
            format="DD/MM/YYYY",
            key="rel_fim",
        )
    if inicio > fim:
        st.error("A data inicial nao pode ser posterior a data final.")
        return
    periodo = (inicio, fim)

    tipos = sorted(x for x in df["tipo"].unique() if x)
    categorias = sorted(x for x in df["categoria"].unique() if x)
    subcategorias = sorted(x for x in df["subcategoria"].unique() if x)
    lotes = sorted(x for x in df["lote_id"].unique() if x)
    opcoes_vinculos = _opcoes_vinculos(cad)

    f3, f4 = st.columns(2)
    with f3:
        tipo_sel = st.selectbox("Tipo", ["Todos"] + tipos)
        categoria_sel = st.selectbox("Categoria", ["Todas"] + categorias)
    with f4:
        subcategoria_sel = st.selectbox("Subcategoria", ["Todas"] + subcategorias)
        vinculo_sel = st.selectbox("Cadastro vinculado", list(opcoes_vinculos))

    with st.expander("Filtros avancados", expanded=False):
        lote_sel = st.selectbox("Lote", ["Todos"] + lotes)

    df_f = _aplicar_filtros(
        df,
        periodo,
        tipo_sel,
        categoria_sel,
        subcategoria_sel,
        opcoes_vinculos[vinculo_sel],
        lote_sel,
    )
    if df_f.empty:
        st.info("Nenhum lancamento para os filtros selecionados.")
        return

    entradas = df_f[df_f["tipo_norm"] == "ENTRADA"]
    saidas = df_f[df_f["tipo_norm"] == "SAIDA"]
    ent = entradas["valor"].sum()
    sai = saidas["valor"].sum()
    saldo = ent - sai

    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Entradas", formatar_moeda(ent))
    k2.metric("Saidas", formatar_moeda(sai))
    k3.metric("Saldo", formatar_moeda(saldo))
    k4.metric("Lancamentos", len(df_f))

    tab_resumo, tab_receitas, tab_despesas, tab_vinculos, tab_auditoria = st.tabs([
        "Resumo", "Receitas", "Despesas", "Vinculos", "Auditoria",
    ])

    resumo_categoria = _resumo_por(df_f, "categoria", "Categoria")
    resumo_subcategoria = _resumo_por(saidas, "subcategoria", "Subcategoria")

    with tab_resumo:
        st.markdown("### Evolucao mensal")
        mensal = (
            df_f.dropna(subset=["mes_ref"])
            .groupby(["mes_ref", "tipo_norm"])["valor"]
            .sum()
            .unstack(fill_value=0.0)
            .rename(columns={"ENTRADA": "Entradas", "SAIDA": "Saidas"})
        )
        for coluna in ("Entradas", "Saidas"):
            if coluna not in mensal.columns:
                mensal[coluna] = 0.0
        mensal["Saldo"] = mensal["Entradas"] - mensal["Saidas"]
        mensal.index = mensal.index.astype(str)
        st.plotly_chart(
            _grafico_barras_mensal(mensal),
            use_container_width=True,
            config=CONFIG_PLOTLY,
        )
        st.dataframe(mensal, use_container_width=True)

        st.markdown("### Totais por categoria")
        st.dataframe(_formatar_resumo(resumo_categoria), use_container_width=True, hide_index=True)

    with tab_receitas:
        st.markdown("### Receitas por categoria")
        st.dataframe(
            _formatar_resumo(_resumo_por(entradas, "categoria", "Categoria")),
            use_container_width=True,
            hide_index=True,
        )

        st.markdown("### Dizimos por membro")
        dizimos = entradas[entradas["categoria_norm"] == "DIZIMO"]
        if dizimos.empty:
            st.info("Sem dizimos no periodo.")
        else:
            por_membro = (
                dizimos.assign(nome_cadastro=_texto(dizimos["nome_cadastro"]).replace("", "Nao vinculado"))
                .groupby(["id_cadastro", "nome_cadastro"], dropna=False)
                .agg(Quantidade=("id_lancamento", "count"), Valor=("valor", "sum"))
                .reset_index()
                .sort_values("Valor", ascending=False)
                .rename(columns={
                    "id_cadastro": "ID cadastro",
                    "nome_cadastro": "Membro",
                    "Valor": "Valor total",
                })
            )
            st.dataframe(_formatar_resumo(por_membro), use_container_width=True, hide_index=True)

    with tab_despesas:
        st.markdown("### Despesas por subcategoria")
        st.dataframe(_formatar_resumo(resumo_subcategoria), use_container_width=True, hide_index=True)

        st.markdown("### Despesas por fornecedor")
        fornecedores = saidas[saidas["tipo_cadastro"].str.upper() == "FORNECEDOR"]
        if fornecedores.empty:
            st.info("Sem despesas vinculadas a fornecedores.")
        else:
            por_fornecedor = (
                fornecedores.assign(nome_cadastro=_texto(fornecedores["nome_cadastro"]).replace("", "Nao vinculado"))
                .groupby(["id_cadastro", "nome_cadastro"], dropna=False)
                .agg(Quantidade=("id_lancamento", "count"), Valor=("valor", "sum"))
                .reset_index()
                .sort_values("Valor", ascending=False)
                .rename(columns={
                    "id_cadastro": "ID cadastro",
                    "nome_cadastro": "Fornecedor",
                    "Valor": "Valor total",
                })
            )
            st.dataframe(_formatar_resumo(por_fornecedor), use_container_width=True, hide_index=True)

    with tab_vinculos:
        sem_vinculo = df_f[df_f["id_cadastro"].isna()]
        sem_subcategoria = saidas[_texto(saidas["subcategoria"]).eq("")]
        lotes_qtd = int(_texto(df_f["lote_id"]).replace("", pd.NA).nunique(dropna=True))
        v1, v2, v3 = st.columns(3)
        v1.metric("Sem vinculo", len(sem_vinculo))
        v2.metric("Despesas sem subcategoria", len(sem_subcategoria))
        v3.metric("Lotes identificados", lotes_qtd)

        if not sem_vinculo.empty:
            st.markdown("### Lancamentos sem cadastro vinculado")
            st.dataframe(_detalhes_exibicao(sem_vinculo), use_container_width=True, hide_index=True)

    with tab_auditoria:
        st.caption(
            "A tabela detalhada preserva IDs e lotes para conferencia. "
            "Evite compartilhar exportacoes sem necessidade, pois podem conter dados pessoais."
        )
        st.dataframe(_detalhes_exibicao(df_f), use_container_width=True, hide_index=True)

    st.divider()
    st.markdown("### Exportar")
    nome_periodo = f"{periodo[0]:%Y%m%d}_{periodo[1]:%Y%m%d}"
    e1, e2, e3 = st.columns(3)
    with e1:
        st.download_button(
            "CSV detalhado",
            gerar_csv(_detalhes_exportacao(df_f)),
            f"lancamentos_{nome_periodo}.csv",
            "text/csv",
        )
    with e2:
        st.download_button(
            "CSV por categoria",
            gerar_csv(resumo_categoria),
            f"resumo_categorias_{nome_periodo}.csv",
            "text/csv",
        )
    with e3:
        st.download_button(
            "CSV despesas",
            gerar_csv(resumo_subcategoria),
            f"resumo_despesas_{nome_periodo}.csv",
            "text/csv",
        )

    st.markdown("#### Prestacao de contas")
    st.caption(
        "O Excel consolida as analises em abas editaveis. "
        "O PDF e indicado para impressao e compartilhamento formal."
    )
    try:
        excel_bytes = gerar_excel_relatorio(
            df_f, resumo_categoria, resumo_subcategoria, igreja, periodo
        )
        pdf_bytes = gerar_pdf_relatorio(
            df_f,
            resumo_categoria,
            resumo_subcategoria,
            igreja,
            periodo,
            logo=obter_logo_igreja(slug),
        )
    except Exception:
        LOGGER.exception("Nao foi possivel gerar os arquivos de prestacao de contas.")
        st.error("Nao foi possivel gerar os arquivos de prestacao de contas.")
    else:
        p1, p2 = st.columns(2)
        with p1:
            st.download_button(
                "Excel consolidado",
                excel_bytes,
                f"prestacao_contas_{nome_periodo}.xlsx",
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        with p2:
            st.download_button(
                "PDF de prestacao de contas",
                pdf_bytes,
                f"prestacao_contas_{nome_periodo}.pdf",
                "application/pdf",
            )


def _gerar_excel_leitura_biblica(confirmacoes_dia, resumo, dia_numero):
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        confirmacoes_dia.to_excel(writer, sheet_name=f"Dia {dia_numero}"[:31], index=False)
        resumo.to_excel(writer, sheet_name="Resumo por leitor", index=False)
    return buffer.getvalue()


def _grafico_progresso_leitura(progresso_diario):
    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=list(progresso_diario.index),
        y=list(progresso_diario.values),
        marker_color=f"#{AZUL}",
        hovertemplate="Dia %{x}: %{y} confirmacao(oes)<extra></extra>",
    ))
    fig.update_layout(
        margin=dict(l=10, r=10, t=10, b=10),
        height=260,
        xaxis_title="Dia do plano",
        yaxis_title="Confirmacoes",
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
    )
    return fig


def _grafico_progresso_individual(dias_confirmados, dia_atual):
    dias = list(range(1, dia_atual + 1))
    status = ["Confirmado" if d in dias_confirmados else "Nao confirmado" for d in dias]
    cores = [CORES["entrada"] if d in dias_confirmados else "#E2E8F0" for d in dias]
    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=dias,
        y=[1] * len(dias),
        marker_color=cores,
        customdata=status,
        hovertemplate="Dia %{x}: %{customdata}<extra></extra>",
    ))
    fig.update_layout(
        margin=dict(l=10, r=10, t=10, b=10),
        height=120,
        xaxis_title="Dia do plano",
        yaxis=dict(visible=False),
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
        showlegend=False,
        bargap=0.15,
    )
    return fig


def _render_leitura_biblica(slug):
    st.caption(
        "Acompanhamento do plano de leitura biblica: quem confirmou a leitura de cada "
        "dia e o total de dias confirmados por leitor."
    )
    with st.expander("Importar leitores do WhatsApp em lote"):
        render_importar_leitores(slug)

    planos = listar_planos_leitura_biblica()
    opcoes_planos = {p["nome"]: p["id"] for p in planos}
    nomes_planos = list(opcoes_planos.keys())
    nome_plano_escolhido = st.selectbox("Plano de leitura", nomes_planos, key="rel_leitura_plano")
    plano_id = opcoes_planos[nome_plano_escolhido]

    data_ref = st.date_input(
        "Ver confirmacoes do dia",
        value=datetime.date.today(),
        format="DD/MM/YYYY",
        key="rel_leitura_data",
    )
    dia_numero = min(data_ref.timetuple().tm_yday, 365)
    leitura = obter_leitura_do_dia(dia_numero, plano_id=plano_id)

    todas_confirmacoes = listar_confirmacoes_leitura_biblica(slug, plano_id=plano_id)

    st.markdown(f"#### Dia {dia_numero} — {data_ref.strftime('%d/%m/%Y')}")
    if leitura:
        st.caption(f"Passagens: {leitura['passagens']}")

    confirmacoes_dia = todas_confirmacoes[todas_confirmacoes["dia_numero"] == dia_numero]
    if confirmacoes_dia.empty:
        st.info("Ninguem confirmou a leitura deste dia ainda.")
    else:
        st.metric("Confirmacoes neste dia", len(confirmacoes_dia))
        st.dataframe(
            confirmacoes_dia.rename(columns={
                "nome": "Nome", "origem": "Origem", "confirmado_em": "Confirmado em",
            })[["Nome", "Origem", "Confirmado em"]],
            use_container_width=True,
            hide_index=True,
        )

    st.divider()
    st.markdown("#### Resumo por leitor")
    resumo = resumo_leitores_biblia(slug, plano_id=plano_id)
    if resumo.empty:
        st.info("Ainda nao ha confirmacoes de leitura registradas.")
        return

    dia_atual_ano = min(datetime.date.today().timetuple().tm_yday, 365)
    resumo = resumo.copy()
    resumo["adesao_pct"] = (resumo["total_confirmacoes"] / dia_atual_ano * 100).round(1)
    st.dataframe(
        resumo.rename(columns={
            "nome": "Nome",
            "origem": "Origem",
            "total_confirmacoes": "Dias confirmados",
            "ultima_confirmacao": "Ultima confirmacao",
            "adesao_pct": "Adesao (%)",
        })[["Nome", "Origem", "Dias confirmados", "Adesao (%)", "Ultima confirmacao"]],
        use_container_width=True,
        hide_index=True,
    )

    st.divider()
    st.markdown("#### Progresso do plano de leitura")
    progresso_diario = (
        todas_confirmacoes.groupby("dia_numero").size()
        .reindex(range(1, dia_atual_ano + 1), fill_value=0)
    )
    st.plotly_chart(
        _grafico_progresso_leitura(progresso_diario),
        use_container_width=True,
        config=CONFIG_PLOTLY,
    )

    st.markdown("#### Progresso individual")
    opcoes_leitor = {"Todos os leitores": None}
    for _, row in resumo.iterrows():
        opcoes_leitor[f'{row["nome"]} ({row["origem"]})'] = (row["origem"], row["id_pessoa"])
    escolha_leitor = st.selectbox(
        "Selecione o leitor", list(opcoes_leitor.keys()), key="rel_leitura_leitor"
    )
    chave = opcoes_leitor[escolha_leitor]
    if chave:
        origem_sel, id_pessoa_sel = chave
        linha = resumo[
            (resumo["origem"] == origem_sel) & (resumo["id_pessoa"] == id_pessoa_sel)
        ].iloc[0]
        m1, m2 = st.columns(2)
        m1.metric("Dias confirmados", int(linha["total_confirmacoes"]))
        m2.metric("Adesao ao plano", f'{linha["adesao_pct"]}%')

        dias_confirmados = set(
            todas_confirmacoes[
                (todas_confirmacoes["origem"] == origem_sel)
                & (todas_confirmacoes["id_pessoa"] == id_pessoa_sel)
            ]["dia_numero"]
        )
        st.plotly_chart(
            _grafico_progresso_individual(dias_confirmados, dia_atual_ano),
            use_container_width=True,
            config=CONFIG_PLOTLY,
        )
        st.caption("Verde = dia confirmado · Cinza = dia nao confirmado")

    c1, c2, c3 = st.columns(3)
    with c1:
        st.download_button(
            "CSV - confirmacoes do dia",
            gerar_csv(confirmacoes_dia),
            f"leitura_biblica_dia_{dia_numero}.csv",
            "text/csv",
        )
    with c2:
        st.download_button(
            "CSV - resumo por leitor",
            gerar_csv(resumo),
            "leitura_biblica_resumo.csv",
            "text/csv",
        )
    with c3:
        st.download_button(
            "Excel - plano de leitura",
            _gerar_excel_leitura_biblica(confirmacoes_dia, resumo, dia_numero),
            "leitura_biblica_relatorio.xlsx",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
