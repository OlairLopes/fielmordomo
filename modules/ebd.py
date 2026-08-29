import logging
import base64
import datetime
import html
import json
import re
import urllib.parse
from collections import defaultdict

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import streamlit as st
import streamlit.components.v1 as components

from data.repository import (
    carregar_cadastros,
    encerrar_ebd_matricula,
    excluir_ebd_classe,
    excluir_ebd_escala,
    excluir_ebd_escala_lote,
    inativar_ebd_secretario,
    listar_ebd_aulas,
    listar_ebd_classes,
    listar_ebd_escala,
    listar_ebd_matriculas,
    listar_ebd_professores_classe,
    listar_ebd_secretarios,
    relatorio_ebd_frequencia,
    relatorio_ebd_resumo_classes,
    obter_config_igreja,
    obter_logo_igreja,
    obter_logo_sistema,
    salvar_config_igreja,
    salvar_ebd_chamada,
    salvar_ebd_classe,
    salvar_ebd_escala,
    salvar_ebd_matricula,
    salvar_ebd_professor_classe,
    salvar_ebd_secretario,
    excluir_ebd_professor_classe,
)
from modules.aniversariantes import (
    _enviar_whatsapp_texto_api,
    _renderizar_resultados_envio,
    _whatsapp_api_configurada,
)
from utils.helpers import confirmar_exclusao, gerar_csv, slug_da_sessao


CORES = {
    "verde": "#1D9E75",
    "azul": "#0F3D5E",
    "laranja": "#F59E0B",
    "vermelho": "#DC2626",
    "cinza": "#64748B",
}
CONFIG_PLOTLY = {"displayModeBar": False, "responsive": True}
CHAVE_CORES_CLASSES_EBD = "ebd_cores_classes"
PALETA_CORES_CLASSES = [
    "#0F3D5E", "#DB2777", "#F59E0B", "#1D9E75", "#7C3AED",
    "#0EA5E9", "#B45309", "#DC2626", "#0891B2", "#64748B",
]
MENSAGEM_ESCALA_PADRAO = """Paz do Senhor, {nome}!

Voce esta escalado(a) para servir na Escola Bíblica.
Data: {data}
Classe: {classe}
Funcao: {funcao}
Tema: {tema}

Contamos com sua presenca e dedicacao. Deus abencoe!"""

MIMES_LOGO = {
    "png": "image/png",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "webp": "image/webp",
}


def _logo_html_cabecalho(igreja):
    slug = str((igreja or {}).get("slug") or "").strip()
    logo_dados = (obter_logo_igreja(slug) if slug else None) or obter_logo_sistema()
    if not logo_dados:
        return ""
    dados, ext = logo_dados
    mime = MIMES_LOGO.get(str(ext or "").strip().lower().replace(".", ""))
    if not mime or not isinstance(dados, (bytes, bytearray, memoryview)):
        return ""
    src = "data:" + mime + ";base64," + base64.b64encode(dados).decode()
    return f'<img class="logo" src="{html.escape(src, quote=True)}" alt="Logo"/>'


TZ_BRASILIA = datetime.timezone(datetime.timedelta(hours=-3))


def _agora_brasil():
    return datetime.datetime.now(TZ_BRASILIA)


def _hoje():
    return datetime.date.today()


def _inicio_mes():
    hoje = _hoje()
    return hoje.replace(day=1)


def _fmt_data(valor):
    try:
        data = _parse_data(valor)
        return data.strftime("%d/%m/%Y") if data else str(valor or "")
    except Exception:
        return str(valor or "")


def _parse_data(valor):
    if valor is None:
        return None
    if isinstance(valor, datetime.datetime):
        return valor.date()
    if isinstance(valor, datetime.date):
        return valor

    try:
        data = pd.to_datetime(valor, errors="coerce")
        if pd.notna(data):
            return data.date()
    except Exception:
        logging.exception("Erro ignorado silenciosamente")

    texto = str(valor or "").strip()
    if not texto:
        return None
    for formato in ("%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.datetime.strptime(texto, formato).date()
        except Exception:
            logging.exception("Erro ignorado silenciosamente")
    return None


def _data_iso(valor):
    try:
        data = _parse_data(valor)
        return data.isoformat() if data else ""
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
    if "ativa" not in dados.columns:
        dados["ativa"] = 1
    inicio = dados["data_inicio"].apply(_data_iso)
    fim = dados["data_fim"].apply(_data_iso)
    ativa = dados["ativa"].apply(lambda v: _int_seguro(v, 1) == 1)

    validas = (
        (inicio.eq("") | (inicio <= data_ref))
        & (fim.eq("") | (fim >= data_ref))
        & (fim.ne("") | ativa)
    )
    return dados[validas].copy()


def _diagnostico_matriculas_na_data(matriculas, data_referencia):
    if matriculas.empty:
        return pd.DataFrame()

    data_ref = _data_iso(data_referencia)
    dados = matriculas.copy()

    for col in ["data_inicio", "data_fim", "ativa"]:
        if col not in dados.columns:
            dados[col] = "" if col != "ativa" else 1

    def situacao(row):
        inicio = _data_iso(row.get("data_inicio"))
        fim = _data_iso(row.get("data_fim"))
        ativa = _int_seguro(row.get("ativa"), 1) == 1

        if data_ref and inicio and inicio > data_ref:
            return "Inicia após esta data"
        if data_ref and fim and fim < data_ref:
            return "Encerrada antes desta data"
        if not ativa and not fim:
            return "Inativa"
        return "Ativa na data"

    dados["Situação na data"] = dados.apply(situacao, axis=1)
    dados["Início"] = dados["data_inicio"].apply(_fmt_data)
    dados["Encerramento"] = dados["data_fim"].apply(lambda v: _fmt_data(v) if str(v or "").strip() else "")

    colunas = ["nome_aluno", "Situação na data", "Início", "Encerramento"]
    if "classe" in dados.columns:
        colunas.insert(1, "classe")

    return dados[colunas].rename(columns={
        "nome_aluno": "Aluno",
        "classe": "Classe",
    })


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


def _int_seguro(valor, padrao=0):
    try:
        if pd.isna(valor):
            return int(padrao)
    except Exception:
        logging.exception("Erro ignorado silenciosamente")
    try:
        texto = str(valor).strip()
        if not texto:
            return int(padrao)
        return int(float(texto.replace(",", ".")))
    except Exception:
        return int(padrao)


def _float_seguro(valor, padrao=0.0):
    try:
        if pd.isna(valor):
            return float(padrao)
    except Exception:
        logging.exception("Erro ignorado silenciosamente")
    try:
        texto = str(valor).strip()
        if not texto:
            return float(padrao)
        return float(texto.replace(".", "").replace(",", ".") if "," in texto else texto)
    except Exception:
        return float(padrao)


def _render_cards_superintendentes(slug):
    escala = listar_ebd_escala(slug)
    if escala.empty or "superintendente" not in escala.columns:
        return

    dados = escala.copy()
    dados["superintendente"] = dados["superintendente"].fillna("").astype(str).str.strip()
    dados = dados[dados["superintendente"] != ""].copy()
    if dados.empty:
        return

    if "data" in dados.columns:
        dados["_data_ordem"] = pd.to_datetime(dados["data"], errors="coerce")
        dados = dados.sort_values("_data_ordem", ascending=False)

    cards = []
    vistos = set()
    for _, row in dados.iterrows():
        nome = str(row.get("superintendente", "") or "").strip()
        chave = nome.lower()
        if not nome or chave in vistos:
            continue
        vistos.add(chave)
        telefone = str(row.get("telefone_superintendente", "") or "").strip()
        cards.append(
            '<div class="ebd-super-card">'
            '<span class="ebd-super-label">Superintendente</span>'
            f'<b>{html.escape(nome)}</b>'
            '<small>Escola Bíblica</small>'
            f'<small>{html.escape(telefone)}</small>'
            '</div>'
        )
        if len(cards) >= 4:
            break

    if not cards:
        return

    st.markdown(
        """
        <style>
        .ebd-super-grid {
            display: grid;
            grid-template-columns: repeat(4, minmax(0, 1fr));
            gap: 12px;
            margin: 18px 0 22px 0;
        }
        .ebd-super-card {
            border: 1px solid #E2E8F0;
            border-radius: 12px;
            padding: 18px 20px;
            background: #FFFFFF;
            box-shadow: 0 10px 24px rgba(15, 23, 42, 0.06);
            min-height: 104px;
        }
        .ebd-super-card b {
            display: block;
            color: #0F172A;
            font-size: 1.05rem;
            font-weight: 800;
            margin-bottom: 8px;
        }
        .ebd-super-card small {
            display: block;
            color: #64748B;
            font-size: 0.82rem;
            line-height: 1.45;
        }
        .ebd-super-label {
            display: block;
            color: #DC2626;
            font-size: 0.76rem;
            font-weight: 800;
            letter-spacing: 0.02em;
            margin-bottom: 8px;
            text-transform: uppercase;
        }
        @media(max-width: 1100px) {
            .ebd-super-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
        }
        @media(max-width: 620px) {
            .ebd-super-grid { grid-template-columns: 1fr; }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )
    st.markdown(
        f'<div class="ebd-super-grid">{"".join(cards)}</div>',
        unsafe_allow_html=True,
    )


def _limpar_tel(tel):
    return "".join(c for c in str(tel or "") if c.isdigit())


def _normalizar_tel_brasil(tel):
    tel_limpo = _limpar_tel(tel)
    if not tel_limpo:
        return ""
    while tel_limpo.startswith("0"):
        tel_limpo = tel_limpo[1:]
    if len(tel_limpo) in (10, 11):
        tel_limpo = "55" + tel_limpo
    return tel_limpo if len(tel_limpo) in (12, 13) and tel_limpo.startswith("55") else ""


def _link_whatsapp(tel, mensagem):
    numero = _normalizar_tel_brasil(tel)
    if not numero:
        return ""
    return f"https://wa.me/{numero}?text={urllib.parse.quote(mensagem)}"


def _mensagem_escala(slug, row, nome, funcao):
    data = _fmt_data(row.get("data", ""))
    classe = str(row.get("classe", "") or "Escola Bíblica").strip()
    tema = str(row.get("tema", "") or "").strip()
    modelo = obter_config_igreja(slug, "mensagem_whatsapp_escala_ebd", MENSAGEM_ESCALA_PADRAO)
    dados = defaultdict(
        str,
        nome=nome,
        data=data,
        classe=classe,
        funcao=funcao,
        tema=tema or "A definir",
    )
    return str(modelo or MENSAGEM_ESCALA_PADRAO).format_map(dados)


def _botao_whatsapp(label, telefone, mensagem, key):
    link = _link_whatsapp(telefone, mensagem)
    if not link:
        st.caption(f"{label}: informe um WhatsApp valido para gerar o aviso.")
        return
    st.markdown(
        f'<a href="{html.escape(link, quote=True)}" target="_blank" '
        'style="display:inline-block;padding:0.55rem 0.85rem;border-radius:10px;'
        'background:#1D9E75;color:white;text-decoration:none;font-weight:700;'
        'box-shadow:0 8px 18px rgba(29,158,117,.25)">'
        f'{html.escape(label)}</a>',
        unsafe_allow_html=True,
    )


def _pessoas_avisos_escala(slug, escala_avisos):
    pessoas = []
    for _, row in escala_avisos.iterrows():
        for funcao, campo_nome, campo_telefone in (
            ("Professor", "professor", "telefone_professor"),
            ("Superintendente", "superintendente", "telefone_superintendente"),
            ("Auxiliar", "auxiliar", "telefone_auxiliar"),
        ):
            nome = str(row.get(campo_nome, "") or "").strip()
            if not nome:
                continue
            pessoas.append({
                "id_escala": row.get("id_escala"),
                "data": _fmt_data(row.get("data", "")),
                "classe": str(row.get("classe", "") or "Escola Bíblica").strip(),
                "funcao": funcao,
                "nome": nome,
                "telefone": row.get(campo_telefone, ""),
                "mensagem": _mensagem_escala(slug, row, nome, funcao),
            })
    return pessoas


def _executar_envio_avisos_escala(pessoas):
    resultados = []
    for pessoa in pessoas:
        telefone_normalizado = _normalizar_tel_brasil(pessoa["telefone"])
        if not telefone_normalizado:
            resultados.append({
                "nome": pessoa["nome"],
                "funcao": pessoa["funcao"],
                "telefone": pessoa["telefone"],
                "status": "ignorado",
                "detalhe": "Telefone invalido ou vazio.",
            })
            continue
        ok, detalhe = _enviar_whatsapp_texto_api(pessoa["telefone"], pessoa["mensagem"])
        resultados.append({
            "nome": pessoa["nome"],
            "funcao": pessoa["funcao"],
            "telefone": telefone_normalizado,
            "status": "enviado" if ok else "erro",
            "detalhe": detalhe,
        })
    return resultados


def _metricas_ebd(resumo, aulas):
    alunos = int(resumo["alunos"].sum()) if not resumo.empty else 0
    classes = int(resumo["classe"].nunique()) if not resumo.empty else 0
    qtd_aulas = int(aulas["id_aula"].nunique()) if not aulas.empty else 0
    presencas = float(resumo["presencas"].sum()) if not resumo.empty else 0
    faltas = float(resumo["faltas"].sum()) if not resumo.empty else 0
    freq = (presencas / (presencas + faltas) * 100) if (presencas + faltas) else 0
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Classes acompanhadas", classes)
    c2.metric("Alunos no relatorio", alunos)
    c3.metric("Aulas registradas", qtd_aulas)
    c4.metric("Frequencia media", _pct(freq))


def _grafico_frequencia_classes(resumo, cores_classes=None, key=None):
    if resumo.empty:
        st.info("Sem dados de frequencia para o periodo selecionado.")
        return
    dados = resumo.sort_values("frequencia_pct", ascending=True)
    cores_classes = cores_classes or {}
    cores_barras = [cores_classes.get(classe, CORES["verde"]) for classe in dados["classe"]]
    fig = go.Figure(go.Bar(
        name="Frequencia",
        x=dados["frequencia_pct"],
        y=dados["classe"],
        orientation="h",
        marker_color=cores_barras,
        text=[_pct(v) for v in dados["frequencia_pct"]],
        textposition="outside",
        hovertemplate="<b>%{y}</b><br>Frequencia: %{x:.1f}%<extra></extra>",
    ))
    fig.update_layout(
        height=max(360, 70 * len(dados)),
        margin=dict(t=35, b=40, l=10, r=30),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(size=12),
        xaxis=dict(range=[0, 105], title="Frequencia (%)", fixedrange=True, automargin=True),
        yaxis=dict(title="", fixedrange=True, automargin=True),
        showlegend=True,
        legend=dict(orientation="h", y=1.12, x=0),
    )
    st.plotly_chart(fig, use_container_width=True, config=CONFIG_PLOTLY, key=key)


def _resumo_professores(aulas):
    colunas = [
        "professor", "classes", "aulas", "matriculados", "presentes", "ausentes",
        "frequencia_pct", "indice_desempenho",
    ]
    if aulas.empty:
        return pd.DataFrame(columns=colunas)
    dados = aulas.copy()
    dados["professor"] = dados["professor"].fillna("").astype(str).str.strip()
    dados = dados[dados["professor"] != ""]
    if dados.empty:
        return pd.DataFrame(columns=colunas)
    resumo = dados.groupby("professor", as_index=False).agg(
        classes=("classe", "nunique"),
        aulas=("id_aula", "nunique"),
        matriculados=("matriculados", "sum"),
        presentes=("presentes", "sum"),
        ausentes=("ausentes", "sum"),
    )
    total = resumo["matriculados"]
    resumo["frequencia_pct"] = (resumo["presentes"] / total.where(total > 0, 1) * 100).round(1)

    # Indice ponderado: pondera a frequencia pela quantidade de aulas ministradas
    # (media bayesiana), para que poucos registros nao distorcam o ranking.
    media_geral = (
        resumo["presentes"].sum() / total.sum() * 100 if total.sum() > 0 else 0
    )
    peso_confianca = max(float(resumo["aulas"].median()), 1.0)
    resumo["indice_desempenho"] = (
        (resumo["aulas"] / (resumo["aulas"] + peso_confianca)) * resumo["frequencia_pct"]
        + (peso_confianca / (resumo["aulas"] + peso_confianca)) * media_geral
    ).round(1)
    return resumo.sort_values("indice_desempenho", ascending=False)


def _grafico_desempenho_professores(dados):
    if dados.empty:
        st.info("Sem dados de professores para o periodo selecionado.")
        return
    ordenado = dados.sort_values("indice_desempenho", ascending=True)
    fig = go.Figure(go.Bar(
        name="Indice de desempenho",
        x=ordenado["indice_desempenho"],
        y=ordenado["professor"],
        orientation="h",
        marker_color=CORES["azul"],
        text=[_pct(v) for v in ordenado["indice_desempenho"]],
        textposition="outside",
        customdata=ordenado[["frequencia_pct", "aulas"]],
        hovertemplate=(
            "<b>%{y}</b><br>Indice de desempenho: %{x:.1f}%"
            "<br>Frequencia dos alunos: %{customdata[0]:.1f}%"
            "<br>Aulas ministradas: %{customdata[1]}<extra></extra>"
        ),
    ))
    fig.update_layout(
        height=max(360, 70 * len(ordenado)),
        margin=dict(t=35, b=40, l=10, r=30),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(size=12),
        xaxis=dict(range=[0, 105], title="Indice de desempenho (%)", fixedrange=True, automargin=True),
        yaxis=dict(title="", fixedrange=True, automargin=True),
        showlegend=True,
        legend=dict(orientation="h", y=1.12, x=0),
    )
    st.plotly_chart(fig, use_container_width=True, config=CONFIG_PLOTLY, key="ebd_grafico_desempenho_professores")


def _valor_grafico_ebd(indicador, valor):
    try:
        numero = float(valor)
    except Exception:
        return str(valor)
    inteiro = int(round(numero))
    if "Oferta" in str(indicador):
        return _moeda(numero)
    return str(inteiro)


def _dispositivo_movel():
    try:
        user_agent = str(st.context.headers.get("user-agent", "") or "")
    except Exception:
        user_agent = ""
    return bool(re.search(r"Mobi|Android|iPhone|iPad|iPod|Tablet", user_agent, re.IGNORECASE))


def _grafico_totais_ebd(titulo, dados, modo="Total", altura=None, key=None, responsivo_mobile=False):
    if not dados:
        st.info("Sem dados para gerar o grafico.")
        return
    df = pd.DataFrame(
        [{"Indicador": chave, modo: valor} for chave, valor in dados.items()]
    )
    df_ofertas = df[df["Indicador"] == "Ofertas"].copy()
    df_qtd = df[df["Indicador"] != "Ofertas"].copy()
    altura = altura or max(380, min(680, 80 * len(df) + 180))
    if responsivo_mobile and _dispositivo_movel():
        altura = round(altura * 0.5)
    fig = make_subplots(specs=[[{"secondary_y": True}]])

    if not df_qtd.empty:
        fig.add_trace(go.Bar(
            name=modo,
            x=df_qtd["Indicador"],
            y=df_qtd[modo],
            marker_color=[
                CORES["azul"], CORES["verde"], CORES["vermelho"], CORES["laranja"],
                "#0EA5E9", "#7C3AED", "#0891B2", "#B45309",
            ][:len(df_qtd)],
            text=[
                _valor_grafico_ebd(row["Indicador"], row[modo])
                for _, row in df_qtd.iterrows()
            ],
            textposition="outside",
            hovertemplate=f"<b>%{{x}}</b><br>{modo}: %{{text}}<extra></extra>",
        ), secondary_y=False)

    if not df_ofertas.empty:
        fig.add_trace(go.Bar(
            name="Ofertas",
            x=df_ofertas["Indicador"],
            y=df_ofertas[modo],
            marker_color="#DB2777",
            text=[
                _valor_grafico_ebd(row["Indicador"], row[modo])
                for _, row in df_ofertas.iterrows()
            ],
            textposition="outside",
            hovertemplate="<b>%{x}</b><br>Total: %{text}<extra></extra>",
        ), secondary_y=True)

    fig.update_layout(
        title=titulo,
        height=altura,
        autosize=True,
        margin=dict(t=60, b=80, l=25, r=25),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(size=12),
        uniformtext=dict(minsize=9, mode="hide"),
        xaxis=dict(fixedrange=True, automargin=True, tickangle=-20),
        yaxis=dict(title="Quantidades", fixedrange=True, gridcolor="#E2E8F0", automargin=True),
        yaxis2=dict(title="Ofertas (R$)", fixedrange=True, overlaying="y", side="right"),
        showlegend=False,
    )
    st.plotly_chart(
        fig,
        use_container_width=True,
        config=CONFIG_PLOTLY,
        key=key,
    )


def _carregar_cores_classes(slug):
    bruto = obter_config_igreja(slug, CHAVE_CORES_CLASSES_EBD, "")
    if not bruto:
        return {}
    try:
        dados = json.loads(bruto)
    except (ValueError, TypeError):
        return {}
    return dados if isinstance(dados, dict) else {}


def _salvar_cores_classes(slug, cores):
    salvar_config_igreja(slug, CHAVE_CORES_CLASSES_EBD, json.dumps(cores))


def _cor_classe(classe, indice, cores_salvas):
    return cores_salvas.get(classe) or PALETA_CORES_CLASSES[indice % len(PALETA_CORES_CLASSES)]


def _mapa_cores_classes(classes, cores_salvas):
    return {
        classe: _cor_classe(classe, indice, cores_salvas)
        for indice, classe in enumerate(classes)
    }


def _seletor_cores_classes(slug, classes):
    cores_salvas = _carregar_cores_classes(slug)
    cores_atuais = {}
    with st.expander("Personalizar cores das classes", expanded=False):
        colunas = st.columns(3)
        for indice, classe in enumerate(classes):
            cor_padrao = _cor_classe(classe, indice, cores_salvas)
            cor_escolhida = colunas[indice % 3].color_picker(
                classe, value=cor_padrao, key=f"ebd_cor_classe_{classe}"
            )
            cores_atuais[classe] = cor_escolhida
        if st.button("Salvar cores", key="ebd_salvar_cores_classes"):
            _salvar_cores_classes(slug, cores_atuais)
            st.success("Cores das classes salvas.")
            st.rerun()
    return cores_atuais


def _grafico_comparativo_classes_ebd(titulo, aulas, cores_classes=None, key=None):
    if aulas.empty:
        st.info("Sem dados para gerar o grafico.")
        return

    linhas = []
    for classe, grupo in aulas.groupby("classe", dropna=False):
        classe_nome = str(classe or "Sem classe")
        media = int(grupo["id_aula"].nunique()) > 1
        dados = _totais_aulas(grupo, media=media)
        for indicador, valor in dados.items():
            linhas.append({
                "Classe": classe_nome,
                "Indicador": indicador,
                "Valor": valor,
                "Texto": _valor_grafico_ebd(indicador, valor),
            })

    df = pd.DataFrame(linhas)
    if df.empty:
        st.info("Sem dados para gerar o grafico.")
        return

    altura = max(460, min(820, 72 * df["Indicador"].nunique() + 220))
    if _dispositivo_movel():
        altura = round(altura * 0.5)
    classes_unicas = df["Classe"].drop_duplicates().tolist()

    fig = make_subplots(specs=[[{"secondary_y": True}]])
    cores_classes = cores_classes or {}
    cores_por_classe = {}
    for idx, classe in enumerate(classes_unicas):
        cor_classe = cores_classes.get(classe) or PALETA_CORES_CLASSES[idx % len(PALETA_CORES_CLASSES)]
        cores_por_classe[classe] = cor_classe
        sub = df[(df["Classe"] == classe) & (df["Indicador"] != "Ofertas")]
        if not sub.empty:
            fig.add_trace(go.Bar(
                name=classe,
                x=sub["Indicador"],
                y=sub["Valor"],
                marker_color=cor_classe,
                text=sub["Texto"],
                textposition="outside",
                hovertemplate="<b>%{fullData.name}</b><br>%{x}: %{text}<extra></extra>",
            ), secondary_y=False)

        sub_ofertas = df[(df["Classe"] == classe) & (df["Indicador"] == "Ofertas")]
        if not sub_ofertas.empty:
            fig.add_trace(go.Bar(
                name=f"{classe} - Ofertas",
                x=sub_ofertas["Indicador"],
                y=sub_ofertas["Valor"],
                marker_color=cor_classe,
                text=sub_ofertas["Texto"],
                textposition="outside",
                hovertemplate="<b>%{fullData.name}</b><br>%{x}: %{text}<extra></extra>",
                showlegend=False,
            ), secondary_y=True)

    fig.update_layout(
        title=titulo,
        height=altura,
        autosize=True,
        barmode="group",
        margin=dict(t=60, b=90, l=25, r=25),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(size=12),
        uniformtext=dict(minsize=9, mode="hide"),
        xaxis=dict(title="", fixedrange=True, automargin=True, tickangle=-20),
        yaxis=dict(title="Quantidades", fixedrange=True, gridcolor="#E2E8F0", automargin=True),
        yaxis2=dict(title="Ofertas (R$)", fixedrange=True, overlaying="y", side="right"),
        showlegend=False,
    )
    st.plotly_chart(
        fig,
        use_container_width=True,
        config=CONFIG_PLOTLY,
        key=key or "ebd_grafico_comparativo_classes",
    )
    _legenda_classes_html(cores_por_classe)


def _legenda_classes_html(cores_por_classe):
    # Legenda em HTML/CSS (flex-wrap) no rodape do grafico: fica fora do
    # canvas do Plotly, entao nunca sobrepoe as barras, e se reorganiza
    # sozinha quando a tela e redimensionada ou girada (portrait/landscape).
    itens = "".join(
        f'<span style="display:inline-flex;align-items:center;gap:6px;'
        f'margin:4px 12px;">'
        f'<span style="width:12px;height:12px;border-radius:3px;'
        f'background:{html.escape(cor)};display:inline-block;flex:none;"></span>'
        f'<span style="font-size:13px;color:#334155;">{html.escape(str(classe))}</span>'
        f'</span>'
        for classe, cor in cores_por_classe.items()
    )
    st.markdown(
        f'<div style="display:flex;flex-wrap:wrap;justify-content:center;'
        f'background:#FFFFFF;border:1px solid #E2E8F0;border-radius:12px;'
        f'box-shadow:0 6px 16px rgba(15,23,42,0.08);'
        f'padding:8px 6px;margin:-10px 0 18px;">{itens}</div>',
        unsafe_allow_html=True,
    )


def _totais_aulas(aulas, media=False, por_semana=False):
    if aulas.empty:
        return {
            "Matriculados": 0,
            "Presentes": 0,
            "Ausentes": 0,
            "Visitantes": 0,
            "Assistentes": 0,
            "Biblias": 0,
            "Revistas": 0,
            "Harpas": 0,
            "Ofertas": 0.0,
        }
    if media:
        coluna_divisor = "data" if por_semana else "id_aula"
        divisor = int(aulas[coluna_divisor].nunique())
    else:
        divisor = 1
    divisor = max(divisor, 1)
    dados = {
        "Matriculados": float(aulas["matriculados"].fillna(0).sum()) / divisor,
        "Presentes": float(aulas["presentes"].fillna(0).sum()) / divisor,
        "Ausentes": float(aulas["ausentes"].fillna(0).sum()) / divisor,
        "Visitantes": float(aulas["visitantes"].fillna(0).sum()),
        "Assistentes": float(aulas["assistentes"].fillna(0).sum()) / divisor,
        "Biblias": float(aulas["qtd_biblias"].fillna(0).sum()) / divisor,
        "Revistas": float(aulas["qtd_revistas"].fillna(0).sum()) / divisor,
        "Harpas": float(aulas["qtd_harpas"].fillna(0).sum()) / divisor,
        "Ofertas": float(aulas["ofertas"].fillna(0).sum()),
    }
    for chave in list(dados.keys()):
        if chave != "Ofertas":
            dados[chave] = int(round(dados[chave]))
    return dados


def _classes_opcoes(df_classes):
    return {
        f'{int(row["id_classe"])} - {row["nome"]}': int(row["id_classe"])
        for _, row in df_classes.iterrows()
    }


def _limpar_estado_pessoa_escala(key_prefix, manter_origem=False):
    chaves = [
        f"{key_prefix}_membro",
        f"{key_prefix}_nome_manual",
        f"{key_prefix}_telefone_manual",
        f"{key_prefix}_funcao_manual",
    ]
    if not manter_origem:
        chaves.append(f"{key_prefix}_origem")
    for chave in chaves:
        st.session_state.pop(chave, None)


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


def _selecionar_pessoa_escala(
    slug, titulo, key_prefix, obrigatorio=False,
    nome_padrao="", telefone_padrao="", funcao_padrao="",
):
    op_membros, df_membros = _membros_opcoes(slug)
    nome_padrao = str(nome_padrao or "").strip()
    id_padrao = None
    if nome_padrao and op_membros:
        for label, id_cadastro in op_membros.items():
            if label.split(" - ", 1)[-1].strip().lower() == nome_padrao.lower():
                id_padrao = id_cadastro
                break
    index_origem = 1 if (nome_padrao and id_padrao is None) else 0
    origem = st.radio(
        titulo,
        ["Buscar no cadastro de membros", "Inserir manualmente"],
        horizontal=True,
        index=index_origem,
        key=f"{key_prefix}_origem",
    )
    chave_origem_anterior = f"{key_prefix}_origem_anterior"
    origem_anterior = st.session_state.get(chave_origem_anterior)
    if origem_anterior != origem:
        if origem == "Inserir manualmente":
            st.session_state[f"{key_prefix}_nome_manual"] = ""
            st.session_state[f"{key_prefix}_telefone_manual"] = ""
            st.session_state[f"{key_prefix}_funcao_manual"] = ""
        else:
            _limpar_estado_pessoa_escala(key_prefix, manter_origem=True)
        st.session_state[chave_origem_anterior] = origem
    if origem == "Buscar no cadastro de membros" and op_membros:
        if st.form_submit_button(
            f"Limpar {titulo.lower()}",
            key=f"{key_prefix}_limpar_busca",
            use_container_width=True,
        ):
            _limpar_estado_pessoa_escala(key_prefix)
            st.rerun()
        labels = list(op_membros.keys())
        index_membro = 0
        if id_padrao is not None:
            for i, label in enumerate(labels):
                if op_membros[label] == id_padrao:
                    index_membro = i
                    break
        membro_label = st.selectbox(
            f"{titulo} - membro",
            labels,
            index=index_membro,
            key=f"{key_prefix}_membro",
        )
        id_cadastro = op_membros[membro_label]
        row = df_membros[df_membros["id_cadastro"] == id_cadastro].iloc[0]
        nome = str(row.get("nome", "") or "")
        telefone = str(row.get("telefone", "") or "")
        funcao = str(row.get("funcao", "") or "")
        st.caption(f"Funcao preenchida pelo cadastro: {funcao or 'sem funcao informada'}")
        return nome, telefone, funcao
    if origem == "Buscar no cadastro de membros":
        st.warning("Nao ha membros ativos cadastrados. Use a insercao manual.")
    c1, c2 = st.columns(2)
    nome = c1.text_input(
        f"{titulo} - nome manual",
        value=nome_padrao,
        key=f"{key_prefix}_nome_manual",
    )
    telefone = c2.text_input(
        f"{titulo} - WhatsApp",
        value=str(telefone_padrao or ""),
        key=f"{key_prefix}_telefone_manual",
        placeholder="Opcional",
    )
    funcao = st.text_input(
        f"{titulo} - funcao",
        value=str(funcao_padrao or ""),
        key=f"{key_prefix}_funcao_manual",
        help="Preencha manualmente quando a pessoa nao estiver no cadastro.",
    )
    if st.form_submit_button(
        f"Limpar {titulo.lower()} digitado",
        key=f"{key_prefix}_limpar_manual",
        use_container_width=True,
    ):
        _limpar_estado_pessoa_escala(key_prefix, manter_origem=True)
        st.session_state[f"{key_prefix}_origem"] = "Inserir manualmente"
        st.session_state[chave_origem_anterior] = "Inserir manualmente"
        st.rerun()
    if obrigatorio and not nome.strip():
        st.caption("Informe o nome antes de salvar.")
    return nome, telefone, funcao


def _normalizar_coluna_importacao(texto):
    return (
        str(texto or "")
        .strip()
        .lower()
        .replace("ã", "a")
        .replace("á", "a")
        .replace("à", "a")
        .replace("â", "a")
        .replace("é", "e")
        .replace("ê", "e")
        .replace("í", "i")
        .replace("ó", "o")
        .replace("ô", "o")
        .replace("õ", "o")
        .replace("ú", "u")
        .replace("ç", "c")
    )


def _importar_escala_planilha(slug, arquivo, df_classes):
    try:
        nome_arquivo = str(getattr(arquivo, "name", "") or "").lower()
        if nome_arquivo.endswith(".csv"):
            planilha = pd.read_csv(arquivo)
        else:
            planilha = pd.read_excel(arquivo)
    except Exception as exc:
        st.error(f"Nao foi possivel ler a planilha: {exc}")
        return

    if planilha.empty:
        st.warning("A planilha enviada esta vazia.")
        return

    planilha = planilha.rename(columns={col: _normalizar_coluna_importacao(col) for col in planilha.columns})
    mapa_colunas = {
        "data": "data",
        "classe": "classe",
        "professor": "professor",
        "telefone professor": "telefone_professor",
        "telefone_professor": "telefone_professor",
        "funcao professor": "funcao_professor",
        "funcao_professor": "funcao_professor",
        "superintendente": "superintendente",
        "telefone superintendente": "telefone_superintendente",
        "telefone_superintendente": "telefone_superintendente",
        "auxiliar": "auxiliar",
        "telefone auxiliar": "telefone_auxiliar",
        "telefone_auxiliar": "telefone_auxiliar",
        "tema": "tema",
        "assunto": "tema",
        "observacoes": "observacoes",
        "observacao": "observacoes",
    }
    planilha = planilha.rename(columns={col: mapa_colunas.get(col, col) for col in planilha.columns})

    faltantes = [col for col in ("data", "professor") if col not in planilha.columns]
    if faltantes:
        st.error("A planilha precisa ter pelo menos as colunas: data e professor.")
        return

    if "classe" not in planilha.columns:
        planilha["classe"] = ""

    classes_por_nome = {}
    if not df_classes.empty:
        for _, row in df_classes.iterrows():
            nome = str(row.get("nome", "") or "").strip()
            if nome:
                classes_por_nome[_normalizar_coluna_importacao(nome)] = int(row["id_classe"])

    erros = []
    salvas = 0
    for idx, row in planilha.fillna("").iterrows():
        data_valor = _parse_data(row.get("data"))
        professor = str(row.get("professor", "") or "").strip()
        classe_texto = str(row.get("classe", "") or "").strip()
        id_classe = None
        classe_nome = ""

        if not data_valor:
            erros.append(f"Linha {idx + 2}: data invalida.")
            continue
        if not professor:
            erros.append(f"Linha {idx + 2}: professor obrigatorio.")
            continue

        if classe_texto:
            classe_normalizada = _normalizar_coluna_importacao(classe_texto)
            if classe_normalizada in ("sem classe definida", "sem classe", "geral"):
                classe_nome = "Sem classe definida"
            elif classe_normalizada in classes_por_nome:
                id_classe = classes_por_nome[classe_normalizada]
            else:
                erros.append(f"Linha {idx + 2}: classe '{classe_texto}' nao encontrada.")
                continue

        try:
            salvar_ebd_escala(
                slug,
                data_valor.isoformat(),
                professor,
                id_classe,
                classe_nome,
                str(row.get("auxiliar", "") or "").strip(),
                str(row.get("tema", "") or "").strip(),
                str(row.get("observacoes", "") or "").strip(),
                telefone_professor=str(row.get("telefone_professor", "") or "").strip(),
                funcao_professor=str(row.get("funcao_professor", "") or "").strip(),
                superintendente=str(row.get("superintendente", "") or "").strip(),
                telefone_superintendente=str(row.get("telefone_superintendente", "") or "").strip(),
                telefone_auxiliar=str(row.get("telefone_auxiliar", "") or "").strip(),
            )
            salvas += 1
        except Exception as exc:
            erros.append(f"Linha {idx + 2}: {exc}")

    if salvas:
        st.success(f"{salvas} escala(s) importada(s) com sucesso.")
    if erros:
        st.warning("Algumas linhas nao puderam ser importadas:")
        st.code("\n".join(erros))
    if salvas:
        st.rerun()


def _escala_da_aula(slug, data_aula, id_classe):
    escala = listar_ebd_escala(
        slug, data_aula.isoformat(), data_aula.isoformat(), id_classe
    )
    if escala.empty:
        return None
    escala_classe = escala[escala["id_classe"].fillna(0).astype(int) == int(id_classe)]
    if escala_classe.empty:
        return None
    return escala_classe.iloc[0].to_dict()


def _gerar_html_chamada_classe(igreja, nome_classe, data_aula, tema, professor, alunos):
    nome_igreja = html.escape(str((igreja or {}).get("nome") or (igreja or {}).get("slug") or "Igreja"))
    logo_html = _logo_html_cabecalho(igreja)
    data_fmt = _fmt_data(data_aula)
    emitido = _agora_brasil().strftime("%d/%m/%Y %H:%M")
    tema_html = html.escape(tema) if tema else "-"
    professor_html = html.escape(professor) if professor else "-"

    linhas = []
    for idx, (nome, presente) in enumerate(sorted(alunos, key=lambda item: item[0].lower()), start=1):
        if presente is None:
            marca_presente = '<span class="quadro"></span>'
            marca_falta = '<span class="quadro"></span>'
        else:
            marca_presente = '<span class="quadro marcado">X</span>' if presente else '<span class="quadro"></span>'
            marca_falta = '<span class="quadro marcado">X</span>' if not presente else '<span class="quadro"></span>'
        linhas.append(
            "<tr>"
            f'<td class="col-num">{idx}</td>'
            f'<td class="col-nome">{html.escape(nome)}</td>'
            f'<td class="col-marca">{marca_presente}</td>'
            f'<td class="col-marca">{marca_falta}</td>'
            '<td class="col-obs"></td>'
            "</tr>"
        )
    linhas_html = "".join(linhas) if linhas else '<tr><td colspan="5">Nenhum aluno matriculado.</td></tr>'

    return f"""
<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="UTF-8"/>
<title>Chamada - {html.escape(nome_classe)} - {data_fmt}</title>
<style>
* {{ box-sizing: border-box; }}
body {{ margin: 0; padding: 18px; background: #f3f4f6; color: #111827; font-family: Arial, Helvetica, sans-serif; }}
.toolbar {{ text-align: center; margin-bottom: 14px; }}
.toolbar button {{ background: #0F6E56; color: white; border: 0; border-radius: 8px; padding: 10px 22px; font-size: 14px; font-weight: 700; cursor: pointer; }}
.folha {{ width: 210mm; min-height: 297mm; margin: 0 auto; background: white; padding: 16mm; border: 1px solid #d1d5db; }}
.cabecalho {{ text-align: center; border-bottom: 2px solid #111827; padding-bottom: 10px; margin-bottom: 16px; }}
.cabecalho .logo {{ max-height: 64px; max-width: 200px; display: block; margin: 0 auto 8px; }}
.igreja {{ font-size: 18px; font-weight: 800; text-transform: uppercase; }}
.titulo {{ font-size: 15px; font-weight: 700; margin-top: 6px; }}
.emitido {{ font-size: 11px; color: #6b7280; margin-top: 4px; }}
.info {{ display: grid; grid-template-columns: repeat(2, 1fr); gap: 6px 16px; margin: 14px 0; font-size: 13px; }}
.info b {{ color: #374151; }}
table {{ width: 100%; border-collapse: collapse; margin-top: 10px; font-size: 12px; }}
th, td {{ border: 1px solid #d1d5db; padding: 6px 8px; text-align: left; }}
th {{ background: #f3f4f6; text-transform: uppercase; font-size: 10px; color: #374151; }}
.col-num {{ width: 30px; text-align: center; }}
.col-marca {{ width: 70px; text-align: center; }}
.col-obs {{ width: 120px; }}
.quadro {{ display: inline-block; width: 16px; height: 16px; border: 1px solid #111827; text-align: center; line-height: 16px; font-weight: 800; }}
.quadro.marcado {{ background: #d1fae5; }}
.rodape {{ margin-top: 30px; display: grid; grid-template-columns: repeat(2, 1fr); gap: 32px; font-size: 12px; }}
.assinatura {{ border-top: 1px solid #111827; text-align: center; padding-top: 6px; }}
@media print {{
    body {{ background: white; padding: 0; }}
    .toolbar {{ display: none !important; }}
    .folha {{ width: 100%; min-height: auto; margin: 0; border: 0; padding: 12mm; }}
}}
</style>
</head>
<body>
<div class="toolbar">
    <button onclick="window.print()">Imprimir chamada</button>
</div>
<main class="folha">
    <header class="cabecalho">
        {logo_html}
        <div class="igreja">{nome_igreja}</div>
        <div class="titulo">Lista de Chamada - Escola Bíblica</div>
        <div class="emitido">Emitido em {emitido}</div>
    </header>
    <div class="info">
        <div><b>Classe:</b> {html.escape(nome_classe)}</div>
        <div><b>Data:</b> {data_fmt}</div>
        <div><b>Professor:</b> {professor_html}</div>
        <div><b>Tema:</b> {tema_html}</div>
    </div>
    <table>
        <thead>
            <tr>
                <th class="col-num">#</th>
                <th>Aluno</th>
                <th class="col-marca">Presente</th>
                <th class="col-marca">Falta</th>
                <th class="col-obs">Observações</th>
            </tr>
        </thead>
        <tbody>
            {linhas_html}
        </tbody>
    </table>
    <div class="rodape">
        <div class="assinatura">Assinatura do professor</div>
        <div class="assinatura">Assinatura do secretário(a)</div>
    </div>
</main>
</body>
</html>"""


def _gerar_html_escala_professores(igreja, periodo_texto, classe_texto, escala, professor_texto="Todos"):
    logo_html = _logo_html_cabecalho(igreja)
    emitido = _agora_brasil().strftime("%d/%m/%Y %H:%M")

    dados = escala.copy()
    if "data" in dados.columns:
        dados["_data_ordem"] = pd.to_datetime(dados["data"], errors="coerce")
        dados = dados.sort_values("_data_ordem")

    linhas = []
    for _, row in dados.iterrows():
        linhas.append(
            "<tr>"
            f"<td>{html.escape(_fmt_data(row.get('data')))}</td>"
            f"<td>{html.escape(str(row.get('classe', '') or 'Sem classe definida'))}</td>"
            f"<td>{html.escape(str(row.get('professor', '') or ''))}</td>"
            f"<td>{html.escape(str(row.get('funcao_professor', '') or ''))}</td>"
            f"<td>{html.escape(str(row.get('superintendente', '') or ''))}</td>"
            f"<td>{html.escape(str(row.get('auxiliar', '') or ''))}</td>"
            f"<td>{html.escape(str(row.get('tema', '') or ''))}</td>"
            "</tr>"
        )
    linhas_html = "".join(linhas) if linhas else '<tr><td colspan="7">Nenhuma escala no periodo.</td></tr>'

    return f"""
<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="UTF-8"/>
<title>Escala de professores - Escola Biblica</title>
<style>
* {{ box-sizing: border-box; }}
body {{ margin: 0; padding: 18px; background: #f3f4f6; color: #111827; font-family: Arial, Helvetica, sans-serif; }}
.toolbar {{ text-align: center; margin-bottom: 14px; }}
.toolbar button {{ background: #0F6E56; color: white; border: 0; border-radius: 8px; padding: 10px 22px; font-size: 14px; font-weight: 700; cursor: pointer; }}
.folha {{ width: 297mm; min-height: 210mm; margin: 0 auto; background: white; padding: 14mm; border: 1px solid #d1d5db; }}
.cabecalho {{ text-align: center; border-bottom: 2px solid #111827; padding-bottom: 10px; margin-bottom: 16px; }}
.cabecalho .logo {{ max-height: 64px; max-width: 200px; display: block; margin: 0 auto 8px; }}
.igreja {{ font-size: 18px; font-weight: 800; text-transform: uppercase; }}
.titulo {{ font-size: 15px; font-weight: 700; margin-top: 6px; }}
.filtro {{ font-size: 12px; color: #374151; margin-top: 4px; }}
.emitido {{ font-size: 11px; color: #6b7280; margin-top: 4px; }}
table {{ border-collapse: collapse; margin-top: 10px; font-size: 11px; width: 100%; }}
th, td {{ border: 1px solid #d1d5db; padding: 6px 8px; text-align: left; vertical-align: top; white-space: nowrap; }}
th {{ background: #f3f4f6; text-transform: uppercase; font-size: 10px; color: #374151; }}
@media print {{
    body {{ background: white; padding: 0; }}
    .toolbar {{ display: none !important; }}
    .folha {{ width: 100%; min-height: auto; margin: 0; border: 0; padding: 10mm; }}
    @page {{ size: landscape; }}
}}
</style>
</head>
<body>
<div class="toolbar">
    <button onclick="window.print()">Imprimir escala</button>
</div>
<main class="folha">
    <header class="cabecalho">
        {logo_html}
        <div class="titulo">Escala de Professores - Escola Biblica</div>
        <div class="filtro">Periodo: {html.escape(periodo_texto)} | Classe: {html.escape(classe_texto)} | Professor: {html.escape(professor_texto)}</div>
        <div class="emitido">Emitido em {emitido}</div>
    </header>
    <table>
        <thead>
            <tr>
                <th>Data</th>
                <th>Classe</th>
                <th>Professor</th>
                <th>Funcao</th>
                <th>Superintendente</th>
                <th>Auxiliar</th>
                <th>Tema</th>
            </tr>
        </thead>
        <tbody>
            {linhas_html}
        </tbody>
    </table>
</main>
</body>
</html>"""


def _render_classes(slug):
    st.markdown("### Classes e alunos")
    df_classes = listar_ebd_classes(slug, incluir_inativas=True)

    with st.expander("Cadastrar ou atualizar classe", expanded=df_classes.empty):
        editar = None
        if not df_classes.empty:
            op_edicao = {"Nova classe": None}
            op_edicao.update(_classes_opcoes(df_classes))
            escolha = st.selectbox("Editar classe existente", list(op_edicao.keys()))
            editar = op_edicao[escolha]
        row = {}
        if editar:
            row = df_classes[df_classes["id_classe"] == editar].iloc[0].to_dict()

        with st.form("form_ebd_classe"):
            nome = st.text_input("Nome da classe", value=row.get("nome", ""))
            c1, c2, c3 = st.columns(3)
            faixa = c1.text_input("Faixa etaria", value=row.get("faixa_etaria", ""))
            professor = c2.text_input("Professor principal", value=row.get("professor_principal", ""))
            sala = c3.text_input("Sala/local", value=row.get("sala", ""))
            ativa = st.checkbox("Classe ativa", value=bool(row.get("ativa", 1)))
            obs = st.text_area("Observacoes", value=row.get("observacoes", ""))
            if st.form_submit_button("Salvar classe", type="primary"):
                try:
                    salvar_ebd_classe(slug, nome, faixa, professor, sala, obs, ativa, editar)
                    st.success("Classe salva com sucesso.")
                    st.rerun()
                except Exception as exc:
                    st.error(str(exc))

    df_classes_ativas = listar_ebd_classes(slug)
    if df_classes_ativas.empty:
        st.info("Cadastre ao menos uma classe para matricular alunos e registrar chamadas.")
        return

    st.markdown("#### Matrículas por classe")
    st.caption(
        "Matricule alunos em cada classe da EBD. A chamada respeita a data de início "
        "e a data de encerramento da matrícula, preservando o histórico."
    )
    op_classes = _classes_opcoes(df_classes_ativas)
    op_membros, df_membros = _membros_opcoes(slug)

    with st.expander("Nova matrícula", expanded=False):
        modo = st.radio(
            "Origem do aluno",
            ["Membro cadastrado", "Nome manual"],
            horizontal=True,
            key="matricula_modo_novo",
        )
        with st.form("form_ebd_matricula"):
            classe_label = st.selectbox("Classe", list(op_classes.keys()), key="matricula_classe_nova")
            id_cadastro = None
            nome_aluno = ""
            if modo == "Membro cadastrado":
                if op_membros:
                    membro_label = st.selectbox("Membro", list(op_membros.keys()))
                    id_cadastro = op_membros[membro_label]
                    nome_aluno = df_membros[df_membros["id_cadastro"] == id_cadastro].iloc[0]["nome"]
                else:
                    st.warning("Nao ha membros ativos cadastrados.")
            else:
                nome_aluno = st.text_input("Nome do aluno", key="matricula_nome_manual_novo")
            c1, c2 = st.columns(2)
            data_inicio = c1.date_input("Data de início", value=_hoje(), format="DD/MM/YYYY")
            obs = c2.text_input("Observações")
            if st.form_submit_button("Matricular", type="primary"):
                if not str(nome_aluno or "").strip():
                    st.error("Informe ou selecione o aluno.")
                else:
                    try:
                        salvar_ebd_matricula(
                            slug,
                            op_classes[classe_label],
                            nome_aluno,
                            id_cadastro,
                            data_inicio.isoformat(),
                            obs,
                        )
                        st.success("Matrícula salva.")
                        st.rerun()
                    except Exception as exc:
                        st.error(str(exc))

    filtro_label = st.selectbox(
        "Filtrar matrículas por classe",
        ["Todas"] + list(op_classes.keys()),
        key="ebd_matriculas_filtro_classe",
    )
    id_classe_filtro = None if filtro_label == "Todas" else op_classes[filtro_label]
    matriculas = listar_ebd_matriculas(slug, id_classe_filtro, incluir_inativas=True)

    if matriculas.empty:
        st.info("Nenhuma matrícula cadastrada para o filtro selecionado.")
    else:
        tabela = matriculas.copy()
        tabela["situacao"] = tabela["ativa"].map({1: "Ativa", 0: "Encerrada"}).fillna("Ativa")
        tabela["data_inicio"] = tabela["data_inicio"].apply(_fmt_data)
        tabela["data_fim"] = tabela["data_fim"].apply(_fmt_data)
        st.dataframe(
            tabela[["classe", "nome_aluno", "situacao", "data_inicio", "data_fim", "observacoes"]],
            use_container_width=True,
            hide_index=True,
        )

        op_matriculas = {
            f'{int(row["id_matricula"])} - {row["nome_aluno"]} ({row["classe"]})': row
            for _, row in matriculas.iterrows()
        }

        with st.expander("Editar matrícula", expanded=False):
            selecionada = st.selectbox(
                "Matrícula para editar",
                ["Selecione"] + list(op_matriculas.keys()),
                key="ebd_editar_matricula",
            )
            if selecionada != "Selecione":
                row = op_matriculas[selecionada]
                classe_labels = list(op_classes.keys())
                classe_idx = 0
                for idx, label in enumerate(classe_labels):
                    if op_classes[label] == int(row["id_classe"]):
                        classe_idx = idx
                        break
                id_matricula_edit = int(row["id_matricula"])
                ativa_edit = st.selectbox(
                    "Situação",
                    ["Ativa", "Encerrada"],
                    index=0 if _int_seguro(row.get("ativa"), 1) == 1 else 1,
                    key=f"ebd_situacao_edit_{id_matricula_edit}",
                )
                with st.form(f"form_editar_matricula_ebd_{id_matricula_edit}"):
                    classe_edit = st.selectbox("Classe", classe_labels, index=classe_idx)
                    c1, c2 = st.columns(2)
                    nome_edit = c1.text_input("Nome do aluno", value=str(row.get("nome_aluno", "") or ""))
                    data_inicio_edit = c2.date_input(
                        "Data de início",
                        value=_parse_data(row.get("data_inicio")) or _hoje(),
                        format="DD/MM/YYYY",
                    )
                    data_fim_edit = None
                    if ativa_edit == "Encerrada":
                        data_fim_edit = st.date_input(
                            "Data de encerramento",
                            value=_parse_data(row.get("data_fim")) or _hoje(),
                            format="DD/MM/YYYY",
                        )
                    obs_edit = st.text_area("Observações", value=str(row.get("observacoes", "") or ""))
                    if st.form_submit_button("Atualizar matrícula", type="primary"):
                        try:
                            salvar_ebd_matricula(
                                slug,
                                op_classes[classe_edit],
                                nome_edit,
                                row.get("id_cadastro"),
                                data_inicio_edit.isoformat(),
                                obs_edit,
                                id_matricula=id_matricula_edit,
                                ativa=ativa_edit == "Ativa",
                                data_fim=data_fim_edit.isoformat() if data_fim_edit else "",
                            )
                            st.success("Matrícula atualizada.")
                            st.rerun()
                        except Exception as exc:
                            st.error(str(exc))

        ativas = matriculas[matriculas["ativa"] == 1]
        if not ativas.empty:
            op_ativas = [
                f'{int(row["id_matricula"])} - {row["nome_aluno"]} ({row["classe"]})'
                for _, row in ativas.iterrows()
            ]
            with st.expander("Encerrar matrícula", expanded=False):
                st.caption(
                    "Use esta opção para retirar o aluno das próximas chamadas "
                    "sem apagar o histórico de participação já registrado."
                )
                encerrar = st.selectbox(
                    "Matrícula ativa",
                    ["Selecione"] + op_ativas,
                    key="ebd_encerrar_matricula",
                )
                data_fim = st.date_input(
                    "Data de encerramento",
                    value=_hoje(),
                    format="DD/MM/YYYY",
                    key="ebd_data_fim_matricula",
                )
                if encerrar != "Selecione" and confirmar_exclusao(
                    f"encerrar_ebd_{encerrar}",
                    "Confirmar encerramento da matrícula",
                ):
                    encerrar_ebd_matricula(
                        slug,
                        int(encerrar.split(" - ")[0]),
                        data_fim.isoformat(),
                    )
                    st.success(
                        "Matrícula encerrada. O histórico foi preservado e o aluno "
                        "não aparecerá nas chamadas após a data de encerramento."
                    )
                    st.rerun()

    st.markdown("#### Classes cadastradas")
    st.dataframe(
        df_classes[["nome", "faixa_etaria", "professor_principal", "sala", "ativa", "observacoes"]],
        use_container_width=True,
        hide_index=True,
    )
    if not df_classes.empty:
        excluir = st.selectbox(
            "Excluir/inativar classe",
            ["Selecione"] + [
                f'{int(row["id_classe"])} - {row["nome"]}'
                for _, row in df_classes.iterrows()
            ],
        )
        if excluir != "Selecione" and confirmar_exclusao(f"excluir_classe_{excluir}", "Excluir ou inativar classe"):
            removida = excluir_ebd_classe(slug, int(excluir.split(" - ")[0]))
            st.success("Classe excluida." if removida else "Classe inativada porque possui historico.")
            st.rerun()


def _render_impressao_chamada(slug, id_classe, nome_classe):
    with st.expander("🖨️ Imprimir chamada da classe", expanded=False):
        st.caption(
            "Gere uma lista para impressão com os alunos da classe. Se já houver "
            "chamada registrada na data escolhida, a lista sai preenchida com as "
            "presenças salvas; caso contrário, sai em branco para preenchimento manual."
        )
        data_impressao = st.date_input(
            "Data da chamada para impressão",
            value=_hoje(),
            format="DD/MM/YYYY",
            key=f"ebd_imprimir_chamada_data_{id_classe}",
        )

        matriculas_todas = listar_ebd_matriculas(slug, id_classe, incluir_inativas=True)
        matriculas_data = _filtrar_matriculas_validas_na_data(matriculas_todas, data_impressao)
        if matriculas_data.empty:
            st.info("Nenhum aluno matriculado ativo nesta data.")
            return

        tema = ""
        professor = ""
        presencas = {}
        aula_salva = listar_ebd_aulas(
            slug, data_impressao.isoformat(), data_impressao.isoformat(), id_classe
        )
        if not aula_salva.empty:
            aula_row = aula_salva.iloc[0]
            tema = str(aula_row.get("tema", "") or "")
            professor = str(aula_row.get("professor", "") or "")
            id_aula = _int_seguro(aula_row.get("id_aula"), 0)
            if id_aula:
                from data.repository import carregar_ebd_presencas
                df_pres = carregar_ebd_presencas(slug, id_aula)
                for _, row in df_pres.iterrows():
                    id_matricula = _int_seguro(row.get("id_matricula"), 0)
                    if id_matricula:
                        presencas[id_matricula] = bool(row.get("presente"))
        else:
            escala_dia = _escala_da_aula(slug, data_impressao, id_classe)
            if escala_dia:
                tema = str(escala_dia.get("tema", "") or "")
                professor = str(escala_dia.get("professor", "") or "")

        alunos = [
            (
                str(row["nome_aluno"]),
                presencas.get(_int_seguro(row["id_matricula"])) if presencas else None,
            )
            for _, row in matriculas_data.iterrows()
        ]

        igreja = st.session_state.get("igreja", {})
        html_chamada = _gerar_html_chamada_classe(
            igreja, nome_classe, data_impressao, tema, professor, alunos,
        )
        components.html(html_chamada, height=760, scrolling=True)
        st.download_button(
            "📥 Baixar lista de chamada (HTML)",
            data=html_chamada,
            file_name=f"chamada_{nome_classe}_{data_impressao.isoformat()}.html",
            mime="text/html",
            key=f"ebd_download_chamada_{id_classe}_{data_impressao.isoformat()}",
        )


def _render_chamada(slug, id_classe_fixo=None):
    try:
        _render_chamada_conteudo(slug, id_classe_fixo)
    except Exception as exc:
        st.error(
            "Nao foi possivel carregar a chamada da Escola Bíblica. "
            f"Tipo do erro: {type(exc).__name__}. Detalhe: {exc}"
        )


def _render_chamada_conteudo(slug, id_classe_fixo=None):
    st.markdown("### Chamada por classe")
    df_classes = listar_ebd_classes(slug)
    if df_classes.empty:
        st.info("Cadastre uma classe antes de registrar chamada.")
        return
    if id_classe_fixo:
        df_classes = df_classes[df_classes["id_classe"] == int(id_classe_fixo)]
        if df_classes.empty:
            st.error("Sua classe vinculada nao esta ativa ou nao foi encontrada.")
            return

    op_classes = _classes_opcoes(df_classes)
    classe_label = st.selectbox(
        "Classe",
        list(op_classes.keys()),
        key="chamada_classe",
        disabled=bool(id_classe_fixo),
    )
    id_classe = op_classes[classe_label]
    nome_classe = df_classes[df_classes["id_classe"] == id_classe].iloc[0]["nome"]

    _render_impressao_chamada(slug, id_classe, nome_classe)

    escala_classe = listar_ebd_escala(slug, id_classe=id_classe)
    chamadas_salvas = listar_ebd_aulas(slug, id_classe=id_classe)
    opcoes_modo = ["Registrar/editar pela escala"]
    if not chamadas_salvas.empty:
        opcoes_modo.append("Editar chamada salva")
    if st.session_state.get("modo_chamada_ebd") not in opcoes_modo:
        st.session_state.pop("modo_chamada_ebd", None)
    modo_chamada = st.radio(
        "Modo da chamada",
        opcoes_modo,
        horizontal=True,
        key="modo_chamada_ebd",
    )

    escala_aula = None
    aula_editada = None
    if modo_chamada == "Editar chamada salva":
        c_ini, c_fim = st.columns(2)
        editar_inicio = c_ini.date_input(
            "Data inicial para localizar chamada",
            value=_inicio_mes(),
            key=f"ebd_edit_ini_{id_classe}",
            format="DD/MM/YYYY",
        )
        editar_fim = c_fim.date_input(
            "Data final para localizar chamada",
            value=_hoje(),
            key=f"ebd_edit_fim_{id_classe}",
            format="DD/MM/YYYY",
        )
        if editar_inicio > editar_fim:
            st.error("A data inicial nao pode ser maior que a data final.")
            return
        chamadas_salvas = listar_ebd_aulas(
            slug,
            editar_inicio.isoformat(),
            editar_fim.isoformat(),
            id_classe,
        )
        if chamadas_salvas.empty:
            st.info("Nenhuma chamada encontrada no periodo selecionado.")
            return
        op_chamadas = {
            f'{_fmt_data(row["data"])} - {row["classe"]} - {row.get("tema", "") or "sem tema"}': row
            for _, row in chamadas_salvas.iterrows()
        }
        labels_chamadas = list(op_chamadas.keys())
        chave_chamada_salva = "editar_chamada_salva"
        if st.session_state.get(chave_chamada_salva) not in labels_chamadas:
            st.session_state[chave_chamada_salva] = labels_chamadas[0]
        idx_atual = labels_chamadas.index(st.session_state[chave_chamada_salva])
        nav_ant, nav_sel, nav_seg = st.columns([1, 3, 1])
        if nav_ant.button(
            "Dia anterior",
            use_container_width=True,
            disabled=idx_atual >= len(labels_chamadas) - 1,
            key=f"ebd_chamada_anterior_{id_classe}",
        ):
            st.session_state[chave_chamada_salva] = labels_chamadas[idx_atual + 1]
        if nav_seg.button(
            "Dia seguinte",
            use_container_width=True,
            disabled=idx_atual <= 0,
            key=f"ebd_chamada_seguinte_{id_classe}",
        ):
            st.session_state[chave_chamada_salva] = labels_chamadas[idx_atual - 1]
        with nav_sel:
            chamada_label = st.selectbox(
                "Chamada salva para editar",
                labels_chamadas,
                key=chave_chamada_salva,
            )
        chamada_row = op_chamadas[chamada_label]
        aula_editada = chamada_row
        data_aula_original = _parse_data(chamada_row["data"]) or _hoje()
        data_aula = st.date_input(
            "Data da aula",
            value=data_aula_original,
            key=f"ebd_data_edit_{int(chamada_row['id_aula'])}",
            format="DD/MM/YYYY",
        )
        escala_aula = _escala_da_aula(slug, data_aula, id_classe)
        st.info(f"Editando chamada salva de {_fmt_data(data_aula.isoformat())}.")
    else:
        if escala_classe.empty:
            st.warning(
                "Nao ha escala de professores cadastrada para esta classe. "
                "Cadastre uma escala antes de registrar a chamada."
            )
            return
        op_escalas = {
            f'{_fmt_data(row["data"])} - {row.get("tema", "") or "sem tema"} - {row["professor"]}': row
            for _, row in escala_classe.iterrows()
        }
        chave_escala = f"escala_para_chamada_{int(id_classe)}"
        if st.session_state.get(chave_escala) not in op_escalas:
            st.session_state.pop(chave_escala, None)
        escala_label = st.selectbox(
            "Data da chamada conforme escala",
            list(op_escalas.keys()),
            key=chave_escala,
        )
        escala_aula = op_escalas[escala_label]
        data_aula = _parse_data(escala_aula["data"]) or _hoje()

    matriculas_todas = listar_ebd_matriculas(slug, id_classe, incluir_inativas=True)
    if matriculas_todas.empty:
        st.warning("Esta classe ainda nao possui alunos matriculados.")
        return

    matriculas = _filtrar_matriculas_validas_na_data(matriculas_todas, data_aula)
    if not matriculas.empty:
        matriculas = matriculas.copy()
        matriculas["id_matricula"] = matriculas["id_matricula"].apply(lambda x: _int_seguro(x, 0))
        matriculas = matriculas[matriculas["id_matricula"] > 0].copy()

    if matriculas.empty:
        st.warning(
            "Nenhuma matricula estava ativa na data desta chamada. "
            "Abaixo estao as matriculas encontradas para esta classe e a situacao delas nesta data."
        )
        st.caption(f"Data selecionada para a chamada: {_fmt_data(data_aula)}")
        st.dataframe(
            _diagnostico_matriculas_na_data(matriculas_todas, data_aula),
            use_container_width=True,
            hide_index=True,
        )
        return

    presencas_salvas = {}
    tema_atual = ""
    professor_atual = ""
    obs_atual = ""
    visitantes_atual = 0
    assistentes_atual = 0
    revistas_atual = 0
    biblias_atual = 0
    harpas_atual = 0
    ofertas_atual = 0.0

    if aula_editada is not None:
        aula = aula_editada
        tema_atual = aula.get("tema", "")
        professor_atual = aula.get("professor", "")
        obs_atual = aula.get("observacoes", "")
        visitantes_atual = _int_seguro(aula.get("visitantes", 0), 0)
        assistentes_atual = _int_seguro(aula.get("assistentes", 0), 0)
        revistas_atual = _int_seguro(aula.get("qtd_revistas", 0), 0)
        biblias_atual = _int_seguro(aula.get("qtd_biblias", 0), 0)
        harpas_atual = _int_seguro(aula.get("qtd_harpas", 0), 0)
        ofertas_atual = _float_seguro(aula.get("ofertas", 0), 0.0)
        id_aula_atual = _int_seguro(aula.get("id_aula"), 0)
        if id_aula_atual:
            from data.repository import carregar_ebd_presencas
            df_pres = carregar_ebd_presencas(slug, id_aula_atual)
            for _, row in df_pres.iterrows():
                id_matricula = _int_seguro(row.get("id_matricula"), 0)
                if id_matricula:
                    presencas_salvas[id_matricula] = bool(row.get("presente"))
    elif escala_aula is not None:
        tema_atual = str(escala_aula.get("tema", "") or "")
        professor_atual = str(escala_aula.get("professor", "") or "")

    acao_presencas = st.radio(
        "Presenças da lista de chamada",
        ["Manter marcação atual", "Marcar todos", "Desmarcar todos"],
        horizontal=True,
        key=f"ebd_acao_presencas_{id_classe}_{data_aula.isoformat()}",
    )

    with st.form("form_ebd_chamada"):
        if escala_aula is not None:
            st.success("Tema e professor preenchidos automaticamente pela escala de professores.")
        else:
            st.info("Nenhuma escala encontrada para esta classe e data.")

        c1, c2 = st.columns(2)
        tema = c1.text_input("Tema da aula", value=tema_atual)
        professor = c2.text_input("Professor", value=professor_atual)

        st.caption("Marque os alunos presentes. Alunos desmarcados serao contabilizados como falta.")
        dados = matriculas[["id_matricula", "nome_aluno"]].copy()
        if acao_presencas == "Marcar todos":
            dados["presente"] = True
        elif acao_presencas == "Desmarcar todos":
            dados["presente"] = False
        else:
            dados["presente"] = dados["id_matricula"].apply(
                lambda x: presencas_salvas.get(_int_seguro(x), True)
            )
        editado = st.data_editor(
            dados,
            hide_index=True,
            use_container_width=True,
            key=f"ebd_editor_chamada_{id_classe}_{data_aula.isoformat()}_{acao_presencas}",
            disabled=["id_matricula", "nome_aluno"],
            column_config={
                "id_matricula": st.column_config.NumberColumn("ID"),
                "nome_aluno": st.column_config.TextColumn("Aluno"),
                "presente": st.column_config.CheckboxColumn("Presente"),
            },
        )

        qtd_matriculados_calc = int(len(editado))
        qtd_presentes_calc = int(editado["presente"].fillna(False).astype(bool).sum())
        qtd_ausentes_calc = max(qtd_matriculados_calc - qtd_presentes_calc, 0)

        st.markdown("#### Totais da chamada")
        c_tot1, c_tot2 = st.columns(2)
        qtd_visitantes = c_tot1.number_input("Visitantes", min_value=0, step=1, value=visitantes_atual)
        qtd_assistentes = c_tot2.number_input("Assistentes", min_value=0, step=1, value=assistentes_atual)
        m1, m2, m3, m4, m5 = st.columns(5)
        m1.metric("Matriculados", qtd_matriculados_calc)
        m2.metric("Presentes", qtd_presentes_calc)
        m3.metric("Ausentes", qtd_ausentes_calc)
        m4.metric("Visitantes", qtd_visitantes)
        m5.metric("Assistentes", qtd_assistentes)

        st.markdown("#### Recursos e ofertas da aula")
        r1, r2, r3, r4 = st.columns(4)
        qtd_revistas = r1.number_input("Revistas", min_value=0, step=1, value=revistas_atual)
        qtd_biblias = r2.number_input("Biblias", min_value=0, step=1, value=biblias_atual)
        qtd_harpas = r3.number_input("Harpas", min_value=0, step=1, value=harpas_atual)
        ofertas = r4.number_input("Ofertas", min_value=0.0, step=1.0, value=ofertas_atual, format="%.2f")
        obs = st.text_area("Observacoes da aula", value=obs_atual)

        if st.form_submit_button("Salvar chamada", type="primary"):
            presencas = {}
            for _, row in editado.iterrows():
                id_matricula = _int_seguro(row.get("id_matricula"), 0)
                if id_matricula:
                    presencas[id_matricula] = bool(row.get("presente"))
            try:
                salvar_ebd_chamada(
                    slug,
                    id_classe,
                    data_aula.isoformat(),
                    tema,
                    professor,
                    obs,
                    presencas,
                    qtd_matriculados_calc,
                    qtd_presentes_calc,
                    qtd_ausentes_calc,
                    qtd_visitantes,
                    qtd_assistentes,
                    qtd_revistas,
                    qtd_biblias,
                    qtd_harpas,
                    ofertas,
                    id_aula=int(aula_editada["id_aula"]) if aula_editada is not None else None,
                )
                st.success("Chamada salva.")
                st.rerun()
            except Exception as exc:
                st.error(str(exc))


def _estilo_sombra_graficos():
    st.markdown(
        """
        <style>
        [data-testid="stPlotlyChart"] {
            background: #FFFFFF;
            border: 1px solid #E2E8F0;
            border-radius: 12px;
            padding: 14px;
            box-shadow: 0 12px 28px rgba(15, 23, 42, 0.16);
            margin-bottom: 18px;
            overflow-x: auto;
            -webkit-overflow-scrolling: touch;
        }
        @media (max-width: 640px) {
            [data-testid="stPlotlyChart"] {
                padding: 8px;
            }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def _render_relatorios(slug):
    _estilo_sombra_graficos()
    st.markdown("### Relatorios da Escola Bíblica")
    c1, c2 = st.columns(2)
    inicio = c1.date_input("Data inicial", value=_inicio_mes(), key="ebd_rel_ini", format="DD/MM/YYYY")
    fim = c2.date_input("Data final", value=_hoje(), key="ebd_rel_fim", format="DD/MM/YYYY")
    if inicio > fim:
        st.error("A data inicial nao pode ser maior que a data final.")
        return

    aulas = listar_ebd_aulas(slug, inicio.isoformat(), fim.isoformat())
    resumo = relatorio_ebd_resumo_classes(slug, inicio.isoformat(), fim.isoformat())
    freq = relatorio_ebd_frequencia(slug, inicio.isoformat(), fim.isoformat())
    professores = _resumo_professores(aulas)

    classes_periodo = (
        sorted(aulas["classe"].dropna().astype(str).unique().tolist()) if not aulas.empty else []
    )
    cores_classes_salvas = _mapa_cores_classes(classes_periodo, _carregar_cores_classes(slug))

    tab_classe, tab_frequencia, tab_professores, tab_geral = st.tabs(
        ["Relatorio por classe", "Frequencia por classe", "Desempenho dos professores", "Relatorio geral"]
    )

    with tab_classe:
        if aulas.empty:
            st.info("Nenhuma aula registrada no periodo selecionado.")
        else:
            st.markdown("#### Grafico por classe")
            classe_escolhida = st.selectbox(
                "Escolha a classe",
                ["Todas as classes"] + classes_periodo,
                key="grafico_ebd_classe",
            )
            if classe_escolhida == "Todas as classes":
                st.caption(
                    "Comparativo por sala. Quando uma sala possui mais de uma chamada "
                    "no periodo, o grafico apresenta a media por chamada daquela sala."
                )
                cores_classes = _seletor_cores_classes(slug, classes_periodo)
                _grafico_comparativo_classes_ebd(
                    "Resumo comparativo por classe",
                    aulas,
                    cores_classes=cores_classes,
                )
                resumo_classe_escolhida = resumo
            else:
                aulas_classe = aulas[aulas["classe"].astype(str) == classe_escolhida]
                media_classe = int(aulas_classe["id_aula"].nunique()) > 1
                modo_classe = "Média por chamada" if media_classe else "Total"
                st.caption(
                    f"{modo_classe}. Chamadas consideradas: "
                    f"{int(aulas_classe['id_aula'].nunique())}."
                )
                _grafico_totais_ebd(
                    f"Resumo da classe {classe_escolhida}",
                    _totais_aulas(aulas_classe, media=media_classe),
                    modo=modo_classe,
                    key="ebd_grafico_totais_classe_selecionada",
                )
                resumo_classe_escolhida = resumo[resumo["classe"].astype(str) == classe_escolhida]
                cores_classes = cores_classes_salvas

            st.markdown("##### Percentual de frequencia")
            _grafico_frequencia_classes(
                resumo_classe_escolhida,
                cores_classes=cores_classes,
                key="ebd_grafico_frequencia_relatorio_classe",
            )

    with tab_frequencia:
        st.markdown("#### Frequencia por classe")
        _grafico_frequencia_classes(
            resumo, cores_classes=cores_classes_salvas, key="ebd_grafico_frequencia_aba_frequencia"
        )
        if not resumo.empty:
            tabela = resumo.copy()
            tabela["frequencia_pct"] = tabela["frequencia_pct"].apply(_pct)
            st.dataframe(tabela, use_container_width=True, hide_index=True)
            st.download_button(
                "Baixar relatorio de classes CSV",
                data=gerar_csv(resumo),
                file_name="relatorio_ebd_classes.csv",
                mime="text/csv",
            )

        with st.expander("Relatorio individual por aluno", expanded=False):
            if freq.empty:
                st.info("Sem chamadas registradas no periodo.")
            else:
                freq = freq.copy()
                total = freq["presencas"] + freq["faltas"]
                freq["frequencia_pct"] = (freq["presencas"] / total.where(total > 0, 1) * 100).round(1)
                freq["acompanhamento"] = freq["frequencia_pct"].apply(
                    lambda v: "Acompanhar aluno/familia" if v < 60 else "Regular"
                )
                exibicao = freq.copy()
                exibicao["frequencia_pct"] = exibicao["frequencia_pct"].apply(_pct)
                st.dataframe(exibicao, use_container_width=True, hide_index=True)
                st.download_button(
                    "Baixar relatorio de alunos CSV",
                    data=gerar_csv(freq),
                    file_name="relatorio_ebd_alunos.csv",
                    mime="text/csv",
                )

    with tab_professores:
        st.markdown("#### Desempenho dos professores")
        st.caption(
            "O indice de desempenho pondera a frequencia dos alunos pela quantidade de aulas "
            "ministradas por cada professor, para que professores com poucos registros nao "
            "fiquem em vantagem ou desvantagem injusta frente aos que ministraram mais aulas "
            "no periodo."
        )
        _grafico_desempenho_professores(professores)
        if not professores.empty:
            tabela_prof = professores.copy()
            tabela_prof["frequencia_pct"] = tabela_prof["frequencia_pct"].apply(_pct)
            tabela_prof["indice_desempenho"] = tabela_prof["indice_desempenho"].apply(_pct)
            tabela_prof = tabela_prof.rename(columns={
                "professor": "Professor",
                "classes": "Classes",
                "aulas": "Aulas",
                "matriculados": "Matriculados",
                "presentes": "Presentes",
                "ausentes": "Ausentes",
                "frequencia_pct": "Frequencia",
                "indice_desempenho": "Indice de desempenho",
            })
            st.dataframe(tabela_prof, use_container_width=True, hide_index=True)
            st.download_button(
                "Baixar desempenho dos professores CSV",
                data=gerar_csv(professores),
                file_name="relatorio_ebd_professores.csv",
                mime="text/csv",
            )

    with tab_geral:
        with st.expander("Aulas registradas", expanded=False):
            if aulas.empty:
                st.info("Nenhuma aula no periodo.")
            else:
                aulas_exibir = aulas.copy()
                aulas_exibir["data"] = aulas_exibir["data"].apply(_fmt_data)
                aulas_exibir["ofertas"] = aulas_exibir["ofertas"].apply(_moeda)
                aulas_exibir["frequencia"] = (
                    aulas_exibir["presentes"].fillna(0)
                    / aulas_exibir["matriculados"].replace(0, 1).fillna(1)
                    * 100
                ).round(1).apply(_pct)
                st.dataframe(
                    aulas_exibir[[
                        "data", "classe", "tema", "professor", "matriculados",
                        "presentes", "ausentes", "visitantes", "frequencia",
                        "assistentes", "qtd_revistas", "qtd_biblias", "qtd_harpas",
                        "ofertas",
                    ]],
                    use_container_width=True,
                    hide_index=True,
                )

        if aulas.empty:
            st.info("Nenhuma aula registrada no periodo selecionado.")
        else:
            modo_geral = "Média ponderada"
            totais = _totais_aulas(aulas, media=True, por_semana=True)
            st.markdown("#### Relatorio geral")
            st.caption(
                "Matriculados, presentes, ausentes, assistentes, biblias, revistas e "
                "harpas somam todas as classes e sao divididos pela quantidade de "
                "domingos com aula no periodo (media ponderada). Visitantes e ofertas "
                "somam o valor total do periodo. Chamadas consideradas: "
                f"{int(aulas['id_aula'].nunique())}."
            )
            c1, c2, c3, c4, c5 = st.columns(5)
            c1.metric("Matriculados", _valor_grafico_ebd("Matriculados", totais["Matriculados"]))
            c2.metric("Presentes", _valor_grafico_ebd("Presentes", totais["Presentes"]))
            c3.metric("Ausentes", _valor_grafico_ebd("Ausentes", totais["Ausentes"]))
            c4.metric("Visitantes", _valor_grafico_ebd("Visitantes", totais["Visitantes"]))
            c5.metric("Assistentes", _valor_grafico_ebd("Assistentes", totais["Assistentes"]))
            c5, c6, c7, c8 = st.columns(4)
            c5.metric("Biblias", _valor_grafico_ebd("Biblias", totais["Biblias"]))
            c6.metric("Revistas", _valor_grafico_ebd("Revistas", totais["Revistas"]))
            c7.metric("Harpas", _valor_grafico_ebd("Harpas", totais["Harpas"]))
            c8.metric("Ofertas", _moeda(totais["Ofertas"]))

            st.markdown("#### Grafico geral da Escola Bíblica")
            _grafico_totais_ebd(
                "Resumo geral da Escola Bíblica",
                totais,
                modo=modo_geral,
                key="ebd_grafico_totais_geral",
                responsivo_mobile=True,
            )

            total_matriculados = float(aulas["matriculados"].fillna(0).sum())
            total_presentes = float(aulas["presentes"].fillna(0).sum())
            freq_geral_pct = round(
                total_presentes / total_matriculados * 100, 1
            ) if total_matriculados else 0.0
            resumo_geral_freq = pd.DataFrame(
                [{"classe": "Escola Bíblica", "frequencia_pct": freq_geral_pct}]
            )
            st.markdown("##### Percentual de frequencia geral")
            _grafico_frequencia_classes(resumo_geral_freq, key="ebd_grafico_frequencia_geral")


def _render_escala_editar(slug, escala, op_classes, opcoes_item):
    editar_label = st.selectbox(
        "Selecione o item para editar",
        ["Selecione"] + list(opcoes_item.keys()),
        key="escala_editar_select",
    )
    if editar_label == "Selecione":
        return
    id_editar = opcoes_item[editar_label]
    linha = escala[escala["id_escala"] == id_editar].iloc[0]
    classe_atual_label = "Sem classe definida"
    if pd.notna(linha.get("id_classe")):
        for label, id_valor in op_classes.items():
            if id_valor == int(linha["id_classe"]):
                classe_atual_label = label
                break
    with st.form(f"form_ebd_escala_editar_{id_editar}"):
        data_edit = st.date_input(
            "Data", value=_parse_data(linha["data"]) or _hoje(), format="DD/MM/YYYY"
        )
        classe_label_edit = st.selectbox(
            "Classe",
            list(op_classes.keys()),
            index=list(op_classes.keys()).index(classe_atual_label),
        )
        st.markdown("##### Professor")
        professor_edit, telefone_professor_edit, funcao_professor_edit = _selecionar_pessoa_escala(
            slug, "Professor", f"escala_editar_professor_{id_editar}", obrigatorio=True,
            nome_padrao=str(linha.get("professor", "") or ""),
            telefone_padrao=str(linha.get("telefone_professor", "") or ""),
            funcao_padrao=str(linha.get("funcao_professor", "") or ""),
        )
        with st.expander("Superintendente"):
            superintendente_edit, telefone_superintendente_edit, _ = _selecionar_pessoa_escala(
                slug, "Superintendente", f"escala_editar_superintendente_{id_editar}",
                nome_padrao=str(linha.get("superintendente", "") or ""),
                telefone_padrao=str(linha.get("telefone_superintendente", "") or ""),
            )
        with st.expander("Auxiliar"):
            auxiliar_edit, telefone_auxiliar_edit, _ = _selecionar_pessoa_escala(
                slug, "Auxiliar", f"escala_editar_auxiliar_{id_editar}",
                nome_padrao=str(linha.get("auxiliar", "") or ""),
                telefone_padrao=str(linha.get("telefone_auxiliar", "") or ""),
            )
        tema_edit = st.text_input("Tema/assunto", value=str(linha.get("tema", "") or ""))
        obs_edit = st.text_area("Observacoes", value=str(linha.get("observacoes", "") or ""))
        classe_nome_edit = "" if op_classes[classe_label_edit] else classe_label_edit
        if st.form_submit_button("Salvar alteracoes", type="primary"):
            if not professor_edit.strip():
                st.error("Professor e obrigatorio.")
            else:
                try:
                    salvar_ebd_escala(
                        slug,
                        data_edit.isoformat(),
                        professor_edit,
                        op_classes[classe_label_edit],
                        classe_nome_edit,
                        auxiliar_edit,
                        tema_edit,
                        obs_edit,
                        id_escala=id_editar,
                        telefone_professor=telefone_professor_edit,
                        funcao_professor=funcao_professor_edit,
                        superintendente=superintendente_edit,
                        telefone_superintendente=telefone_superintendente_edit,
                        telefone_auxiliar=telefone_auxiliar_edit,
                    )
                    st.success("Escala atualizada.")
                    st.rerun()
                except Exception as exc:
                    st.error(str(exc))


def _render_escala_excluir(slug, escala, opcoes_item, periodo_texto):
    modo_excluir = st.radio(
        "Como deseja excluir?",
        ["Um item especifico", "Todo o periodo filtrado"],
        key="escala_excluir_modo",
    )
    if modo_excluir == "Um item especifico":
        excluir_label = st.selectbox(
            "Selecione o item para excluir",
            ["Selecione"] + list(opcoes_item.keys()),
            key="escala_excluir_select",
        )
        if excluir_label == "Selecione":
            return
        if confirmar_exclusao(f"excluir_escala_{excluir_label}", "Excluir escala selecionada"):
            excluir_ebd_escala(slug, opcoes_item[excluir_label])
            st.success("Escala excluida.")
            st.rerun()
    else:
        qtd = len(escala)
        if qtd == 0:
            st.info("Nenhuma escala no periodo/filtro atual.")
            return
        st.warning(f"Isso ira excluir {qtd} escala(s) do periodo filtrado ({periodo_texto}).")
        if confirmar_exclusao("excluir_escala_periodo", f"Excluir {qtd} escala(s) do periodo filtrado"):
            excluir_ebd_escala_lote(slug, escala["id_escala"].tolist())
            st.success(f"{qtd} escala(s) excluida(s).")
            st.rerun()


def _render_escala_duplicar(slug, escala, opcoes_item):
    duplicar_label = st.selectbox(
        "Selecione o item para duplicar",
        ["Selecione"] + list(opcoes_item.keys()),
        key="escala_duplicar_select",
    )
    if duplicar_label == "Selecione":
        return
    id_duplicar = opcoes_item[duplicar_label]
    linha = escala[escala["id_escala"] == id_duplicar].iloc[0]
    with st.form(f"form_ebd_escala_duplicar_{id_duplicar}"):
        st.caption(
            f"Professor: {linha.get('professor', '') or '-'} | "
            f"Classe: {linha.get('classe', '') or 'Sem classe definida'}"
        )
        nova_data = st.date_input(
            "Nova data",
            value=(_parse_data(linha["data"]) or _hoje()) + datetime.timedelta(days=7),
            format="DD/MM/YYYY",
        )
        if st.form_submit_button("Duplicar para a nova data", type="primary"):
            try:
                id_classe = int(linha["id_classe"]) if pd.notna(linha.get("id_classe")) else None
                salvar_ebd_escala(
                    slug,
                    nova_data.isoformat(),
                    str(linha.get("professor", "") or ""),
                    id_classe,
                    "" if id_classe else str(linha.get("classe", "") or ""),
                    str(linha.get("auxiliar", "") or ""),
                    str(linha.get("tema", "") or ""),
                    str(linha.get("observacoes", "") or ""),
                    telefone_professor=str(linha.get("telefone_professor", "") or ""),
                    funcao_professor=str(linha.get("funcao_professor", "") or ""),
                    superintendente=str(linha.get("superintendente", "") or ""),
                    telefone_superintendente=str(linha.get("telefone_superintendente", "") or ""),
                    telefone_auxiliar=str(linha.get("telefone_auxiliar", "") or ""),
                )
                st.success("Escala duplicada.")
                st.rerun()
            except Exception as exc:
                st.error(str(exc))


def _salvar_edicoes_tabela_escala(slug, escala):
    estado = st.session_state.get("escala_data_editor", {})
    linhas_alteradas = estado.get("edited_rows", {})
    if not linhas_alteradas:
        st.info("Nenhuma alteracao para salvar.")
        return
    base = escala.reset_index(drop=True)
    for idx_str, alteracoes in linhas_alteradas.items():
        linha_original = base.iloc[int(idx_str)]
        linha = {**linha_original.to_dict(), **alteracoes}
        data_valor = _parse_data(linha.get("data")) or _hoje()
        id_classe = int(linha_original["id_classe"]) if pd.notna(linha_original.get("id_classe")) else None
        salvar_ebd_escala(
            slug,
            data_valor.isoformat(),
            str(linha.get("professor", "") or ""),
            id_classe,
            "" if id_classe else str(linha_original.get("classe", "") or ""),
            str(linha.get("auxiliar", "") or ""),
            str(linha.get("tema", "") or ""),
            str(linha.get("observacoes", "") or ""),
            id_escala=int(linha_original["id_escala"]),
            telefone_professor=str(linha.get("telefone_professor", "") or ""),
            funcao_professor=str(linha.get("funcao_professor", "") or ""),
            superintendente=str(linha.get("superintendente", "") or ""),
            telefone_superintendente=str(linha.get("telefone_superintendente", "") or ""),
            telefone_auxiliar=str(linha.get("telefone_auxiliar", "") or ""),
        )
    st.success(f"{len(linhas_alteradas)} escala(s) atualizada(s).")
    st.rerun()


def _render_professores_classe_editar(slug, quadro, id_classe_contexto, funcoes_disponiveis, opcoes_item):
    editar_label = st.selectbox(
        "Selecione para editar",
        ["Selecione"] + list(opcoes_item.keys()),
        key="prof_classe_editar_select",
    )
    if editar_label == "Selecione":
        return
    id_item = opcoes_item[editar_label]
    linha = quadro[quadro["id_professor_classe"] == id_item].iloc[0]
    with st.form(f"form_prof_classe_editar_{id_item}"):
        nome_edit = st.text_input("Nome", value=str(linha["nome"]))
        telefone_edit = st.text_input("WhatsApp", value=str(linha.get("telefone", "") or ""))
        if len(funcoes_disponiveis) > 1:
            funcao_edit = st.radio(
                "Funcao",
                funcoes_disponiveis,
                horizontal=True,
                index=funcoes_disponiveis.index(linha["funcao"]) if linha["funcao"] in funcoes_disponiveis else 0,
                key=f"prof_classe_funcao_editar_{id_item}",
            )
        else:
            funcao_edit = funcoes_disponiveis[0]
        ativo_edit = st.checkbox("Ativo", value=bool(linha["ativo"]))
        if st.form_submit_button("Salvar alteracoes", type="primary"):
            if not nome_edit.strip():
                st.error("Informe o nome.")
            else:
                try:
                    salvar_ebd_professor_classe(
                        slug, nome_edit, id_classe=id_classe_contexto, funcao=funcao_edit,
                        telefone=telefone_edit, ativo=ativo_edit, ordem=int(linha["ordem"]),
                        id_professor_classe=id_item,
                    )
                    st.success("Professor atualizado.")
                    st.rerun()
                except Exception as exc:
                    st.error(str(exc))


def _render_professores_classe_excluir(slug, opcoes_item):
    excluir_label = st.selectbox(
        "Selecione para remover",
        ["Selecione"] + list(opcoes_item.keys()),
        key="prof_classe_excluir_select",
    )
    if excluir_label == "Selecione":
        return
    if confirmar_exclusao(f"excluir_prof_classe_{excluir_label}", "Remover professor selecionado"):
        excluir_ebd_professor_classe(slug, opcoes_item[excluir_label])
        st.success("Professor removido.")
        st.rerun()


def _render_professores_classe(slug, df_classes):
    st.caption(
        "Cadastre o quadro fixo de professores de cada classe (recomendado: 4 "
        "titulares por classe) para a geracao automatica dividir as aulas de "
        "forma equilibrada entre eles. Cadastre tambem o rodizio de "
        "superintendentes, valido para toda a Escola Biblica em cada data."
    )
    opcoes_contexto = {"Superintendentes (toda a Escola Biblica)": None}
    if not df_classes.empty:
        opcoes_contexto.update(_classes_opcoes(df_classes))
    contexto_label = st.selectbox(
        "Contexto", list(opcoes_contexto.keys()), key="prof_classe_contexto"
    )
    id_classe_contexto = opcoes_contexto[contexto_label]
    e_superintendente = id_classe_contexto is None
    funcoes_disponiveis = ["Superintendente"] if e_superintendente else ["Professor", "Auxiliar"]

    quadro = listar_ebd_professores_classe(slug, id_classe=id_classe_contexto, incluir_inativos=True)
    qtd_titulares = int((quadro["funcao"] == funcoes_disponiveis[0]).sum()) if not quadro.empty else 0
    rotulo_titular = "superintendentes" if e_superintendente else "professores titulares"
    st.caption(f"{qtd_titulares} de 4 {rotulo_titular} cadastrados (recomendado).")

    if quadro.empty:
        st.info("Nenhum professor cadastrado ainda para este contexto.")
    else:
        exibir = quadro.copy()
        exibir["Situacao"] = exibir["ativo"].apply(lambda v: "Ativo" if v else "Inativo")
        st.dataframe(
            exibir[["funcao", "nome", "telefone", "Situacao"]].rename(
                columns={"funcao": "Funcao", "nome": "Nome", "telefone": "WhatsApp"}
            ),
            use_container_width=True,
            hide_index=True,
        )

    rotulo_add = "Adicionar superintendente" if e_superintendente else "Adicionar professor"
    with st.expander(rotulo_add, expanded=quadro.empty), st.form(
        f"form_prof_classe_add_{id_classe_contexto or 'sup'}"
    ):
        if len(funcoes_disponiveis) > 1:
            funcao = st.radio(
                "Funcao", funcoes_disponiveis, horizontal=True, key="prof_classe_funcao_add"
            )
        else:
            funcao = funcoes_disponiveis[0]
        nome, telefone, _ = _selecionar_pessoa_escala(
            slug, funcao, f"prof_classe_pessoa_{id_classe_contexto or 'sup'}", obrigatorio=True,
        )
        if st.form_submit_button("Salvar", type="primary"):
            if not nome.strip():
                st.error("Informe o nome.")
            else:
                try:
                    salvar_ebd_professor_classe(
                        slug, nome, id_classe=id_classe_contexto, funcao=funcao,
                        telefone=telefone, ordem=len(quadro),
                    )
                    st.success("Professor cadastrado.")
                    st.rerun()
                except Exception as exc:
                    st.error(str(exc))

    if not quadro.empty:
        opcoes_item = {
            f'{int(row["id_professor_classe"])} - {row["funcao"]} - {row["nome"]}': int(row["id_professor_classe"])
            for _, row in quadro.iterrows()
        }
        col_editar, col_excluir = st.columns(2)
        with col_editar:
            st.markdown("##### Editar professor")
            _render_professores_classe_editar(
                slug, quadro, id_classe_contexto, funcoes_disponiveis, opcoes_item
            )
        with col_excluir:
            st.markdown("##### Remover professor")
            _render_professores_classe_excluir(slug, opcoes_item)


def _gerar_datas_periodo(inicio, fim, intervalo_dias):
    datas = []
    atual = inicio
    while atual <= fim:
        datas.append(atual)
        atual += datetime.timedelta(days=intervalo_dias)
    return datas


def _montar_plano_escala_automatica(slug, inicio, fim, intervalo_dias, ids_classes, incluir_superintendente):
    datas = _gerar_datas_periodo(inicio, fim, intervalo_dias)
    avisos = []
    if not datas or not ids_classes:
        return [], avisos

    existentes = listar_ebd_escala(slug, datas[0].isoformat(), datas[-1].isoformat())
    ocupadas = set()
    for _, row in existentes.iterrows():
        id_classe_existente = int(row["id_classe"]) if pd.notna(row.get("id_classe")) else None
        ocupadas.add((_data_iso(row["data"]), id_classe_existente))

    superintendentes = []
    if incluir_superintendente:
        superintendentes = listar_ebd_professores_classe(
            slug, id_classe=None, funcao="Superintendente"
        ).to_dict("records")
        if not superintendentes:
            avisos.append(
                "Nenhum superintendente cadastrado: as aulas serao geradas sem superintendente."
            )
    superintendente_por_data = {}
    if superintendentes:
        for i, data in enumerate(datas):
            superintendente_por_data[data] = superintendentes[i % len(superintendentes)]

    df_classes = listar_ebd_classes(slug, incluir_inativas=True)
    nomes_classes = {int(row["id_classe"]): row["nome"] for _, row in df_classes.iterrows()}

    plano = []
    for id_classe in ids_classes:
        professores = listar_ebd_professores_classe(
            slug, id_classe=id_classe, funcao="Professor"
        ).to_dict("records")
        if not professores:
            avisos.append(
                f"Classe '{nomes_classes.get(id_classe, id_classe)}' sem professores "
                "cadastrados: nenhuma aula gerada para ela."
            )
            continue
        auxiliares = listar_ebd_professores_classe(
            slug, id_classe=id_classe, funcao="Auxiliar"
        ).to_dict("records")
        for i, data in enumerate(datas):
            if (data.isoformat(), id_classe) in ocupadas:
                continue
            professor = professores[i % len(professores)]
            auxiliar = auxiliares[i % len(auxiliares)] if auxiliares else None
            superintendente = superintendente_por_data.get(data)
            plano.append({
                "data": data.isoformat(),
                "id_classe": id_classe,
                "classe_nome": nomes_classes.get(id_classe, ""),
                "professor": professor["nome"],
                "telefone_professor": professor.get("telefone", "") or "",
                "auxiliar": auxiliar["nome"] if auxiliar else "",
                "telefone_auxiliar": (auxiliar.get("telefone", "") or "") if auxiliar else "",
                "superintendente": superintendente["nome"] if superintendente else "",
                "telefone_superintendente": (
                    (superintendente.get("telefone", "") or "") if superintendente else ""
                ),
            })
    return plano, avisos


def _render_gerar_escala_automatica(slug, df_classes):
    st.caption(
        "Gera automaticamente a escala de professores para o periodo escolhido, "
        "dividindo as aulas de forma equilibrada entre os professores cadastrados "
        "no quadro de cada classe. Datas que ja tiverem escala cadastrada sao "
        "preservadas e puladas."
    )
    if df_classes.empty:
        st.info("Cadastre ao menos uma classe antes de gerar a escala.")
        return

    c1, c2 = st.columns(2)
    inicio = c1.date_input(
        "Data inicial", value=_hoje(), key="gerar_escala_ini", format="DD/MM/YYYY"
    )
    fim = c2.date_input(
        "Data final",
        value=_hoje() + datetime.timedelta(days=84),
        key="gerar_escala_fim",
        format="DD/MM/YYYY",
    )
    intervalo_label = st.selectbox(
        "Intervalo entre aulas",
        ["Semanal (7 dias)", "Quinzenal (14 dias)", "Mensal (28 dias)"],
        key="gerar_escala_intervalo",
    )
    if inicio > fim:
        st.error("A data inicial nao pode ser maior que a data final.")
        return

    op_classes = _classes_opcoes(df_classes)
    classes_escolhidas = st.multiselect(
        "Classes incluidas na geracao",
        list(op_classes.keys()),
        default=list(op_classes.keys()),
        key="gerar_escala_classes",
    )
    incluir_superintendente = st.checkbox(
        "Incluir rodizio de superintendentes (um por data, para toda a escola)",
        value=True,
        key="gerar_escala_incluir_superintendente",
    )

    if st.button("Pre-visualizar geracao", type="primary", key="gerar_escala_preview_btn"):
        intervalo_dias = {
            "Semanal (7 dias)": 7, "Quinzenal (14 dias)": 14, "Mensal (28 dias)": 28,
        }[intervalo_label]
        ids_classes = [op_classes[label] for label in classes_escolhidas]
        plano, avisos = _montar_plano_escala_automatica(
            slug, inicio, fim, intervalo_dias, ids_classes, incluir_superintendente
        )
        st.session_state["gerar_escala_plano"] = plano
        st.session_state["gerar_escala_avisos"] = avisos

    plano = st.session_state.get("gerar_escala_plano")
    if plano is None:
        return

    for aviso in st.session_state.get("gerar_escala_avisos", []):
        st.warning(aviso)

    if not plano:
        st.info(
            "Nada para gerar: todas as datas do periodo ja possuem escala, ou "
            "nenhuma classe selecionada tem professores cadastrados."
        )
        return

    st.markdown(f"##### Previa: {len(plano)} aula(s) serao criadas")
    previa = pd.DataFrame([
        {
            "Data": _fmt_data(item["data"]),
            "Classe": item["classe_nome"],
            "Professor": item["professor"],
            "Auxiliar": item["auxiliar"],
            "Superintendente": item["superintendente"],
        }
        for item in plano
    ])
    st.dataframe(previa, use_container_width=True, hide_index=True)
    if st.button("Confirmar e salvar escala", type="primary", key="gerar_escala_confirmar_btn"):
        for item in plano:
            salvar_ebd_escala(
                slug,
                item["data"],
                item["professor"],
                item["id_classe"],
                "",
                item["auxiliar"],
                "",
                "Gerado automaticamente",
                telefone_professor=item["telefone_professor"],
                funcao_professor="Professor",
                superintendente=item["superintendente"],
                telefone_superintendente=item["telefone_superintendente"],
                telefone_auxiliar=item["telefone_auxiliar"],
            )
        st.session_state.pop("gerar_escala_plano", None)
        st.session_state.pop("gerar_escala_avisos", None)
        st.success(f"{len(plano)} aula(s) adicionadas a escala.")
        st.rerun()


def _render_escala(slug):
    st.markdown("### Escala de professores")
    df_classes = listar_ebd_classes(slug)
    op_classes = {"Sem classe definida": None}
    if not df_classes.empty:
        op_classes.update(_classes_opcoes(df_classes))

    tab_nova, tab_consulta, tab_professores, tab_gerar, tab_avisos = st.tabs(
        ["Nova escala", "Consultar / editar", "Professores por classe", "Gerar automatica", "Avisos"]
    )

    with tab_professores:
        _render_professores_classe(slug, df_classes)

    with tab_gerar:
        _render_gerar_escala_automatica(slug, df_classes)

    with tab_nova:
        with st.form("form_ebd_escala"):
            c1, c2 = st.columns(2)
            data = c1.date_input("Data", value=_hoje(), format="DD/MM/YYYY")
            classe_label = c2.selectbox("Classe", list(op_classes.keys()))
            st.markdown("#### Professor")
            professor, telefone_professor, funcao_professor = _selecionar_pessoa_escala(
                slug, "Professor", "escala_professor", obrigatorio=True
            )
            with st.expander("Superintendente (opcional)"):
                superintendente, telefone_superintendente, _ = _selecionar_pessoa_escala(
                    slug, "Superintendente", "escala_superintendente"
                )
            with st.expander("Auxiliar (opcional)"):
                auxiliar, telefone_auxiliar, _ = _selecionar_pessoa_escala(
                    slug, "Auxiliar", "escala_auxiliar"
                )
            tema = st.text_input("Tema/assunto")
            obs = st.text_area("Observacoes")
            st.markdown("#### Repetir escala")
            repetir = st.checkbox("Repetir esta escala em mais datas")
            st.caption("Os campos abaixo so tem efeito se a opcao acima estiver marcada.")
            c3, c4 = st.columns(2)
            intervalo_label = c3.selectbox(
                "Intervalo entre repeticoes",
                ["Semanal (7 dias)", "Quinzenal (14 dias)", "Mensal (28 dias)"],
            )
            repeticoes = c4.number_input(
                "Quantas datas seguidas (alem da data acima)",
                min_value=1,
                max_value=24,
                value=4,
            )
            classe_nome = "" if op_classes[classe_label] else classe_label
            if st.form_submit_button("Adicionar escala", type="primary"):
                if not professor.strip():
                    st.error("Professor e obrigatorio.")
                else:
                    try:
                        intervalo_dias = {
                            "Semanal (7 dias)": 7,
                            "Quinzenal (14 dias)": 14,
                            "Mensal (28 dias)": 28,
                        }[intervalo_label]
                        qtd_datas = int(repeticoes) + 1 if repetir else 1
                        for i in range(qtd_datas):
                            data_ocorrencia = data + datetime.timedelta(days=intervalo_dias * i)
                            salvar_ebd_escala(
                                slug,
                                data_ocorrencia.isoformat(),
                                professor,
                                op_classes[classe_label],
                                classe_nome,
                                auxiliar,
                                tema,
                                obs,
                                telefone_professor=telefone_professor,
                                funcao_professor=funcao_professor,
                                superintendente=superintendente,
                                telefone_superintendente=telefone_superintendente,
                                telefone_auxiliar=telefone_auxiliar,
                            )
                        if qtd_datas > 1:
                            st.success(f"Escala salva para {qtd_datas} datas.")
                        else:
                            st.success("Escala salva.")
                        st.rerun()
                    except Exception as exc:
                        st.error(str(exc))

        with st.expander("Importar escala do Excel"):
            st.caption(
                "Colunas aceitas: data, classe, professor, telefone_professor, funcao_professor, "
                "superintendente, telefone_superintendente, auxiliar, telefone_auxiliar, tema e observacoes."
            )
            arquivo = st.file_uploader(
                "Selecione a planilha",
                type=["xlsx", "xls", "csv"],
                key="escala_importacao_excel",
                help="As colunas obrigatorias sao: data e professor.",
            )
            if arquivo is not None and st.button("Importar planilha", type="primary"):
                _importar_escala_planilha(slug, arquivo, df_classes)

    with tab_consulta:
        c1, c2, c3, c4 = st.columns(4)
        inicio = c1.date_input("Inicio da escala", value=_inicio_mes(), key="escala_ini", format="DD/MM/YYYY")
        fim = c2.date_input("Fim da escala", value=_hoje() + datetime.timedelta(days=60), key="escala_fim", format="DD/MM/YYYY")
        filtro_classe = c3.selectbox(
            "Filtrar por classe",
            ["Todas"] + list(op_classes.keys()),
            key="escala_filtro_classe",
        )
        escala = listar_ebd_escala(slug, inicio.isoformat(), fim.isoformat())
        if filtro_classe != "Todas":
            id_classe_filtro = op_classes[filtro_classe]
            if id_classe_filtro is None:
                escala = escala[
                    escala["id_classe"].isna()
                    | (escala["id_classe"].fillna(0).astype(int) == 0)
                ].copy()
            else:
                escala = escala[
                    escala["id_classe"].fillna(0).astype(int) == int(id_classe_filtro)
                ].copy()
        professores_disponiveis = sorted({
            str(p).strip()
            for p in escala.get("professor", pd.Series(dtype=str)).dropna()
            if str(p).strip()
        })
        filtro_professor = c4.selectbox(
            "Filtrar por professor",
            ["Todos"] + professores_disponiveis,
            key="escala_filtro_professor",
        )
        if filtro_professor != "Todos":
            escala = escala[
                escala["professor"].fillna("").astype(str).str.strip() == filtro_professor
            ].copy()
        if escala.empty:
            st.info("Nenhuma escala cadastrada para o periodo.")
        else:
            st.caption("Edite direto na tabela (data, professor, telefones, tema...) e clique em salvar.")
            exibir = escala.reset_index(drop=True).copy()
            exibir["data"] = exibir["data"].apply(_fmt_data)
            ids_exibidos = tuple(int(i) for i in escala["id_escala"].tolist())
            if st.session_state.get("escala_data_editor_ids") != ids_exibidos:
                st.session_state["escala_data_editor_ids"] = ids_exibidos
                st.session_state.pop("escala_data_editor", None)
            st.data_editor(
                exibir[[
                    "data", "classe", "professor", "funcao_professor",
                    "telefone_professor", "superintendente", "telefone_superintendente",
                    "auxiliar", "telefone_auxiliar", "tema", "observacoes",
                ]],
                use_container_width=True,
                hide_index=True,
                num_rows="fixed",
                disabled=["classe"],
                key="escala_data_editor",
            )
            if st.button("Salvar alteracoes da tabela"):
                _salvar_edicoes_tabela_escala(slug, escala)
            st.download_button(
                "Baixar escala CSV",
                data=gerar_csv(escala),
                file_name="escala_professores_ebd.csv",
                mime="text/csv",
            )

            with st.expander("🖨️ Imprimir escala de professores", expanded=False):
                periodo_texto = f"{_fmt_data(inicio)} a {_fmt_data(fim)}"
                igreja = st.session_state.get("igreja", {})
                html_escala = _gerar_html_escala_professores(
                    igreja, periodo_texto, filtro_classe, escala, filtro_professor,
                )
                components.html(html_escala, height=760, scrolling=True)
                sufixo_professor = (
                    "_" + re.sub(r"[^a-z0-9]+", "_", filtro_professor.lower()).strip("_")
                    if filtro_professor != "Todos"
                    else ""
                )
                st.download_button(
                    "📥 Baixar escala de professores (HTML)",
                    data=html_escala,
                    file_name=f"escala_professores_ebd_{inicio.isoformat()}_{fim.isoformat()}{sufixo_professor}.html",
                    mime="text/html",
                    key="ebd_download_escala_html",
                )

            opcoes_item = {
                f'{int(row["id_escala"])} - {_fmt_data(row["data"])} - {row["professor"]}': int(row["id_escala"])
                for _, row in escala.iterrows()
            }
            col_duplicar, col_editar, col_excluir = st.columns(3)
            with col_duplicar:
                st.markdown("#### Duplicar para outra data")
                _render_escala_duplicar(slug, escala, opcoes_item)
            with col_editar:
                st.markdown("#### Editar item da escala")
                st.caption("Use para trocar a classe vinculada.")
                _render_escala_editar(slug, escala, op_classes, opcoes_item)
            with col_excluir:
                st.markdown("#### Excluir escala")
                periodo_texto_excluir = f"{_fmt_data(inicio)} a {_fmt_data(fim)}"
                if filtro_classe != "Todas":
                    periodo_texto_excluir += f" | Classe: {filtro_classe}"
                if filtro_professor != "Todos":
                    periodo_texto_excluir += f" | Professor: {filtro_professor}"
                _render_escala_excluir(slug, escala, opcoes_item, periodo_texto_excluir)

    with tab_avisos:
        c1, c2 = st.columns(2)
        inicio_av = c1.date_input(
            "Inicio da escala", value=_inicio_mes(), key="escala_avisos_ini", format="DD/MM/YYYY"
        )
        fim_av = c2.date_input(
            "Fim da escala",
            value=_hoje() + datetime.timedelta(days=60),
            key="escala_avisos_fim",
            format="DD/MM/YYYY",
        )
        escala_periodo = listar_ebd_escala(slug, inicio_av.isoformat(), fim_av.isoformat())
        if escala_periodo.empty:
            st.info("Nenhuma escala cadastrada para o periodo.")
        else:
            st.caption("Filtre por data e clique para abrir o WhatsApp com a mensagem pronta.")
            modo_aviso = st.radio(
                "Filtro dos avisos",
                ["Todos do período", "Uma data específica"],
                horizontal=True,
                key="ebd_avisos_modo_data",
            )
            escala_avisos = escala_periodo.copy()
            if modo_aviso == "Uma data específica":
                datas_disponiveis = sorted(
                    {
                        _data_iso(data)
                        for data in escala_avisos["data"].dropna().tolist()
                        if _data_iso(data)
                    }
                )
                if not datas_disponiveis:
                    st.info("Nenhuma data disponível para avisos no período selecionado.")
                    escala_avisos = escala_avisos.iloc[0:0]
                else:
                    data_padrao = _data_iso(_hoje())
                    index_data = datas_disponiveis.index(data_padrao) if data_padrao in datas_disponiveis else 0
                    data_aviso = st.selectbox(
                        "Data dos avisos",
                        datas_disponiveis,
                        index=index_data,
                        format_func=_fmt_data,
                        key="ebd_avisos_data",
                    )
                    escala_avisos = escala_avisos[
                        escala_avisos["data"].apply(_data_iso) == data_aviso
                    ].copy()

            professores_avisos_disponiveis = sorted({
                str(p).strip()
                for p in escala_avisos.get("professor", pd.Series(dtype=str)).dropna()
                if str(p).strip()
            })
            filtro_professor_aviso = st.selectbox(
                "Filtrar por professor",
                ["Todos"] + professores_avisos_disponiveis,
                key="ebd_avisos_filtro_professor",
            )
            if filtro_professor_aviso != "Todos":
                escala_avisos = escala_avisos[
                    escala_avisos["professor"].fillna("").astype(str).str.strip() == filtro_professor_aviso
                ].copy()

            if escala_avisos.empty:
                st.info("Nenhum aviso encontrado para o filtro selecionado.")
            else:
                pessoas_avisos = _pessoas_avisos_escala(slug, escala_avisos)
                pessoas_validas = [p for p in pessoas_avisos if _normalizar_tel_brasil(p["telefone"])]

                st.divider()
                st.markdown("#### 📤 Envio em lote")
                st.caption(
                    f"{len(pessoas_validas)} de {len(pessoas_avisos)} envolvido(s) "
                    "(professor, superintendente e auxiliar) com WhatsApp valido no filtro atual."
                )
                if not _whatsapp_api_configurada():
                    st.info(
                        "Para enviar em lote automaticamente, configure a WhatsApp Cloud API em "
                        "st.secrets (mesma configuracao usada em Aniversariantes). Sem isso, use "
                        "os botoes individuais abaixo para abrir o WhatsApp manualmente."
                    )
                if st.button(
                    "📤 Enviar avisos em lote agora",
                    type="primary",
                    disabled=not _whatsapp_api_configurada() or not pessoas_validas,
                    key="ebd_avisos_enviar_lote",
                ):
                    with st.spinner("Enviando avisos..."):
                        resultados_lote = _executar_envio_avisos_escala(pessoas_avisos)
                    _renderizar_resultados_envio(resultados_lote)
                st.divider()

            for _, row in escala_avisos.iterrows():
                titulo = f'{_fmt_data(row["data"])} - {row.get("classe", "Escola Bíblica")} - {row["professor"]}'
                with st.expander(titulo):
                    c1, c2 = st.columns(2)
                    with c1:
                        mensagem = _mensagem_escala(slug, row, row["professor"], "Professor")
                        _botao_whatsapp("Avisar professor", row.get("telefone_professor", ""), mensagem, f"prof_{row['id_escala']}")
                        st.text_area("Mensagem ao professor", value=mensagem, height=180, key=f"msg_prof_{row['id_escala']}")
                    with c2:
                        superintendente = str(row.get("superintendente", "") or "").strip()
                        if superintendente:
                            mensagem = _mensagem_escala(slug, row, superintendente, "Superintendente")
                            _botao_whatsapp(
                                "Avisar superintendente",
                                row.get("telefone_superintendente", ""),
                                mensagem,
                                f"sup_{row['id_escala']}",
                            )
                            st.text_area("Mensagem ao superintendente", value=mensagem, height=180, key=f"msg_sup_{row['id_escala']}")
                        else:
                            st.info("Nenhum superintendente informado para esta escala.")
                    c3, _ = st.columns(2)
                    with c3:
                        auxiliar = str(row.get("auxiliar", "") or "").strip()
                        if auxiliar:
                            mensagem = _mensagem_escala(slug, row, auxiliar, "Auxiliar")
                            _botao_whatsapp("Avisar auxiliar", row.get("telefone_auxiliar", ""), mensagem, f"aux_{row['id_escala']}")
                            st.text_area("Mensagem ao auxiliar", value=mensagem, height=180, key=f"msg_aux_{row['id_escala']}")
                        else:
                            st.info("Nenhum auxiliar informado para esta escala.")


def _render_secretarios(slug):
    st.markdown("### Secretarios da Escola Bíblica")
    st.caption(
        "Cadastre acessos restritos: secretario de classe acessa somente a chamada "
        "da classe vinculada; secretario geral acessa todo o modulo Escola Bíblica."
    )
    df_classes = listar_ebd_classes(slug)
    if df_classes.empty:
        st.info("Cadastre uma classe antes de criar secretario de classe.")
    op_classes = {"Selecione": None}
    op_classes.update(_classes_opcoes(df_classes))

    with st.expander("Cadastrar secretario", expanded=False):
        with st.form("form_ebd_secretario"):
            c1, c2 = st.columns(2)
            nome = c1.text_input("Nome")
            usuario = c2.text_input("Usuario", help="Use letras, numeros, ponto, hifen ou underline.")
            c3, c4 = st.columns(2)
            senha = c3.text_input("PIN de 4 digitos", type="password", max_chars=4)
            perfil_rotulo = c4.selectbox(
                "Perfil",
                ["Secretario de classe", "Secretario geral"],
            )
            perfil = "geral" if perfil_rotulo == "Secretario geral" else "classe"
            id_classe = None
            if perfil == "classe":
                classe_label = st.selectbox("Classe vinculada", list(op_classes.keys()))
                id_classe = op_classes[classe_label]
            c5, c6 = st.columns(2)
            telefone = c5.text_input("Telefone / WhatsApp")
            email = c6.text_input("E-mail")
            observacoes = st.text_area("Observacoes")
            if st.form_submit_button("Salvar secretario", type="primary"):
                try:
                    salvar_ebd_secretario(
                        slug, nome, usuario, senha, perfil, id_classe,
                        telefone, email, "Ativo", observacoes,
                    )
                    st.success("Secretario da Escola Bíblica cadastrado.")
                    st.rerun()
                except Exception as exc:
                    st.error(str(exc))

    df = listar_ebd_secretarios(slug)
    if df.empty:
        st.info("Nenhum secretario da Escola Bíblica cadastrado.")
        return

    exibir = df.copy()
    exibir["perfil"] = exibir["perfil"].map({
        "classe": "Secretario de classe",
        "geral": "Secretario geral",
    }).fillna(exibir["perfil"])
    st.dataframe(
        exibir[["nome", "usuario", "perfil", "classe", "telefone", "email", "situacao"]],
        use_container_width=True,
        hide_index=True,
    )

    st.markdown("#### Editar acesso")
    opcoes = {
        f'{int(row["id_secretario"])} - {row["nome"]} - {row["usuario"]}': row
        for _, row in df.iterrows()
    }
    selecionado = st.selectbox("Selecionar secretario", ["Selecione"] + list(opcoes.keys()))
    if selecionado == "Selecione":
        return
    row = opcoes[selecionado]
    id_secretario = int(row["id_secretario"])
    with st.form(f"form_editar_secretario_ebd_{id_secretario}"):
        c1, c2 = st.columns(2)
        nome = c1.text_input("Nome", value=row["nome"])
        usuario = c2.text_input("Usuario", value=row["usuario"])
        perfil_atual = "Secretario geral" if row["perfil"] == "geral" else "Secretario de classe"
        c3, c4 = st.columns(2)
        senha = c3.text_input(
            "Novo PIN de 4 digitos",
            type="password",
            max_chars=4,
            help="Deixe em branco para manter o PIN atual.",
        )
        perfil_rotulo = c4.selectbox(
            "Perfil",
            ["Secretario de classe", "Secretario geral"],
            index=1 if perfil_atual == "Secretario geral" else 0,
        )
        perfil = "geral" if perfil_rotulo == "Secretario geral" else "classe"
        id_classe = None
        if perfil == "classe":
            classe_labels = list(op_classes.keys())
            classe_atual = "Selecione"
            for label, valor in op_classes.items():
                if valor and row.get("id_classe") and int(valor) == int(row["id_classe"]):
                    classe_atual = label
                    break
            classe_label = st.selectbox(
                "Classe vinculada",
                classe_labels,
                index=classe_labels.index(classe_atual) if classe_atual in classe_labels else 0,
            )
            id_classe = op_classes[classe_label]
        c5, c6 = st.columns(2)
        telefone = c5.text_input("Telefone / WhatsApp", value=row.get("telefone", ""))
        email = c6.text_input("E-mail", value=row.get("email", ""))
        situacao = st.selectbox(
            "Situacao",
            ["Ativo", "Inativo"],
            index=0 if row.get("situacao") == "Ativo" else 1,
        )
        observacoes = st.text_area("Observacoes", value=row.get("observacoes", ""))
        if st.form_submit_button("Atualizar secretario", type="primary"):
            try:
                salvar_ebd_secretario(
                    slug, nome, usuario, senha, perfil, id_classe, telefone,
                    email, situacao, observacoes, id_secretario,
                )
                st.success("Secretario da Escola Bíblica atualizado.")
                st.rerun()
            except Exception as exc:
                st.error(str(exc))

    if confirmar_exclusao(f"inativar_secretario_ebd_{id_secretario}", "Inativar secretario selecionado"):
        inativar_ebd_secretario(slug, id_secretario)
        st.success("Secretario inativado.")
        st.rerun()


def render():
    st.subheader("Escola Bíblica")
    st.caption("Gestao de classes, chamada, frequencia e escala de professores da Escola Bíblica.")
    slug = slug_da_sessao()
    if not slug:
        st.error("Sessao invalida. Faca login novamente.")
        return

    def render_seguro(titulo, fn, *args):
        try:
            fn(*args)
        except Exception as exc:
            st.error(
                f"Nao foi possivel carregar {titulo}. "
                f"Tipo do erro: {type(exc).__name__}. Detalhe: {exc}"
            )

    _render_cards_superintendentes(slug)

    secretario = st.session_state.get("secretario_ebd", {})
    modo = st.session_state.get("modo", "")
    if modo == "pastor_auxiliar":
        st.info("Acesso de Pastor Auxiliar: somente relatórios da Escola Bíblica.")
        render_seguro("os relatórios da Escola Bíblica", _render_relatorios, slug)
        return
    if modo == "secretario_ebd" and isinstance(secretario, dict):
        perfil = secretario.get("perfil", "classe")
        if perfil == "classe":
            st.info(
                f"Acesso de secretario de classe: {secretario.get('classe', 'classe vinculada')}."
            )
            render_seguro("a chamada da Escola Bíblica", _render_chamada, slug, secretario.get("id_classe"))
            return
        st.info("Acesso de secretario geral da Escola Bíblica.")

    pode_gerenciar_secretarios = (
        modo != "secretario_ebd"
        or secretario.get("perfil") == "geral"
    )
    abas = [
        "Classes e alunos",
        "Chamada",
        "Relatorios",
        "Escala de professores",
    ]
    if pode_gerenciar_secretarios:
        abas.append("Secretarios")

    tabs = st.tabs(abas)
    tab_classes, tab_chamada, tab_relatorios, tab_escala = tabs[:4]
    with tab_classes:
        render_seguro("classes e alunos", _render_classes, slug)
    with tab_chamada:
        render_seguro("a chamada da Escola Bíblica", _render_chamada, slug)
    with tab_relatorios:
        render_seguro("os relatórios da Escola Bíblica", _render_relatorios, slug)
    with tab_escala:
        render_seguro("a escala de professores", _render_escala, slug)
    if pode_gerenciar_secretarios:
        with tabs[4]:
            render_seguro("secretários da Escola Bíblica", _render_secretarios, slug)

