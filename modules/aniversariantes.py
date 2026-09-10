"""
Modulo de aniversariantes — cards visuais, calendario, WhatsApp manual
e envio automatico via WhatsApp Cloud API.
"""
import logging

import os
import json
import calendar
import datetime
import urllib.parse

import requests
import pandas as pd
import streamlit as st

from data.repository import carregar_cadastros
from utils.helpers import slug_da_sessao, gerar_csv


MESES_PT = {
    1: "Janeiro",   2: "Fevereiro", 3: "Marco",     4: "Abril",
    5: "Maio",      6: "Junho",     7: "Julho",     8: "Agosto",
    9: "Setembro", 10: "Outubro",  11: "Novembro", 12: "Dezembro",
}

DIAS_SEMANA = ["Seg", "Ter", "Qua", "Qui", "Sex", "Sab", "Dom"]


# ─────────────────────────────────────────────────────────────
# CSS
# ─────────────────────────────────────────────────────────────

def _injetar_css():
    st.markdown("""
    <style>
    .aniv-card {
        background: white;
        border-radius: 12px;
        padding: 16px;
        box-shadow: 0 2px 6px rgba(0,0,0,0.08);
        border-left: 4px solid #0F6E56;
        margin-bottom: 10px;
        display: flex;
        align-items: center;
        gap: 14px;
    }
    .aniv-card.hoje    { border-left-color: #D85A30; background: #FFF7F2; }
    .aniv-card.semana  { border-left-color: #F5A623; }

    .aniv-icone {
        width: 48px;
        height: 48px;
        border-radius: 50%;
        background: linear-gradient(135deg, #1D9E75, #0F6E56);
        color: white;
        display: flex;
        align-items: center;
        justify-content: center;
        font-size: 1.4rem;
        flex-shrink: 0;
    }
    .aniv-card.hoje .aniv-icone {
        background: linear-gradient(135deg, #F5A623, #D85A30);
    }

    .aniv-info { flex: 1; }
    .aniv-nome {
        font-size: 1rem;
        font-weight: 700;
        color: #1a1a1a;
        margin-bottom: 2px;
    }
    .aniv-data { font-size: 0.8rem; color: #666; }
    .aniv-idade {
        font-size: 0.82rem;
        font-weight: 600;
        color: #0F6E56;
        margin-top: 2px;
    }
    .aniv-card.hoje .aniv-idade { color: #D85A30; }

    .cal-titulo {
        text-align: center;
        font-weight: 700;
        font-size: 1.05rem;
        color: #0F6E56;
        margin-bottom: 8px;
    }
    .cal-grid {
        display: grid;
        grid-template-columns: repeat(7, 1fr);
        gap: 4px;
    }
    .cal-cab {
        text-align: center;
        font-size: 0.72rem;
        font-weight: 700;
        color: #888;
        padding: 4px 0;
        text-transform: uppercase;
    }
    .cal-dia {
        aspect-ratio: 1;
        border-radius: 6px;
        padding: 4px;
        background: #f8f9fa;
        text-align: center;
        font-size: 0.78rem;
        min-height: 38px;
        display: flex;
        flex-direction: column;
        justify-content: center;
        align-items: center;
    }
    .cal-dia.vazio { background: transparent; }
    .cal-dia.hoje { background: #D85A30; color: white; font-weight: 700; }
    .cal-dia.tem-aniv {
        background: #E8F5E9;
        border: 2px solid #1D9E75;
        font-weight: 600;
    }
    .cal-dia.hoje.tem-aniv { background: #D85A30; border-color: #D85A30; }
    .cal-aniv-marcador { font-size: 0.6rem; color: #0F6E56; font-weight: 700; }
    .cal-dia.hoje .cal-aniv-marcador { color: white; }

    .aniv-vazio {
        text-align: center;
        padding: 30px 20px;
        color: #888;
        font-style: italic;
    }
    </style>
    """, unsafe_allow_html=True)


# ─────────────────────────────────────────────────────────────
# TELEFONE / WHATSAPP
# ─────────────────────────────────────────────────────────────

def _limpar_tel(tel):
    return "".join(c for c in str(tel) if c.isdigit())


def _normalizar_tel_brasil(tel):
    tel_limpo = _limpar_tel(tel)

    if not tel_limpo:
        return ""

    while tel_limpo.startswith("0"):
        tel_limpo = tel_limpo[1:]

    if not tel_limpo.startswith("55"):
        tel_limpo = "55" + tel_limpo

    return tel_limpo


def _link_whatsapp(tel, mensagem):
    tel_limpo = _normalizar_tel_brasil(tel)

    if not tel_limpo:
        return ""

    msg_enc = urllib.parse.quote(mensagem)
    return f"https://wa.me/{tel_limpo}?text={msg_enc}"


def _tratamento_por_sexo(sexo):
    sexo_up = str(sexo).strip().upper()

    if sexo_up.startswith("M"):
        return "irmão"

    if sexo_up.startswith("F"):
        return "irmã"

    return "irmão(ã)"


def _montar_mensagem_aniversario(nome, idade, nome_igreja, sexo=""):
    tratamento = _tratamento_por_sexo(sexo)
    ano_str = "anos" if idade != 1 else "ano"

    return (
        f"A paz do Senhor, {tratamento} {nome}! \n\n"
        f"Neste dia especial, a família {nome_igreja} se alegra por sua vida "
        f"e deseja a você um feliz aniversário.\n\n"
        f"Nossa oração é que Deus continue conduzindo seus passos, "
        f"fortalecendo sua fé e concedendo saúde, paz e alegria.\n\n"
        f"Parabéns por mais um ano de vida! \n\n"

        f"Pr. Olair Pereira Lopes.\n\n"
    )


# ─────────────────────────────────────────────────────────────
# CONFIGURAÇÃO WHATSAPP CLOUD API
# ─────────────────────────────────────────────────────────────

def _config_whatsapp():
    """
    Configure no arquivo .streamlit/secrets.toml:

    [whatsapp]
    auto_enviar = true
    access_token = "SEU_TOKEN_META"
    phone_number_id = "SEU_PHONE_NUMBER_ID"
    api_version = "v20.0"
    modo_envio = "text"

    # Opcional, caso use template aprovado:
    # modo_envio = "template"
    # template_name = "feliz_aniversario"
    # language_code = "pt_BR"
    """

    try:
        cfg = st.secrets.get("whatsapp", {})
    except Exception:
        cfg = {}

    return {
        "auto_enviar": bool(cfg.get("auto_enviar", False)),
        "access_token": str(
            cfg.get("access_token", "") or os.environ.get("WHATSAPP_ACCESS_TOKEN", "")
        ).strip(),
        "phone_number_id": str(
            cfg.get("phone_number_id", "") or os.environ.get("WHATSAPP_PHONE_NUMBER_ID", "")
        ).strip(),
        "api_version": str(cfg.get("api_version", "v20.0")).strip(),
        "modo_envio": str(cfg.get("modo_envio", "text")).strip().lower(),
        "template_name": str(cfg.get("template_name", "feliz_aniversario")).strip(),
        "language_code": str(cfg.get("language_code", "pt_BR")).strip(),
    }


def _whatsapp_api_configurada():
    cfg = _config_whatsapp()
    return bool(cfg["access_token"] and cfg["phone_number_id"])


def _enviar_whatsapp_texto_api(telefone, mensagem):
    cfg = _config_whatsapp()
    numero = _normalizar_tel_brasil(telefone)

    if not numero:
        return False, "Telefone inválido ou vazio."

    if not cfg["access_token"] or not cfg["phone_number_id"]:
        return False, "WhatsApp Cloud API não configurada no st.secrets."

    url = (
        f"https://graph.facebook.com/"
        f"{cfg['api_version']}/{cfg['phone_number_id']}/messages"
    )

    headers = {
        "Authorization": f"Bearer {cfg['access_token']}",
        "Content-Type": "application/json",
    }

    payload = {
        "messaging_product": "whatsapp",
        "to": numero,
        "type": "text",
        "text": {
            "preview_url": False,
            "body": mensagem,
        },
    }

    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=25)

        if 200 <= resp.status_code < 300:
            return True, "Mensagem enviada com sucesso."

        return False, f"Erro {resp.status_code}: {resp.text}"

    except requests.RequestException as e:
        return False, f"Falha na requisição: {e}"


def _enviar_whatsapp_template_api(telefone, nome, idade, nome_igreja, sexo=""):
    """
    Use esta função caso você tenha um template aprovado na Meta.

    O template sugerido deve ter 5 variáveis no corpo, nesta ordem:
    {{1}} tratamento
    {{2}} nome
    {{3}} nome_igreja
    {{4}} idade
    {{5}} ano_str

    Exemplo de texto do template aprovado:
    A paz do Senhor, {{1}} {{2}}!
    A família {{3}} deseja a você um feliz aniversário.
    Parabéns pelos seus {{4}} {{5}} de vida!
    """

    cfg = _config_whatsapp()
    numero = _normalizar_tel_brasil(telefone)

    if not numero:
        return False, "Telefone inválido ou vazio."

    if not cfg["access_token"] or not cfg["phone_number_id"]:
        return False, "WhatsApp Cloud API não configurada no st.secrets."

    tratamento = _tratamento_por_sexo(sexo)
    ano_str = "anos" if idade != 1 else "ano"

    url = (
        f"https://graph.facebook.com/"
        f"{cfg['api_version']}/{cfg['phone_number_id']}/messages"
    )

    headers = {
        "Authorization": f"Bearer {cfg['access_token']}",
        "Content-Type": "application/json",
    }

    payload = {
        "messaging_product": "whatsapp",
        "to": numero,
        "type": "template",
        "template": {
            "name": cfg["template_name"],
            "language": {
                "code": cfg["language_code"],
            },
            "components": [
                {
                    "type": "body",
                    "parameters": [
                        {"type": "text", "text": tratamento},
                        {"type": "text", "text": str(nome)},
                        {"type": "text", "text": str(nome_igreja)},
                        {"type": "text", "text": str(idade)},
                        {"type": "text", "text": ano_str},
                    ],
                }
            ],
        },
    }

    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=25)

        if 200 <= resp.status_code < 300:
            return True, "Template enviado com sucesso."

        return False, f"Erro {resp.status_code}: {resp.text}"

    except requests.RequestException as e:
        return False, f"Falha na requisição: {e}"


def _enviar_whatsapp_api(telefone, mensagem, nome, idade, nome_igreja, sexo=""):
    cfg = _config_whatsapp()

    if cfg["modo_envio"] == "template":
        return _enviar_whatsapp_template_api(
            telefone=telefone,
            nome=nome,
            idade=idade,
            nome_igreja=nome_igreja,
            sexo=sexo,
        )

    return _enviar_whatsapp_texto_api(
        telefone=telefone,
        mensagem=mensagem,
    )


# ─────────────────────────────────────────────────────────────
# CONTROLE PARA NÃO REENVIAR NO MESMO DIA
# ─────────────────────────────────────────────────────────────

def _pasta_controle_envios():
    pasta = os.path.join(os.getcwd(), ".controle_envios")
    os.makedirs(pasta, exist_ok=True)
    return pasta


def _arquivo_controle_envios(slug):
    return os.path.join(
        _pasta_controle_envios(),
        f"aniversariantes_whatsapp_{slug}.json",
    )


def _ler_controle_envios(slug):
    caminho = _arquivo_controle_envios(slug)

    if not os.path.exists(caminho):
        return {}

    try:
        with open(caminho, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _salvar_controle_envios(slug, dados):
    caminho = _arquivo_controle_envios(slug)

    with open(caminho, "w", encoding="utf-8") as f:
        json.dump(dados, f, ensure_ascii=False, indent=2)


def _chave_envio(data_ref, telefone, nome):
    tel = _normalizar_tel_brasil(telefone)
    identificador = tel if tel else str(nome).strip().upper()
    return f"{data_ref.isoformat()}|{identificador}"


def _ja_enviado_hoje(slug, data_ref, telefone, nome):
    controle = _ler_controle_envios(slug)
    chave = _chave_envio(data_ref, telefone, nome)
    return chave in controle


def _registrar_envio(slug, data_ref, telefone, nome):
    controle = _ler_controle_envios(slug)
    chave = _chave_envio(data_ref, telefone, nome)

    controle[chave] = {
        "nome": str(nome),
        "telefone": _normalizar_tel_brasil(telefone),
        "data_envio": datetime.datetime.now().isoformat(timespec="seconds"),
    }

    _salvar_controle_envios(slug, controle)


# ─────────────────────────────────────────────────────────────
# DADOS DOS ANIVERSARIANTES
# ─────────────────────────────────────────────────────────────

def _preparar_df_aniv(df_cad):
    if df_cad.empty or "data_nascimento" not in df_cad.columns:
        return pd.DataFrame()

    if "tipo_cadastro" not in df_cad.columns:
        return pd.DataFrame()

    df = df_cad[
        df_cad["tipo_cadastro"].fillna("").astype(str).str.upper() == "MEMBRO"
    ].copy()

    df = df[df["data_nascimento"].fillna("").astype(str).str.strip() != ""]

    if df.empty:
        return df

    def parse_data(d):
        texto = str(d).strip()

        if not texto:
            return None

        formatos = [
            "%Y-%m-%d",
            "%d/%m/%Y",
            "%d-%m-%Y",
        ]

        for fmt in formatos:
            try:
                return datetime.datetime.strptime(texto, fmt).date()
            except Exception:
                logging.exception("Erro ignorado silenciosamente")

        try:
            return datetime.date.fromisoformat(texto)
        except Exception:
            return None

    df["dt_nasc"] = df["data_nascimento"].apply(parse_data)
    df = df[df["dt_nasc"].notna()].copy()

    if df.empty:
        return df

    hoje = datetime.date.today()

    df["dia_aniv"] = df["dt_nasc"].apply(lambda d: d.day)
    df["mes_aniv"] = df["dt_nasc"].apply(lambda d: d.month)

    df["idade"] = df["dt_nasc"].apply(
        lambda d: hoje.year - d.year - (
            (hoje.month, hoje.day) < (d.month, d.day)
        )
    )

    df["aniv_str"] = df["dt_nasc"].apply(lambda d: d.strftime("%d/%m"))

    if "sexo" not in df.columns:
        df["sexo"] = ""

    if "telefone" not in df.columns:
        df["telefone"] = ""

    if "nome" not in df.columns:
        df["nome"] = ""

    return df


def _aniversariantes_hoje(df_aniv):
    hoje = datetime.date.today()

    return df_aniv[
        (df_aniv["dia_aniv"] == hoje.day) &
        (df_aniv["mes_aniv"] == hoje.month)
    ].sort_values("nome")


# ─────────────────────────────────────────────────────────────
# ENVIO AUTOMÁTICO
# ─────────────────────────────────────────────────────────────

def _executar_envio_aniversariantes_hoje(df_hoje, nome_igreja, slug, forcar=False):
    hoje = datetime.date.today()
    resultados = []

    if df_hoje.empty:
        return resultados

    for _, r in df_hoje.iterrows():
        nome = str(r.get("nome", "")).strip()
        telefone = str(r.get("telefone", "")).strip()
        sexo = str(r.get("sexo", "")).strip()
        idade = int(r.get("idade", 0))

        if not nome:
            resultados.append({
                "nome": "(sem nome)",
                "telefone": telefone,
                "status": "ignorado",
                "detalhe": "Cadastro sem nome.",
            })
            continue

        if not _normalizar_tel_brasil(telefone):
            resultados.append({
                "nome": nome,
                "telefone": telefone,
                "status": "ignorado",
                "detalhe": "Cadastro sem telefone válido.",
            })
            continue

        if not forcar and _ja_enviado_hoje(slug, hoje, telefone, nome):
            resultados.append({
                "nome": nome,
                "telefone": telefone,
                "status": "já enviado",
                "detalhe": "Mensagem já enviada hoje.",
            })
            continue

        mensagem = _montar_mensagem_aniversario(
            nome=nome,
            idade=idade,
            nome_igreja=nome_igreja,
            sexo=sexo,
        )

        ok, detalhe = _enviar_whatsapp_api(
            telefone=telefone,
            mensagem=mensagem,
            nome=nome,
            idade=idade,
            nome_igreja=nome_igreja,
            sexo=sexo,
        )

        if ok:
            _registrar_envio(slug, hoje, telefone, nome)
            resultados.append({
                "nome": nome,
                "telefone": _normalizar_tel_brasil(telefone),
                "status": "enviado",
                "detalhe": detalhe,
            })
        else:
            resultados.append({
                "nome": nome,
                "telefone": _normalizar_tel_brasil(telefone),
                "status": "erro",
                "detalhe": detalhe,
            })

    return resultados


def _renderizar_resultados_envio(resultados):
    if not resultados:
        st.info("Nenhum envio foi processado.")
        return

    df_res = pd.DataFrame(resultados)

    qtd_enviado = int((df_res["status"] == "enviado").sum())
    qtd_erro = int((df_res["status"] == "erro").sum())
    qtd_ja = int((df_res["status"] == "já enviado").sum())
    qtd_ign = int((df_res["status"] == "ignorado").sum())

    c1, c2, c3, c4 = st.columns(4)

    c1.metric("Enviados", qtd_enviado)
    c2.metric("Erros", qtd_erro)
    c3.metric("Já enviados", qtd_ja)
    c4.metric("Ignorados", qtd_ign)

    st.dataframe(df_res, use_container_width=True, hide_index=True)


# ─────────────────────────────────────────────────────────────
# CARD VISUAL
# ─────────────────────────────────────────────────────────────

def _card_aniv(nome, data_str, idade, telefone, nome_igreja, sexo="", classe=""):
    inicial = (nome[0] if nome else "?").upper()
    ano_str = "anos" if idade != 1 else "ano"

    st.markdown(f"""
    <div class="aniv-card {classe}">
        <div class="aniv-icone">{inicial}</div>
        <div class="aniv-info">
            <div class="aniv-nome">{nome}</div>
            <div class="aniv-data">🎂 {data_str}</div>
            <div class="aniv-idade">{idade} {ano_str}</div>
        </div>
    </div>
    """, unsafe_allow_html=True)

    tel_limpo = _normalizar_tel_brasil(telefone)

    if tel_limpo:
        mensagem = _montar_mensagem_aniversario(
            nome=nome,
            idade=idade,
            nome_igreja=nome_igreja,
            sexo=sexo,
        )

        link = _link_whatsapp(telefone, mensagem)

        if link:
            st.markdown(
                f'<a href="{link}" target="_blank" '
                f'style="display:inline-block;background:#25D366;color:white;'
                f'padding:6px 14px;border-radius:6px;text-decoration:none;'
                f'font-size:0.82rem;margin-bottom:14px">'
                f'💬 Enviar parabéns pelo WhatsApp</a>',
                unsafe_allow_html=True,
            )


# ─────────────────────────────────────────────────────────────
# CALENDÁRIO
# ─────────────────────────────────────────────────────────────

def _renderizar_calendario(df_aniv, ano, mes):
    hoje = datetime.date.today()
    dias_com_aniv = set(
        df_aniv[df_aniv["mes_aniv"] == mes]["dia_aniv"].tolist()
    )

    cal = calendar.Calendar(firstweekday=0)
    dias_mes = cal.monthdayscalendar(ano, mes)

    nome_mes = MESES_PT[mes]

    st.markdown(
        f'<div class="cal-titulo">{nome_mes} {ano}</div>',
        unsafe_allow_html=True,
    )

    html = '<div class="cal-grid">'

    for d in DIAS_SEMANA:
        html += f'<div class="cal-cab">{d}</div>'

    for semana in dias_mes:
        for dia in semana:
            if dia == 0:
                html += '<div class="cal-dia vazio"></div>'
            else:
                classes = ["cal-dia"]

                if dia in dias_com_aniv:
                    classes.append("tem-aniv")

                if ano == hoje.year and mes == hoje.month and dia == hoje.day:
                    classes.append("hoje")

                marcador = (
                    '<div class="cal-aniv-marcador">🎂</div>'
                    if dia in dias_com_aniv else ""
                )

                classe_css = " ".join(classes)

                html += (
                    f'<div class="{classe_css}">'
                    f'<div>{dia}</div>{marcador}</div>'
                )

    html += '</div>'

    st.markdown(html, unsafe_allow_html=True)


# ─────────────────────────────────────────────────────────────
# RENDER PRINCIPAL
# ─────────────────────────────────────────────────────────────

def render():
    _injetar_css()

    slug = slug_da_sessao()
    igreja = st.session_state.get("igreja", {})
    nome_igreja = igreja.get("nome", "Igreja")

    df_cad = carregar_cadastros(slug)
    df_aniv = _preparar_df_aniv(df_cad)

    st.subheader("🎂 Aniversariantes")
    st.caption("Acompanhe os aniversariantes dos membros da igreja.")

    if df_aniv.empty:
        st.info("Nenhum membro com data de nascimento cadastrada ainda.")
        st.caption("Para usar este módulo, cadastre a data de nascimento dos membros.")
        return

    hoje = datetime.date.today()
    hoje_df = _aniversariantes_hoje(df_aniv)

    cfg_whats = _config_whatsapp()

    # Envio automático ao abrir o módulo, se habilitado no secrets.
    if cfg_whats["auto_enviar"]:
        if _whatsapp_api_configurada():
            resultados_auto = _executar_envio_aniversariantes_hoje(
                df_hoje=hoje_df,
                nome_igreja=nome_igreja,
                slug=slug,
                forcar=False,
            )

            enviados = [
                r for r in resultados_auto
                if r.get("status") == "enviado"
            ]

            if enviados:
                st.toast(
                    f"{len(enviados)} mensagem(ns) de aniversário enviada(s).",
                    icon="🎂",
                )
        else:
            st.warning(
                "O envio automático está habilitado, mas a WhatsApp Cloud API "
                "não foi configurada no st.secrets."
            )

    aba_hoje, aba_semana, aba_mes, aba_cal, aba_envio = st.tabs([
        "Hoje",
        "Semana",
        "Mes",
        "📅 Calendario",
        "📲 Envio WhatsApp",
    ])

    # ── ABA: HOJE ────────────────────────────────────────────────────────
    with aba_hoje:
        dias_pt = {
            0: "Segunda",
            1: "Terca",
            2: "Quarta",
            3: "Quinta",
            4: "Sexta",
            5: "Sabado",
            6: "Domingo",
        }

        st.markdown(
            f"**{hoje.strftime('%d/%m/%Y')}** — {dias_pt[hoje.weekday()]}"
        )

        if hoje_df.empty:
            st.markdown(
                '<div class="aniv-vazio">Nenhum aniversariante hoje. 🌷</div>',
                unsafe_allow_html=True,
            )
        else:
            st.success(f"🎉 {len(hoje_df)} aniversariante(s) hoje!")

            for _, r in hoje_df.iterrows():
                _card_aniv(
                    nome=str(r["nome"]),
                    data_str=r["aniv_str"],
                    idade=int(r["idade"]),
                    telefone=str(r.get("telefone", "")),
                    nome_igreja=nome_igreja,
                    sexo=str(r.get("sexo", "")),
                    classe="hoje",
                )

    # ── ABA: SEMANA ──────────────────────────────────────────────────────
    with aba_semana:
        ini_sem = hoje - datetime.timedelta(days=hoje.weekday())
        fim_sem = ini_sem + datetime.timedelta(days=6)

        st.markdown(
            f"De **{ini_sem.strftime('%d/%m')}** "
            f"a **{fim_sem.strftime('%d/%m/%Y')}**"
        )

        dias_semana_set = set()
        d = ini_sem

        while d <= fim_sem:
            dias_semana_set.add((d.day, d.month))
            d += datetime.timedelta(days=1)

        sem_df = df_aniv[
            df_aniv.apply(
                lambda r: (
                    int(r["dia_aniv"]),
                    int(r["mes_aniv"]),
                ) in dias_semana_set,
                axis=1,
            )
        ].sort_values(["mes_aniv", "dia_aniv", "nome"])

        if sem_df.empty:
            st.markdown(
                '<div class="aniv-vazio">Nenhum aniversariante nesta semana.</div>',
                unsafe_allow_html=True,
            )
        else:
            st.info(f"🎈 {len(sem_df)} aniversariante(s) nesta semana")

            for _, r in sem_df.iterrows():
                eh_hoje = (
                    int(r["dia_aniv"]) == hoje.day and
                    int(r["mes_aniv"]) == hoje.month
                )

                _card_aniv(
                    nome=str(r["nome"]),
                    data_str=r["aniv_str"],
                    idade=int(r["idade"]),
                    telefone=str(r.get("telefone", "")),
                    nome_igreja=nome_igreja,
                    sexo=str(r.get("sexo", "")),
                    classe="hoje" if eh_hoje else "semana",
                )

            st.divider()

            df_exp = sem_df[["nome", "aniv_str", "idade", "telefone"]].copy()
            df_exp.columns = ["Nome", "Data", "Idade", "Telefone"]

            st.download_button(
                "📥 Exportar CSV da semana",
                gerar_csv(df_exp),
                f"aniversariantes_semana_{hoje.strftime('%Y%m%d')}.csv",
                "text/csv",
            )

    # ── ABA: MÊS ─────────────────────────────────────────────────────────
    with aba_mes:
        st.markdown(f"Mes de **{MESES_PT[hoje.month]}/{hoje.year}**")

        mes_df = df_aniv[
            df_aniv["mes_aniv"] == hoje.month
        ].sort_values(["dia_aniv", "nome"])

        if mes_df.empty:
            st.markdown(
                '<div class="aniv-vazio">Nenhum aniversariante este mes.</div>',
                unsafe_allow_html=True,
            )
        else:
            st.info(
                f"🎊 {len(mes_df)} aniversariante(s) em {MESES_PT[hoje.month]}"
            )

            for _, r in mes_df.iterrows():
                eh_hoje = (
                    int(r["dia_aniv"]) == hoje.day and
                    int(r["mes_aniv"]) == hoje.month
                )

                _card_aniv(
                    nome=str(r["nome"]),
                    data_str=r["aniv_str"],
                    idade=int(r["idade"]),
                    telefone=str(r.get("telefone", "")),
                    nome_igreja=nome_igreja,
                    sexo=str(r.get("sexo", "")),
                    classe="hoje" if eh_hoje else "",
                )

            st.divider()

            df_exp = mes_df[["nome", "aniv_str", "idade", "telefone"]].copy()
            df_exp.columns = ["Nome", "Data", "Idade", "Telefone"]

            st.download_button(
                "📥 Exportar CSV do mes",
                gerar_csv(df_exp),
                f"aniversariantes_{MESES_PT[hoje.month]}_{hoje.year}.csv",
                "text/csv",
            )

    # ── ABA: CALENDÁRIO ──────────────────────────────────────────────────
    with aba_cal:
        c1, c2 = st.columns(2)

        with c1:
            mes_sel = st.selectbox(
                "Mes",
                list(MESES_PT.keys()),
                index=hoje.month - 1,
                format_func=lambda m: MESES_PT[m],
                key="aniv_cal_mes",
            )

        with c2:
            ano_sel = st.number_input(
                "Ano",
                min_value=2020,
                max_value=2100,
                value=hoje.year,
                key="aniv_cal_ano",
            )

        _renderizar_calendario(df_aniv, int(ano_sel), int(mes_sel))

        st.markdown("")
        st.caption("🎂 = dia com aniversariante  |  Vermelho = hoje")

        mes_sel_df = df_aniv[
            df_aniv["mes_aniv"] == int(mes_sel)
        ].sort_values(["dia_aniv", "nome"])

        if not mes_sel_df.empty:
            st.divider()
            st.markdown(f"**Aniversariantes de {MESES_PT[int(mes_sel)]}:**")

            tabela = mes_sel_df[["aniv_str", "nome", "idade"]].copy()
            tabela.columns = ["Data", "Nome", "Idade atual"]

            st.dataframe(tabela, use_container_width=True, hide_index=True)

    # ── ABA: ENVIO WHATSAPP ──────────────────────────────────────────────
    with aba_envio:
        st.markdown("### 📲 Envio automático de mensagens")

        st.caption(
            "Esta rotina envia mensagens aos aniversariantes do dia e registra "
            "o envio para não repetir a mensagem no mesmo dia."
        )

        if cfg_whats["auto_enviar"]:
            st.success("Envio automático habilitado no st.secrets.")
        else:
            st.info("Envio automático desabilitado no st.secrets.")

        if _whatsapp_api_configurada():
            st.success("WhatsApp Cloud API configurada.")
        else:
            st.warning(
                "WhatsApp Cloud API ainda não configurada. "
                "Os links manuais continuam funcionando normalmente."
            )

        st.markdown("#### Aniversariantes de hoje")

        if hoje_df.empty:
            st.info("Não há aniversariantes hoje.")
        else:
            tabela_hoje = hoje_df[["nome", "aniv_str", "idade", "telefone"]].copy()
            tabela_hoje.columns = ["Nome", "Data", "Idade", "Telefone"]

            st.dataframe(tabela_hoje, use_container_width=True, hide_index=True)

            st.divider()

            col1, col2 = st.columns(2)

            with col1:
                enviar_agora = st.button(
                    "📤 Enviar agora",
                    type="primary",
                    use_container_width=True,
                    disabled=not _whatsapp_api_configurada(),
                )

            with col2:
                reenviar_forcado = st.button(
                    "🔄 Reenviar mesmo se já enviado",
                    use_container_width=True,
                    disabled=not _whatsapp_api_configurada(),
                )

            if enviar_agora:
                with st.spinner("Enviando mensagens..."):
                    resultados = _executar_envio_aniversariantes_hoje(
                        df_hoje=hoje_df,
                        nome_igreja=nome_igreja,
                        slug=slug,
                        forcar=False,
                    )

                _renderizar_resultados_envio(resultados)

            if reenviar_forcado:
                with st.spinner("Reenviando mensagens..."):
                    resultados = _executar_envio_aniversariantes_hoje(
                        df_hoje=hoje_df,
                        nome_igreja=nome_igreja,
                        slug=slug,
                        forcar=True,
                    )

                _renderizar_resultados_envio(resultados)

        st.divider()

        with st.expander("Como configurar o envio automático"):
            st.markdown("""
Crie ou atualize o arquivo:

`.streamlit/secrets.toml`

Com o seguinte conteúdo:

```toml
[whatsapp]
auto_enviar = true
access_token = "SEU_TOKEN_META"
phone_number_id = "SEU_PHONE_NUMBER_ID"
api_version = "v20.0"
modo_envio = "text"
```

Para usar template aprovado pela Meta, altere para:

```toml
[whatsapp]
auto_enviar = true
access_token = "SEU_TOKEN_META"
phone_number_id = "SEU_PHONE_NUMBER_ID"
api_version = "v20.0"
modo_envio = "template"
template_name = "feliz_aniversario"
language_code = "pt_BR"
```

Observações:

- `auto_enviar = true` ativa o envio automático quando o módulo for aberto.
- `modo_envio = "text"` envia mensagem livre, quando permitido pela janela de conversa.
- `modo_envio = "template"` usa modelo aprovado previamente na Meta.
- O controle interno evita reenviar a mesma mensagem para o mesmo aniversariante no mesmo dia.
""")
