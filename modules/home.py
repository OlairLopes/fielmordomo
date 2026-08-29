"""
Tela inicial da igreja - logo centralizado + KPIs.
"""

import datetime
import base64
import html
import re
import pandas as pd
import streamlit as st

from data.repository import (
    carregar_lancamentos, carregar_cadastros,
    obter_logo_igreja, obter_logo_sistema,
)
from utils.helpers import formatar_moeda, slug_da_sessao
from utils.planos import obter_plano, texto_limite


MESES_PT_BR = [
    "", "Janeiro", "Fevereiro", "Marco", "Abril", "Maio", "Junho",
    "Julho", "Agosto", "Setembro", "Outubro", "Novembro", "Dezembro",
]
MIMES_IMAGEM = {
    "png": "image/png",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "webp": "image/webp",
}
COR_HEX_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")


def _html(valor):
    return html.escape(str(valor if valor is not None else ""), quote=True)


def _img_b64(dados, ext):
    ext = str(ext or "").strip().lower().replace(".", "")
    mime = MIMES_IMAGEM.get(ext)
    if not mime or not isinstance(dados, (bytes, bytearray, memoryview)):
        return ""
    return "data:" + mime + ";base64," + base64.b64encode(dados).decode()


def render():
    slug   = slug_da_sessao()
    igreja = st.session_state.get("igreja", {})
    if not isinstance(igreja, dict):
        igreja = {}
    nome_igreja = _html(igreja.get("nome", "FielMordomo"))

    # ── Logo grande centralizado ──────────────────────────────────────────
    logo_r = obter_logo_igreja(slug) or obter_logo_sistema()

    if logo_r:
        dados, ext = logo_r
        img_src = _img_b64(dados, ext)
    else:
        img_src = ""

    if img_src:
        st.markdown(f"""
        <div style="display:flex;flex-direction:column;align-items:center;
                    justify-content:center;padding:40px 20px 30px 20px">
            <img src="{img_src}"
                 style="max-width:260px;max-height:200px;object-fit:contain;
                        filter:drop-shadow(0 4px 12px rgba(6,27,68,0.15))"/>
            <h2 style="color:#061B44;margin:20px 0 4px 0;font-weight:700;
                       font-size:1.8rem;text-align:center">
                {nome_igreja}
            </h2>
            <p style="color:#888;font-size:0.95rem;margin:0;text-align:center">
                Gestao financeira da igreja
            </p>
        </div>
        """, unsafe_allow_html=True)
    else:
        st.markdown(f"""
        <div style="display:flex;flex-direction:column;align-items:center;
                    justify-content:center;padding:60px 20px 40px 20px">
            <div style="font-size:3.5rem;font-weight:800;color:#061B44;
                        letter-spacing:-1px">FielMordomo</div>
            <h2 style="color:#061B44;margin:20px 0 4px 0;font-weight:700;
                       font-size:1.6rem;text-align:center">
                {nome_igreja}
            </h2>
            <p style="color:#888;font-size:0.95rem;margin:0;text-align:center">
                Gestao financeira da igreja
            </p>
        </div>
        """, unsafe_allow_html=True)

    st.divider()

    # ── KPIs do mes corrente ──────────────────────────────────────────────
    df_lanc = carregar_lancamentos(slug)
    df_cad  = carregar_cadastros(slug)

    hoje = datetime.date.today()
    ini_mes = hoje.replace(day=1)

    colunas_lanc = {"data", "valor", "tipo"}
    if not df_lanc.empty and colunas_lanc.issubset(df_lanc.columns):
        datas_originais = df_lanc["data"].copy()
        valores_originais = df_lanc["valor"].copy()
        df_lanc["data"] = pd.to_datetime(df_lanc["data"], errors="coerce")
        valores_numericos = pd.to_numeric(df_lanc["valor"], errors="coerce")
        qtd_datas_invalidas = int(
            (datas_originais.notna() & datas_originais.astype(str).str.strip().ne("") & df_lanc["data"].isna()).sum()
        )
        qtd_valores_invalidos = int(
            (valores_originais.notna() & valores_originais.astype(str).str.strip().ne("") & valores_numericos.isna()).sum()
        )
        df_lanc["valor"] = valores_numericos.fillna(0.0)
        df_mes = df_lanc[
            (df_lanc["data"] >= pd.Timestamp(ini_mes)) &
            (df_lanc["data"] <= pd.Timestamp(hoje))
        ]
        tipos = df_mes["tipo"].fillna("").astype(str).str.strip().str.upper()
        ent_mes = df_mes[tipos == "ENTRADA"]["valor"].sum()
        sai_mes = df_mes[tipos == "SAIDA"]["valor"].sum()
        sal_mes = ent_mes - sai_mes
        n_lanc_mes = len(df_mes)
    else:
        ent_mes = sai_mes = sal_mes = 0.0
        n_lanc_mes = 0
        qtd_datas_invalidas = qtd_valores_invalidos = 0
        if not df_lanc.empty:
            st.warning("Nao foi possivel calcular os indicadores: existem colunas financeiras ausentes.")

    if not df_cad.empty and "tipo_cadastro" in df_cad.columns:
        tipos_cadastro = df_cad["tipo_cadastro"].fillna("").astype(str).str.strip().str.upper()
        membros = df_cad[tipos_cadastro == "MEMBRO"]
        qtd_membros = len(membros)
        if "situacao" in membros.columns:
            situacoes = membros["situacao"].fillna("").astype(str).str.strip().str.upper()
            qtd_membros_ativos = int((situacoes == "ATIVO").sum())
        else:
            qtd_membros_ativos = qtd_membros
    else:
        qtd_membros = 0
        qtd_membros_ativos = 0

    plano    = igreja.get("plano", "basico")
    p_info   = obter_plano(plano)
    lim_txt  = texto_limite(plano)
    mes_ano = f"{MESES_PT_BR[hoje.month]}/{hoje.year}"

    if qtd_datas_invalidas or qtd_valores_invalidos:
        st.warning(
            "Existem lancamentos antigos com dados invalidos: "
            f"{qtd_datas_invalidas} data(s) e {qtd_valores_invalidos} valor(es). "
            "Revise esses registros para manter os indicadores confiaveis."
        )

    st.markdown(f"""
    <h4 style="color:#061B44;margin:18px 0 12px 0">
        📊 Resumo de {mes_ano}
    </h4>
    """, unsafe_allow_html=True)

    c1, c2, c3, c4 = st.columns(4)

    cor_saldo = "#1E73BE" if sal_mes >= 0 else "#C62828"
    with c1:
        st.markdown(f"""
        <div style="background:white;border-radius:12px;padding:16px 18px;
                    box-shadow:0 2px 6px rgba(0,0,0,0.08);
                    border-left:4px solid {cor_saldo};height:100%">
            <div style="font-size:0.72rem;font-weight:600;color:#888;
                        text-transform:uppercase;letter-spacing:0.05em">Saldo do mes</div>
            <div style="font-size:1.35rem;font-weight:700;color:{cor_saldo};
                        line-height:1.2;margin-top:4px">{formatar_moeda(sal_mes)}</div>
        </div>
        """, unsafe_allow_html=True)

    with c2:
        st.markdown(f"""
        <div style="background:white;border-radius:12px;padding:16px 18px;
                    box-shadow:0 2px 6px rgba(0,0,0,0.08);
                    border-left:4px solid #1E73BE;height:100%">
            <div style="font-size:0.72rem;font-weight:600;color:#888;
                        text-transform:uppercase;letter-spacing:0.05em">Entradas do mes</div>
            <div style="font-size:1.35rem;font-weight:700;color:#1E73BE;
                        line-height:1.2;margin-top:4px">{formatar_moeda(ent_mes)}</div>
        </div>
        """, unsafe_allow_html=True)

    with c3:
        st.markdown(f"""
        <div style="background:white;border-radius:12px;padding:16px 18px;
                    box-shadow:0 2px 6px rgba(0,0,0,0.08);
                    border-left:4px solid #C62828;height:100%">
            <div style="font-size:0.72rem;font-weight:600;color:#888;
                        text-transform:uppercase;letter-spacing:0.05em">Saidas do mes</div>
            <div style="font-size:1.35rem;font-weight:700;color:#C62828;
                        line-height:1.2;margin-top:4px">{formatar_moeda(sai_mes)}</div>
        </div>
        """, unsafe_allow_html=True)

    with c4:
        st.markdown(f"""
        <div style="background:white;border-radius:12px;padding:16px 18px;
                    box-shadow:0 2px 6px rgba(0,0,0,0.08);
                    border-left:4px solid #F57C00;height:100%">
            <div style="font-size:0.72rem;font-weight:600;color:#888;
                        text-transform:uppercase;letter-spacing:0.05em">Lancamentos no mes / membros ativos</div>
            <div style="font-size:1.35rem;font-weight:700;color:#F57C00;
                        line-height:1.2;margin-top:4px">{n_lanc_mes} / {qtd_membros_ativos}</div>
            <div style="font-size:0.72rem;color:#888;margin-top:4px">
                {_html(qtd_membros)} membro(s) cadastrado(s) no total
            </div>
        </div>
        """, unsafe_allow_html=True)

    # ── Card do plano ─────────────────────────────────────────────────────
    cor_plano = str(p_info.get("cor", "#061B44"))
    if not COR_HEX_RE.fullmatch(cor_plano):
        cor_plano = "#061B44"
    cor_plano_fim = str(p_info.get("cor_fim", cor_plano))
    if not COR_HEX_RE.fullmatch(cor_plano_fim):
        cor_plano_fim = cor_plano
    nome_plano = _html(p_info.get("nome", "Basico"))
    preco_plano = _html(p_info.get("preco", ""))
    lim_txt = _html(lim_txt)

    st.markdown("")
    st.markdown(f"""
    <div style="background:linear-gradient(135deg,{cor_plano} 0%,{cor_plano_fim} 100%);
                border-radius:14px;padding:22px 26px;color:white;margin-top:14px;
                box-shadow:0 4px 14px rgba(6,27,68,0.25)">
        <div style="display:flex;justify-content:space-between;align-items:center;
                    flex-wrap:wrap;gap:10px">
            <div>
                <div style="font-size:0.72rem;text-transform:uppercase;
                            letter-spacing:0.08em;opacity:0.85">Plano atual</div>
                <div style="font-size:1.6rem;font-weight:700;margin-top:2px">
                    {nome_plano}
                </div>
                <div style="font-size:0.85rem;opacity:0.9;margin-top:4px">
                    Limite: {lim_txt} membros • {preco_plano}
                </div>
            </div>
            <div style="font-size:2.6rem;opacity:0.5">⛪</div>
        </div>
    </div>
    """, unsafe_allow_html=True)
