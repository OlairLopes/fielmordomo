"""Dashboard executivo consolidado por ministerio."""

import datetime
import html
import logging

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from data.repository import carregar_dashboard_ministerio, listar_ministerios
from utils.helpers import formatar_moeda, gerar_csv


LOGGER = logging.getLogger(__name__)
CORES = {
    "entrada": "#10B981",
    "saida": "#EF4444",
    "resultado": "#3B82F6",
    "alerta": "#F59E0B",
}
CONFIG_PLOTLY = {
    "displayModeBar": False,
    "displaylogo": False,
    "responsive": True,
    "scrollZoom": False,
    "doubleClick": False,
}


def _escape(valor):
    return html.escape(str(valor if valor is not None else ""), quote=True)


def _card(titulo, valor, nota=""):
    st.markdown(
        '<div class="min-card">'
        f'<div class="min-label">{_escape(titulo)}</div>'
        f'<div class="min-value">{_escape(valor)}</div>'
        f'<div class="min-note">{_escape(nota)}</div>'
        "</div>",
        unsafe_allow_html=True,
    )


def _injetar_css():
    st.markdown(
        """
        <style>
        .min-hero {background:linear-gradient(135deg,#061B44,#0B3A66);color:#fff;
            padding:22px 26px;border-radius:16px;margin-bottom:18px}
        .min-hero h1 {color:#fff;margin:0 0 5px;font-size:1.65rem}
        .min-hero p {color:#DCE8F8;margin:0;font-size:.92rem}
        .min-card {background:#FFFFFF;border:1px solid #E2E8F0;border-radius:12px;
            padding:14px 16px;height:100%;box-shadow:0 4px 12px rgba(15,23,42,.05)}
        .min-label {color:#64748B;font-size:.74rem;text-transform:uppercase;letter-spacing:.04em}
        .min-value {color:#0F172A;font-size:1.35rem;font-weight:750;margin-top:5px}
        .min-note {color:#64748B;font-size:.73rem;margin-top:5px}
        .min-section {color:#0F172A;font-size:1rem;font-weight:700;margin:18px 0 10px;
            padding-bottom:8px;border-bottom:1px solid #E2E8F0}
        .min-section span {color:#64748B;display:block;font-size:.78rem;font-weight:400;margin-top:3px}
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
        """,
        unsafe_allow_html=True,
    )


def _secao(titulo, subtitulo):
    st.markdown(
        f'<div class="min-section">{_escape(titulo)}'
        f'<span>{_escape(subtitulo)}</span></div>',
        unsafe_allow_html=True,
    )


def _figura_mensal(mensal):
    fig = go.Figure([
        go.Bar(
            name="Entradas",
            x=mensal["mes"],
            y=mensal["entradas"],
            marker_color=CORES["entrada"],
            text=[formatar_moeda(valor) if valor else "" for valor in mensal["entradas"]],
            textposition="outside",
            textfont=dict(size=10, color="#475569"),
        ),
        go.Bar(
            name="Saidas",
            x=mensal["mes"],
            y=mensal["saidas"],
            marker_color=CORES["saida"],
            text=[formatar_moeda(valor) if valor else "" for valor in mensal["saidas"]],
            textposition="outside",
            textfont=dict(size=10, color="#475569"),
        ),
        go.Scatter(
            name="Resultado",
            x=mensal["mes"],
            y=mensal["resultado"],
            mode="lines+markers",
            line=dict(color=CORES["resultado"], width=3),
            marker=dict(size=7),
        ),
    ])
    fig.update_layout(
        template="plotly_white",
        autosize=True,
        barmode="group",
        height=430,
        margin=dict(t=55, b=35, l=20, r=20),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(color="#475569"),
        legend=dict(orientation="h", y=1.14, x=0),
        hovermode="x unified",
        dragmode=False,
        xaxis=dict(fixedrange=True, gridcolor="#E2E8F0"),
        yaxis=dict(fixedrange=True, gridcolor="#E2E8F0", tickformat=",.0f"),
    )
    return fig


def _resumo_por_coluna(df, coluna):
    if df.empty:
        return pd.DataFrame(columns=[coluna, "valor"])
    resumo = df.copy()
    resumo[coluna] = resumo[coluna].fillna("").astype(str).str.strip().replace("", "Nao informado")
    return resumo.groupby(coluna, as_index=False)["valor"].sum().sort_values("valor", ascending=False)


def _tabela_financeira(df):
    tabela = df.copy()
    for coluna in ("entradas", "saidas", "resultado"):
        if coluna in tabela.columns:
            tabela[coluna] = tabela[coluna].map(formatar_moeda)
    return tabela


def _tab_visao(dados):
    mensal = dados["mensal"]
    if mensal.empty:
        st.info("Nao ha movimentacoes validas no periodo selecionado.")
    else:
        _secao(
            "Evolucao financeira consolidada",
            "Barras com entradas e saidas; linha com o resultado mensal das congregacoes.",
        )
        st.plotly_chart(
            _figura_mensal(mensal),
            use_container_width=True,
            config=CONFIG_PLOTLY,
        )

    st.markdown("#### Resultado por congregacao")
    congregacoes = dados["por_igreja"]
    if congregacoes.empty:
        st.info("Nenhuma congregacao vinculada ao ministerio.")
        return
    congregacoes = congregacoes.sort_values("resultado", ascending=False)
    st.dataframe(
        _tabela_financeira(congregacoes[[
            "igreja", "tipo_unidade", "membros_ativos", "entradas", "saidas",
            "resultado", "status_qualidade",
        ]]).rename(columns={
            "igreja": "Congregacao",
            "tipo_unidade": "Tipo",
            "membros_ativos": "Membros ativos",
            "entradas": "Entradas",
            "saidas": "Saidas",
            "resultado": "Resultado",
            "status_qualidade": "Qualidade",
        }),
        use_container_width=True,
        hide_index=True,
    )


def _tab_congregacoes(dados):
    por_igreja = dados["por_igreja"].copy()
    if por_igreja.empty:
        st.info("Nenhuma congregacao vinculada ao ministerio.")
        return
    por_igreja["participacao_entradas_pct"] = (
        por_igreja["entradas"] / max(float(por_igreja["entradas"].sum()), 1.0) * 100
    ).round(1)
    st.dataframe(
        _tabela_financeira(por_igreja[[
            "igreja", "slug", "tipo_unidade", "ativa", "plano", "membros_ativos",
            "entradas", "saidas", "resultado", "participacao_entradas_pct",
            "status_qualidade",
        ]]).rename(columns={
            "igreja": "Congregacao",
            "slug": "Slug",
            "tipo_unidade": "Tipo",
            "ativa": "Ativa",
            "plano": "Plano",
            "membros_ativos": "Membros ativos",
            "entradas": "Entradas",
            "saidas": "Saidas",
            "resultado": "Resultado",
            "participacao_entradas_pct": "Participacao nas entradas (%)",
            "status_qualidade": "Qualidade",
        }),
        use_container_width=True,
        hide_index=True,
    )


def _tab_movimentos(dados, tipo):
    detalhes = dados["detalhes"]
    movimentos = detalhes[detalhes["tipo"] == tipo].copy()
    coluna = "categoria" if tipo == "Entrada" else "subcategoria"
    resumo = _resumo_por_coluna(movimentos, coluna)
    if resumo.empty:
        st.info(f"Nao ha {tipo.lower()}s validas no periodo.")
        return
    resumo["valor"] = resumo["valor"].map(formatar_moeda)
    st.dataframe(
        resumo.rename(columns={coluna: "Classificacao", "valor": "Valor"}),
        use_container_width=True,
        hide_index=True,
    )


def _tab_qualidade(dados):
    qualidade = dados["qualidade"]
    if qualidade.empty:
        st.info("Nenhuma congregacao vinculada ao ministerio.")
        return
    pendencias = qualidade[qualidade["status"] != "ok"]
    if pendencias.empty:
        st.success("Todas as congregacoes foram consolidadas sem pendencias.")
    else:
        st.warning(
            f"{len(pendencias)} congregacao(oes) possui(em) pendencias. "
            "Registros invalidos foram excluidos dos indicadores."
        )
    st.dataframe(
        qualidade.rename(columns={
            "igreja": "Congregacao",
            "slug": "Slug",
            "status": "Status",
            "lancamentos_invalidos": "Lancamentos invalidos",
            "cadastros_invalidos": "Cadastros invalidos",
            "mensagem": "Diagnostico",
        }),
        use_container_width=True,
        hide_index=True,
    )


def _tab_auditoria(dados, ministerio_slug, inicio, fim):
    detalhes = dados["detalhes"].copy()
    if detalhes.empty:
        st.info("Nao ha lancamentos validos para exportar.")
        return
    detalhes["data"] = detalhes["data"].dt.strftime("%d/%m/%Y")
    st.caption(
        "Exportacao consolidada para conferencia. O arquivo preserva a congregacao "
        "de origem de cada lancamento."
    )
    st.download_button(
        "Exportar lancamentos consolidados",
        gerar_csv(detalhes),
        f"auditoria_{ministerio_slug}_{inicio}_{fim}.csv",
        "text/csv",
        key=f"csv_auditoria_{ministerio_slug}_{inicio}_{fim}",
    )
    st.dataframe(detalhes, use_container_width=True, hide_index=True)


def render():
    _injetar_css()
    st.markdown(
        """
        <div class="min-hero">
          <h1>Dashboard Ministerial</h1>
          <p>Visao financeira consolidada das congregacoes vinculadas ao ministerio.</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    ministerios = listar_ministerios()
    if ministerios.empty:
        st.error("Nenhum ministerio ativo foi encontrado.")
        return

    hoje = datetime.date.today()
    inicio_padrao = hoje.replace(day=1)
    opcoes = {
        f"{row['nome']} ({int(row['qtd_igrejas'])} congregacao(oes))": row
        for _, row in ministerios.iterrows()
    }
    f1, f2, f3, f4 = st.columns([2.2, 1, 1, 1])
    with f1:
        ministerio_label = st.selectbox("Ministerio", list(opcoes), key="dashboard_ministerio")
    with f2:
        inicio = st.date_input("Inicio", inicio_padrao, key="dashboard_ministerio_inicio")
    with f3:
        fim = st.date_input("Fim", hoje, key="dashboard_ministerio_fim")
    with f4:
        incluir_inativas = st.toggle(
            "Incluir inativas", value=False, key="dashboard_ministerio_inativas"
        )

    ministerio = opcoes[ministerio_label]
    try:
        dados = carregar_dashboard_ministerio(
            int(ministerio["id"]), inicio, fim, incluir_inativas=incluir_inativas
        )
    except ValueError as ex:
        st.error(str(ex))
        return
    except Exception:
        LOGGER.exception("Falha ao carregar dashboard ministerial.")
        st.error("Nao foi possivel consolidar o dashboard. Consulte o log do sistema.")
        return

    totais = dados["totais"]
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        _card("Congregacoes", totais["igrejas"], f"{totais['membros_ativos']} membros ativos")
    with c2:
        _card("Entradas", formatar_moeda(totais["entradas"]), "No periodo selecionado")
    with c3:
        _card("Saidas", formatar_moeda(totais["saidas"]), "No periodo selecionado")
    with c4:
        _card("Resultado", formatar_moeda(totais["resultado"]), "Entradas - saidas")

    if totais["igrejas_com_pendencias"]:
        st.warning(
            f"{totais['igrejas_com_pendencias']} congregacao(oes) possui(em) "
            "pendencias de qualidade. Consulte a aba Qualidade."
        )
    st.caption(f"Atualizado em {dados['atualizado_em'].replace('T', ' ')}")

    tabs = st.tabs([
        "Visao Executiva", "Congregacoes", "Receitas", "Despesas", "Qualidade", "Auditoria",
    ])
    with tabs[0]:
        _tab_visao(dados)
    with tabs[1]:
        _tab_congregacoes(dados)
    with tabs[2]:
        _tab_movimentos(dados, "Entrada")
    with tabs[3]:
        _tab_movimentos(dados, "Saida")
    with tabs[4]:
        _tab_qualidade(dados)
    with tabs[5]:
        _tab_auditoria(dados, ministerio["slug"], inicio, fim)


def render_dashboard_geral():
    render()


def exibir_dashboard_geral():
    render()


def dashboard_geral():
    render()


def renderizar():
    render()


def renderizar_dashboard_geral():
    render()


def aba_dashboard_geral():
    render()


__all__ = [
    "render", "render_dashboard_geral", "exibir_dashboard_geral", "dashboard_geral",
    "renderizar", "renderizar_dashboard_geral", "aba_dashboard_geral",
]
