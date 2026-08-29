import datetime
import html
import logging
import urllib.parse

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

LOGGER = logging.getLogger(__name__)

from data.repository import (
    DIAS_DIZIMISTA_ATIVO_DEFAULT,
    autenticar_senha_pastoral,
    carregar_cadastros,
    carregar_lancamentos,
    obter_config_igreja,
    senha_pastoral_configurada,
)
from utils.helpers import formatar_moeda, gerar_csv, slug_da_sessao


CORES = {
    "entrada": "#1D9E75",
    "saida": "#D85A30",
    "saldo": "#185FA5",
    "dizimo": "#185FA5",
    "despesa": "#D85A30",
    "funcao": "#534AB7",
    "alerta": "#F59E0B",
    "neutro": "#64748B",
}
PALETA = [
    "#1D9E75", "#185FA5", "#D85A30", "#534AB7", "#F59E0B",
    "#0F6E56", "#378ADD", "#D4537E", "#888780",
]
CONFIG_PLOTLY = {
    "displayModeBar": False,
    "displaylogo": False,
    "responsive": True,
    "scrollZoom": False,
    "doubleClick": False,
}
MESES_PT = [
    "", "Jan", "Fev", "Mar", "Abr", "Mai", "Jun",
    "Jul", "Ago", "Set", "Out", "Nov", "Dez",
]


def _sk(nome, slug):
    return f"dashboard_{nome}_{slug}"


def _escape(valor):
    return html.escape(str(valor if valor is not None else ""), quote=True)


def _texto(serie):
    return serie.fillna("").astype(str).str.strip()


def _mes_label(periodo):
    return f"{MESES_PT[periodo.month]}/{str(periodo.year)[-2:]}"


def _normalizar_dados(df_lanc, df_cad):
    df = df_lanc.copy()
    cad = df_cad.copy()
    lanc_obrigatorias = {"id_lancamento", "data", "valor", "tipo", "categoria"}
    cad_obrigatorias = {"id_cadastro", "tipo_cadastro", "situacao", "nome"}
    faltantes = sorted((lanc_obrigatorias - set(df.columns)) | (cad_obrigatorias - set(cad.columns)))
    if faltantes:
        return df, cad, faltantes, {}

    for coluna in (
        "tipo", "categoria", "subcategoria", "descricao", "forma_pagamento",
        "nome_cadastro", "tipo_cadastro", "lote_id",
    ):
        if coluna not in df.columns:
            df[coluna] = ""
        df[coluna] = _texto(df[coluna])

    for coluna in ("tipo_cadastro", "situacao", "nome", "telefone", "funcao"):
        if coluna not in cad.columns:
            cad[coluna] = ""
        cad[coluna] = _texto(cad[coluna])

    if "id_cadastro" not in df.columns:
        df["id_cadastro"] = pd.NA

    datas_txt = _texto(df["data"])
    valores_txt = _texto(df["valor"])
    df["data"] = pd.to_datetime(df["data"], errors="coerce")
    df["valor"] = pd.to_numeric(df["valor"], errors="coerce")
    df["id_cadastro"] = pd.to_numeric(df["id_cadastro"], errors="coerce")
    cad["id_cadastro"] = pd.to_numeric(cad["id_cadastro"], errors="coerce")
    df["tipo_norm"] = _texto(df["tipo"]).str.upper()
    df["categoria_norm"] = _texto(df["categoria"]).str.upper()
    df["mes_periodo"] = df["data"].dt.to_period("M")

    qualidade = {
        "datas_invalidas": int((datas_txt.ne("") & df["data"].isna()).sum()),
        "valores_invalidos": int((valores_txt.ne("") & df["valor"].isna()).sum()),
        "valores_nao_positivos": int((df["valor"].fillna(0) <= 0).sum()),
        "sem_vinculo": int(df["id_cadastro"].isna().sum()),
        "despesas_sem_subcategoria": int(
            ((df["tipo_norm"] == "SAIDA") & (_texto(df["subcategoria"]) == "")).sum()
        ),
    }
    df_validos = df[df["data"].notna() & df["valor"].notna() & (df["valor"] > 0)].copy()
    return df_validos, cad, faltantes, qualidade


def _membros_ativos(cad):
    return cad[
        (cad["tipo_cadastro"].str.upper() == "MEMBRO")
        & (cad["situacao"].str.upper() == "ATIVO")
        & cad["id_cadastro"].notna()
    ].copy()


def _periodo(df, inicio, fim):
    return df[df["data"].between(pd.Timestamp(inicio), pd.Timestamp(fim), inclusive="both")].copy()


def _totais(df):
    entradas = float(df[df["tipo_norm"] == "ENTRADA"]["valor"].sum())
    saidas = float(df[df["tipo_norm"] == "SAIDA"]["valor"].sum())
    return entradas, saidas, entradas - saidas


def _variacao(atual, anterior):
    if anterior == 0:
        return "Novo" if atual else "Sem movimento"
    return f"{((atual - anterior) / abs(anterior)) * 100:+.1f}%"


def _participacao_dizimistas(df_periodo, membros):
    ids_ativos = set(membros["id_cadastro"].dropna().astype(int))
    dizimos = df_periodo[
        (df_periodo["tipo_norm"] == "ENTRADA")
        & (df_periodo["categoria_norm"] == "DIZIMO")
    ]
    ids_dizimistas = set(dizimos["id_cadastro"].dropna().astype(int))
    qtd = len(ids_ativos & ids_dizimistas)
    total = len(ids_ativos)
    return qtd, total, (qtd / total * 100) if total else 0.0


def _comparativo_ytd(df, ano, ate_mes):
    atual = df[(df["data"].dt.year == ano) & (df["data"].dt.month <= ate_mes)]
    anterior = df[(df["data"].dt.year == ano - 1) & (df["data"].dt.month <= ate_mes)]
    return _totais(atual), _totais(anterior)


def _serie_mensal(df, fim_mes, quantidade=12, inicio_minimo=None):
    colunas_vazias = ["mes", "rotulo", "entradas", "saidas", "saldo"]
    meses_com_dados = df.loc[
        df["mes_periodo"].notna() & (df["mes_periodo"] <= fim_mes),
        "mes_periodo",
    ]
    if meses_com_dados.empty:
        return pd.DataFrame(columns=colunas_vazias)

    inicio_mes = max(meses_com_dados.min(), fim_mes - (quantidade - 1))
    if inicio_minimo is not None:
        inicio_mes = max(inicio_mes, inicio_minimo)
    if inicio_mes > fim_mes:
        return pd.DataFrame(columns=colunas_vazias)
    meses = [inicio_mes + i for i in range((fim_mes - inicio_mes).n + 1)]
    linhas = []
    for mes in meses:
        sub = df[df["mes_periodo"] == mes]
        entradas, saidas, saldo = _totais(sub)
        linhas.append({
            "mes": mes,
            "rotulo": _mes_label(mes),
            "entradas": entradas,
            "saidas": saidas,
            "saldo": saldo,
        })
    return pd.DataFrame(linhas)


def _faixas_acompanhamento(membros, dizimos, hoje, dias_ativo):
    ultimos = {}
    if not dizimos.empty:
        ultimos = dizimos.groupby("id_cadastro")["data"].max().to_dict()

    limites = sorted(
        {limite for limite in (dias_ativo, 60, 90) if limite >= dias_ativo},
        reverse=True,
    )
    faixas = {"Nunca contribuiu": []}
    faixas.update({f"Mais de {limite} dias": [] for limite in reversed(limites)})
    for _, membro in membros.iterrows():
        id_cadastro = int(membro["id_cadastro"])
        ultima = ultimos.get(id_cadastro)
        if ultima is None or pd.isna(ultima):
            faixa = "Nunca contribuiu"
            dias = None
            ultima_txt = ""
        else:
            ultima_data = pd.Timestamp(ultima).date()
            dias = (hoje - ultima_data).days
            ultima_txt = ultima_data.strftime("%d/%m/%Y")
            faixa = next(
                (f"Mais de {limite} dias" for limite in limites if dias > limite),
                None,
            )
            if faixa is None:
                continue
        faixas[faixa].append({
            "ID": id_cadastro,
            "Nome": membro["nome"],
            "Telefone": membro.get("telefone", ""),
            "Ultima contribuicao": ultima_txt or "Sem registro",
            "Dias sem contribuicao": dias if dias is not None else "Sem registro",
        })
    return faixas


def _layout_grafico(altura=380, margem=None, **extras):
    layout = {
        "template": "plotly_white",
        "autosize": True,
        "height": altura,
        "margin": margem or dict(t=25, b=35, l=20, r=20),
        "paper_bgcolor": "rgba(0,0,0,0)",
        "plot_bgcolor": "rgba(0,0,0,0)",
        "font": dict(color="#475569"),
        "hovermode": False,
        "dragmode": False,
    }
    layout.update(extras)
    return layout


# ═══════════════════════════════════════════════════════════════════════
# NOVOS HELPERS DE ANALISE (Onda 1, 2 e 3)
# ═══════════════════════════════════════════════════════════════════════

def _totais_dizimo(df_periodo):
    """Retorna total, quantidade de dizimistas unicos e quantidade de lancamentos."""
    dizimos = df_periodo[
        (df_periodo["tipo_norm"] == "ENTRADA")
        & (df_periodo["categoria_norm"] == "DIZIMO")
    ]
    total = float(dizimos["valor"].sum())
    dizimistas = int(dizimos["id_cadastro"].dropna().nunique())
    lancamentos = int(len(dizimos))
    return total, dizimistas, lancamentos


def _ticket_medio_arrecadacao(df_periodo, membros):
    """
    Calcula ticket medio, potencial e gap de arrecadacao de dizimo.
    """
    total_dizimo, dizimistas, _ = _totais_dizimo(df_periodo)
    n_membros = len(membros)
    ticket_medio = total_dizimo / dizimistas if dizimistas > 0 else 0.0
    potencial = ticket_medio * n_membros if n_membros > 0 else 0.0
    gap = max(potencial - total_dizimo, 0.0)
    percentual_arrecadado = (total_dizimo / potencial * 100) if potencial > 0 else 0.0
    return {
        "total_dizimo": total_dizimo,
        "dizimistas": dizimistas,
        "ticket_medio": ticket_medio,
        "potencial": potencial,
        "gap": gap,
        "percentual_arrecadado": percentual_arrecadado,
        "membros_ativos": n_membros,
    }


def _mesmo_mes_ano_anterior(df, mes_ref):
    """Retorna DataFrame filtrado para o mesmo mes do ano anterior."""
    mes_ano_anterior = pd.Period(f"{mes_ref.year - 1}-{mes_ref.month:02d}", freq="M")
    return df[df["mes_periodo"] == mes_ano_anterior].copy()


def _identificar_churn(df, mes_ref, membros, dias_referencia=90):
    """
    Identifica dizimistas em churn: contribuiram nos ultimos N dias
    mas nao contribuiram no mes de referencia.
    """
    dizimos_ref = df[
        (df["tipo_norm"] == "ENTRADA")
        & (df["categoria_norm"] == "DIZIMO")
        & (df["mes_periodo"] == mes_ref)
    ]
    ids_contribuiram_no_mes = set(dizimos_ref["id_cadastro"].dropna().astype(int))

    fim_mes_ref = mes_ref.start_time.date()
    inicio_periodo = fim_mes_ref - datetime.timedelta(days=dias_referencia)
    fim_periodo = fim_mes_ref - datetime.timedelta(days=1)

    dizimos_historico = df[
        (df["tipo_norm"] == "ENTRADA")
        & (df["categoria_norm"] == "DIZIMO")
        & (df["data"] >= pd.Timestamp(inicio_periodo))
        & (df["data"] <= pd.Timestamp(fim_periodo))
    ]

    if dizimos_historico.empty:
        return {"quantidade": 0, "lista": [], "impacto_estimado": 0.0,
                "dias_referencia": dias_referencia}

    stats = dizimos_historico.groupby("id_cadastro")["valor"].agg(["mean", "count"])
    stats = stats[stats["count"] >= 2]

    ids_regulares = set(stats.index.astype(int))
    ids_em_churn = ids_regulares - ids_contribuiram_no_mes

    if not ids_em_churn:
        return {"quantidade": 0, "lista": [], "impacto_estimado": 0.0,
                "dias_referencia": dias_referencia}

    membros_dict = membros.set_index("id_cadastro").to_dict("index")
    lista = []
    impacto_total = 0.0
    for id_membro in ids_em_churn:
        media = float(stats.loc[id_membro, "mean"])
        impacto_total += media
        info = membros_dict.get(id_membro, {})
        lista.append({
            "ID": id_membro,
            "Nome": info.get("nome", "(sem cadastro ativo)"),
            "Telefone": info.get("telefone", ""),
            "Media mensal": media,
            "Media mensal formatada": formatar_moeda(media),
            "Contribuicoes no periodo": int(stats.loc[id_membro, "count"]),
        })
    lista.sort(key=lambda x: -x["Media mensal"])

    return {
        "quantidade": len(ids_em_churn),
        "lista": lista,
        "impacto_estimado": impacto_total,
        "dias_referencia": dias_referencia,
    }


def _curva_abc_dizimistas(df_periodo, membros):
    """
    Classifica dizimistas em curva ABC (Pareto).
    """
    dizimos = df_periodo[
        (df_periodo["tipo_norm"] == "ENTRADA")
        & (df_periodo["categoria_norm"] == "DIZIMO")
        & df_periodo["id_cadastro"].notna()
    ]
    if dizimos.empty:
        return None

    por_membro = (
        dizimos.groupby("id_cadastro", as_index=False)["valor"].sum()
        .sort_values("valor", ascending=False)
    )
    total = float(por_membro["valor"].sum())
    if total <= 0:
        return None

    por_membro["percentual"] = por_membro["valor"] / total * 100
    por_membro["acumulado"] = por_membro["percentual"].cumsum()

    def _classificar(acumulado):
        if acumulado <= 80:
            return "A"
        elif acumulado <= 95:
            return "B"
        return "C"

    por_membro["classe"] = por_membro["acumulado"].apply(_classificar)
    membros_dict = membros.set_index("id_cadastro")["nome"].to_dict()
    por_membro["nome"] = por_membro["id_cadastro"].map(
        lambda x: membros_dict.get(int(x), "(sem cadastro ativo)")
    )

    resumo_classes = por_membro.groupby("classe", as_index=False).agg(
        quantidade=("id_cadastro", "count"),
        valor=("valor", "sum"),
    )
    resumo_classes["percentual_valor"] = resumo_classes["valor"] / total * 100
    resumo_classes["percentual_membros"] = (
        resumo_classes["quantidade"] / len(por_membro) * 100
    )

    classe_a = por_membro[por_membro["classe"] == "A"]
    pct_a = len(classe_a) / len(por_membro) * 100 if len(por_membro) else 0

    return {
        "por_membro": por_membro,
        "resumo_classes": resumo_classes,
        "total": total,
        "n_dizimistas": len(por_membro),
        "pct_dizimistas_top_a": pct_a,
        "pct_valor_top_a": float(classe_a["valor"].sum() / total * 100) if len(classe_a) else 0,
    }


def _score_saude_financeira(df, mes_ref, saude_info, qualidade, membros):
    """
    Score 0-100 combinando 5 dimensoes ponderadas.
    """
    # 1. Cobertura reserva (30 pontos)
    cobertura = saude_info.get("cobertura")
    if cobertura is None:
        score_cobertura = 30
    else:
        score_cobertura = min(30, max(0, (cobertura / 3) * 30))

    # 2. Saldo YTD positivo (25 pontos)
    ate_ref = df[df["mes_periodo"] <= mes_ref]
    saldo_ytd = _totais(ate_ref)[2]
    total_ytd = _totais(ate_ref)[0]
    if total_ytd <= 0:
        score_saldo = 0
    else:
        margem = saldo_ytd / total_ytd
        score_saldo = max(0, min(25, 12.5 + margem * 62.5))

    # 3. Variacao das entradas (20 pontos)
    serie = _serie_mensal(df, mes_ref, quantidade=3)
    if len(serie) >= 3:
        entradas = serie["entradas"].tolist()
        media_anterior = (entradas[0] + entradas[1]) / 2
        atual = entradas[-1]
        if media_anterior > 0:
            variacao = (atual - media_anterior) / media_anterior
            score_variacao = max(0, min(20, 10 + variacao * 50))
        else:
            score_variacao = 10
    else:
        score_variacao = 10

    # 4. % dizimistas (15 pontos)
    _, _, pct_diz = _participacao_dizimistas(df[df["mes_periodo"] == mes_ref], membros)
    score_dizimistas = min(15, (pct_diz / 80) * 15)

    # 5. Qualidade dados (10 pontos)
    total_pendencias = sum(qualidade.values())
    if total_pendencias == 0:
        score_qualidade = 10
    else:
        score_qualidade = max(0, 10 - (total_pendencias / 10))

    score_total = (
        score_cobertura + score_saldo + score_variacao
        + score_dizimistas + score_qualidade
    )

    if score_total >= 75:
        classificacao = "excelente"
        emoji = "🟢"
    elif score_total >= 50:
        classificacao = "atencao"
        emoji = "🟡"
    else:
        classificacao = "critico"
        emoji = "🔴"

    return {
        "score_total": round(score_total, 1),
        "classificacao": classificacao,
        "emoji": emoji,
        "componentes": {
            "Cobertura de reserva": round(score_cobertura, 1),
            "Saldo YTD": round(score_saldo, 1),
            "Variacao de entradas": round(score_variacao, 1),
            "Participacao dizimistas": round(score_dizimistas, 1),
            "Qualidade dos dados": round(score_qualidade, 1),
        },
        "maximos": {
            "Cobertura de reserva": 30,
            "Saldo YTD": 25,
            "Variacao de entradas": 20,
            "Participacao dizimistas": 15,
            "Qualidade dos dados": 10,
        },
    }


def _rotulo_periodo(inicio, fim):
    """Formata o periodo para exibicao textual (ex: '01/07 a 15/07/2026')."""
    if inicio == fim:
        return inicio.strftime("%d/%m/%Y")
    if inicio.year == fim.year and inicio.month == fim.month:
        return f"{inicio.strftime('%d')} a {fim.strftime('%d/%m/%Y')}"
    return f"{inicio.strftime('%d/%m/%Y')} a {fim.strftime('%d/%m/%Y')}"


def _gerar_insight_textual(
    inicio, fim, ent, ent_ant, ref, membros, saude_info, ticket_info, score,
):
    """
    Gera paragrafo curto de resumo executivo do periodo selecionado.
    """
    variacao_ent = ((ent - ent_ant) / ent_ant * 100) if ent_ant > 0 else 0

    dizimo_periodo, _, _ = _totais_dizimo(ref)
    pct_dizimo = (dizimo_periodo / ent * 100) if ent > 0 else 0

    qtd_diz, qtd_membros, pct_diz = _participacao_dizimistas(ref, membros)

    frases = []
    periodo_str = _rotulo_periodo(inicio, fim)
    if variacao_ent >= 0:
        frases.append(
            f"No periodo **{periodo_str}**, as entradas totalizaram **{formatar_moeda(ent)}**, "
            f"variacao de **{variacao_ent:+.1f}%** vs periodo anterior equivalente."
        )
    else:
        frases.append(
            f"⚠️ No periodo **{periodo_str}**, as entradas foram de **{formatar_moeda(ent)}** — "
            f"queda de **{abs(variacao_ent):.1f}%** vs periodo anterior equivalente."
        )

    if pct_dizimo > 0:
        frases.append(
            f"O dizimo representa **{pct_dizimo:.1f}%** das entradas do periodo."
        )

    if qtd_membros > 0:
        frases.append(
            f"**{qtd_diz} de {qtd_membros}** membros ativos contribuiram ({pct_diz:.1f}%)."
        )

    cobertura = saude_info.get("cobertura")
    if cobertura is not None:
        frases.append(
            f"A reserva cobre **{cobertura:.1f} meses** de despesa media."
        )

    if ticket_info["gap"] > 0 and ticket_info["dizimistas"] > 0:
        frases.append(
            f"O gap para arrecadacao potencial e de **{formatar_moeda(ticket_info['gap'])}**."
        )

    frases.append(
        f"Score de saude financeira: **{score['score_total']:.0f}/100** "
        f"({score['emoji']} {score['classificacao']})."
    )

    return " ".join(frases)


def _sazonalidade_mensal(df):
    """
    Media de entradas/saidas por mes calendario (jan-dez).
    """
    if df.empty:
        return pd.DataFrame(columns=["mes_num", "mes_nome", "entradas_media", "saidas_media"])

    df_c = df.copy()
    df_c["ano"] = df_c["data"].dt.year
    df_c["mes_num"] = df_c["data"].dt.month

    mensal = df_c.groupby(["ano", "mes_num", "tipo_norm"], as_index=False)["valor"].sum()

    linhas = []
    for mes_num in range(1, 13):
        entradas_medias = mensal[
            (mensal["mes_num"] == mes_num) & (mensal["tipo_norm"] == "ENTRADA")
        ]["valor"]
        saidas_medias = mensal[
            (mensal["mes_num"] == mes_num) & (mensal["tipo_norm"] == "SAIDA")
        ]["valor"]
        linhas.append({
            "mes_num": mes_num,
            "mes_nome": MESES_PT[mes_num],
            "entradas_media": float(entradas_medias.mean()) if not entradas_medias.empty else 0.0,
            "saidas_media": float(saidas_medias.mean()) if not saidas_medias.empty else 0.0,
            "anos_com_dados": int(len(entradas_medias)),
        })
    return pd.DataFrame(linhas)


def _previsao_regressao_linear(df, mes_ref, horizonte=3):
    """
    Previsao simples via regressao linear dos ultimos 12 meses.
    """
    serie = _serie_mensal(df, mes_ref, quantidade=12)
    if len(serie) < 3:
        return None

    x = np.arange(len(serie))

    y_ent = serie["entradas"].values
    coef_ent = np.polyfit(x, y_ent, 1)
    intercepto_ent = coef_ent[1]
    inclinacao_ent = coef_ent[0]

    y_sai = serie["saidas"].values
    coef_sai = np.polyfit(x, y_sai, 1)
    intercepto_sai = coef_sai[1]
    inclinacao_sai = coef_sai[0]

    residuo_ent = y_ent - (inclinacao_ent * x + intercepto_ent)
    erro_ent = float(np.std(residuo_ent)) if len(residuo_ent) > 1 else 0

    residuo_sai = y_sai - (inclinacao_sai * x + intercepto_sai)
    erro_sai = float(np.std(residuo_sai)) if len(residuo_sai) > 1 else 0

    previsoes = []
    for i in range(1, horizonte + 1):
        pos_futura = len(serie) + i - 1
        mes_futuro = mes_ref + i
        ent_prev = max(0, inclinacao_ent * pos_futura + intercepto_ent)
        sai_prev = max(0, inclinacao_sai * pos_futura + intercepto_sai)
        previsoes.append({
            "mes": mes_futuro,
            "rotulo": _mes_label(mes_futuro),
            "entradas_previstas": ent_prev,
            "entradas_min": max(0, ent_prev - erro_ent),
            "entradas_max": ent_prev + erro_ent,
            "saidas_previstas": sai_prev,
            "saidas_min": max(0, sai_prev - erro_sai),
            "saidas_max": sai_prev + erro_sai,
            "saldo_previsto": ent_prev - sai_prev,
        })
    return pd.DataFrame(previsoes)


def _cruzar_com_frequencia_geo(slug, membros, dizimos_periodo, inicio, fim):
    """
    Cruza dados de frequencia (Monitoramento Geo) com contribuicao.
    Retorna None se tabela nao existir.
    """
    try:
        from data.repository import _tenant_db
        import sqlite3

        db_path = _tenant_db(slug)
        if not db_path.exists():
            return None

        with sqlite3.connect(db_path) as conn:
            cursor = conn.execute("""
                SELECT name FROM sqlite_master
                WHERE type='table' AND name='geo_presencas'
            """)
            if not cursor.fetchone():
                return None

            df_presencas = pd.read_sql_query(
                """SELECT id_cadastro, data, presente
                   FROM geo_presencas
                   WHERE data >= ? AND data <= ?""",
                conn,
                params=(inicio.isoformat(), fim.isoformat()),
            )

        if df_presencas.empty:
            return None

        # Conta presencas por membro
        presencas_por_membro = df_presencas[df_presencas["presente"] == 1].groupby(
            "id_cadastro"
        ).size().to_dict()
        contribuicoes_por_membro = dizimos_periodo.groupby(
            "id_cadastro"
        ).size().to_dict()

        linhas = []
        for _, membro in membros.iterrows():
            id_m = int(membro["id_cadastro"])
            presencas = int(presencas_por_membro.get(id_m, 0))
            contribuicoes = int(contribuicoes_por_membro.get(id_m, 0))
            if presencas == 0 and contribuicoes == 0:
                classe = "ausente_total"
            elif presencas > 0 and contribuicoes == 0:
                classe = "presente_sem_contribuir"
            elif presencas == 0 and contribuicoes > 0:
                classe = "contribui_sem_presenca"
            else:
                classe = "engajado"
            linhas.append({
                "id_cadastro": id_m,
                "nome": membro["nome"],
                "presencas": presencas,
                "contribuicoes": contribuicoes,
                "classe": classe,
            })

        return pd.DataFrame(linhas)
    except Exception as exc:
        LOGGER.warning("Nao foi possivel cruzar dados de geo_frequencia: %s", exc)
        return None


def _mensagem_agradecimento_dizimista(nome_igreja, nome_membro, mes_str):
    return (
        f"Paz do Senhor, {nome_membro}! "

        f"Somos gratos pela sua fidelidade nos dízimos e ofertas no mês de {mes_str}. "
        f"Que Deus continue abencoando abundantemente sua vida e familia. "
        
        f"Equipe {nome_igreja}."
    )


def _mensagem_acompanhamento_afastado(nome_igreja, nome_membro, mes_str):
    return (
        f"Paz do Senhor, {nome_membro}! "

        f"Queremos agradecer por sua presença e participação nos trabalhos da igreja. "
        f"Sua vida é importante para nós e para o Reino de Deus! "

        f"Percebemos que, neste mês de {mes_str}, não houve registro de suas contribuições no tesouro da igreja, "
        f"e gostaríamos de saber, com carinho e respeito, se você está passando por alguma dificuldade. "

        f"Estamos disponiveis se precisar conversar ou orar. "
        f"Equipe pastoral {nome_igreja}."
    )


def _link_whatsapp_padrao(tel, mensagem):
    """Gera link wa.me com telefone normalizado."""
    tel_limpo = "".join(c for c in str(tel or "") if c.isdigit())
    if not tel_limpo:
        return ""
    while tel_limpo.startswith("0"):
        tel_limpo = tel_limpo[1:]
    if not tel_limpo.startswith("55"):
        tel_limpo = "55" + tel_limpo
    if len(tel_limpo) not in (12, 13):
        return ""
    return f"https://wa.me/{tel_limpo}?text={urllib.parse.quote(mensagem)}"


def _secao_dashboard(titulo, subtitulo):
    st.markdown(
        f'<div class="dash-section"><strong>{_escape(titulo)}</strong>'
        f'<span>{_escape(subtitulo)}</span></div>',
        unsafe_allow_html=True,
    )


def _render_legenda(itens):
    """
    Legenda de cores customizada (HTML/CSS com flex-wrap), renderizada abaixo
    do grafico. Diferente do legend nativo do Plotly - que fica preso a area
    de altura fixa do grafico e pode cortar/sobrepor texto quando ha muitos
    itens ou nomes longos - esta legenda ocupa o fluxo normal da pagina.
    """
    legenda = ['<div class="dash-legenda">']
    for titulo, cor in itens:
        legenda.append(
            f'<span><i style="background:{_escape(cor)}"></i>{_escape(titulo)}</span>'
        )
    legenda.append("</div>")
    st.markdown("".join(legenda), unsafe_allow_html=True)


def _legenda_cores():
    _render_legenda([
        ("Entradas", CORES["entrada"]),
        ("Saidas e despesas", CORES["saida"]),
        ("Saldo e dizimos", CORES["saldo"]),
        ("Funcoes", CORES["funcao"]),
        ("Alertas", CORES["alerta"]),
    ])


def _grafico_rosca(
    resumo,
    rotulos,
    valores,
    cores=None,
    total_label="Total",
    valor_central=None,
    label_central=None,
    cor_central="#10213A",
):
    """Renderiza o grafico de rosca e, logo abaixo, a legenda de cores customizada."""
    total = float(resumo[valores].sum())
    valor_centro = total if valor_central is None else float(valor_central)
    label_centro = total_label if label_central is None else label_central
    cores_fatias = cores or PALETA[:len(resumo)]
    percentuais = [
        (float(valor) / total * 100) if total else 0.0
        for valor in resumo[valores]
    ]
    fig = go.Figure(go.Pie(
        name=total_label,
        labels=resumo[rotulos],
        values=resumo[valores],
        hole=.68,
        textinfo="percent",
        textposition="outside",
        textfont=dict(size=12, color="#475569"),
        hovertemplate="<b>%{label}</b><br>%{customdata}<extra></extra>",
        customdata=[formatar_moeda(valor) for valor in resumo[valores]],
        marker=dict(
            colors=cores_fatias,
            line=dict(color="#FFFFFF", width=2),
        ),
    ))
    fig.add_annotation(
        text=f"<b>{formatar_moeda(valor_centro)}</b><br><span style='font-size:11px'>{label_centro}</span>",
        x=.5,
        y=.5,
        showarrow=False,
        font=dict(size=16, color=cor_central),
    )
    fig.update_layout(**_layout_grafico(
        altura=420,
        margem=dict(t=30, b=30, l=105, r=105),
        showlegend=False,
    ))
    st.plotly_chart(fig, use_container_width=True, config=CONFIG_PLOTLY)
    _render_legenda([
        (f"{rotulo} ({percentual:.1f}%)", cor)
        for rotulo, percentual, cor in zip(resumo[rotulos], percentuais, cores_fatias)
    ])


def _grafico_ranking(resumo, rotulos, valores, cor):
    dados = resumo.sort_values(valores, ascending=True)
    fig = go.Figure(go.Bar(
        name="Valor",
        x=dados[valores],
        y=dados[rotulos],
        orientation="h",
        marker_color=cor,
        text=[formatar_moeda(valor) for valor in dados[valores]],
        textposition="outside",
        textfont=dict(size=10, color="#475569"),
    ))
    fig.update_layout(**_layout_grafico(
        altura=max(320, len(dados) * 34 + 100),
        showlegend=False,
        xaxis=dict(fixedrange=True, showgrid=False, showticklabels=False),
        yaxis=dict(fixedrange=True, showgrid=False),
    ))
    return fig


def _tabela_monetaria(df, coluna_valor="Valor"):
    tabela = df.copy()
    if coluna_valor in tabela.columns:
        tabela[coluna_valor] = tabela[coluna_valor].apply(formatar_moeda)
    return tabela


def _numero_config(valor, padrao=0.0):
    texto = str(valor or "").strip().replace("R$", "").replace(" ", "")
    if "," in texto:
        texto = texto.replace(".", "").replace(",", ".")
    try:
        numero = float(texto)
    except (TypeError, ValueError):
        return float(padrao)
    return numero if numero >= 0 else float(padrao)


def _indicadores_saude(df, mes_ref, reserva, meta_reserva):
    serie = _serie_mensal(df, mes_ref, quantidade=6)
    recentes = serie.tail(3)
    media_entradas = float(recentes["entradas"].mean()) if not recentes.empty else 0.0
    media_saidas = float(recentes["saidas"].mean()) if not recentes.empty else 0.0
    resultado_medio = media_entradas - media_saidas
    cobertura = (reserva / media_saidas) if media_saidas > 0 else None
    ate_referencia = df[df["mes_periodo"] <= mes_ref]
    saldo_acumulado = _totais(ate_referencia)[2]
    projecoes = pd.DataFrame({
        "Horizonte": ["30 dias", "60 dias", "90 dias"],
        "Meses": [1, 2, 3],
    })
    projecoes["Saldo projetado"] = (
        saldo_acumulado + projecoes["Meses"] * resultado_medio
    )

    alertas = []
    if cobertura is not None and cobertura < meta_reserva:
        alertas.append((
            "critico",
            f"A reserva cobre {cobertura:.1f} mes(es), abaixo da meta de {meta_reserva} mes(es).",
        ))
    if saldo_acumulado < 0:
        alertas.append((
            "critico",
            "O saldo acumulado dos lancamentos registrados esta negativo.",
        ))
    if not serie.empty and float(serie.iloc[-1]["saldo"]) < 0:
        alertas.append((
            "atencao",
            "O mes selecionado fechou com mais saidas do que entradas.",
        ))
    if len(serie) >= 2:
        saida_atual = float(serie.iloc[-1]["saidas"])
        saida_anterior = float(serie.iloc[-2]["saidas"])
        if saida_anterior > 0 and saida_atual > saida_anterior * 1.2:
            variacao = ((saida_atual - saida_anterior) / saida_anterior) * 100
            alertas.append((
                "atencao",
                f"As despesas cresceram {variacao:.1f}% em relacao ao mes anterior.",
            ))
    if len(serie) >= 3:
        entradas = serie["entradas"].tail(3).tolist()
        if entradas[0] > entradas[1] > entradas[2]:
            alertas.append((
                "atencao",
                "As entradas cairam por dois meses consecutivos.",
            ))
    if (projecoes["Saldo projetado"] < 0).any():
        primeiro = projecoes[projecoes["Saldo projetado"] < 0].iloc[0]["Horizonte"]
        alertas.append((
            "critico",
            f"A projecao indica saldo negativo em ate {primeiro}.",
        ))

    return {
        "serie": serie,
        "media_entradas": media_entradas,
        "media_saidas": media_saidas,
        "resultado_medio": resultado_medio,
        "cobertura": cobertura,
        "saldo_acumulado": saldo_acumulado,
        "projecoes": projecoes,
        "alertas": alertas,
    }


def _render_saude_financeira(df, mes_ref, slug):
    reserva = _numero_config(
        obter_config_igreja(slug, "reserva_financeira_disponivel", "0")
    )
    meta_reserva = int(_numero_config(
        obter_config_igreja(slug, "meta_reserva_meses", "3"), 3
    ))
    if meta_reserva < 1:
        meta_reserva = 3
    saude = _indicadores_saude(df, mes_ref, reserva, meta_reserva)

    _secao_dashboard(
        "Saude financeira",
        "Indicadores para apoio a decisao. A projecao utiliza os lancamentos registrados e a media dos ultimos tres meses.",
    )
    s1, s2, s3, s4 = st.columns(4)
    with s1:
        _card("Reserva disponivel", formatar_moeda(reserva), "Configurada em Minha Conta")
    with s2:
        cobertura = saude["cobertura"]
        valor_cobertura = f"{cobertura:.1f} mes(es)" if cobertura is not None else "Sem despesas"
        _card("Cobertura da reserva", valor_cobertura, f"Meta: {meta_reserva} mes(es)")
    with s3:
        _card("Despesa media mensal", formatar_moeda(saude["media_saidas"]), "Media dos ultimos 3 meses")
    with s4:
        _card("Resultado medio mensal", formatar_moeda(saude["resultado_medio"]), "Entradas - saidas")

    _secao_dashboard(
        "Alertas executivos",
        "Pontos que merecem avaliacao antes de assumir novos compromissos financeiros.",
    )
    if saude["alertas"]:
        for nivel, mensagem in saude["alertas"]:
            st.markdown(
                f'<div class="saude-alerta {nivel}">{_escape(mensagem)}</div>',
                unsafe_allow_html=True,
            )
    else:
        st.success("Nenhum alerta financeiro relevante foi identificado.")

    _secao_dashboard(
        "Projecao de caixa",
        "Estimativa baseada no saldo acumulado registrado e no resultado medio mensal recente.",
    )
    projecoes = saude["projecoes"]
    fig_projecao = go.Figure(go.Bar(
        x=projecoes["Horizonte"],
        y=projecoes["Saldo projetado"],
        marker_color=[
            CORES["entrada"] if valor >= 0 else CORES["saida"]
            for valor in projecoes["Saldo projetado"]
        ],
        text=[formatar_moeda(valor) for valor in projecoes["Saldo projetado"]],
        textposition="outside",
        textfont=dict(size=11, color="#475569"),
    ))
    fig_projecao.update_layout(**_layout_grafico(
        altura=340,
        xaxis=dict(fixedrange=True, showgrid=False),
        yaxis=dict(fixedrange=True, gridcolor="#E2E8F0", tickformat=",.0f"),
    ))
    st.plotly_chart(fig_projecao, use_container_width=True, config=CONFIG_PLOTLY)
    st.caption(
        f"Saldo acumulado registrado ate {_mes_label(mes_ref)}: "
        f"{formatar_moeda(saude['saldo_acumulado'])}. "
        "A projecao nao substitui conciliacao bancaria nem planejamento orcamentario."
    )


def _cartao_atencao(titulo, quantidade, percentual, classe):
    st.markdown(
        f'<div class="pastoral-card {classe}"><div>{_escape(titulo)}</div>'
        f'<strong>{quantidade}</strong><span>{percentual:.1f}% dos membros</span></div>',
        unsafe_allow_html=True,
    )


def _resumo_acompanhamento(membros, dizimos, hoje, dias_ativo):
    ultimos = {}
    if not dizimos.empty:
        ultimos = dizimos.groupby("id_cadastro")["data"].max().to_dict()

    total = len(membros)
    limites = sorted({limite for limite in (dias_ativo, 60, 90) if limite >= dias_ativo})
    resumo = []
    for limite in limites:
        quantidade = 0
        for id_cadastro in membros["id_cadastro"].dropna().astype(int):
            ultima = ultimos.get(id_cadastro)
            if ultima is None or pd.isna(ultima):
                quantidade += 1
            elif (hoje - pd.Timestamp(ultima).date()).days > limite:
                quantidade += 1
        resumo.append({
            "limite": limite,
            "quantidade": quantidade,
            "percentual": (quantidade / total * 100) if total else 0.0,
        })
    return resumo


def _frequencia_membros(membros, dizimos):
    contagem = dizimos.groupby("id_cadastro").size().to_dict() if not dizimos.empty else {}
    valores = dizimos.groupby("id_cadastro")["valor"].sum().to_dict() if not dizimos.empty else {}
    linhas = []
    for _, membro in membros.sort_values("nome").iterrows():
        id_cadastro = int(membro["id_cadastro"])
        linhas.append({
            "ID": id_cadastro,
            "Nome": membro["nome"],
            "Contribuicoes": int(contagem.get(id_cadastro, 0)),
            "Valor total": float(valores.get(id_cadastro, 0.0)),
        })
    return pd.DataFrame(linhas)


def _meses_periodo(inicio, fim):
    primeiro = pd.Period(inicio, freq="M")
    ultimo = pd.Period(fim, freq="M")
    return [primeiro + i for i in range((ultimo - primeiro).n + 1)]


def _resumo_individual_mensal(dados, meses):
    resumo = {}
    if not dados.empty:
        resumo = (
            dados.groupby("mes_periodo")["valor"]
            .agg(["count", "sum"])
            .to_dict("index")
        )

    linhas = []
    for mes in meses:
        registro = resumo.get(mes, {})
        linhas.append({
            "mes": mes,
            "rotulo": _mes_label(mes),
            "quantidade": int(registro.get("count", 0)),
            "valor": float(registro.get("sum", 0.0)),
        })
    return linhas


def _avaliacao_fidelidade(resumo_mensal):
    total_meses = len(resumo_mensal)
    meses_com_contribuicao = sum(1 for mes in resumo_mensal if mes["quantidade"] > 0)
    taxa = (meses_com_contribuicao / total_meses * 100) if total_meses else 0.0
    if meses_com_contribuicao == 0:
        return taxa, "Sem contribuicoes no periodo", "critico"
    if taxa < 50:
        return taxa, "Frequencia baixa: avaliar necessidade de acompanhamento pastoral", "atencao"
    if taxa < 80:
        return taxa, "Frequencia moderada: observar a regularidade das contribuicoes", "moderado"
    return taxa, "Boa regularidade de contribuicoes no periodo", "positivo"


def _cartoes_fidelidade(resumo_mensal):
    cartoes = ['<div class="fidelidade-grid">']
    for mes in resumo_mensal:
        if mes["quantidade"]:
            classe = "presente"
            detalhe = f'{mes["quantidade"]}x | {formatar_moeda(mes["valor"])}'
        else:
            classe = "ausente"
            detalhe = "Sem dizimo"
        cartoes.append(
            f'<div class="fidelidade-mes {classe}"><strong>{_escape(mes["rotulo"])}</strong>'
            f'<span>{_escape(detalhe)}</span></div>'
        )
    cartoes.append("</div>")
    st.markdown("".join(cartoes), unsafe_allow_html=True)


def _mensagem_fidelidade(nome, resumo_mensal):
    taxa, titulo, classe = _avaliacao_fidelidade(resumo_mensal)
    meses_presentes = sum(1 for mes in resumo_mensal if mes["quantidade"] > 0)
    total_meses = len(resumo_mensal)
    complemento = (
        "Recomenda-se avaliacao humana e, quando apropriado, contato ou visita pastoral."
        if classe in {"critico", "atencao"}
        else "Use esta informacao como apoio ao acompanhamento pastoral."
    )
    st.markdown(
        f'<div class="fidelidade-aviso {classe}"><strong>{_escape(titulo)}</strong>'
        f'<span>{_escape(nome)} contribuiu em {meses_presentes} de {total_meses} meses '
        f'({taxa:.1f}% de fidelidade mensal). {_escape(complemento)}</span></div>',
        unsafe_allow_html=True,
    )


def _injetar_css():
    st.markdown("""
    <style>
    h1,h2,h3,h4 { color:#10213A !important; }
    .dash-card { background:#FFFFFF;border:1px solid #E2E8F0;border-radius:12px;padding:16px;
        height:100%;display:flex;flex-direction:column;justify-content:space-between;
        min-height:112px;box-sizing:border-box;box-shadow:0 1px 2px rgba(10,27,61,.05); }
    .dash-label { color:#64748B;font-size:.78rem;text-transform:uppercase;letter-spacing:.04em; }
    .dash-value { color:#10213A;font-size:1.45rem;font-weight:700;margin-top:5px; }
    .dash-note { color:#475569;font-size:.76rem;margin-top:5px; }

    /* ═══ Grade uniforme: cards com mesma altura e espacamento consistente ═══ */
    div[data-testid="stHorizontalBlock"] {
        gap:16px !important;
        margin-bottom:16px;
        align-items:stretch !important;
    }
    div[data-testid="stHorizontalBlock"] > div[data-testid="column"] {
        display:flex !important;
        flex:1 1 0 !important;
        min-width:0;
    }
    div[data-testid="column"] > div {
        width:100%;
        display:flex;
        flex-direction:column;
    }
    div[data-testid="column"] [data-testid="stVerticalBlockBorderWrapper"],
    div[data-testid="column"] [data-testid="stVerticalBlock"] {
        height:100%;
    }
    @media (max-width:640px) {
        div[data-testid="stHorizontalBlock"] { gap:10px !important;margin-bottom:10px; }
        .dash-card { min-height:96px;padding:12px; }
    }
    .stPlotlyChart, [data-testid="stPlotlyChart"] {
        background:#FFFFFF;
        border:1px solid #E2E8F0;
        border-radius:14px;
        box-shadow:0 1px 2px rgba(10,27,61,.05);
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
            box-shadow:0 1px 2px rgba(10,27,61,.05);
            padding:4px;
        }
    }
    .dash-section { color:#10213A;font-size:1rem;margin:22px 0 10px;padding-bottom:8px;border-bottom:1px solid #E2E8F0; }
    .dash-section span { color:#64748B;display:block;font-size:.78rem;font-weight:400;margin-top:3px; }
    .dash-legenda { display:flex;flex-wrap:wrap;gap:9px 16px;margin:10px 0 14px; }
    .dash-legenda span { color:#475569;font-size:.78rem;white-space:nowrap; }
    .dash-legenda i { border-radius:50%;display:inline-block;height:10px;margin-right:6px;width:10px; }
    .pastoral-card { background:#FFFFFF;border:1px solid #E2E8F0;border-radius:12px;padding:14px;text-align:center;height:100%; }
    .pastoral-card div { color:#475569;font-size:.78rem; }
    .pastoral-card strong { display:block;font-size:1.9rem;margin-top:5px; }
    .pastoral-card span { color:#64748B;font-size:.75rem; }
    .pastoral-card.amarelo strong { color:#B45309; }
    .pastoral-card.laranja strong { color:#C2410C; }
    .pastoral-card.vermelho strong { color:#DC2626; }
    .fidelidade-grid { display:flex;flex-wrap:wrap;gap:8px;margin:14px 0; }
    .fidelidade-mes { border-radius:8px;min-width:96px;padding:9px 11px;text-align:center; }
    .fidelidade-mes strong { display:block;font-size:.8rem; }
    .fidelidade-mes span { display:block;font-size:.7rem;margin-top:4px; }
    .fidelidade-mes.presente { background:#DCFCE7;color:#166534; }
    .fidelidade-mes.ausente { background:#F1F5F9;color:#64748B; }
    .fidelidade-aviso { background:#FFFFFF;border:1px solid #E2E8F0;border-left:4px solid;border-radius:8px;margin:12px 0 18px;padding:13px 16px; }
    .fidelidade-aviso strong { display:block;font-size:.95rem; }
    .fidelidade-aviso span { color:#475569;display:block;font-size:.82rem;margin-top:5px; }
    .fidelidade-aviso.critico { border-left-color:#DC2626; }
    .fidelidade-aviso.critico strong { color:#DC2626; }
    .fidelidade-aviso.atencao { border-left-color:#F97316; }
    .fidelidade-aviso.atencao strong { color:#C2410C; }
    .fidelidade-aviso.moderado { border-left-color:#F59E0B; }
    .fidelidade-aviso.moderado strong { color:#B45309; }
    .fidelidade-aviso.positivo { border-left-color:#10B981; }
    .fidelidade-aviso.positivo strong { color:#0F766E; }
    .saude-alerta { background:#FFFFFF;border:1px solid #E2E8F0;border-left:4px solid;border-radius:8px;
        color:#475569;font-size:.86rem;margin:8px 0;padding:12px 15px; }
    .saude-alerta.critico { border-left-color:#DC2626; }
    .saude-alerta.atencao { border-left-color:#F59E0B; }

    /* ═══ Insight textual no topo ═══ */
    .insight-topo {
        background:linear-gradient(135deg,#FFFFFF 0%,#FBF3DC 100%);
        border:1px solid #E2E8F0;border-left:5px solid #D4AF37;
        border-radius:12px;padding:18px 22px;margin:14px 0 20px;
        color:#10213A;font-size:.94rem;line-height:1.55;
        box-shadow:0 1px 2px rgba(10,27,61,.05);
    }
    .insight-topo strong { color:#9C7317; }

    /* ═══ Score de saude 0-100 ═══ */
    .score-card {
        background:#FFFFFF;border:1px solid #E2E8F0;border-radius:14px;
        padding:22px;text-align:center;position:relative;overflow:hidden;
    }
    .score-card .valor { font-size:3.4rem;font-weight:800;line-height:1; }
    .score-card .barra { color:#64748B;font-size:.72rem;text-transform:uppercase;
        letter-spacing:.08em;margin-top:6px; }
    .score-card .classificacao { font-size:1rem;font-weight:700;margin-top:6px;
        text-transform:uppercase;letter-spacing:.06em; }
    .score-card.excelente .valor,.score-card.excelente .classificacao { color:#0F766E; }
    .score-card.atencao .valor,.score-card.atencao .classificacao { color:#B45309; }
    .score-card.critico .valor,.score-card.critico .classificacao { color:#DC2626; }

    .score-componentes { margin-top:12px; }
    .score-comp-linha { display:flex;justify-content:space-between;align-items:center;
        margin:6px 0;font-size:.8rem;color:#475569; }
    .score-comp-linha .barra-bg { background:#E2E8F0;border-radius:4px;
        height:6px;margin-left:12px;overflow:hidden;flex:1;max-width:60%; }
    .score-comp-linha .barra-fg { background:#10B981;height:100%;border-radius:4px; }

    /* ═══ Churn alert ═══ */
    .churn-alert {
        background:#FEE2E2;border:1px solid #FCA5A5;border-radius:12px;
        color:#7F1D1D;padding:16px 20px;margin:12px 0;
        display:flex;align-items:center;gap:14px;
    }
    .churn-alert .icone { font-size:2rem; }
    .churn-alert .conteudo strong { display:block;font-size:1rem;margin-bottom:2px; }
    .churn-alert .conteudo span { font-size:.85rem;color:#B91C1C; }

    /* ═══ Curva ABC (Pareto) ═══ */
    .abc-grid { display:grid;grid-template-columns:repeat(3,1fr);gap:10px;margin:14px 0; }
    .abc-card {
        background:#FFFFFF;border:1px solid #E2E8F0;border-left:4px solid;border-radius:8px;padding:14px;
    }
    .abc-card.classe-A { border-left-color:#DC2626; }
    .abc-card.classe-B { border-left-color:#F59E0B; }
    .abc-card.classe-C { border-left-color:#10B981; }
    .abc-card .titulo { font-size:1.2rem;font-weight:800;margin-bottom:8px; }
    .abc-card.classe-A .titulo { color:#DC2626; }
    .abc-card.classe-B .titulo { color:#B45309; }
    .abc-card.classe-C .titulo { color:#0F766E; }
    .abc-card .stat { color:#10213A;font-size:.9rem;margin:3px 0; }
    .abc-card .stat strong { font-size:1.05rem; }
    .abc-card .sub { color:#64748B;font-size:.72rem; }
    .abc-insight {
        background:#FFFFFF;border:1px solid #E2E8F0;border-left:4px solid #D4AF37;border-radius:8px;
        padding:12px 16px;margin:10px 0;color:#10213A;font-size:.88rem;
    }

    /* ═══ Metas com barra de progresso ═══ */
    .meta-card {
        background:#FFFFFF;border:1px solid #E2E8F0;border-radius:12px;
        padding:16px 18px;margin:10px 0;
    }
    .meta-card .cabecalho { display:flex;justify-content:space-between;
        margin-bottom:8px;color:#475569; }
    .meta-card .cabecalho strong { color:#10213A; }
    .meta-progresso {
        background:#E2E8F0;border-radius:6px;height:12px;overflow:hidden;
        position:relative;
    }
    .meta-progresso-barra {
        background:linear-gradient(90deg,#10B981,#34D399);
        height:100%;border-radius:6px;transition:width .3s;
    }
    .meta-progresso-barra.parcial {
        background:linear-gradient(90deg,#F59E0B,#FBBF24);
    }
    .meta-progresso-barra.baixa {
        background:linear-gradient(90deg,#DC2626,#F87171);
    }
    .meta-card .rodape { color:#64748B;font-size:.75rem;margin-top:6px; }

    /* ═══ Heatmap sazonalidade ═══ */
    .heatmap-grid {
        display:grid;grid-template-columns:repeat(6,1fr);gap:8px;
        margin:12px 0;
    }
    .heatmap-mes {
        background:#FFFFFF;border:1px solid #E2E8F0;border-radius:8px;
        padding:10px 8px;text-align:center;transition:transform .15s;
    }
    .heatmap-mes:hover { transform:scale(1.03); }
    .heatmap-mes .nome { color:#475569;font-size:.72rem;
        text-transform:uppercase;letter-spacing:.05em;margin-bottom:4px; }
    .heatmap-mes .valor { color:#10213A;font-size:.9rem;font-weight:700; }
    .heatmap-mes .info { color:#64748B;font-size:.65rem;margin-top:2px; }

    /* ═══ Previsao ═══ */
    .previsao-tabela {
        background:#FFFFFF;border:1px solid #E2E8F0;border-radius:10px;
        overflow:hidden;margin:12px 0;
    }
    .previsao-tabela .linha {
        display:grid;grid-template-columns:1fr 1fr 1fr 1fr;
        padding:10px 14px;border-bottom:1px solid #E2E8F0;color:#475569;
        font-size:.86rem;align-items:center;
    }
    .previsao-tabela .linha:last-child { border-bottom:none; }
    .previsao-tabela .linha.header {
        background:#F1F5F9;color:#10213A;font-weight:700;
        font-size:.75rem;text-transform:uppercase;letter-spacing:.05em;
    }
    .previsao-tabela .saldo-positivo { color:#0F766E;font-weight:600; }
    .previsao-tabela .saldo-negativo { color:#DC2626;font-weight:600; }

    /* ═══ Botoes de acao rapida ═══ */
    .acao-rapida-info {
        background:#EFF6FF;border:1px solid #93C5FD;border-radius:10px;
        color:#1E3A5F;padding:12px 16px;margin:10px 0;font-size:.85rem;
    }
    .acao-rapida-info strong { color:#1D4ED8; }

    /* ═══ Cruzamento com geo ═══ */
    .geo-classe-card {
        background:#FFFFFF;border:1px solid #E2E8F0;border-radius:10px;
        padding:14px;text-align:center;
    }
    .geo-classe-card .qtd { font-size:2rem;font-weight:800;color:#10213A; }
    .geo-classe-card .rotulo { color:#475569;font-size:.78rem;margin-top:2px; }
    .geo-classe-card.engajado .qtd { color:#0F766E; }
    .geo-classe-card.presente_sem_contribuir .qtd { color:#B45309; }
    .geo-classe-card.contribui_sem_presenca .qtd { color:#1D4ED8; }
    .geo-classe-card.ausente_total .qtd { color:#DC2626; }
    </style>
    """, unsafe_allow_html=True)


def _card(titulo, valor, nota=""):
    st.markdown(
        f'<div class="dash-card"><div class="dash-label">{_escape(titulo)}</div>'
        f'<div class="dash-value">{_escape(valor)}</div>'
        f'<div class="dash-note">{_escape(nota)}</div></div>',
        unsafe_allow_html=True,
    )


def _autorizacao_pastoral(slug):
    chave = _sk("pastoral_ate", slug)
    agora = datetime.datetime.now().timestamp()
    if st.session_state.get(chave, 0) > agora:
        return True
    st.session_state.pop(chave, None)
    if not senha_pastoral_configurada(slug):
        st.info(
            "Cadastre uma senha exclusiva para o acompanhamento pastoral "
            "na pagina Minha Conta."
        )
        return False
    with st.form(_sk("pastoral_form", slug)):
        senha = st.text_input("Senha do acompanhamento pastoral", type="password")
        if st.form_submit_button("Acessar acompanhamento pastoral", type="primary"):
            if autenticar_senha_pastoral(slug, senha):
                st.session_state[chave] = agora + 5 * 60
                st.rerun()
            else:
                st.error("Senha pastoral incorreta.")
    return False


# ═══════════════════════════════════════════════════════════════════════
# NOVAS FUNCOES DE RENDERIZACAO (Onda 1, 2 e 3)
# ═══════════════════════════════════════════════════════════════════════

def _render_insight_topo(insight_texto):
    """Renderiza o insight textual no topo da Visao Executiva."""
    # Converter markdown ** para HTML
    texto_html = insight_texto.replace("**", "___SEP___")
    partes = texto_html.split("___SEP___")
    resultado = ""
    for i, parte in enumerate(partes):
        parte_esc = _escape(parte)
        if i % 2 == 1:
            resultado += f"<strong>{parte_esc}</strong>"
        else:
            resultado += parte_esc
    st.markdown(
        f'<div class="insight-topo">💡 {resultado}</div>',
        unsafe_allow_html=True,
    )


def _render_ticket_medio_gap(ticket_info):
    """Renderiza cards com ticket medio, potencial e gap."""
    t1, t2, t3 = st.columns(3)
    with t1:
        _card(
            "Ticket medio dizimo",
            formatar_moeda(ticket_info["ticket_medio"]),
            f"{ticket_info['dizimistas']} dizimista(s) no mes",
        )
    with t2:
        _card(
            "Arrecadacao potencial",
            formatar_moeda(ticket_info["potencial"]),
            f"Ticket medio x {ticket_info['membros_ativos']} membros ativos",
        )
    with t3:
        cor_gap = "#EF4444" if ticket_info["gap"] > ticket_info["total_dizimo"] else "#F59E0B"
        st.markdown(
            f'<div class="dash-card"><div class="dash-label">Gap de arrecadacao</div>'
            f'<div class="dash-value" style="color:{cor_gap}">{_escape(formatar_moeda(ticket_info["gap"]))}</div>'
            f'<div class="dash-note">{ticket_info["percentual_arrecadado"]:.1f}% do potencial alcancado</div></div>',
            unsafe_allow_html=True,
        )


def _render_score_saude(score):
    """Renderiza o score de saude financeira 0-100 com decomposicao."""
    classe = score["classificacao"]
    componentes_html = ""
    for nome, valor in score["componentes"].items():
        maximo = score["maximos"][nome]
        pct = (valor / maximo * 100) if maximo > 0 else 0
        componentes_html += (
            f'<div class="score-comp-linha">'
            f'<span>{_escape(nome)}</span>'
            f'<span>{valor:.1f} / {maximo}</span>'
            f'<div class="barra-bg"><div class="barra-fg" style="width:{pct:.0f}%"></div></div>'
            f'</div>'
        )
    st.markdown(
        f'<div class="score-card {classe}">'
        f'<div class="valor">{score["emoji"]} {score["score_total"]:.0f}<span style="font-size:1.2rem;color:#64748B">/100</span></div>'
        f'<div class="barra">Score de saude financeira</div>'
        f'<div class="classificacao">{_escape(score["classificacao"])}</div>'
        f'<div class="score-componentes">{componentes_html}</div>'
        f'</div>',
        unsafe_allow_html=True,
    )


def _render_churn_alerta(churn_info, slug, igreja, mes_ref):
    """Renderiza alerta e lista de dizimistas em churn."""
    if churn_info["quantidade"] == 0:
        st.success(
            f"✅ Nenhum dizimista regular parou de contribuir nos ultimos "
            f"{churn_info['dias_referencia']} dias."
        )
        return

    st.markdown(
        f'<div class="churn-alert">'
        f'<div class="icone">⚠️</div>'
        f'<div class="conteudo">'
        f'<strong>{churn_info["quantidade"]} dizimista(s) regular(es) pararam de contribuir</strong>'
        f'<span>Impacto estimado: {formatar_moeda(churn_info["impacto_estimado"])} por mes '
        f'(analise dos ultimos {churn_info["dias_referencia"]} dias)</span>'
        f'</div></div>',
        unsafe_allow_html=True,
    )

    with st.expander(f"Ver {churn_info['quantidade']} dizimista(s) em churn", expanded=False):
        for item in churn_info["lista"]:
            col_info, col_wa = st.columns([3, 1])
            with col_info:
                st.markdown(
                    f"**{_escape(item['Nome'])}** — Media {item['Media mensal formatada']} "
                    f"({item['Contribuicoes no periodo']} contribuicoes anteriores)"
                )
            with col_wa:
                if item["Telefone"]:
                    nome_igreja = igreja.get("nome", "Igreja")
                    mes_str = _mes_label(mes_ref)
                    msg = _mensagem_acompanhamento_afastado(nome_igreja, item["Nome"], mes_str)
                    link = _link_whatsapp_padrao(item["Telefone"], msg)
                    if link:
                        st.markdown(
                            f'<a href="{_escape(link)}" target="_blank" '
                            f'style="background:#25D366;color:white;padding:6px 12px;'
                            f'border-radius:6px;text-decoration:none;font-size:.78rem;'
                            f'font-weight:600;display:inline-block;">📱 WhatsApp</a>',
                            unsafe_allow_html=True,
                        )


def _render_curva_abc(abc_info):
    """Renderiza a curva ABC (Pareto) dos dizimistas."""
    if abc_info is None:
        st.info("Sem dados suficientes para calcular a curva ABC de dizimistas.")
        return

    resumo = abc_info["resumo_classes"]

    # Insight principal
    st.markdown(
        f'<div class="abc-insight">'
        f'💡 <strong>{abc_info["pct_dizimistas_top_a"]:.1f}% dos dizimistas '
        f'(Classe A) respondem por {abc_info["pct_valor_top_a"]:.1f}% da arrecadacao.</strong> '
        f'Uma queda concentrada neste grupo teria impacto financeiro proporcional.'
        f'</div>',
        unsafe_allow_html=True,
    )

    # Grid de 3 cards A/B/C
    cards_html = '<div class="abc-grid">'
    descricoes = {
        "A": "Contribuintes principais (top ~80% do valor)",
        "B": "Contribuintes intermediarios (proximos 15%)",
        "C": "Contribuintes eventuais (ultimos 5%)",
    }
    for classe in ["A", "B", "C"]:
        linha = resumo[resumo["classe"] == classe]
        if linha.empty:
            qtd, valor, pct_v, pct_m = 0, 0, 0, 0
        else:
            qtd = int(linha["quantidade"].iloc[0])
            valor = float(linha["valor"].iloc[0])
            pct_v = float(linha["percentual_valor"].iloc[0])
            pct_m = float(linha["percentual_membros"].iloc[0])
        cards_html += (
            f'<div class="abc-card classe-{classe}">'
            f'<div class="titulo">Classe {classe}</div>'
            f'<div class="stat"><strong>{qtd}</strong> dizimista(s)</div>'
            f'<div class="stat">{_escape(formatar_moeda(valor))}</div>'
            f'<div class="stat">{pct_v:.1f}% do valor | {pct_m:.1f}% dos dizimistas</div>'
            f'<div class="sub">{_escape(descricoes[classe])}</div>'
            f'</div>'
        )
    cards_html += '</div>'
    st.markdown(cards_html, unsafe_allow_html=True)


def _render_metas_arrecadacao(slug, ent_atual, dizimo_atual):
    """Renderiza barra de progresso das metas de arrecadacao."""
    try:
        meta_arrecadacao = _numero_config(
            obter_config_igreja(slug, "meta_arrecadacao_mensal", "0"), 0
        )
        meta_dizimo = _numero_config(
            obter_config_igreja(slug, "meta_dizimo_mensal", "0"), 0
        )
    except Exception:
        meta_arrecadacao, meta_dizimo = 0.0, 0.0

    if meta_arrecadacao <= 0 and meta_dizimo <= 0:
        st.info(
            "Configure metas mensais em **Minha conta > Configuracoes** para "
            "acompanhar o progresso da arrecadacao. Campos: `meta_arrecadacao_mensal` e `meta_dizimo_mensal`."
        )
        return

    if meta_arrecadacao > 0:
        pct = (ent_atual / meta_arrecadacao * 100) if meta_arrecadacao > 0 else 0
        pct_clip = min(pct, 100)
        classe = "" if pct >= 95 else "parcial" if pct >= 60 else "baixa"
        st.markdown(
            f'<div class="meta-card">'
            f'<div class="cabecalho">'
            f'<span>Meta de arrecadacao total</span>'
            f'<strong>{formatar_moeda(ent_atual)} / {formatar_moeda(meta_arrecadacao)}</strong>'
            f'</div>'
            f'<div class="meta-progresso"><div class="meta-progresso-barra {classe}" '
            f'style="width:{pct_clip:.1f}%"></div></div>'
            f'<div class="rodape">{pct:.1f}% da meta atingida</div>'
            f'</div>',
            unsafe_allow_html=True,
        )

    if meta_dizimo > 0:
        pct = (dizimo_atual / meta_dizimo * 100) if meta_dizimo > 0 else 0
        pct_clip = min(pct, 100)
        classe = "" if pct >= 95 else "parcial" if pct >= 60 else "baixa"
        st.markdown(
            f'<div class="meta-card">'
            f'<div class="cabecalho">'
            f'<span>Meta de dizimo</span>'
            f'<strong>{formatar_moeda(dizimo_atual)} / {formatar_moeda(meta_dizimo)}</strong>'
            f'</div>'
            f'<div class="meta-progresso"><div class="meta-progresso-barra {classe}" '
            f'style="width:{pct_clip:.1f}%"></div></div>'
            f'<div class="rodape">{pct:.1f}% da meta atingida</div>'
            f'</div>',
            unsafe_allow_html=True,
        )


def _render_heatmap_sazonalidade(df):
    """Renderiza o heatmap de sazonalidade mensal (jan-dez)."""
    sazonalidade = _sazonalidade_mensal(df)
    if sazonalidade.empty or sazonalidade["anos_com_dados"].sum() == 0:
        st.info("Sem dados historicos suficientes para analise sazonal.")
        return

    max_ent = sazonalidade["entradas_media"].max()
    if max_ent <= 0:
        st.info("Sem entradas historicas para analise sazonal.")
        return

    grid = '<div class="heatmap-grid">'
    for _, row in sazonalidade.iterrows():
        intensidade = row["entradas_media"] / max_ent if max_ent > 0 else 0
        # Cor de fundo baseada na intensidade (verde escuro -> claro)
        alpha = 0.15 + (intensidade * 0.5)
        cor_fundo = f"rgba(16,185,129,{alpha})"
        grid += (
            f'<div class="heatmap-mes" style="background:{cor_fundo}">'
            f'<div class="nome">{_escape(row["mes_nome"])}</div>'
            f'<div class="valor">{_escape(formatar_moeda(row["entradas_media"]))}</div>'
            f'<div class="info">{int(row["anos_com_dados"])} ano(s)</div>'
            f'</div>'
        )
    grid += '</div>'
    st.markdown(grid, unsafe_allow_html=True)

    # Insight sobre o melhor mes
    if len(sazonalidade[sazonalidade["anos_com_dados"] > 0]) >= 3:
        top = sazonalidade.nlargest(1, "entradas_media").iloc[0]
        media_geral = sazonalidade[sazonalidade["anos_com_dados"] > 0]["entradas_media"].mean()
        if media_geral > 0:
            variacao = (top["entradas_media"] - media_geral) / media_geral * 100
            st.caption(
                f"💡 O mes historicamente mais forte e **{top['mes_nome']}** "
                f"({formatar_moeda(top['entradas_media'])}), {variacao:+.1f}% em relacao "
                f"a media anual."
            )


def _render_previsao(df, mes_ref):
    """Renderiza previsao dos proximos 3 meses via regressao linear."""
    previsao = _previsao_regressao_linear(df, mes_ref, horizonte=3)
    if previsao is None:
        st.info(
            "Sao necessarios pelo menos 3 meses de dados para gerar previsao. "
            "A previsao usa regressao linear simples sobre os ultimos 12 meses."
        )
        return

    linhas_html = (
        '<div class="previsao-tabela">'
        '<div class="linha header">'
        '<div>Mes</div><div>Entradas previstas</div>'
        '<div>Saidas previstas</div><div>Saldo previsto</div>'
        '</div>'
    )
    for _, row in previsao.iterrows():
        classe_saldo = "saldo-positivo" if row["saldo_previsto"] >= 0 else "saldo-negativo"
        linhas_html += (
            f'<div class="linha">'
            f'<div><strong>{_escape(row["rotulo"])}</strong></div>'
            f'<div>{_escape(formatar_moeda(row["entradas_previstas"]))}</div>'
            f'<div>{_escape(formatar_moeda(row["saidas_previstas"]))}</div>'
            f'<div class="{classe_saldo}">{_escape(formatar_moeda(row["saldo_previsto"]))}</div>'
            f'</div>'
        )
    linhas_html += '</div>'
    st.markdown(linhas_html, unsafe_allow_html=True)

    st.caption(
        "⚠️ Previsao baseada em regressao linear dos ultimos 12 meses. "
        "Nao considera eventos excepcionais (campanhas, feriados, sazonalidade). "
        "Use como orientacao complementar, nao como fato consumado."
    )


def _render_cruzamento_geo(df_cruzamento):
    """Renderiza cruzamento de frequencia geo x contribuicao."""
    if df_cruzamento is None or df_cruzamento.empty:
        st.info(
            "Cruzamento de dados nao disponivel. "
            "Requer registros no modulo Monitoramento Geo no periodo selecionado."
        )
        return

    classes_labels = {
        "engajado": ("✅ Engajados", "Presente + contribuindo"),
        "presente_sem_contribuir": ("⚠️ Presentes sem contribuir", "Frequenta mas nao dizima"),
        "contribui_sem_presenca": ("📱 Contribuem a distancia", "Dizima mas nao esta presente"),
        "ausente_total": ("❌ Ausentes totais", "Nem presente nem contribuindo"),
    }

    cols = st.columns(4)
    for col, (chave, (rotulo, descricao)) in zip(cols, classes_labels.items()):
        qtd = int((df_cruzamento["classe"] == chave).sum())
        with col:
            st.markdown(
                f'<div class="geo-classe-card {chave}">'
                f'<div class="qtd">{qtd}</div>'
                f'<div class="rotulo">{_escape(rotulo)}</div>'
                f'<div class="rotulo" style="font-size:.68rem;color:#64748B">{_escape(descricao)}</div>'
                f'</div>',
                unsafe_allow_html=True,
            )


def _render_lista_whatsapp_classe(classe_df, membros, igreja, mes_ref, rotulo_classe):
    """Lista dizimistas de uma classe ABC com botao de envio de agradecimento via WhatsApp."""
    if classe_df.empty:
        st.caption(f"Sem dizimistas Classe {rotulo_classe} no periodo.")
        return

    telefones_dict = membros.set_index("id_cadastro")["telefone"].to_dict()
    classe_df = classe_df.copy()
    classe_df["telefone"] = classe_df["id_cadastro"].map(
        lambda x: telefones_dict.get(int(x), "")
    )

    with_tel = classe_df[classe_df["telefone"].astype(str).str.len() > 0]
    without_tel = classe_df[classe_df["telefone"].astype(str).str.len() == 0]

    if not with_tel.empty:
        st.markdown(f"**Dizimistas Classe {rotulo_classe} com telefone:** {len(with_tel)}")
        with st.expander(f"Ver {len(with_tel)} membro(s)", expanded=False):
            nome_igreja = igreja.get("nome", "Igreja")
            mes_str = _mes_label(mes_ref)
            for _, row in with_tel.iterrows():
                col_info, col_wa = st.columns([3, 1])
                with col_info:
                    st.markdown(
                        f"**{_escape(row['nome'])}** — {_escape(formatar_moeda(row['valor']))} "
                        f"({row['percentual']:.1f}% do valor)"
                    )
                with col_wa:
                    msg = _mensagem_agradecimento_dizimista(nome_igreja, row["nome"], mes_str)
                    link = _link_whatsapp_padrao(row["telefone"], msg)
                    if link:
                        st.markdown(
                            f'<a href="{_escape(link)}" target="_blank" '
                            f'style="background:#25D366;color:white;padding:6px 12px;'
                            f'border-radius:6px;text-decoration:none;font-size:.78rem;'
                            f'font-weight:600;display:inline-block;">📱 Agradecer</a>',
                            unsafe_allow_html=True,
                        )

    if not without_tel.empty:
        st.caption(
            f"⚠️ {len(without_tel)} dizimista(s) Classe {rotulo_classe} sem telefone cadastrado. "
            "Atualize os cadastros para enviar mensagens automaticas."
        )


def _render_botoes_acao_rapida(abc_info, membros, igreja, mes_ref, slug):
    """Renderiza botoes de acao rapida: agradecimento a dizimistas das classes A, B e C."""
    if abc_info is None:
        return

    st.markdown(
        '<div class="acao-rapida-info">'
        '<strong>💬 Acao rapida:</strong> Envie mensagens de agradecimento aos '
        'dizimistas por classe ABC (Classe A = principais contribuintes, '
        'B e C = demais contribuintes do periodo).'
        '</div>',
        unsafe_allow_html=True,
    )

    por_membro = abc_info["por_membro"]
    tab_a, tab_b, tab_c = st.tabs(["Classe A", "Classe B", "Classe C"])
    for tab, classe in ((tab_a, "A"), (tab_b, "B"), (tab_c, "C")):
        with tab:
            classe_df = por_membro[por_membro["classe"] == classe]
            _render_lista_whatsapp_classe(classe_df, membros, igreja, mes_ref, classe)


def _gerar_html_relatorio_executivo(
    igreja, slug, inicio, fim, ent, sai, saldo,
    ticket_info, score, saude_info, insight_texto,
):
    """Gera HTML de relatorio executivo pronto para impressao."""
    nome_igreja = _escape(igreja.get("nome", "Igreja"))
    periodo_str = _rotulo_periodo(inicio, fim)
    data_emissao = datetime.datetime.now().strftime("%d/%m/%Y %H:%M")

    # Componentes do score
    comps_html = ""
    for nome, valor in score["componentes"].items():
        maximo = score["maximos"][nome]
        pct = (valor / maximo * 100) if maximo > 0 else 0
        comps_html += (
            f'<tr><td>{_escape(nome)}</td>'
            f'<td style="text-align:right">{valor:.1f} / {maximo}</td>'
            f'<td style="text-align:right">{pct:.0f}%</td></tr>'
        )

    insight_html = insight_texto.replace("**", "").replace("⚠️", "")
    insight_html = _escape(insight_html)

    cor_score = "#10B981" if score["classificacao"] == "excelente" \
        else "#F59E0B" if score["classificacao"] == "atencao" else "#EF4444"

    return f"""
<!DOCTYPE html>
<html lang="pt-BR"><head>
<meta charset="UTF-8">
<title>Relatorio Executivo - {periodo_str}</title>
<style>
* {{ box-sizing:border-box;margin:0;padding:0; }}
body {{ font-family:Arial,sans-serif;background:#f0f0f0;padding:20px;color:#111; }}
.relatorio {{ background:white;max-width:800px;margin:0 auto;padding:32px;
    box-shadow:0 4px 12px rgba(0,0,0,.1);border-radius:8px; }}
h1 {{ font-size:20px;margin-bottom:4px;color:#1E293B; }}
h2 {{ font-size:14px;color:#64748B;font-weight:normal;margin-bottom:20px; }}
h3 {{ font-size:15px;color:#334155;margin:22px 0 8px;border-bottom:2px solid #E2E8F0;
    padding-bottom:6px; }}
.grade-kpi {{ display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin:12px 0; }}
.kpi {{ background:#F8FAFC;border:1px solid #E2E8F0;padding:12px;border-radius:6px; }}
.kpi .rotulo {{ font-size:10px;color:#64748B;text-transform:uppercase;letter-spacing:.05em; }}
.kpi .valor {{ font-size:16px;font-weight:700;color:#1E293B;margin-top:4px; }}
.insight {{ background:#FEF3C7;border-left:4px solid #D4AF37;padding:14px 18px;
    border-radius:6px;margin:12px 0;font-size:12px;line-height:1.6; }}
.score-box {{ text-align:center;padding:20px;border:2px solid {cor_score};
    border-radius:8px;margin:14px 0; }}
.score-box .num {{ font-size:36px;font-weight:800;color:{cor_score}; }}
.score-box .cls {{ font-size:12px;color:#64748B;text-transform:uppercase;
    letter-spacing:.05em;margin-top:4px; }}
table {{ width:100%;border-collapse:collapse;margin:8px 0;font-size:12px; }}
th {{ background:#F1F5F9;color:#1E293B;text-align:left;padding:8px;border-bottom:1px solid #E2E8F0; }}
td {{ padding:6px 8px;border-bottom:1px solid #F1F5F9;color:#334155; }}
.rodape {{ text-align:center;color:#64748B;font-size:10px;margin-top:22px;
    padding-top:14px;border-top:1px solid #E2E8F0; }}
.btn-imprimir {{ background:#0F6E56;color:white;border:none;padding:10px 24px;
    border-radius:6px;font-size:13px;cursor:pointer;font-weight:600; }}
@media print {{
    body {{ background:white;padding:0; }}
    .relatorio {{ box-shadow:none; }}
    .btn-imprimir {{ display:none; }}
}}
</style></head>
<body>
<div style="text-align:center;margin-bottom:12px">
<button class="btn-imprimir" onclick="window.print()">🖨️ Imprimir / Salvar PDF</button>
</div>

<div class="relatorio">
<h1>{nome_igreja}</h1>
<h2>Relatorio Executivo — {_escape(periodo_str)} | Emitido em {_escape(data_emissao)}</h2>

<div class="insight">💡 {insight_html}</div>

<h3>Indicadores do Mes</h3>
<div class="grade-kpi">
    <div class="kpi"><div class="rotulo">Entradas</div><div class="valor">{_escape(formatar_moeda(ent))}</div></div>
    <div class="kpi"><div class="rotulo">Saidas</div><div class="valor">{_escape(formatar_moeda(sai))}</div></div>
    <div class="kpi"><div class="rotulo">Saldo</div><div class="valor">{_escape(formatar_moeda(saldo))}</div></div>
    <div class="kpi"><div class="rotulo">Dizimistas</div><div class="valor">{ticket_info["dizimistas"]}</div></div>
</div>

<h3>Score de Saude Financeira</h3>
<div class="score-box">
    <div class="num">{score["score_total"]:.0f}<span style="font-size:16px;color:#64748B">/100</span></div>
    <div class="cls">{score["emoji"]} {_escape(score["classificacao"])}</div>
</div>

<table>
<thead><tr><th>Componente</th><th style="text-align:right">Pontos</th><th style="text-align:right">%</th></tr></thead>
<tbody>{comps_html}</tbody>
</table>

<h3>Ticket Medio e Potencial</h3>
<table>
<tr><td>Ticket medio de dizimo</td><td style="text-align:right">{_escape(formatar_moeda(ticket_info["ticket_medio"]))}</td></tr>
<tr><td>Arrecadacao potencial (se 100% dos membros dizimasse)</td><td style="text-align:right">{_escape(formatar_moeda(ticket_info["potencial"]))}</td></tr>
<tr><td>Gap para o potencial</td><td style="text-align:right">{_escape(formatar_moeda(ticket_info["gap"]))}</td></tr>
<tr><td>% do potencial arrecadado</td><td style="text-align:right">{ticket_info["percentual_arrecadado"]:.1f}%</td></tr>
</table>

<h3>Saude e Reserva</h3>
<table>
<tr><td>Cobertura da reserva</td><td style="text-align:right">{f"{saude_info['cobertura']:.1f} meses" if saude_info.get('cobertura') is not None else "Sem despesas"}</td></tr>
<tr><td>Despesa media mensal</td><td style="text-align:right">{_escape(formatar_moeda(saude_info["media_saidas"]))}</td></tr>
<tr><td>Resultado medio mensal</td><td style="text-align:right">{_escape(formatar_moeda(saude_info["resultado_medio"]))}</td></tr>
<tr><td>Saldo acumulado</td><td style="text-align:right">{_escape(formatar_moeda(saude_info["saldo_acumulado"]))}</td></tr>
</table>

<div class="rodape">
    FielMordomo — Sistema de Gestao Financeira para Igrejas<br>
    Este relatorio nao substitui conciliacao bancaria nem planejamento orcamentario formal.
</div>
</div>
</body></html>"""


def render():
    _injetar_css()
    slug = slug_da_sessao()
    df_lanc, df_cad = carregar_lancamentos(slug), carregar_cadastros(slug)
    if df_lanc.empty:
        st.info("Ainda nao ha lancamentos para o dashboard.")
        return

    df, cad, faltantes, qualidade = _normalizar_dados(df_lanc, df_cad)
    if faltantes:
        st.error("Dashboard indisponivel. Colunas ausentes: " + ", ".join(faltantes))
        return
    if df.empty:
        st.error("Nao existem lancamentos validos para calcular o dashboard.")
        return

    membros = _membros_ativos(cad)
    igreja = st.session_state.get("igreja", {})

    # ═══ NOVO: Selecao de periodo (data inicial / data final) ═══
    # Substitui o antigo seletor de "mes de referencia" por um intervalo
    # livre de datas, mais flexivel para analises fora do mes calendario.
    data_min = df["data"].min().date()
    data_max = df["data"].max().date()
    hoje = datetime.date.today()
    fim_padrao = min(hoje, data_max)
    inicio_padrao = max(fim_padrao.replace(day=1), data_min)

    col_pi, col_pf = st.columns(2)
    with col_pi:
        inicio_mes = st.date_input(
            "Periodo - de",
            value=inicio_padrao,
            min_value=data_min,
            max_value=data_max,
            format="DD/MM/YYYY",
            key=_sk("periodo_inicio", slug),
        )
    with col_pf:
        fim_mes = st.date_input(
            "Periodo - ate",
            value=fim_padrao,
            min_value=data_min,
            max_value=data_max,
            format="DD/MM/YYYY",
            key=_sk("periodo_fim", slug),
        )
    if inicio_mes > fim_mes:
        st.error("A data inicial nao pode ser posterior a data final.")
        inicio_mes, fim_mes = fim_mes, inicio_mes

    # Periodo de comparacao imediatamente anterior, com a mesma duracao
    dias_periodo = (fim_mes - inicio_mes).days + 1
    inicio_anterior = inicio_mes - datetime.timedelta(days=dias_periodo)
    fim_anterior = inicio_mes - datetime.timedelta(days=1)

    # mes_ref (Period) e usado pelas analises de tendencia mensal
    # (evolucao 12 meses, score de saude, sazonalidade, previsao, YTD),
    # que continuam calculadas com base no mes final do periodo escolhido.
    mes_ref = pd.Period(fim_mes, freq="M")

    ref = _periodo(df, inicio_mes, fim_mes)
    comp = _periodo(df, inicio_anterior, fim_anterior)
    ent, sai, saldo = _totais(ref)
    ent_ant, sai_ant, saldo_ant = _totais(comp)
    qtd_diz, membros_n, pct_diz = _participacao_dizimistas(ref, membros)
    (ent_ytd, sai_ytd, saldo_ytd), (ent_ytd_ant, _, _) = _comparativo_ytd(df, mes_ref.year, mes_ref.month)

    # ═══ Comparativo mesmo periodo do ano anterior ═══
    try:
        inicio_ano_ant = inicio_mes.replace(year=inicio_mes.year - 1)
        fim_ano_ant = fim_mes.replace(year=fim_mes.year - 1)
    except ValueError:
        # Trata 29/02 em ano nao bissexto
        inicio_ano_ant = inicio_mes - datetime.timedelta(days=365)
        fim_ano_ant = fim_mes - datetime.timedelta(days=365)
    mesmo_periodo_ano_ant = _periodo(df, inicio_ano_ant, fim_ano_ant)
    ent_mma, sai_mma, saldo_mma = _totais(mesmo_periodo_ano_ant)

    # ═══ Calculos para novos indicadores ═══
    reserva = _numero_config(
        obter_config_igreja(slug, "reserva_financeira_disponivel", "0")
    )
    meta_reserva = int(_numero_config(
        obter_config_igreja(slug, "meta_reserva_meses", "3"), 3
    ))
    if meta_reserva < 1:
        meta_reserva = 3
    saude_info = _indicadores_saude(df, mes_ref, reserva, meta_reserva)
    ticket_info = _ticket_medio_arrecadacao(ref, membros)
    score = _score_saude_financeira(df, mes_ref, saude_info, qualidade, membros)
    insight_texto = _gerar_insight_textual(
        inicio_mes, fim_mes, ent, ent_ant, ref, membros, saude_info, ticket_info, score,
    )

    dizimo_mes, _, _ = _totais_dizimo(ref)

    st.markdown("## Dashboard Financeiro")
    st.caption("Visao executiva para decisao, conferencia e acompanhamento de tendencias.")
    dashboard_restrito = st.session_state.get("modo") == "pastor_auxiliar"
    if dashboard_restrito:
        st.info(
            "Acesso de Pastor Auxiliar: as areas Saude Financeira, Qualidade "
            "e Acompanhamento Pastoral nao estao disponiveis neste perfil."
        )

    # ═══ NOVO: Botao de exportacao executiva no topo ═══
    if not dashboard_restrito:
        col_btn_exp, _ = st.columns([1, 3])
        with col_btn_exp:
            if st.button("📄 Exportar relatorio executivo", key=_sk("btn_export_exec", slug),
                         use_container_width=True):
                html_relatorio = _gerar_html_relatorio_executivo(
                    igreja, slug, inicio_mes, fim_mes, ent, sai, saldo,
                    ticket_info, score, saude_info, insight_texto,
                )
                st.session_state[_sk("html_export", slug)] = html_relatorio

        if _sk("html_export", slug) in st.session_state:
            st.download_button(
                "⬇️ Baixar relatorio (HTML - abra no navegador e imprima como PDF)",
                data=st.session_state[_sk("html_export", slug)],
                file_name=f"relatorio_executivo_{inicio_mes:%Y%m%d}_{fim_mes:%Y%m%d}.html",
                mime="text/html",
                key=_sk("dl_export", slug),
            )

    _legenda_cores()

    # ═══ NOVO: Insight textual automatico ═══
    _render_insight_topo(insight_texto)

    # ═══ KPIs principais com COMPARATIVO ANO ANTERIOR ═══
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        nota_ent = f"{_variacao(ent, ent_ant)} vs mes ant."
        if ent_mma > 0:
            nota_ent += f" | {_variacao(ent, ent_mma)} vs mesmo mes ano ant."
        _card("Entradas", formatar_moeda(ent), nota_ent)
    with c2:
        nota_sai = f"{_variacao(sai, sai_ant)} vs mes ant."
        if sai_mma > 0:
            nota_sai += f" | {_variacao(sai, sai_mma)} vs mesmo mes ano ant."
        _card("Saidas", formatar_moeda(sai), nota_sai)
    with c3:
        nota_saldo = f"{_variacao(saldo, saldo_ant)} vs mes ant."
        if saldo_mma != 0:
            nota_saldo += f" | {_variacao(saldo, saldo_mma)} vs mesmo mes ano ant."
        _card("Saldo", formatar_moeda(saldo), nota_saldo)
    with c4:
        _card("Participacao dizimistas ativos", f"{pct_diz:.1f}%",
              f"{qtd_diz} de {membros_n} membros ativos")

    a1, a2, a3 = st.columns(3)
    with a1: _card("Entradas YTD", formatar_moeda(ent_ytd), f"{_variacao(ent_ytd, ent_ytd_ant)} vs mesmo periodo anterior")
    with a2: _card("Saidas YTD", formatar_moeda(sai_ytd))
    with a3: _card("Saldo YTD", formatar_moeda(saldo_ytd))

    tab_visao, tab_despesas, tab_receitas, tab_pastoral = st.tabs([
        "Visao Executiva", "Despesas", "Receitas",
        "Acompanhamento Pastoral",
    ])

    with tab_visao:
        # ═══ NOVO: Ticket medio, potencial e gap ═══
        _secao_dashboard(
            "Ticket medio e potencial de arrecadacao",
            "Analise do valor medio por dizimista e do potencial de arrecadacao vs realizado.",
        )
        _render_ticket_medio_gap(ticket_info)

        _secao_dashboard(
            "Evolucao financeira",
            "Entradas, saidas e saldo acumulado mes a mes desde janeiro/2026.",
        )
        serie = _serie_mensal(df, mes_ref, inicio_minimo=pd.Period("2026-01", freq="M"))
        # Posicoes alternadas (acima/abaixo) para o texto do saldo, reduzindo
        # sobreposicao com os rotulos das barras de entradas/saidas.
        posicoes_saldo = [
            "top center" if i % 2 == 0 else "bottom center"
            for i in range(len(serie))
        ]
        # Cor do texto do saldo: verde-folha escuro quando positivo,
        # vermelho quando negativo.
        cor_texto_saldo = [
            "#166534" if v >= 0 else "#DC2626"
            for v in serie["saldo"]
        ]
        fig = go.Figure([
            go.Bar(
                name="Entradas",
                x=serie["rotulo"],
                y=serie["entradas"],
                marker_color=CORES["entrada"],
                text=[formatar_moeda(v) if v else "" for v in serie["entradas"]],
                textposition="outside",
                textfont=dict(size=9, color="#475569"),
            ),
            go.Bar(
                name="Saidas",
                x=serie["rotulo"],
                y=serie["saidas"],
                marker_color=CORES["saida"],
                text=[formatar_moeda(v) if v else "" for v in serie["saidas"]],
                textposition="outside",
                textfont=dict(size=9, color="#475569"),
            ),
            go.Scatter(
                name="Saldo",
                x=serie["rotulo"],
                y=serie["saldo"],
                mode="lines+markers+text",
                line=dict(color=CORES["saldo"], width=3),
                text=[formatar_moeda(v) for v in serie["saldo"]],
                textposition=posicoes_saldo,
                textfont=dict(size=9, color=cor_texto_saldo),
            ),
        ])
        fig.update_layout(**_layout_grafico(
            altura=430,
            margem=dict(t=25, b=40, l=20, r=20),
            barmode="group",
            showlegend=False,
            xaxis=dict(fixedrange=True, gridcolor="#E2E8F0"),
            yaxis=dict(fixedrange=True, gridcolor="#E2E8F0", tickformat=",.0f"),
        ))
        st.plotly_chart(fig, use_container_width=True, config=CONFIG_PLOTLY)
        st.markdown(
            '<div class="dash-legenda">'
            f'<span><i style="background:{CORES["entrada"]}"></i>Verde: Receita</span>'
            f'<span><i style="background:{CORES["saida"]}"></i>Laranja: Saidas</span>'
            f'<span><i style="background:{CORES["saldo"]}"></i>Azul: Saldo (texto verde = positivo, vermelho = negativo)</span>'
            '</div>',
            unsafe_allow_html=True,
        )

        _secao_dashboard(
            "Composicao do periodo",
            "Leitura rapida da relacao entre recursos recebidos e despesas realizadas.",
        )
        composicao = pd.DataFrame({
            "Tipo": ["Entradas", "Saidas"],
            "Valor": [ent, sai],
        })
        if composicao["Valor"].sum() > 0:
            _grafico_rosca(
                composicao,
                "Tipo",
                "Valor",
                [CORES["entrada"], CORES["saida"]],
                "Composicao",
                valor_central=saldo,
                label_central="Saldo do periodo",
                cor_central=CORES["entrada"] if saldo >= 0 else CORES["saida"],
            )

        # ═══ NOVO: Heatmap de sazonalidade ═══
        _secao_dashboard(
            "Sazonalidade mensal",
            "Media historica de entradas por mes calendario. Cor mais intensa = arrecadacao mais alta.",
        )
        _render_heatmap_sazonalidade(df)

    with tab_despesas:
        saidas = ref[ref["tipo_norm"] == "SAIDA"].copy()
        saidas["subcategoria"] = _texto(saidas["subcategoria"]).replace("", "Sem subcategoria")
        resumo = saidas.groupby("subcategoria", as_index=False)["valor"].sum().sort_values("valor", ascending=False)
        resumo = resumo.rename(columns={"subcategoria": "Subcategoria", "valor": "Valor"})
        _secao_dashboard(
            "Distribuicao das despesas",
            "Participacao de cada subcategoria no total de saidas do periodo selecionado.",
        )
        if resumo.empty:
            st.info("Nao ha despesas no periodo selecionado.")
        else:
            _grafico_rosca(resumo, "Subcategoria", "Valor", PALETA, "Despesas")
            _secao_dashboard(
                "Ranking de despesas",
                "Subcategorias ordenadas pelo valor realizado no mes.",
            )
            st.plotly_chart(
                _grafico_ranking(resumo, "Subcategoria", "Valor", CORES["despesa"]),
                use_container_width=True,
                config=CONFIG_PLOTLY,
            )

            # ═══ NOVO: Analise temporal de despesas por subcategoria ═══
            _secao_dashboard(
                "Evolucao temporal por subcategoria",
                "Despesas por subcategoria ao longo dos ultimos 6 meses. "
                "Ajuda a identificar categorias com crescimento anormal.",
            )
            saidas_temporal = df[
                (df["tipo_norm"] == "SAIDA")
                & (df["mes_periodo"] <= mes_ref)
                & (df["mes_periodo"] >= (mes_ref - 5))
            ].copy()
            saidas_temporal["subcategoria"] = _texto(saidas_temporal["subcategoria"]).replace("", "Sem subcategoria")

            if saidas_temporal.empty:
                st.info("Sem despesas nos ultimos 6 meses para analise temporal.")
            else:
                # Top 5 subcategorias por valor total
                top5_subs = (
                    saidas_temporal.groupby("subcategoria")["valor"].sum()
                    .nlargest(5).index.tolist()
                )
                saidas_top = saidas_temporal[saidas_temporal["subcategoria"].isin(top5_subs)]
                pivot = saidas_top.pivot_table(
                    index="mes_periodo", columns="subcategoria",
                    values="valor", aggfunc="sum",
                ).fillna(0).sort_index()

                fig_temporal = go.Figure()
                for i, col in enumerate(pivot.columns):
                    fig_temporal.add_trace(go.Bar(
                        name=col,
                        x=[_mes_label(m) for m in pivot.index],
                        y=pivot[col],
                        marker_color=PALETA[i % len(PALETA)],
                    ))
                fig_temporal.update_layout(**_layout_grafico(
                    altura=380,
                    margem=dict(t=25, b=40, l=20, r=20),
                    barmode="group",
                    showlegend=False,
                    xaxis=dict(fixedrange=True, gridcolor="#E2E8F0"),
                    yaxis=dict(fixedrange=True, gridcolor="#E2E8F0", tickformat=",.0f"),
                ))
                st.plotly_chart(fig_temporal, use_container_width=True, config=CONFIG_PLOTLY)
                _render_legenda([
                    (col, PALETA[i % len(PALETA)])
                    for i, col in enumerate(pivot.columns)
                ])

    with tab_receitas:
        entradas = ref[ref["tipo_norm"] == "ENTRADA"]
        resumo = entradas.groupby("categoria", as_index=False)["valor"].sum().sort_values("valor", ascending=False)
        resumo = resumo.rename(columns={"categoria": "Categoria", "valor": "Valor"})
        _secao_dashboard(
            "Distribuicao das receitas",
            "Participacao de cada categoria no total de entradas do periodo selecionado.",
        )
        if resumo.empty:
            st.info("Nao ha receitas no periodo selecionado.")
        else:
            _grafico_rosca(resumo, "Categoria", "Valor", PALETA, "Receitas")
            _secao_dashboard(
                "Ranking de receitas",
                "Categorias ordenadas pelo valor recebido no mes.",
            )
            st.plotly_chart(
                _grafico_ranking(resumo, "Categoria", "Valor", CORES["entrada"]),
                use_container_width=True,
                config=CONFIG_PLOTLY,
            )

    with tab_pastoral:
        if dashboard_restrito:
            st.warning("Area nao disponivel para o perfil Pastor Auxiliar.")
            return
        st.warning(
            "Area restrita. Exibe dados individuais de contribuicao. "
            "Acesse somente quando necessario e nao compartilhe exportacoes sem autorizacao."
        )
        if _autorizacao_pastoral(slug):
            # ═══ Saude financeira (transferido da antiga aba Saude Financeira) ═══
            _secao_dashboard(
                "Score de saude financeira",
                "Indice unico 0-100 combinando cobertura de reserva, saldo YTD, "
                "variacao de entradas, participacao dizimistas e qualidade dos dados.",
            )
            _render_score_saude(score)

            _secao_dashboard(
                "Metas de arrecadacao",
                "Progresso do periodo selecionado em relacao as metas mensais configuradas em Minha Conta.",
            )
            dias_periodo_metas = (fim_mes - inicio_mes).days + 1
            if dias_periodo_metas < 25 or dias_periodo_metas > 35:
                st.caption(
                    f"⚠️ O periodo selecionado tem {dias_periodo_metas} dia(s). "
                    "As metas cadastradas sao mensais; para comparacao mais precisa, "
                    "selecione um periodo de aproximadamente um mes."
                )
            _render_metas_arrecadacao(slug, ent, dizimo_mes)

            _render_saude_financeira(df, mes_ref, slug)

            _secao_dashboard(
                "Alerta de churn (dizimistas afastando-se)",
                "Membros que contribuiram nos ultimos 90 dias mas nao contribuiram "
                "no mes de referencia. Impacto financeiro estimado.",
            )
            churn_info = _identificar_churn(df, mes_ref, membros, dias_referencia=90)
            _render_churn_alerta(churn_info, slug, igreja, mes_ref)

            _secao_dashboard(
                "Previsao (proximos 3 meses)",
                "Estimativa via regressao linear dos ultimos 12 meses. "
                "Use como orientacao complementar.",
            )
            _render_previsao(df, mes_ref)

            # ═══ Qualidade dos dados (transferido da antiga aba Qualidade) ═══
            _secao_dashboard(
                "Qualidade dos dados",
                "Pendencias que precisam ser corrigidas para manter os indicadores confiaveis.",
            )
            q1, q2, q3, q4 = st.columns(4)
            q1.metric("Datas invalidas", qualidade["datas_invalidas"])
            q2.metric("Valores invalidos", qualidade["valores_invalidos"])
            q3.metric("Sem vinculo", qualidade["sem_vinculo"])
            q4.metric("Despesas sem subcategoria", qualidade["despesas_sem_subcategoria"])
            pendencias = pd.DataFrame({
                "Pendencia": [
                    "Datas invalidas",
                    "Valores invalidos",
                    "Valores nao positivos",
                    "Sem vinculo",
                    "Despesas sem subcategoria",
                ],
                "Quantidade": [
                    qualidade["datas_invalidas"],
                    qualidade["valores_invalidos"],
                    qualidade["valores_nao_positivos"],
                    qualidade["sem_vinculo"],
                    qualidade["despesas_sem_subcategoria"],
                ],
            })
            pendencias["Status"] = pendencias["Quantidade"].apply(
                lambda qtd: "Pendente" if qtd else "OK"
            )
            pendencias["Acao sugerida"] = [
                "Corrigir ou excluir lancamentos com data ausente/invalida.",
                "Corrigir valores que nao foram reconhecidos como numero.",
                "Revisar lancamentos com valor zerado ou negativo.",
                "Vincular lancamentos a membro ou fornecedor quando aplicavel.",
                "Classificar despesas em uma subcategoria.",
            ]
            if pendencias["Quantidade"].sum():
                fig_qualidade = go.Figure(go.Bar(
                    name="Pendencias",
                    x=pendencias["Quantidade"],
                    y=pendencias["Pendencia"],
                    orientation="h",
                    marker_color=CORES["alerta"],
                    text=pendencias["Quantidade"],
                    textposition="outside",
                    textfont=dict(size=11, color="#475569"),
                ))
                fig_qualidade.update_layout(**_layout_grafico(
                    altura=340,
                    showlegend=False,
                    xaxis=dict(fixedrange=True, showgrid=False, showticklabels=False),
                    yaxis=dict(fixedrange=True, showgrid=False),
                ))
                st.plotly_chart(fig_qualidade, use_container_width=True, config=CONFIG_PLOTLY)
            else:
                st.success("Nenhuma pendencia identificada nos dados.")
            st.caption("Registros invalidos sao excluidos dos KPIs ate serem corrigidos.")

            st.divider()

            dias_ativo = DIAS_DIZIMISTA_ATIVO_DEFAULT
            try:
                dias_ativo = int(obter_config_igreja(slug, "dias_dizimista_ativo", str(dias_ativo)))
            except (TypeError, ValueError):
                pass

            dizimos = df[(df["tipo_norm"] == "ENTRADA") & (df["categoria_norm"] == "DIZIMO")]
            inicio_padrao = max(df["data"].min().date(), (mes_ref - 11).start_time.date())
            fim_padrao = min(df["data"].max().date(), mes_ref.end_time.date())
            f1, f2 = st.columns(2)
            with f1:
                inicio_pastoral = st.date_input(
                    "Analisar contribuicoes de",
                    value=inicio_padrao,
                    format="DD/MM/YYYY",
                    key=_sk("pastoral_inicio", slug),
                )
            with f2:
                fim_pastoral = st.date_input(
                    "Ate",
                    value=fim_padrao,
                    format="DD/MM/YYYY",
                    key=_sk("pastoral_fim", slug),
                )
            if inicio_pastoral > fim_pastoral:
                st.error("A data inicial nao pode ser posterior a data final.")
                inicio_pastoral = fim_pastoral

            df_pastoral = _periodo(df, inicio_pastoral, fim_pastoral)
            dizimos_periodo = df_pastoral[
                (df_pastoral["tipo_norm"] == "ENTRADA")
                & (df_pastoral["categoria_norm"] == "DIZIMO")
            ]

            _secao_dashboard(
                "Evolucao dos dizimos",
                "Total arrecadado mes a mes no periodo analisado, com linha de tendencia.",
            )
            mes_fim_pastoral = pd.Period(fim_pastoral, freq="M")
            mes_inicio_pastoral = pd.Period(inicio_pastoral, freq="M")
            qtd_meses_pastoral = max(1, (mes_fim_pastoral - mes_inicio_pastoral).n + 1)
            serie_dizimos = _serie_mensal(
                dizimos_periodo,
                mes_fim_pastoral,
                quantidade=qtd_meses_pastoral,
            )
            valores_dizimos = serie_dizimos["entradas"].tolist()
            if not any(valor > 0 for valor in valores_dizimos):
                st.info("Ainda nao ha dizimos registrados para exibir a evolucao mensal.")
            else:
                fig_dizimos = go.Figure(go.Bar(
                    name="Dizimos",
                    x=serie_dizimos["rotulo"],
                    y=valores_dizimos,
                    marker_color=CORES["dizimo"],
                    text=[formatar_moeda(v) if v else "" for v in valores_dizimos],
                    textposition="outside",
                    textfont=dict(size=10, color="#475569"),
                ))
                tem_tendencia = sum(1 for valor in valores_dizimos if valor > 0) >= 3
                if tem_tendencia:
                    tendencia = pd.Series(valores_dizimos).rolling(3, min_periods=1).mean()
                    fig_dizimos.add_trace(go.Scatter(
                        x=serie_dizimos["rotulo"],
                        y=tendencia,
                        mode="lines",
                        line=dict(color="#475569", width=2, dash="dot"),
                        name="Tendencia",
                    ))
                fig_dizimos.update_layout(**_layout_grafico(
                    altura=380,
                    margem=dict(t=25, b=40, l=20, r=20),
                    showlegend=False,
                    xaxis=dict(fixedrange=True, gridcolor="#E2E8F0"),
                    yaxis=dict(fixedrange=True, gridcolor="#E2E8F0", tickformat=",.0f"),
                ))
                st.plotly_chart(fig_dizimos, use_container_width=True, config=CONFIG_PLOTLY)
                legenda_dizimos = [("Dizimos", CORES["dizimo"])]
                if tem_tendencia:
                    legenda_dizimos.append(("Tendencia (media movel 3 meses)", "#475569"))
                _render_legenda(legenda_dizimos)

            _secao_dashboard(
                "Dizimos por membro - top 8",
                "Membros com os maiores valores registrados no periodo analisado.",
            )
            dizimos_membros = dizimos_periodo[dizimos_periodo["id_cadastro"].notna()].merge(
                membros[["id_cadastro", "nome"]],
                on="id_cadastro",
                how="inner",
            )
            ranking_membros = (
                dizimos_membros.groupby("nome", as_index=False)["valor"].sum()
                .sort_values("valor", ascending=False)
                .head(8)
                .sort_values("valor")
            )
            if ranking_membros.empty:
                st.info("Sem dizimos vinculados a membros no periodo.")
            else:
                fig_ranking = go.Figure(go.Bar(
                    x=ranking_membros["valor"],
                    y=ranking_membros["nome"],
                    orientation="h",
                    marker_color=CORES["dizimo"],
                    text=[formatar_moeda(valor) for valor in ranking_membros["valor"]],
                    textposition="outside",
                    textfont=dict(size=10, color="#475569"),
                ))
                fig_ranking.update_layout(**_layout_grafico(
                    altura=max(280, len(ranking_membros) * 40 + 80),
                    xaxis=dict(fixedrange=True, showgrid=False, showticklabels=False),
                    yaxis=dict(fixedrange=True, showgrid=False),
                ))
                st.plotly_chart(fig_ranking, use_container_width=True, config=CONFIG_PLOTLY)

            _secao_dashboard(
                "Entradas de membros por funcao",
                "Valores recebidos agrupados pela funcao cadastrada dos membros.",
            )
            entradas_membros = df_pastoral[
                (df_pastoral["tipo_norm"] == "ENTRADA")
                & (df_pastoral["tipo_cadastro"].str.upper() == "MEMBRO")
                & df_pastoral["id_cadastro"].notna()
            ].merge(
                membros[["id_cadastro", "funcao"]],
                on="id_cadastro",
                how="inner",
            )
            entradas_membros["funcao"] = _texto(entradas_membros["funcao"]).replace("", "Sem funcao")
            resumo_funcoes = (
                entradas_membros.groupby("funcao", as_index=False)["valor"].sum()
                .sort_values("valor", ascending=False)
            )
            if resumo_funcoes.empty:
                st.info("Sem entradas vinculadas a membros no periodo.")
            else:
                fig_funcoes = go.Figure(go.Bar(
                    x=resumo_funcoes["funcao"],
                    y=resumo_funcoes["valor"],
                    marker_color=CORES["funcao"],
                    text=[formatar_moeda(valor) for valor in resumo_funcoes["valor"]],
                    textposition="outside",
                    textfont=dict(size=10, color="#475569"),
                ))
                fig_funcoes.update_layout(**_layout_grafico(
                    altura=320,
                    xaxis=dict(fixedrange=True, showgrid=False),
                    yaxis=dict(fixedrange=True, showgrid=False, showticklabels=False),
                ))
                st.plotly_chart(fig_funcoes, use_container_width=True, config=CONFIG_PLOTLY)

            # ═══ NOVO: Curva ABC (Pareto) de dizimistas ═══
            _secao_dashboard(
                "Curva ABC de dizimistas (Pareto)",
                "Classificacao de dizimistas por concentracao de arrecadacao. "
                "Ajuda a identificar dependencia de poucos contribuintes.",
            )
            abc_info = _curva_abc_dizimistas(dizimos_periodo, membros)
            _render_curva_abc(abc_info)

            # ═══ NOVO: Botoes de acao rapida ═══
            _secao_dashboard(
                "Acoes rapidas via WhatsApp",
                "Envio de mensagens padronizadas de agradecimento aos principais dizimistas.",
            )
            _render_botoes_acao_rapida(abc_info, membros, igreja, mes_ref, slug)

            # ═══ NOVO: Cruzamento com Monitoramento Geo ═══
            _secao_dashboard(
                "Cruzamento com Monitoramento Geo (frequencia x contribuicao)",
                "Cruza dados de presenca no Monitoramento Geo com contribuicoes de dizimo. "
                "Ajuda a identificar padroes de engajamento.",
            )
            df_cruzamento = _cruzar_com_frequencia_geo(
                slug, membros, dizimos_periodo, inicio_pastoral, fim_pastoral,
            )
            _render_cruzamento_geo(df_cruzamento)

            _secao_dashboard(
                "Membros que requerem acompanhamento",
                f"Criterio configurado: dizimista ativo quando contribuiu nos ultimos {dias_ativo} dias.",
            )
            resumo_atencao = _resumo_acompanhamento(
                membros, dizimos, datetime.date.today(), dias_ativo
            )
            classes = ["amarelo", "laranja", "vermelho"]
            colunas_atencao = st.columns(len(resumo_atencao))
            for coluna, dados, classe in zip(colunas_atencao, resumo_atencao, classes):
                with coluna:
                    _cartao_atencao(
                        f"Mais de {dados['limite']} dias",
                        dados["quantidade"],
                        dados["percentual"],
                        classe,
                    )

            faixas = _faixas_acompanhamento(membros, dizimos, datetime.date.today(), dias_ativo)
            st.caption(
                "Os cartoes sao cumulativos. As listas abaixo sao exclusivas para evitar "
                "duplicidade. A interpretacao e a eventual abordagem dependem de avaliacao humana."
            )
            for titulo, registros in faixas.items():
                with st.expander(f"{titulo}: {len(registros)} membro(s)"):
                    tabela = pd.DataFrame(registros)
                    if tabela.empty:
                        st.info("Nenhum registro nesta faixa.")
                    else:
                        st.download_button(
                            f"Exportar {titulo.lower()}",
                            gerar_csv(tabela),
                            f"acompanhamento_{titulo.lower().replace(' ', '_')}.csv",
                            "text/csv",
                            key=_sk(f"csv_{titulo}", slug),
                        )

            _secao_dashboard(
                "Participacao dos dizimistas",
                "Membros ativos que registraram ao menos uma contribuicao no periodo analisado.",
            )
            qtd_periodo, total_membros, percentual_periodo = _participacao_dizimistas(df_pastoral, membros)
            nao_dizimistas = max(total_membros - qtd_periodo, 0)
            if total_membros:
                fig_participacao = go.Figure(go.Pie(
                    name="Participacao",
                    labels=["Dizimistas", "Sem contribuicao no periodo"],
                    values=[qtd_periodo, nao_dizimistas],
                    hole=.7,
                    textinfo="none",
                    marker=dict(colors=[CORES["entrada"], "#E2E8F0"], line=dict(color="#FFFFFF", width=2)),
                ))
                fig_participacao.add_annotation(
                    text=f"<b>{percentual_periodo:.1f}%</b><br><span style='font-size:12px'>dizimistas</span>",
                    x=.5,
                    y=.5,
                    showarrow=False,
                    font=dict(size=25, color="#10213A"),
                )
                fig_participacao.update_layout(**_layout_grafico(
                    altura=330,
                    margem=dict(t=25, b=25, l=35, r=35),
                    showlegend=False,
                ))
                st.plotly_chart(fig_participacao, use_container_width=True, config=CONFIG_PLOTLY)
                _render_legenda([
                    ("Dizimistas", CORES["entrada"]),
                    ("Sem contribuicao no periodo", "#374151"),
                ])
                p1, p2, p3 = st.columns(3)
                p1.metric("Membros ativos", total_membros)
                p2.metric("Dizimistas no periodo", qtd_periodo)
                p3.metric("Sem contribuicao no periodo", nao_dizimistas)
            else:
                st.info("Nao ha membros ativos cadastrados.")

            _secao_dashboard(
                "Frequencia de contribuicoes",
                "Quantidade de registros por membro no periodo analisado. O grafico exibe somente quem contribuiu.",
            )
            frequencia = _frequencia_membros(membros, dizimos_periodo)
            if frequencia.empty:
                st.info("Nao ha membros ativos para exibir.")
            else:
                grafico_freq = frequencia[frequencia["Contribuicoes"] > 0].sort_values(
                    ["Contribuicoes", "Nome"],
                    ascending=[True, False],
                )
                if grafico_freq.empty:
                    st.info("Nenhum membro registrou contribuicao no periodo analisado.")
                else:
                    fig_freq = go.Figure(go.Bar(
                        x=grafico_freq["Contribuicoes"],
                        y=grafico_freq["Nome"],
                        orientation="h",
                        marker_color=CORES["entrada"],
                        text=[str(quantidade) for quantidade in grafico_freq["Contribuicoes"]],
                        textposition="outside",
                        textfont=dict(size=10, color="#475569"),
                    ))
                    fig_freq.update_layout(**_layout_grafico(
                        altura=max(340, len(grafico_freq) * 30 + 100),
                        xaxis=dict(fixedrange=True, showgrid=False, showticklabels=False),
                        yaxis=dict(fixedrange=True, showgrid=False),
                    ))
                    st.plotly_chart(fig_freq, use_container_width=True, config=CONFIG_PLOTLY)
                freq_exportacao = frequencia.copy()
                freq_exportacao["Valor total"] = freq_exportacao["Valor total"].apply(formatar_moeda)
                st.download_button(
                    "Exportar lista completa de frequencia",
                    gerar_csv(freq_exportacao),
                    "frequencia_dizimos_periodo.csv",
                    "text/csv",
                    key=_sk("csv_frequencia", slug),
                )

            _secao_dashboard(
                "Consulta individual",
                "Historico do membro selecionado e distribuicao mensal das contribuicoes.",
            )
            opcoes = {
                f"{int(row['id_cadastro'])} | {row['nome']}": int(row["id_cadastro"])
                for _, row in membros.sort_values("nome").iterrows()
            }
            if opcoes:
                selecionado = st.selectbox("Consultar membro", ["Selecione"] + list(opcoes), key=_sk("membro", slug))
                if selecionado != "Selecione":
                    id_membro = opcoes[selecionado]
                    dados = dizimos_periodo[dizimos_periodo["id_cadastro"] == id_membro].copy()
                    ultimos_dados = dados.sort_values("data", ascending=False)
                    ultima_data = (
                        ultimos_dados.iloc[0]["data"].strftime("%d/%m/%Y")
                        if not ultimos_dados.empty else "Sem registro"
                    )
                    meses_individual = _meses_periodo(inicio_pastoral, fim_pastoral)
                    resumo_individual = _resumo_individual_mensal(dados, meses_individual)
                    meses_com_dizimo = sum(
                        1 for mes in resumo_individual if mes["quantidade"] > 0
                    )
                    fidelidade = (
                        meses_com_dizimo / len(meses_individual) * 100
                        if meses_individual else 0.0
                    )
                    i1, i2, i3, i4 = st.columns(4)
                    i1.metric("Contribuicoes registradas", len(dados))
                    i2.metric("Valor total registrado", formatar_moeda(dados["valor"].sum()))
                    i3.metric("Ultima contribuicao", ultima_data)
                    i4.metric("Fidelidade mensal", f"{fidelidade:.1f}%")
                    if dados.empty:
                        st.info("Nao ha contribuicoes registradas no periodo analisado.")
                    else:
                        mensal = (
                            dados.groupby("mes_periodo", as_index=False)["valor"].sum()
                            .sort_values("mes_periodo")
                        )
                        fig_membro = go.Figure(go.Bar(
                            x=[_mes_label(periodo) for periodo in mensal["mes_periodo"]],
                            y=mensal["valor"],
                            marker_color=CORES["dizimo"],
                            text=[formatar_moeda(valor) for valor in mensal["valor"]],
                            textposition="outside",
                            textfont=dict(size=10, color="#475569"),
                        ))
                        fig_membro.update_layout(**_layout_grafico(
                            altura=320,
                            xaxis=dict(fixedrange=True, gridcolor="#E2E8F0"),
                            yaxis=dict(fixedrange=True, gridcolor="#E2E8F0", tickformat=",.0f"),
                        ))
                        st.plotly_chart(fig_membro, use_container_width=True, config=CONFIG_PLOTLY)
                    st.caption("Presenca mensal das contribuicoes no periodo analisado")
                    _cartoes_fidelidade(resumo_individual)
                    _mensagem_fidelidade(selecionado.split(" | ", 1)[-1], resumo_individual)

    st.divider()
    st.download_button(
        "Exportar dados do periodo",
        gerar_csv(ref),
        f"dashboard_{inicio_mes:%Y%m%d}_{fim_mes:%Y%m%d}.csv",
        "text/csv",
        key=_sk("csv_mes", slug),
    )