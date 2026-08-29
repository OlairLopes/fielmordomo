import datetime
import logging
import time

import pandas as pd
import streamlit as st

from data.repository import autenticar_igreja


AUTORIZACAO_TTL_SEGUNDOS = 5 * 60


def normalizar_data_digitada(texto: str) -> str:
    """Aceita datas digitadas somente com numeros (ex.: 26061979 ou 260679) e
    retorna no formato dd/mm/aaaa. Anos com 2 digitos sao expandidos para 4
    (00-49 -> 20xx, 50-99 -> 19xx). Entradas ja formatadas (com barra ou hifen)
    ou que nao tenham 6 ou 8 digitos sao devolvidas sem alteracao."""
    original = str(texto or "").strip()
    if not original or not original.isdigit():
        return original

    digitos = original
    if len(digitos) == 6:
        dia, mes, ano2 = digitos[:2], digitos[2:4], digitos[4:6]
        ano4 = f"20{ano2}" if int(ano2) < 50 else f"19{ano2}"
        digitos = dia + mes + ano4
    if len(digitos) == 8:
        return f"{digitos[0:2]}/{digitos[2:4]}/{digitos[4:8]}"
    return original


def formatar_moeda(valor) -> str:
    try:
        return f"R$ {float(valor):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except Exception:
        return "R$ 0,00"


def formatar_percentual(valor) -> str:
    try:
        return f"{float(valor):.1f}%"
    except Exception:
        return "0.0%"


def hoje() -> datetime.date:
    return datetime.date.today()


def inicio_mes() -> datetime.date:
    return hoje().replace(day=1)


def formatar_data(valor) -> str:
    """Converte uma data ISO (aaaa-mm-dd) ou objeto date/datetime para dd/mm/aaaa."""
    try:
        return datetime.date.fromisoformat(str(valor)).strftime("%d/%m/%Y")
    except Exception:
        return str(valor or "")


def preparar_df(df: pd.DataFrame) -> pd.DataFrame:
    v = df.copy()
    if "data" in v.columns:
        v["data"] = pd.to_datetime(v["data"], errors="coerce").dt.strftime("%d/%m/%Y").fillna("")
    if "valor" in v.columns:
        v["valor"] = pd.to_numeric(v["valor"], errors="coerce").fillna(0.0).apply(formatar_moeda)
    return v


def obter_ativos(df_cad: pd.DataFrame, tipo: str) -> pd.DataFrame:
    colunas = {"tipo_cadastro", "situacao", "id_cadastro", "nome"}
    if df_cad.empty or not colunas.issubset(df_cad.columns):
        return pd.DataFrame(columns=df_cad.columns)
    tipos = df_cad["tipo_cadastro"].fillna("").astype(str).str.strip().str.upper()
    situacoes = df_cad["situacao"].fillna("").astype(str).str.strip().str.upper()
    return (
        df_cad[(tipos == str(tipo).upper()) & (situacoes == "ATIVO")]
        .drop_duplicates("id_cadastro")
        .sort_values("nome")
    )


def montar_opcoes(df: pd.DataFrame) -> dict:
    return {
        f'{int(r["id_cadastro"])} - {r["nome"]}': r
        for _, r in df.iterrows()
        if pd.notna(r["id_cadastro"])
    }


def encontrar_chave(opcoes: dict, id_cad) -> str | None:
    try:
        target = int(id_cad)
    except (ValueError, TypeError):
        return None
    for chave, row in opcoes.items():
        try:
            if int(row["id_cadastro"]) == target:
                return chave
        except (ValueError, TypeError):
            continue
    return None


def _sanitizar_csv(valor):
    if isinstance(valor, str) and valor.lstrip().startswith(("=", "+", "-", "@")):
        return "'" + valor
    return valor


def gerar_csv(df: pd.DataFrame) -> bytes:
    seguro = df.copy()
    for coluna in seguro.select_dtypes(include=["object", "string"]).columns:
        seguro[coluna] = seguro[coluna].map(_sanitizar_csv)
    return seguro.to_csv(index=False).encode("utf-8-sig")


def data_iso(valor) -> str:
    """Normaliza uma data (date, datetime ou string dd/mm/aaaa ou aaaa-mm-dd)
    para o formato ISO aaaa-mm-dd. Retorna string vazia se nao reconhecer."""
    try:
        if isinstance(valor, datetime.datetime):
            return valor.date().isoformat()
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


def filtrar_matriculas_validas_na_data(matriculas: pd.DataFrame, data_referencia) -> pd.DataFrame:
    """Filtra matriculas vigentes na data de referencia, com base nas colunas
    data_inicio/data_fim (matricula ativa quando a data cai dentro do
    intervalo, ou quando o intervalo esta em aberto). Sem data de referencia
    valida, cai de volta ao flag booleano 'ativa'."""
    if matriculas.empty:
        return matriculas

    data_ref = data_iso(data_referencia)
    if not data_ref:
        return matriculas[matriculas["ativa"] == 1].copy()

    dados = matriculas.copy()
    if "data_inicio" not in dados.columns:
        dados["data_inicio"] = ""
    if "data_fim" not in dados.columns:
        dados["data_fim"] = ""
    inicio = dados["data_inicio"].apply(data_iso)
    fim = dados["data_fim"].apply(data_iso)

    validas = (inicio.eq("") | (inicio <= data_ref)) & (fim.eq("") | (fim >= data_ref))
    return dados[validas].copy()


def slug_da_sessao() -> str:
    igreja = st.session_state.get("igreja", {})
    if not isinstance(igreja, dict):
        return ""
    return str(igreja.get("slug", "") or "").strip().lower()


def confirmar_exclusao(key: str, label: str) -> bool:
    flag = f"_del_{key}"
    if st.button(label, key=key, type="secondary"):
        st.session_state[flag] = True
    if st.session_state.get(flag):
        st.warning("Tem certeza? Esta acao nao pode ser desfeita.")
        c1, c2 = st.columns(2)
        with c1:
            if st.button("Sim, excluir", key=f"{key}_sim", type="primary"):
                st.session_state[flag] = False
                return True
        with c2:
            if st.button("Cancelar", key=f"{key}_nao"):
                st.session_state[flag] = False
    return False


def solicitar_autorizacao(key: str, acao: str = "continuar") -> bool:
    """Solicita a senha da igreja e mantem autorizacao por cinco minutos."""
    flag_mostrar = f"_auth_mostrar_{key}"
    flag_ate = f"_auth_ate_{key}"
    agora = time.monotonic()

    if st.session_state.get(flag_ate, 0) > agora:
        return True
    st.session_state.pop(flag_ate, None)

    if not st.session_state.get(flag_mostrar):
        if st.button(f"Autorizar para {acao}", key=f"btn_auth_{key}", type="primary"):
            st.session_state[flag_mostrar] = True
            st.rerun()
        return False

    st.info("Digite a senha da igreja para autorizar esta acao.")
    senha = st.text_input(
        "Senha de autorizacao",
        type="password",
        key=f"senha_auth_{key}",
        placeholder="Digite sua senha...",
    )

    c1, c2 = st.columns(2)
    with c1:
        if st.button("Confirmar", key=f"confirmar_auth_{key}", type="primary"):
            slug = slug_da_sessao()
            if slug and autenticar_igreja(slug, senha):
                st.session_state[flag_mostrar] = False
                st.session_state[flag_ate] = agora + AUTORIZACAO_TTL_SEGUNDOS
                st.rerun()
            else:
                st.error("Senha incorreta. Tente novamente.")
    with c2:
        if st.button("Cancelar", key=f"cancelar_auth_{key}"):
            st.session_state[flag_mostrar] = False
            st.rerun()

    return False
