import datetime
import base64
import html
import io
import logging
import os
import re
import unicodedata
import urllib.parse

import pandas as pd
import requests
import streamlit as st
import streamlit.components.v1 as components

from data.models import Lancamento
from data.repository import (
    carregar_cadastros, carregar_lancamentos,
    inserir_lancamento, inserir_lancamentos_lote, atualizar_lancamento, excluir_lancamento,
    obter_logo_igreja, listar_subcategorias_despesa, obter_config_igreja,
)
from utils.helpers import (
    formatar_moeda, preparar_df, obter_ativos, montar_opcoes,
    encontrar_chave, confirmar_exclusao, gerar_csv,
    slug_da_sessao, solicitar_autorizacao,
)
from utils.planos import tem_lancamento_lote, obter_plano, proximo_plano

CATEGORIAS_ENTRADA = [
    "Campanha",
    "Dizimo",
    "Missao",
    "Oferta",
    "Oferta Culto Missões",
    "Oferta Culto Jovens",
    "Oferta Culto Senhoras",
    "Oferta Culto Senhores",
    "Oferta Escola Bíblica",
    "Oferta Culto Infantil",
    "Revista EBD",
    "Saldo ano anterior",
]
FORMAS_PAGAMENTO = [
    "Pix", "Dinheiro", "Transferencia", "Boleto", "Cheque",
    "Cartao Debito", "Cartao Credito",
]
TIPOS_VINCULO = ["Nenhum", "Membro", "Fornecedor"]
MESES_PDF_PIX = {
    "jan": 1, "fev": 2, "mar": 3, "abr": 4,
    "mai": 5, "jun": 6, "jul": 7, "ago": 8,
    "set": 9, "out": 10, "nov": 11, "dez": 12,
}

LOGGER = logging.getLogger(__name__)
API_VERSION_RE = re.compile(r"^v\d+\.\d+$")
PHONE_NUMBER_ID_RE = re.compile(r"^\d+$")


# ═══════════════════════════════════════════════════════════════════════
# Helpers de formatacao e sessao (inalterados do original)
# ═══════════════════════════════════════════════════════════════════════

def _rotulo_vinculo(tipo):
    return "Fornecedor (empresa)" if tipo == "Fornecedor" else tipo


def _ck(sufixo, slug):
    return f"df_{sufixo}_{slug}"


def _sk(sufixo, slug):
    return f"{sufixo}_{slug}"


def _html(valor):
    return html.escape(str(valor if valor is not None else ""), quote=True)


def _invalida():
    keys_to_remove = [k for k in list(st.session_state.keys()) if k.startswith("df_")]
    for k in keys_to_remove:
        st.session_state.pop(k, None)


def _get_cad(slug):
    k = _ck("cad", slug)
    if k not in st.session_state:
        st.session_state[k] = carregar_cadastros(slug)
    return st.session_state[k]


def _get_lanc(slug):
    return carregar_lancamentos(slug)


def _logo_base64(slug):
    resultado = obter_logo_igreja(slug)
    if resultado:
        dados, ext = resultado
        b64 = base64.b64encode(dados).decode()
        mime = "image/jpeg" if ext in ("jpg", "jpeg") else f"image/{ext}"
        return f"data:{mime};base64,{b64}"
    return None


def _opcoes_com_registro_atual(df_ativos, id_atual, nome_atual, tipo_atual):
    opcoes = montar_opcoes(df_ativos) if not df_ativos.empty else {}
    chave_atual = encontrar_chave(opcoes, id_atual)

    if chave_atual:
        return opcoes, chave_atual

    if pd.notna(id_atual) and str(nome_atual or "").strip():
        chave_atual = f"{nome_atual} (cadastro atual/inativo)"
        opcoes[chave_atual] = {
            "id_cadastro": int(id_atual),
            "nome": nome_atual,
            "tipo_cadastro": tipo_atual,
        }

    return opcoes, chave_atual


def _limpar_tel(tel):
    return "".join(c for c in str(tel) if c.isdigit())


def _normalizar_tel_brasil(tel):
    tel_limpo = _limpar_tel(tel)
    if not tel_limpo:
        return ""
    while tel_limpo.startswith("0"):
        tel_limpo = tel_limpo[1:]
    if len(tel_limpo) in (10, 11):
        tel_limpo = "55" + tel_limpo
    return tel_limpo if len(tel_limpo) in (12, 13) and tel_limpo.startswith("55") else ""


def _assinatura_igreja(slug):
    return obter_config_igreja(slug, "nome_assinatura_comprovante", "Responsavel")


def _subcategorias_despesa_seguras(slug):
    try:
        return listar_subcategorias_despesa(slug)
    except Exception:
        LOGGER.exception("Nao foi possivel carregar subcategorias de despesa.")
        st.warning("Nao foi possivel carregar as subcategorias de despesa.")
        return []


def _valor_texto(valor):
    return "" if pd.isna(valor) else str(valor or "")


def _parse_data_digitada(texto):
    """Converte texto digitado (com ou sem barras) em data.

    Aceita "29/08/2026", "29082026" ou "290826" (ano com 2 digitos).
    Retorna None se o texto estiver vazio ou nao formar uma data valida.
    """
    digitos = re.sub(r"\D", "", texto or "")
    if not digitos:
        return None
    if len(digitos) == 6:
        digitos = digitos[:4] + ("20" if digitos[4:6] < "70" else "19") + digitos[4:6]
    if len(digitos) != 8:
        return None
    try:
        return datetime.datetime.strptime(digitos, "%d%m%Y").date()
    except ValueError:
        return None


def _normalizar_texto_importacao(valor):
    texto = str(valor if valor is not None else "").strip().lower()
    texto = unicodedata.normalize("NFKD", texto)
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    texto = re.sub(r"[^a-z0-9]+", " ", texto)
    return re.sub(r"\s+", " ", texto).strip()


def _ler_csv_pix(arquivo):
    dados = arquivo.getvalue()
    for encoding in ("utf-8-sig", "utf-8", "latin1"):
        try:
            return pd.read_csv(io.BytesIO(dados), sep=None, engine="python", encoding=encoding)
        except Exception:
            logging.exception("Erro ignorado silenciosamente")
            continue
    raise ValueError("Nao foi possivel ler o CSV. Verifique o arquivo ou a codificacao.")


def _ano_periodo_pdf_pix(texto):
    match = re.search(r"Periodo:\s*\d{2}/\d{2}/(\d{4})\s*-\s*\d{2}/\d{2}/(\d{4})", texto)
    if not match:
        match = re.search(r"Per\S*odo:\s*\d{2}/\d{2}/(\d{4})\s*-\s*\d{2}/\d{2}/(\d{4})", texto)
    if match:
        return int(match.group(2))
    return datetime.date.today().year


def _extrair_nome_pdf_pix(trecho):
    antes_valor = re.split(r"\s+R\$\s*[\d.]+,\d{2}", trecho, maxsplit=1)[0]
    antes_valor = re.sub(r"\s+[\u2022*]{3}\.\d{3}\.\d{3}-[\u2022*]{2}.*$", "", antes_valor)
    antes_valor = re.sub(r"\s+\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2}.*$", "", antes_valor)
    antes_valor = re.sub(r"^\d{2}\.\d{3}\.\d{3}\s+", "", antes_valor)
    return re.sub(r"\s+", " ", antes_valor).strip()


def _extrair_pdf_pix(arquivo):
    try:
        from pypdf import PdfReader
    except ImportError as ex:
        raise ValueError(
            "Para importar PDF, adicione pypdf ao requirements.txt."
        ) from ex

    reader = PdfReader(io.BytesIO(arquivo.getvalue()))
    texto = "\n".join((page.extract_text() or "") for page in reader.pages)
    if not texto.strip():
        raise ValueError("O PDF nao possui texto extraivel. Converta para CSV ou use OCR.")

    ano = _ano_periodo_pdf_pix(texto)
    registros = []
    for linha in texto.splitlines():
        linha = re.sub(r"\s+", " ", linha).strip()
        if not re.match(r"^\d{2}/[A-Za-z\u00C0-\u00FF]{3}\b", linha):
            continue
        data_match = re.match(r"^(\d{2})/([A-Za-z\u00C0-\u00FF]{3})\s+", linha)
        tx_match = re.search(r"\b(E[A-Za-z0-9]{20,})\b\s+(.+)$", linha)
        valores = re.findall(r"R\$\s*([\d.]+,\d{2})", linha)
        if not data_match or not tx_match or len(valores) < 2:
            continue
        mes = MESES_PDF_PIX.get(_normalizar_texto_importacao(data_match.group(2))[:3])
        if not mes:
            continue
        dia = int(data_match.group(1))
        try:
            data = datetime.date(ano, mes, dia)
        except ValueError:
            continue
        nome = _extrair_nome_pdf_pix(tx_match.group(2))
        if not nome:
            continue
        registros.append({
            "data": data.strftime("%d/%m/%Y"),
            "membro": nome,
            "valor": valores[-1],
            "transacao_pix": tx_match.group(1),
        })

    if not registros:
        raise ValueError("Nao encontrei recebimentos Pix no formato esperado deste PDF.")
    return pd.DataFrame(registros)


def _ler_arquivo_pix(arquivo):
    nome = str(getattr(arquivo, "name", "") or "").lower()
    if nome.endswith(".pdf"):
        return _extrair_pdf_pix(arquivo)
    return _ler_csv_pix(arquivo)


def _detectar_coluna(colunas, candidatos):
    normalizadas = {_normalizar_texto_importacao(col): col for col in colunas}
    for candidato in candidatos:
        alvo = _normalizar_texto_importacao(candidato)
        for normalizada, original in normalizadas.items():
            if alvo in normalizada:
                return original
    return colunas[0] if colunas else None


def _valor_importacao(valor):
    texto = str(valor if valor is not None else "").strip()
    texto = texto.replace("R$", "").replace(" ", "")
    negativo = texto.startswith("(") and texto.endswith(")")
    texto = texto.strip("()")
    if "," in texto:
        texto = texto.replace(".", "").replace(",", ".")
    texto = re.sub(r"[^0-9.\-]", "", texto)
    try:
        numero = float(texto)
    except ValueError:
        return 0.0
    if negativo:
        numero = -abs(numero)
    return abs(numero)


def _preparar_importacao_dizimos_pix(
    df_csv, membros, df_lanc, col_data, col_nome, col_valor, col_transacao=None
):
    mapa_membros = {}
    for _, membro in membros.iterrows():
        nome = str(membro.get("nome", "") or "")
        chave = _normalizar_texto_importacao(nome)
        if chave:
            mapa_membros[chave] = membro

    existentes = set()
    transacoes_existentes = set()
    if not df_lanc.empty:
        base = df_lanc.copy()
        base["data_key"] = pd.to_datetime(base["data"], errors="coerce").dt.date
        base["valor_key"] = pd.to_numeric(base["valor"], errors="coerce").round(2)
        if "descricao" in base.columns:
            transacoes_existentes = {
                tx for desc in base["descricao"].fillna("").astype(str)
                for tx in re.findall(r"\bE[A-Za-z0-9]{20,}\b", desc)
            }
        ids = pd.to_numeric(base.get("id_cadastro", pd.Series(dtype=float)), errors="coerce")
        for _, row in base.iterrows():
            if str(row.get("tipo", "")).strip() != "Entrada":
                continue
            if str(row.get("categoria", "")).strip() != "Dizimo":
                continue
            if str(row.get("forma_pagamento", "")).strip() != "Pix":
                continue
            id_cadastro = ids.loc[row.name] if row.name in ids.index else pd.NA
            if pd.isna(row.get("data_key")) or pd.isna(id_cadastro):
                continue
            existentes.add((row["data_key"], int(id_cadastro), float(row["valor_key"])))

    linhas = []
    lancamentos = []
    for idx, row in df_csv.iterrows():
        data = pd.to_datetime(row.get(col_data), errors="coerce", dayfirst=True)
        valor = _valor_importacao(row.get(col_valor))
        nome_bruto = str(row.get(col_nome, "") or "").strip()
        transacao = str(row.get(col_transacao, "") or "").strip() if col_transacao else ""
        membro = mapa_membros.get(_normalizar_texto_importacao(nome_bruto))

        status = "Pronto"
        motivo = ""
        if pd.isna(data):
            status, motivo = "Ignorado", "Data invalida"
        elif valor <= 0:
            status, motivo = "Ignorado", "Valor invalido"
        elif membro is None:
            status, motivo = "Ignorado", "Membro nao encontrado pelo nome"
        elif transacao and transacao in transacoes_existentes:
            status, motivo = "Ignorado", "Transacao Pix ja importada"
        else:
            chave = (data.date(), int(membro["id_cadastro"]), round(float(valor), 2))
            if chave in existentes:
                status, motivo = "Ignorado", "Duplicado provavel"

        if status == "Pronto":
            descricao = "Importado de Pix"
            if transacao:
                descricao += f" - {transacao}"
            lancamentos.append(Lancamento(
                data=data.date(),
                tipo="Entrada",
                categoria="Dizimo",
                valor=float(valor),
                descricao=descricao,
                forma_pagamento="Pix",
                id_cadastro=int(membro["id_cadastro"]),
                nome_cadastro=str(membro["nome"]),
                tipo_cadastro=str(membro["tipo_cadastro"]),
            ))

        linhas.append({
            "Linha": idx + 1,
            "Data": data.strftime("%d/%m/%Y") if pd.notna(data) else "",
            "Membro informado": nome_bruto,
            "Membro vinculado": str(membro["nome"]) if membro is not None else "",
            "Valor": formatar_moeda(valor),
            "Transacao Pix": transacao,
            "Status": status,
            "Motivo": motivo,
        })

    return pd.DataFrame(linhas), lancamentos


def _link_whatsapp(tel, mensagem):
    tel_limpo = _normalizar_tel_brasil(tel)
    if not tel_limpo:
        return ""
    msg_enc = urllib.parse.quote(mensagem)
    return f"https://wa.me/{tel_limpo}?text={msg_enc}"


def _config_whatsapp():
    try:
        cfg = st.secrets.get("whatsapp", {})
    except Exception:
        cfg = {}

    resultado = {
        "access_token": str(
            cfg.get("access_token", "") or os.environ.get("WHATSAPP_ACCESS_TOKEN", "")
        ).strip(),
        "phone_number_id": str(
            cfg.get("phone_number_id", "") or os.environ.get("WHATSAPP_PHONE_NUMBER_ID", "")
        ).strip(),
        "api_version": str(cfg.get("api_version", "v20.0")).strip(),
    }
    if not PHONE_NUMBER_ID_RE.fullmatch(resultado["phone_number_id"]):
        resultado["phone_number_id"] = ""
    if not API_VERSION_RE.fullmatch(resultado["api_version"]):
        resultado["api_version"] = "v20.0"
    return resultado


def _whatsapp_api_configurada():
    cfg = _config_whatsapp()
    return bool(cfg["access_token"] and cfg["phone_number_id"])


def _enviar_whatsapp_texto_api(telefone, mensagem):
    cfg = _config_whatsapp()
    numero = _normalizar_tel_brasil(telefone)
    if not numero:
        return False, "Telefone invalido ou vazio."
    if not cfg["access_token"] or not cfg["phone_number_id"]:
        return False, "WhatsApp Cloud API nao configurada no st.secrets."

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
        "text": {"preview_url": False, "body": mensagem},
    }

    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=25)
        if 200 <= resp.status_code < 300:
            return True, "Comprovante enviado com sucesso."
        LOGGER.warning("WhatsApp Cloud API retornou HTTP %s: %s", resp.status_code, resp.text[:1000])
        return False, f"Nao foi possivel enviar o comprovante (HTTP {resp.status_code})."
    except requests.RequestException:
        LOGGER.exception("Falha ao enviar comprovante pela WhatsApp Cloud API.")
        return False, "Falha de comunicacao com o WhatsApp. Tente novamente."


def _telefone_do_lancamento(df_cad, lancamento):
    id_cadastro = lancamento.get("id_cadastro")
    if pd.isna(id_cadastro):
        return ""
    try:
        id_cadastro = int(id_cadastro)
    except Exception:
        return ""
    if df_cad.empty or "id_cadastro" not in df_cad.columns:
        return ""
    ids = pd.to_numeric(df_cad["id_cadastro"], errors="coerce")
    linha = df_cad[ids == id_cadastro]
    if linha.empty or "telefone" not in linha.columns:
        return ""
    return str(linha.iloc[0].get("telefone", "") or "")


def _montar_mensagem_comprovante(lancamento, igreja, slug):
    nome_igreja = igreja.get("nome", "Igreja")
    data_fmt = pd.to_datetime(lancamento.get("data"), errors="coerce")
    data_str = data_fmt.strftime("%d/%m/%Y") if pd.notna(data_fmt) else "-"

    id_lanc = lancamento.get("id_lancamento", 0)
    tipo = lancamento.get("tipo", "-")
    categoria = lancamento.get("categoria", "-")
    subcategoria = lancamento.get("subcategoria", "") or ""
    descricao = lancamento.get("descricao", "") or "-"
    forma_pag = lancamento.get("forma_pagamento", "Dinheiro") or "Dinheiro"
    valor = formatar_moeda(lancamento.get("valor", 0))
    nome_vinc = lancamento.get("nome_cadastro", "") or "Nao vinculado"

    linhas = [
        f"Comprovante de lancamento - {nome_igreja}",
        "",
        f"Cupom: #{str(id_lanc).zfill(6)}",
        f"Data: {data_str}",
        f"Tipo: {tipo}",
        f"Categoria: {categoria}",
    ]
    if subcategoria:
        linhas.append(f"Subcategoria: {subcategoria}")
    linhas.extend([
        f"Vinculado: {nome_vinc}",
        f"Descricao: {descricao}",
        f"Pagamento: {forma_pag}",
        f"Valor: {valor}",
        "",
        "Mensagem enviada pelo sistema FielMordomo.",
        _assinatura_igreja(slug),
    ])
    return "\n".join(linhas)


# ═══════════════════════════════════════════════════════════════════════
# HTML de comprovantes (inalterados - mantidos do original)
# ═══════════════════════════════════════════════════════════════════════

def _gerar_html_comprovante(lancamento, igreja, slug, auto_imprimir=True):
    """Gera o HTML do comprovante. auto_imprimir=False para preview."""
    nome_igreja = _html(igreja.get("nome", "Igreja"))
    data_fmt = pd.to_datetime(lancamento.get("data"), errors="coerce")
    data_str = data_fmt.strftime("%d/%m/%Y") if pd.notna(data_fmt) else "-"
    data_emissao = datetime.datetime.now().strftime("%d/%m/%Y %H:%M:%S")
    id_lanc = lancamento.get("id_lancamento", 0)
    tipo = _html(lancamento.get("tipo", "-"))
    categoria = _html(lancamento.get("categoria", "-"))
    subcategoria = _html(lancamento.get("subcategoria", "") or "")
    descricao = _html(lancamento.get("descricao", "") or "")
    valor = _html(formatar_moeda(lancamento.get("valor", 0)))
    nome_vinc = _html(lancamento.get("nome_cadastro", "") or "Nao vinculado")
    tipo_vinc = _html(lancamento.get("tipo_cadastro", "") or "")
    forma_pag = _html(lancamento.get("forma_pagamento", "Dinheiro") or "Dinheiro")

    logo_b64 = _logo_base64(slug)
    logo_html = ""
    if logo_b64:
        logo_html = (
            '<div style="text-align:center;margin-bottom:6px">'
            f'<img src="{logo_b64}" style="max-height:60px;max-width:160px;object-fit:contain"/>'
            '</div>'
        )

    sep = "-" * 40
    sep2 = "=" * 40
    vinc_str = nome_vinc + (f" ({tipo_vinc})" if tipo_vinc else "")
    nome_assinatura = _html(_assinatura_igreja(slug))

    subcat_html = ""
    if subcategoria:
        subcat_html = (
            '<div class="linha"><span class="label">Subcategoria</span>'
            f'<span class="valor">{subcategoria}</span></div>'
        )

    descricao_html = descricao if descricao else "-"

    # Script de auto-imprimir SO se auto_imprimir=True
    auto_print_script = ""
    if auto_imprimir:
        auto_print_script = (
            "<script>window.onload = function() { "
            "setTimeout(function(){ window.print(); }, 800); };</script>"
        )

    return f"""
<!DOCTYPE html><html lang="pt-BR"><head><meta charset="UTF-8"/>
<title>Cupom #{str(id_lanc).zfill(6)}</title>
<style>
* {{ box-sizing: border-box; margin: 0; padding: 0; }}
body {{ background: #f0f0f0; display: flex; justify-content: center; padding: 20px; }}
.cupom {{ background: white; width: 320px; padding: 16px 14px;
         font-family: 'Courier New', Courier, monospace; font-size: 12px; color: #111;
         box-shadow: 2px 2px 8px rgba(0,0,0,0.15); }}
.centro {{ text-align: center; }}
.nome-igreja {{ font-size: 14px; font-weight: bold; text-align: center;
               text-transform: uppercase; letter-spacing: 0.05em; margin: 6px 0 2px; }}
.subtitulo {{ text-align: center; font-size: 10px; color: #555; margin-bottom: 4px; }}
.sep {{ color: #aaa; margin: 6px 0; letter-spacing: -1px; }}
.sep2 {{ color: #333; margin: 6px 0; letter-spacing: -1px; }}
.linha {{ display: flex; justify-content: space-between; margin: 3px 0; font-size: 11px; }}
.linha .label {{ color: #555; }}
.linha .valor {{ font-weight: 600; text-align: right; max-width: 55%; word-break: break-word; }}
.tipo-badge {{ text-align: center; font-size: 13px; font-weight: bold;
              letter-spacing: 0.1em; padding: 4px 0; margin: 4px 0; }}
.valor-total {{ text-align: center; font-size: 20px; font-weight: bold;
               margin: 8px 0 4px; letter-spacing: 0.02em; }}
.cupom-num {{ text-align: center; font-size: 10px; color: #777; margin-bottom: 4px; }}
.assinatura-bloco {{ margin-top: 12px; display: flex; justify-content: center; gap: 20px; }}
.assinatura-item {{ flex: 1; max-width: 45%; }}
.assinatura-linha {{ border-top: 1px dashed #aaa; margin-top: 28px; padding-top: 4px;
                    text-align: center; font-size: 10px; color: #555;
                    width: 80%; margin-left: auto; margin-right: auto; }}
.rodape {{ text-align: center; font-size: 9px; color: #888; margin-top: 8px; }}
@media print {{
  body {{ background: white; padding: 0; }}
  .cupom {{ box-shadow: none; width: 100%; max-width: 320px; margin: 0 auto; }}
  .btn-imprimir {{ display: none !important; }}
}}
</style></head><body>

<div style="text-align:center;margin-bottom:12px">
  <button class="btn-imprimir" onclick="window.print()"
    style="background:#061B44;color:white;border:none;padding:8px 24px;
           border-radius:6px;font-size:13px;cursor:pointer;font-weight:600">
    Imprimir cupom
  </button>
</div>

<div class="cupom">
  {logo_html}
  <div class="nome-igreja">{nome_igreja}</div>
  <div class="subtitulo">Comprovante de Lancamento</div>
  <div class="sep centro">{sep}</div>
  <div class="cupom-num">CUPOM N: {str(id_lanc).zfill(6)}</div>
  <div class="cupom-num">Emitido: {data_emissao}</div>
  <div class="sep centro">{sep}</div>
  <div class="tipo-badge">*** {tipo.upper()} - {categoria.upper()} ***</div>
  <div class="sep centro">{sep}</div>
  <div class="linha"><span class="label">Data</span><span class="valor">{data_str}</span></div>
  <div class="linha"><span class="label">Categoria</span><span class="valor">{categoria}</span></div>
  {subcat_html}
  <div class="linha"><span class="label">Vinculado</span><span class="valor">{vinc_str}</span></div>
  <div class="linha"><span class="label">Descricao</span><span class="valor">{descricao_html}</span></div>
  <div class="linha"><span class="label">Pagamento</span><span class="valor">{forma_pag}</span></div>
  <div class="sep2 centro">{sep2}</div>
  <div class="subtitulo">VALOR TOTAL</div>
  <div class="valor-total">{valor}</div>
  <div class="sep2 centro">{sep2}</div>
  <div class="assinatura-bloco">
    <div class="assinatura-item"><div class="assinatura-linha">Tesoureiro</div></div>
    <div class="assinatura-item"><div class="assinatura-linha">{nome_assinatura}</div></div>
  </div>
  <div class="sep centro">{sep}</div>
  <div class="rodape">FielMordomo - Sistema de Gestao Financeira</div>
  <div class="rodape">para Igrejas</div>
</div>

{auto_print_script}
</body></html>"""


def _gerar_html_comprovante_lote(itens, igreja, slug, data_str, vinc_str,
                                  forma_pag, numero_lote):
    nome_igreja = _html(igreja.get("nome", "Igreja"))
    data_emissao = datetime.datetime.now().strftime("%d/%m/%Y %H:%M:%S")
    total = sum(item["valor"] for item in itens)

    logo_b64 = _logo_base64(slug)
    logo_html = ""
    if logo_b64:
        logo_html = (
            '<div style="text-align:center;margin-bottom:6px">'
            f'<img src="{logo_b64}" style="max-height:60px;max-width:160px;object-fit:contain"/>'
            '</div>'
        )

    sep = "-" * 40
    sep2 = "=" * 40
    nome_assinatura = _html(_assinatura_igreja(slug))

    itens_html = ""
    for it in itens:
        rotulo = _html(it["categoria"])
        if it.get("subcategoria"):
            rotulo += " (" + _html(it["subcategoria"]) + ")"
        desc_extra = " - " + _html(it["descricao"]) if it.get("descricao") else ""
        itens_html += (
            '<div class="linha">'
            f'<span class="label">{rotulo}{desc_extra}</span>'
            f'<span class="valor">{_html(formatar_moeda(it["valor"]))}</span>'
            '</div>'
        )

    return f"""
<!DOCTYPE html><html lang="pt-BR"><head><meta charset="UTF-8"/>
<title>Cupom Lote #{_html(numero_lote)}</title>
<style>
* {{ box-sizing: border-box; margin: 0; padding: 0; }}
body {{ background: #f0f0f0; display: flex; justify-content: center; padding: 20px; }}
.cupom {{ background: white; width: 340px; padding: 16px 14px;
         font-family: 'Courier New', Courier, monospace; font-size: 12px; color: #111;
         box-shadow: 2px 2px 8px rgba(0,0,0,0.15); }}
.centro {{ text-align: center; }}
.nome-igreja {{ font-size: 14px; font-weight: bold; text-align: center;
               text-transform: uppercase; letter-spacing: 0.05em; margin: 6px 0 2px; }}
.subtitulo {{ text-align: center; font-size: 10px; color: #555; margin-bottom: 4px; }}
.sep {{ color: #aaa; margin: 6px 0; letter-spacing: -1px; }}
.sep2 {{ color: #333; margin: 6px 0; letter-spacing: -1px; }}
.linha {{ display: flex; justify-content: space-between; margin: 3px 0; font-size: 11px; }}
.linha .label {{ color: #555; flex: 1; padding-right: 8px; }}
.linha .valor {{ font-weight: 600; text-align: right; white-space: nowrap; }}
.tipo-badge {{ text-align: center; font-size: 12px; font-weight: bold;
              letter-spacing: 0.1em; padding: 4px 0; margin: 4px 0; }}
.valor-total {{ text-align: center; font-size: 20px; font-weight: bold;
               margin: 8px 0 4px; letter-spacing: 0.02em; }}
.cupom-num {{ text-align: center; font-size: 10px; color: #777; margin-bottom: 4px; }}
.info-bloco {{ font-size: 11px; margin: 4px 0; }}
.assinatura-bloco {{ margin-top: 12px; display: flex; justify-content: center; gap: 20px; }}
.assinatura-item {{ flex: 1; max-width: 45%; }}
.assinatura-linha {{ border-top: 1px dashed #aaa; margin-top: 28px; padding-top: 4px;
                    text-align: center; font-size: 10px; color: #555;
                    width: 80%; margin-left: auto; margin-right: auto; }}
.rodape {{ text-align: center; font-size: 9px; color: #888; margin-top: 8px; }}
@media print {{
  body {{ background: white; padding: 0; }}
  .cupom {{ box-shadow: none; width: 100%; max-width: 340px; margin: 0 auto; }}
  .btn-imprimir {{ display: none !important; }}
}}
</style></head><body>

<div style="text-align:center;margin-bottom:12px">
  <button class="btn-imprimir" onclick="window.print()"
    style="background:#061B44;color:white;border:none;padding:8px 24px;
           border-radius:6px;font-size:13px;cursor:pointer;font-weight:600">
    Imprimir cupom
  </button>
</div>

<div class="cupom">
  {logo_html}
  <div class="nome-igreja">{nome_igreja}</div>
  <div class="subtitulo">Comprovante Consolidado</div>
  <div class="sep centro">{sep}</div>
  <div class="cupom-num">LOTE: {_html(numero_lote)}</div>
  <div class="cupom-num">Emitido: {data_emissao}</div>
  <div class="sep centro">{sep}</div>
  <div class="info-bloco">
    <div class="linha"><span class="label">Data</span><span class="valor">{_html(data_str)}</span></div>
    <div class="linha"><span class="label">Vinculado</span><span class="valor">{_html(vinc_str)}</span></div>
    <div class="linha"><span class="label">Pagamento</span><span class="valor">{_html(forma_pag)}</span></div>
    <div class="linha"><span class="label">Itens</span><span class="valor">{len(itens)}</span></div>
  </div>
  <div class="sep centro">{sep}</div>
  <div class="tipo-badge">*** DETALHAMENTO ***</div>
  <div class="sep centro">{sep}</div>
  {itens_html}
  <div class="sep2 centro">{sep2}</div>
  <div class="subtitulo">VALOR TOTAL</div>
  <div class="valor-total">{_html(formatar_moeda(total))}</div>
  <div class="sep2 centro">{sep2}</div>
  <div class="assinatura-bloco">
    <div class="assinatura-item"><div class="assinatura-linha">Tesoureiro</div></div>
    <div class="assinatura-item"><div class="assinatura-linha">{nome_assinatura}</div></div>
  </div>
  <div class="sep centro">{sep}</div>
  <div class="rodape">FielMordomo - Sistema de Gestao Financeira</div>
</div>

<script>window.onload = function() {{ setTimeout(function(){{ window.print(); }}, 800); }};</script>
</body></html>"""


def _gerar_html_fechamento_caixa(lancamentos, igreja, slug, data_inicio, data_fim,
                                 forma_pagamento="Todas"):
    nome_igreja = _html(igreja.get("nome", "Igreja"))
    data_emissao = datetime.datetime.now().strftime("%d/%m/%Y %H:%M:%S")
    periodo = (
        data_inicio.strftime("%d/%m/%Y")
        if data_inicio == data_fim
        else f"{data_inicio.strftime('%d/%m/%Y')} a {data_fim.strftime('%d/%m/%Y')}"
    )

    df = lancamentos.copy()
    if df.empty:
        entradas = saidas = saldo = 0.0
        qtd = 0
    else:
        df["tipo_norm"] = df["tipo"].fillna("").astype(str).str.upper().str.strip()
        df["valor"] = pd.to_numeric(df["valor"], errors="coerce").fillna(0.0)
        entradas = float(df[df["tipo_norm"] == "ENTRADA"]["valor"].sum())
        saidas = float(df[df["tipo_norm"] == "SAIDA"]["valor"].sum())
        saldo = entradas - saidas
        qtd = len(df)

    logo_b64 = _logo_base64(slug)
    logo_html = ""
    if logo_b64:
        logo_html = (
            '<div style="text-align:center;margin-bottom:6px">'
            f'<img src="{logo_b64}" style="max-height:60px;max-width:160px;object-fit:contain"/>'
            '</div>'
        )

    sep = "-" * 42
    sep2 = "=" * 42

    def _resumo_formas_html(titulo, dataframe, total):
        html_secao = f'<div class="subsecao-titulo">{_html(titulo)}</div>'
        if dataframe.empty or "forma_pagamento" not in dataframe.columns:
            return (
                html_secao
                + '<div class="linha"><span class="label">Sem movimento</span>'
                '<span class="valor">R$ 0,00</span></div>'
                '<div class="linha total-pagamento"><span class="label">Total</span>'
                '<span class="valor">R$ 0,00</span></div>'
            )
        resumo_pag = (
            dataframe.assign(
                forma_pagamento=dataframe["forma_pagamento"]
                .fillna("")
                .astype(str)
                .str.strip()
                .replace("", "Nao informado")
            )
            .groupby("forma_pagamento", as_index=False)["valor"]
            .sum()
            .sort_values("valor", ascending=False)
        )
        linhas = []
        for _, row in resumo_pag.iterrows():
            linhas.append(
                '<div class="linha">'
                f'<span class="label">{_html(row["forma_pagamento"])}</span>'
                f'<span class="valor">{_html(formatar_moeda(row["valor"]))}</span>'
                '</div>'
            )
        linhas.append(
            '<div class="linha total-pagamento">'
            f'<span class="label">Total {len(dataframe)} lancamento(s)</span>'
            f'<span class="valor">{_html(formatar_moeda(total))}</span>'
            '</div>'
        )
        return html_secao + "".join(linhas)

    if df.empty:
        resumo_pag_html = (
            _resumo_formas_html("ENTRADAS", df, 0.0)
            + _resumo_formas_html("SAIDAS", df, 0.0)
        )
    else:
        resumo_pag_html = (
            _resumo_formas_html("ENTRADAS", df[df["tipo_norm"] == "ENTRADA"], entradas)
            + _resumo_formas_html("SAIDAS", df[df["tipo_norm"] == "SAIDA"], saidas)
        )

    def _item_fechamento_html(row):
        data_row = row.get("data_dt")
        data_txt = data_row.strftime("%d/%m") if pd.notna(data_row) else "--/--"
        id_txt = str(int(row["id_lancamento"])).zfill(6) if pd.notna(row.get("id_lancamento")) else "------"
        tipo = _html(row.get("tipo", "-"))
        categoria = _html(row.get("categoria", "-"))
        subcategoria = _html(row.get("subcategoria", "") or "")
        nome_vinc = _html(row.get("nome_cadastro", "") or "Sem vinculo")
        tipo_vinc = _html(row.get("tipo_cadastro", "") or "")
        vinculo = nome_vinc + (f" ({tipo_vinc})" if tipo_vinc else "")
        forma = _html(row.get("forma_pagamento", "") or "-")
        valor = _html(formatar_moeda(row.get("valor", 0)))
        desc = _html(row.get("descricao", "") or "")
        complemento = f" / {subcategoria}" if subcategoria else ""
        if desc:
            complemento += f" - {desc}"
        return (
            '<div class="item">'
            f'<div><strong>#{id_txt}</strong> {data_txt} - {tipo}</div>'
            f'<div>{categoria}{complemento}</div>'
            f'<div class="vinculo">Vinculado: {vinculo}</div>'
            f'<div class="linha"><span class="label">{forma}</span><span class="valor">{valor}</span></div>'
            '</div>'
        )

    def _secao_fechamento_html(titulo, dataframe, total):
        if dataframe.empty:
            return (
                f'<div class="secao-titulo">{_html(titulo)}</div>'
                '<div class="vazio">Sem lancamentos nesta secao.</div>'
                '<div class="linha total-secao"><span class="label">Total</span>'
                '<span class="valor">R$ 0,00</span></div>'
            )
        itens = "".join(_item_fechamento_html(row) for _, row in dataframe.iterrows())
        return (
            f'<div class="secao-titulo">{_html(titulo)}</div>'
            f"{itens}"
            '<div class="linha total-secao">'
            f'<span class="label">Total {len(dataframe)} lancamento(s)</span>'
            f'<span class="valor">{_html(formatar_moeda(total))}</span>'
            '</div>'
        )

    if df.empty:
        itens_html = '<div class="vazio">Sem lancamentos para os filtros selecionados.</div>'
    else:
        ordenado = df.copy()
        ordenado["data_dt"] = pd.to_datetime(ordenado["data"], errors="coerce")
        ordenado = ordenado.sort_values(["data_dt", "id_lancamento"], na_position="last")
        entradas_df = ordenado[ordenado["tipo_norm"] == "ENTRADA"]
        saidas_df = ordenado[ordenado["tipo_norm"] == "SAIDA"]
        outros_df = ordenado[~ordenado["tipo_norm"].isin(["ENTRADA", "SAIDA"])]
        itens_html = (
            _secao_fechamento_html("ENTRADAS", entradas_df, entradas)
            + _secao_fechamento_html("SAIDAS", saidas_df, saidas)
        )
        if not outros_df.empty:
            itens_html += _secao_fechamento_html(
                "OUTROS LANCAMENTOS",
                outros_df,
                float(outros_df["valor"].sum()),
            )

    responsavel = _html(_assinatura_igreja(slug))
    return f"""
<!DOCTYPE html><html lang="pt-BR"><head><meta charset="UTF-8"/>
<title>Fechamento de Caixa - 2a Via</title>
<style>
* {{ box-sizing: border-box; margin: 0; padding: 0; }}
body {{ background: #f0f0f0; display: flex; justify-content: center; padding: 20px; }}
.cupom {{ background: white; width: 360px; padding: 16px 14px;
         font-family: 'Courier New', Courier, monospace; font-size: 12px; color: #111;
         box-shadow: 2px 2px 8px rgba(0,0,0,0.15); }}
.centro {{ text-align: center; }}
.nome-igreja {{ font-size: 14px; font-weight: bold; text-align: center;
               text-transform: uppercase; letter-spacing: 0.05em; margin: 6px 0 2px; }}
.subtitulo {{ text-align: center; font-size: 10px; color: #555; margin-bottom: 4px; }}
.sep {{ color: #aaa; margin: 6px 0; letter-spacing: -1px; }}
.sep2 {{ color: #333; margin: 6px 0; letter-spacing: -1px; }}
.badge {{ text-align: center; font-size: 13px; font-weight: bold;
          letter-spacing: 0.08em; padding: 4px 0; margin: 4px 0; }}
.linha {{ display: flex; justify-content: space-between; gap: 8px; margin: 3px 0; font-size: 11px; }}
.linha .label {{ color: #555; }}
.linha .valor {{ font-weight: 700; text-align: right; }}
.valor-total {{ text-align: center; font-size: 20px; font-weight: bold; margin: 8px 0 4px; }}
.subsecao-titulo {{ font-size: 11px; font-weight: 800; margin-top: 7px; text-align: center; }}
.total-pagamento {{ border-top: 1px dashed #999; margin-bottom: 5px; padding-top: 4px; }}
.total-pagamento .label, .total-pagamento .valor {{ color: #111; font-weight: 800; }}
.item {{ border-top: 1px dashed #bbb; padding: 6px 0; font-size: 10px; }}
.item strong {{ font-size: 10px; }}
.secao-titulo {{ border-top: 2px solid #333; font-size: 12px; font-weight: 800;
                letter-spacing: .08em; margin-top: 8px; padding-top: 7px; text-align: center; }}
.total-secao {{ border-top: 1px solid #333; font-size: 12px; margin: 6px 0 8px; padding-top: 5px; }}
.total-secao .label, .total-secao .valor {{ color: #111; font-weight: 800; }}
.vinculo {{ color: #333; font-size: 10px; font-weight: 700; margin-top: 2px; word-break: break-word; }}
.vazio {{ text-align: center; color: #666; font-size: 10px; padding: 10px 0; }}
.assinatura-bloco {{ margin-top: 12px; display: flex; justify-content: center; gap: 18px; }}
.assinatura-item {{ flex: 1; max-width: 46%; }}
.assinatura-linha {{ border-top: 1px dashed #aaa; margin-top: 28px; padding-top: 4px;
                    text-align: center; font-size: 10px; color: #555; }}
.rodape {{ text-align: center; font-size: 9px; color: #888; margin-top: 8px; }}
@media print {{
  body {{ background: white; padding: 0; }}
  .cupom {{ box-shadow: none; width: 100%; max-width: 360px; margin: 0 auto; }}
  .btn-imprimir {{ display: none !important; }}
}}
</style></head><body>

<div style="text-align:center;margin-bottom:12px">
  <button class="btn-imprimir" onclick="window.print()"
    style="background:#061B44;color:white;border:none;padding:8px 24px;
           border-radius:6px;font-size:13px;cursor:pointer;font-weight:600">
    Imprimir 2a via
  </button>
</div>

<div class="cupom">
  {logo_html}
  <div class="nome-igreja">{nome_igreja}</div>
  <div class="subtitulo">Fechamento de Caixa</div>
  <div class="badge">*** 2a VIA ***</div>
  <div class="sep centro">{sep}</div>
  <div class="linha"><span class="label">Periodo</span><span class="valor">{_html(periodo)}</span></div>
  <div class="linha"><span class="label">Filtro pagamento</span><span class="valor">{_html(forma_pagamento)}</span></div>
  <div class="linha"><span class="label">Emitido</span><span class="valor">{_html(data_emissao)}</span></div>
  <div class="linha"><span class="label">Lancamentos</span><span class="valor">{qtd}</span></div>
  <div class="sep2 centro">{sep2}</div>
  <div class="linha"><span class="label">Entradas</span><span class="valor">{_html(formatar_moeda(entradas))}</span></div>
  <div class="linha"><span class="label">Saidas</span><span class="valor">{_html(formatar_moeda(saidas))}</span></div>
  <div class="subtitulo">SALDO DO FECHAMENTO</div>
  <div class="valor-total">{_html(formatar_moeda(saldo))}</div>
  <div class="sep2 centro">{sep2}</div>
  <div class="badge">FORMAS DE PAGAMENTO</div>
  {resumo_pag_html}
  <div class="sep centro">{sep}</div>
  <div class="badge">DETALHAMENTO</div>
  {itens_html}
  <div class="sep centro">{sep}</div>
  <div class="assinatura-bloco">
    <div class="assinatura-item"><div class="assinatura-linha">Tesoureiro</div></div>
    <div class="assinatura-item"><div class="assinatura-linha">{responsavel}</div></div>
  </div>
  <div class="rodape">FielMordomo - Sistema de Gestao Financeira para Igrejas</div>
</div>

<script>window.onload = function() {{ setTimeout(function(){{ window.print(); }}, 800); }};</script>
</body></html>"""


# ═══════════════════════════════════════════════════════════════════════
# MODAL: Novo lancamento
# ═══════════════════════════════════════════════════════════════════════

@st.dialog("➕ Novo lancamento", width="large")
def modal_novo_lancamento(slug, membros, fornec):
    """Modal para criar um novo lancamento (entrada ou saida)."""

    # Version counter para limpar widgets apos salvar
    if "mnl_ver" not in st.session_state:
        st.session_state["mnl_ver"] = 0
    ver = st.session_state["mnl_ver"]

    st.markdown("**Dados do lancamento**")

    col_data, col_tipo = st.columns(2)
    with col_data:
        data_l_texto = st.text_input(
            "Data",
            value="",
            placeholder="DD/MM/AAAA",
            help="Digite com ou sem as barras. Ex.: 29082026 ou 29/08/2026.",
            key=f"mnl_data_v{ver}",
        )
        data_l = _parse_data_digitada(data_l_texto)
        if data_l_texto and data_l is None:
            st.caption(":red[Data invalida.]")
    with col_tipo:
        tipo = st.selectbox("Tipo", ["Entrada", "Saida"], key=f"mnl_tipo_v{ver}")

    subcategoria_nl = ""

    if tipo == "Entrada":
        cat = st.selectbox("Categoria", CATEGORIAS_ENTRADA, key=f"mnl_cat_v{ver}")
    else:
        cat = "Despesa"
        st.text_input("Categoria", value="Despesa", disabled=True, key=f"mnl_cat_d_v{ver}")

        subcategorias = _subcategorias_despesa_seguras(slug)
        if subcategorias:
            subcategoria_nl = st.selectbox(
                "Subcategoria",
                [""] + subcategorias,
                key=f"mnl_subcat_v{ver}",
                help="Selecione a categoria detalhada da despesa.",
            )
        else:
            st.caption(
                "⚠️ Nenhuma subcategoria de despesa cadastrada. "
                "Peca ao administrador para adicionar."
            )

    # Definir vinculo padrao
    if tipo == "Entrada" and cat == "Dizimo":
        vinc_pad = "Membro"
    elif tipo == "Saida":
        vinc_pad = "Fornecedor"
    else:
        vinc_pad = "Nenhum"

    vincular = st.selectbox(
        "Vincular a",
        TIPOS_VINCULO,
        index=TIPOS_VINCULO.index(vinc_pad),
        format_func=_rotulo_vinculo,
        key=f"mnl_vincular_v{ver}",
    )

    id_cad, nome_cad, tipo_cad = None, "", ""

    if vincular == "Membro":
        if membros.empty:
            st.warning("Nenhum membro ativo cadastrado.")
        else:
            opc = montar_opcoes(membros)
            esc = st.selectbox("Membro", list(opc.keys()), key=f"mnl_membro_v{ver}")
            l = opc[esc]
            id_cad, nome_cad, tipo_cad = int(l["id_cadastro"]), l["nome"], l["tipo_cadastro"]
    elif vincular == "Fornecedor":
        if fornec.empty:
            st.warning("Nenhum fornecedor ativo cadastrado.")
        else:
            opc = montar_opcoes(fornec)
            esc = st.selectbox("Fornecedor (empresa)", list(opc.keys()), key=f"mnl_forn_v{ver}")
            l = opc[esc]
            id_cad, nome_cad, tipo_cad = int(l["id_cadastro"]), l["nome"], l["tipo_cadastro"]

    desc = st.text_input("Descricao", key=f"mnl_desc_v{ver}")

    col_fp, col_val = st.columns([2, 1])
    with col_fp:
        forma_pag = st.selectbox("Forma de pagamento", FORMAS_PAGAMENTO, key=f"mnl_fp_v{ver}")
    with col_val:
        valor = st.number_input(
            "Valor (R$)",
            min_value=0.0,
            value=None,
            step=0.01,
            format="%.2f",
            placeholder="0,00",
            key=f"mnl_valor_v{ver}",
        )

    st.divider()

    c_salvar, c_cancelar = st.columns(2)
    with c_salvar:
        salvar = st.button(
            "💾 Salvar lancamento",
            type="primary",
            use_container_width=True,
            key=f"mnl_salvar_v{ver}",
        )
    with c_cancelar:
        cancelar = st.button(
            "Cancelar",
            use_container_width=True,
            key=f"mnl_cancelar_v{ver}",
        )

    if cancelar:
        st.session_state["mnl_ver"] += 1
        st.session_state["mnl_aberto"] = False
        st.rerun()

    if salvar:
        lanc = Lancamento(
            data=data_l,
            tipo=tipo,
            categoria=cat,
            valor=valor if valor is not None else 0.0,
            descricao=desc,
            forma_pagamento=forma_pag,
            subcategoria=subcategoria_nl,
            id_cadastro=id_cad,
            nome_cadastro=nome_cad,
            tipo_cadastro=tipo_cad,
        )
        erros = lanc.validar()
        if vincular == "Membro" and membros.empty:
            erros.append("Nenhum membro ativo disponivel.")
        if vincular == "Fornecedor" and fornec.empty:
            erros.append("Nenhum fornecedor ativo disponivel.")
        if valor is None or valor <= 0:
            erros.append("Informe um valor maior que zero.")

        if erros:
            for e in erros:
                st.error(e)
        else:
            try:
                inserir_lancamento(slug, lanc)
            except Exception as ex:
                st.error(f"Erro ao salvar: {ex}")
            else:
                _invalida()
                st.session_state["mnl_ver"] += 1
                st.toast("✅ Lancamento salvo!")
                st.rerun()


# ═══════════════════════════════════════════════════════════════════════
# MODAL: Editar lancamento
# ═══════════════════════════════════════════════════════════════════════

@st.dialog("✏️ Editar lancamento", width="large")
def modal_editar_lancamento(slug, sel, membros, fornec):
    """Modal para editar um lancamento existente."""

    id_lanc = int(sel["id_lancamento"])
    kp = f"medit_lanc_{id_lanc}_"

    valor_atual = float(sel.get("valor", 0) or 0)
    st.markdown(
        f"**Editando:** #{str(id_lanc).zfill(6)} - "
        f"{sel.get('tipo', '-')} / {sel.get('categoria', '-')} - "
        f"{formatar_moeda(valor_atual)}"
    )
    st.divider()

    data_base = pd.to_datetime(sel["data"], errors="coerce")
    col_data, col_tipo = st.columns(2)
    with col_data:
        data_edit_texto = st.text_input(
            "Data",
            value=data_base.strftime("%d/%m/%Y") if pd.notna(data_base) else "",
            placeholder="DD/MM/AAAA",
            help="Digite com ou sem as barras. Ex.: 29082026 ou 29/08/2026.",
            key=kp + "data",
        )
        data_edit = _parse_data_digitada(data_edit_texto)
        if data_edit_texto and data_edit is None:
            st.caption(":red[Data invalida.]")
    with col_tipo:
        tipo_opc = ["Entrada", "Saida"]
        tipo_e = st.selectbox(
            "Tipo",
            tipo_opc,
            index=tipo_opc.index(sel["tipo"]) if sel["tipo"] in tipo_opc else 0,
            key=kp + "tipo",
        )

    subcategoria_edit = ""

    if tipo_e == "Entrada":
        cat_atual = sel["categoria"] if sel["categoria"] in CATEGORIAS_ENTRADA else CATEGORIAS_ENTRADA[0]
        cat_e = st.selectbox(
            "Categoria",
            CATEGORIAS_ENTRADA,
            index=CATEGORIAS_ENTRADA.index(cat_atual),
            key=kp + "cat",
        )
    else:
        cat_e = "Despesa"
        st.text_input("Categoria", value="Despesa", disabled=True, key=kp + "cat_d")

        subcategorias_edit = _subcategorias_despesa_seguras(slug)
        subcat_atual = _valor_texto(sel.get("subcategoria", "")) if "subcategoria" in sel.index else ""
        if subcategorias_edit:
            opcoes_sub = [""] + subcategorias_edit
            if subcat_atual and subcat_atual not in opcoes_sub:
                opcoes_sub = [""] + [subcat_atual] + subcategorias_edit
            idx_sub = opcoes_sub.index(subcat_atual) if subcat_atual in opcoes_sub else 0
            subcategoria_edit = st.selectbox(
                "Subcategoria",
                opcoes_sub,
                index=idx_sub,
                key=kp + "subcat",
            )
        else:
            subcategoria_edit = subcat_atual
            if subcat_atual:
                st.text_input("Subcategoria", value=subcat_atual, disabled=True, key=kp + "subcat_d")

    # Vinculo
    vinc_str = _valor_texto(sel["tipo_cadastro"]).strip().upper()
    vinc_pad_e = (
        "Membro" if (tipo_e == "Entrada" and cat_e == "Dizimo")
        else "Fornecedor" if vinc_str == "FORNECEDOR"
        else "Membro" if vinc_str == "MEMBRO"
        else "Nenhum"
    )
    vincular_e = st.selectbox(
        "Vincular a",
        TIPOS_VINCULO,
        index=TIPOS_VINCULO.index(vinc_pad_e),
        format_func=_rotulo_vinculo,
        key=kp + "vinc",
    )

    id_e, nome_e, tipo_e2 = None, "", ""

    if vincular_e == "Membro":
        opc, chave = _opcoes_com_registro_atual(
            membros, sel["id_cadastro"], sel["nome_cadastro"], sel["tipo_cadastro"]
        )
        if opc:
            chaves = list(opc.keys())
            esc = st.selectbox(
                "Membro",
                chaves,
                index=chaves.index(chave) if chave in chaves else 0,
                key=kp + "mem",
            )
            l = opc[esc]
            id_e, nome_e, tipo_e2 = int(l["id_cadastro"]), l["nome"], l["tipo_cadastro"]
        else:
            st.warning("Nenhum membro ativo cadastrado.")
    elif vincular_e == "Fornecedor":
        opc, chave = _opcoes_com_registro_atual(
            fornec, sel["id_cadastro"], sel["nome_cadastro"], sel["tipo_cadastro"]
        )
        if opc:
            chaves = list(opc.keys())
            esc = st.selectbox(
                "Fornecedor (empresa)",
                chaves,
                index=chaves.index(chave) if chave in chaves else 0,
                key=kp + "forn",
            )
            l = opc[esc]
            id_e, nome_e, tipo_e2 = int(l["id_cadastro"]), l["nome"], l["tipo_cadastro"]
        else:
            st.warning("Nenhum fornecedor ativo cadastrado.")

    desc_e = st.text_input(
        "Descricao",
        value=_valor_texto(sel["descricao"]),
        key=kp + "desc",
    )

    forma_pag_atual = _valor_texto(sel.get("forma_pagamento", "Dinheiro")) if "forma_pagamento" in sel.index else "Dinheiro"
    idx_fp = FORMAS_PAGAMENTO.index(forma_pag_atual) if forma_pag_atual in FORMAS_PAGAMENTO else 1
    col_fp, col_val = st.columns([2, 1])
    with col_fp:
        forma_pag_e = st.selectbox(
            "Forma de pagamento",
            FORMAS_PAGAMENTO,
            index=idx_fp,
            key=kp + "forma_pag",
        )
    with col_val:
        valor_e = st.number_input(
            "Valor (R$)",
            min_value=0.0,
            value=float(sel["valor"]),
            step=0.01,
            format="%.2f",
            key=kp + "val",
        )

    st.divider()

    c_salvar, c_cancelar = st.columns(2)
    with c_salvar:
        salvar = st.button(
            "💾 Salvar alteracoes",
            type="primary",
            use_container_width=True,
            key=kp + "btn_salvar",
        )
    with c_cancelar:
        cancelar = st.button(
            "Cancelar",
            use_container_width=True,
            key=kp + "btn_cancelar",
        )

    if cancelar:
        for k in list(st.session_state.keys()):
            if k.startswith(kp):
                st.session_state.pop(k, None)
        st.rerun()

    if salvar:
        lanc = Lancamento(
            data=data_edit,
            tipo=tipo_e,
            categoria=cat_e,
            valor=valor_e,
            descricao=desc_e,
            forma_pagamento=forma_pag_e,
            subcategoria=subcategoria_edit,
            id_cadastro=id_e,
            nome_cadastro=nome_e,
            tipo_cadastro=tipo_e2,
            id_lancamento=id_lanc,
        )
        erros = lanc.validar()

        if erros:
            for e in erros:
                st.error(e)
        else:
            try:
                atualizar_lancamento(slug, lanc)
            except Exception as ex:
                st.error(f"Erro ao atualizar: {ex}")
            else:
                _invalida()
                for k in list(st.session_state.keys()):
                    if k.startswith(kp) or k.startswith("_auth_"):
                        st.session_state.pop(k, None)
                st.toast("✅ Lancamento alterado!")
                st.rerun()


# ═══════════════════════════════════════════════════════════════════════
# MODAL: Visualizar lancamento (com preview do cupom + WhatsApp)
# ═══════════════════════════════════════════════════════════════════════

@st.dialog("👁️ Visualizar lancamento", width="large")
def modal_visualizar_lancamento(sel, igreja, slug, df_cad):
    """Modal com detalhes do lancamento, preview do cupom e opcoes de envio."""

    id_lanc = int(sel["id_lancamento"])
    tipo = _valor_texto(sel.get("tipo", "-"))
    categoria = _valor_texto(sel.get("categoria", "-"))
    valor = float(sel.get("valor", 0) or 0)
    data_fmt = pd.to_datetime(sel.get("data"), errors="coerce")
    data_str = data_fmt.strftime("%d/%m/%Y") if pd.notna(data_fmt) else "-"

    # Header com badge de tipo e valor destacado
    cor_tipo = "#10B981" if tipo == "Entrada" else "#EF4444"
    st.markdown(
        f"""
        <div style="margin-bottom:16px;padding:14px;background:#F9FAFB;border-radius:8px;">
            <div style="display:flex;justify-content:space-between;align-items:center;">
                <div>
                    <span style="background:{cor_tipo}22;color:{cor_tipo};padding:4px 12px;
                                 border-radius:12px;font-size:12px;font-weight:700;">
                        {_html(tipo)}
                    </span>
                    <span style="color:#6b7280;font-size:12px;margin-left:8px;">
                        Cupom #{str(id_lanc).zfill(6)}
                    </span>
                </div>
                <div style="text-align:right;">
                    <div style="font-size:24px;font-weight:700;color:{cor_tipo};">
                        {_html(formatar_moeda(valor))}
                    </div>
                    <div style="color:#6b7280;font-size:12px;">{_html(data_str)}</div>
                </div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    tab_dados, tab_cupom, tab_whatsapp = st.tabs([
        "📋 Detalhes",
        "🧾 Cupom",
        "📱 WhatsApp",
    ])

    with tab_dados:
        c1, c2 = st.columns(2)
        with c1:
            st.markdown("**Categoria**")
            st.code(categoria or "-", language=None)

            subcategoria = _valor_texto(sel.get("subcategoria", ""))
            if subcategoria:
                st.markdown("**Subcategoria**")
                st.code(subcategoria, language=None)

            st.markdown("**Forma de pagamento**")
            forma_pag = _valor_texto(sel.get("forma_pagamento", "Dinheiro")) or "Dinheiro"
            st.code(forma_pag, language=None)

        with c2:
            st.markdown("**Vinculado a**")
            nome_vinc = _valor_texto(sel.get("nome_cadastro", ""))
            tipo_vinc = _valor_texto(sel.get("tipo_cadastro", ""))
            if nome_vinc:
                st.code(f"{nome_vinc}" + (f" ({tipo_vinc})" if tipo_vinc else ""), language=None)
            else:
                st.code("Nao vinculado", language=None)

            st.markdown("**Descricao**")
            desc = _valor_texto(sel.get("descricao", ""))
            st.code(desc if desc else "(sem descricao)", language=None)

    with tab_cupom:
        st.caption("Pre-visualizacao do cupom. Use os botoes abaixo para imprimir ou baixar.")

        html_preview = _gerar_html_comprovante(dict(sel), igreja, slug, auto_imprimir=False)
        components.html(html_preview, height=560, scrolling=True)

        html_full = _gerar_html_comprovante(dict(sel), igreja, slug, auto_imprimir=True)
        st.download_button(
            "📥 Baixar cupom (HTML)",
            data=html_full,
            file_name=f"comprovante_{id_lanc}.html",
            mime="text/html",
            use_container_width=True,
            key=f"mview_dl_{id_lanc}",
        )

    with tab_whatsapp:
        telefone = _telefone_do_lancamento(df_cad, dict(sel))
        mensagem = _montar_mensagem_comprovante(dict(sel), igreja, slug)

        if not telefone:
            st.warning("⚠️ Este lancamento nao possui telefone vinculado.")
        else:
            st.caption(f"📞 Telefone do vinculado: **{telefone}**")

            st.markdown("**Preview da mensagem:**")
            st.text_area(
                "",
                value=mensagem,
                height=220,
                key=f"mview_msg_{id_lanc}",
                disabled=True,
                label_visibility="collapsed",
            )

            link = _link_whatsapp(telefone, mensagem)
            if link:
                st.markdown(
                    f'<a href="{_html(link)}" target="_blank" rel="noopener noreferrer" '
                    f'style="display:inline-block;background:#25D366;color:white;'
                    f'padding:10px 24px;border-radius:6px;text-decoration:none;'
                    f'font-weight:600;margin-top:10px;width:100%;text-align:center;box-sizing:border-box;">'
                    f'💬 Abrir conversa no WhatsApp</a>',
                    unsafe_allow_html=True,
                )

            if _whatsapp_api_configurada():
                st.divider()
                st.caption("📡 Envio automatico via WhatsApp Cloud API:")
                if st.button(
                    "📤 Enviar automaticamente via API",
                    use_container_width=True,
                    key=f"mview_api_{id_lanc}",
                ):
                    ok, detalhe = _enviar_whatsapp_texto_api(telefone, mensagem)
                    if ok:
                        st.success(detalhe)
                    else:
                        st.error(detalhe)

    st.divider()

    if st.button("Fechar", use_container_width=True, key=f"mview_fechar_{id_lanc}"):
        st.rerun()


# ═══════════════════════════════════════════════════════════════════════
# MODAL: Excluir lancamento
# ═══════════════════════════════════════════════════════════════════════

@st.dialog("🗑️ Excluir lancamento", width="small")
def modal_excluir_lancamento(slug, sel):
    """Modal para confirmar exclusao do lancamento."""

    id_lanc = int(sel["id_lancamento"])
    tipo = _valor_texto(sel.get("tipo", "-"))
    categoria = _valor_texto(sel.get("categoria", "-"))
    valor = float(sel.get("valor", 0) or 0)
    nome_vinc = _valor_texto(sel.get("nome_cadastro", ""))
    data_fmt = pd.to_datetime(sel.get("data"), errors="coerce")
    data_str = data_fmt.strftime("%d/%m/%Y") if pd.notna(data_fmt) else "-"

    st.warning(
        f"⚠️ Voce esta prestes a excluir o lancamento:\n\n"
        f"**Cupom #{str(id_lanc).zfill(6)}**\n\n"
        f"- Data: {data_str}\n"
        f"- Tipo: {tipo} / {categoria}\n"
        f"- Valor: **{formatar_moeda(valor)}**\n"
        f"- Vinculado: {nome_vinc or '(sem vinculo)'}\n\n"
        f"Esta acao **nao pode ser desfeita**."
    )

    confirmar = st.checkbox(
        "Confirmo a exclusao deste lancamento",
        key=f"mexc_lanc_conf_{id_lanc}",
    )

    c1, c2 = st.columns(2)
    with c1:
        excluir_btn = st.button(
            "🗑️ Excluir definitivamente",
            type="primary",
            use_container_width=True,
            disabled=not confirmar,
            key=f"mexc_lanc_btn_{id_lanc}",
        )
    with c2:
        cancelar = st.button(
            "Cancelar",
            use_container_width=True,
            key=f"mexc_lanc_cancelar_{id_lanc}",
        )

    if cancelar:
        st.session_state.pop(f"mexc_lanc_conf_{id_lanc}", None)
        st.rerun()

    if excluir_btn:
        try:
            excluir_lancamento(slug, id_lanc)
            _invalida()
            for k in list(st.session_state.keys()):
                if (k.startswith("mexc_lanc_")
                    or k.startswith("_auth_")
                    or k == "sel_lanc_acao"):
                    st.session_state.pop(k, None)
            st.toast(f"✅ Lancamento #{str(id_lanc).zfill(6)} excluido!")
            st.rerun()
        except Exception as exc:
            st.error(f"❌ Erro ao excluir: {exc}")


# ═══════════════════════════════════════════════════════════════════════
# Funcao principal: render()
# ═══════════════════════════════════════════════════════════════════════

def render():
    slug = slug_da_sessao()
    df_cad = _get_cad(slug)
    df_lanc = _get_lanc(slug)
    membros = obter_ativos(df_cad, "MEMBRO")
    fornec = obter_ativos(df_cad, "FORNECEDOR")
    igreja = st.session_state.get("igreja", {})
    plano_igreja = igreja.get("plano", "basico")

    lote_itens_key = _sk("lote_itens", slug)
    lote_comprovante_key = _sk("lote_comprovante_html", slug)

    st.subheader("💰 Lancamentos financeiros")

    # ─── BOTAO PRINCIPAL: Novo lancamento ──────────────────────────
    if "mnl_aberto" not in st.session_state:
        st.session_state["mnl_aberto"] = False

    # Streamlit so permite um dialogo aberto por execucao. Se outra acao
    # (Visualizar/Editar/Excluir) foi acionada nesta mesma execucao, fecha
    # o "Novo lancamento" para evitar StreamlitAPIException por dialogos
    # simultaneos.
    if any(
        st.session_state.get(k)
        for k in ("btn_abrir_view_lanc", "btn_abrir_edit_lanc", "btn_abrir_del_lanc")
    ):
        st.session_state["mnl_aberto"] = False

    if st.button(
        "➕ Novo lancamento",
        type="primary",
        use_container_width=True,
        key="btn_abrir_novo_lanc",
    ):
        st.session_state["mnl_aberto"] = True

    if st.session_state["mnl_aberto"]:
        modal_novo_lancamento(slug, membros, fornec)

    # ─── Importar dizimos via Pix (mantido como expander) ──────────
    with st.expander("💠 Importar dizimos via Pix (CSV ou PDF)", expanded=False):
        st.caption(
            "Use um CSV do banco, uma planilha exportada ou o PDF de recebimentos Pix "
            "no modelo analisado. Os registros serao lancados como Entrada > Dizimo > Pix."
        )
        st.info(
            "PDFs de outros bancos podem ter estrutura diferente. Sempre confira a "
            "pre-visualizacao antes de importar."
        )

        if membros.empty:
            st.warning("Cadastre membros ativos antes de importar dizimos.")
        else:
            modelo = pd.DataFrame([
                {"data": "04/06/2026", "membro": "Nome do membro", "valor": "100,00"}
            ])
            st.download_button(
                "Baixar modelo CSV",
                gerar_csv(modelo),
                "modelo_importacao_dizimos_pix.csv",
                "text/csv",
                key=_sk("csv_modelo_pix", slug),
            )

            arquivo_pix = st.file_uploader(
                "Arquivo CSV ou PDF dos Pix",
                type=["csv", "pdf"],
                key=_sk("upload_pix_csv", slug),
            )
            if arquivo_pix:
                try:
                    df_pix_csv = _ler_arquivo_pix(arquivo_pix)
                except ValueError as ex:
                    st.error(str(ex))
                except Exception:
                    LOGGER.exception("Nao foi possivel processar o CSV de Pix.")
                    st.error("Nao foi possivel processar o CSV enviado.")
                else:
                    if df_pix_csv.empty:
                        st.warning("O CSV enviado esta vazio.")
                    else:
                        colunas = list(df_pix_csv.columns)
                        col_data_padrao = _detectar_coluna(colunas, ["data", "dt", "date"])
                        col_nome_padrao = _detectar_coluna(
                            colunas,
                            ["membro", "nome", "pagador", "remetente", "cliente", "descricao"],
                        )
                        col_valor_padrao = _detectar_coluna(
                            colunas,
                            ["valor", "amount", "quantia", "credito", "entrada"],
                        )
                        col_transacao_padrao = (
                            _detectar_coluna(colunas, ["transacao_pix", "transacao", "txid", "endtoend"])
                            if any(_normalizar_texto_importacao(c) in {
                                "transacao pix", "transacao", "txid", "endtoend"
                            } for c in colunas)
                            else None
                        )

                        c1, c2, c3 = st.columns(3)
                        with c1:
                            col_data = st.selectbox(
                                "Coluna da data",
                                colunas,
                                index=colunas.index(col_data_padrao),
                                key=_sk("pix_col_data", slug),
                            )
                        with c2:
                            col_nome = st.selectbox(
                                "Coluna do nome do membro",
                                colunas,
                                index=colunas.index(col_nome_padrao),
                                key=_sk("pix_col_nome", slug),
                            )
                        with c3:
                            col_valor = st.selectbox(
                                "Coluna do valor",
                                colunas,
                                index=colunas.index(col_valor_padrao),
                                key=_sk("pix_col_valor", slug),
                            )
                        col_transacao = None
                        if col_transacao_padrao:
                            col_transacao = col_transacao_padrao
                            st.caption(f"Identificador Pix detectado em: {col_transacao_padrao}")

                        preview, lancamentos_importar = _preparar_importacao_dizimos_pix(
                            df_pix_csv, membros, df_lanc,
                            col_data, col_nome, col_valor,
                            col_transacao=col_transacao,
                        )
                        total_prontos = int((preview["Status"] == "Pronto").sum())
                        total_ignorados = int((preview["Status"] != "Pronto").sum())
                        p1, p2, p3 = st.columns(3)
                        p1.metric("Linhas no CSV", len(preview))
                        p2.metric("Prontas para importar", total_prontos)
                        p3.metric("Ignoradas", total_ignorados)

                        st.dataframe(preview, use_container_width=True, hide_index=True)

                        if total_prontos:
                            if st.button(
                                "Importar dizimos Pix validos",
                                type="primary",
                                key=_sk("pix_importar", slug),
                            ):
                                try:
                                    lote_id, ids = inserir_lancamentos_lote(
                                        slug,
                                        lancamentos_importar,
                                        lote_id=f"PIX-{datetime.datetime.now():%Y%m%d%H%M%S}",
                                    )
                                except ValueError as ex:
                                    st.error(str(ex))
                                except Exception:
                                    LOGGER.exception("Falha ao importar dizimos Pix.")
                                    st.error("Nao foi possivel importar os dizimos Pix.")
                                else:
                                    _invalida()
                                    st.success(
                                        f"{len(ids)} dizimo(s) importado(s) com sucesso. Lote: {lote_id}"
                                    )
                                    st.rerun()
                        else:
                            st.warning("Nenhuma linha valida para importar.")

    # ─── Lancamento em lote (mantido como expander) ────────────────
    if tem_lancamento_lote(plano_igreja):
        with st.expander("📦 Lancamento em lote (multiplos itens)", expanded=False):
            st.caption("Lance varios itens (dizimo + oferta + missao etc) "
                       "compartilhando data, membro/fornecedor e forma de pagamento.")

            if lote_itens_key not in st.session_state:
                st.session_state[lote_itens_key] = []

            st.markdown("**Dados compartilhados**")
            data_lote = st.date_input("Data", value=datetime.date.today(),
                                       format="DD/MM/YYYY", key="lote_data")
            tipo_lote = st.selectbox(
                "Tipo", ["Entrada", "Saida"], key=_sk("lote_tipo", slug),
                disabled=bool(st.session_state[lote_itens_key]),
                help="Limpe os itens para alterar o tipo do lote.",
            )

            vinc_pad_l = "Membro" if tipo_lote == "Entrada" else "Fornecedor"
            vincular_lote = st.selectbox(
                "Vincular a", TIPOS_VINCULO,
                index=TIPOS_VINCULO.index(vinc_pad_l),
                format_func=_rotulo_vinculo,
                key="lote_vincular",
            )

            id_cad_l, nome_cad_l, tipo_cad_l = None, "", ""

            if vincular_lote == "Membro":
                if membros.empty:
                    st.warning("Nenhum membro ativo cadastrado.")
                else:
                    opc = montar_opcoes(membros)
                    esc = st.selectbox("Membro", list(opc.keys()), key="lote_membro")
                    l = opc[esc]
                    id_cad_l, nome_cad_l, tipo_cad_l = int(l["id_cadastro"]), l["nome"], l["tipo_cadastro"]
            elif vincular_lote == "Fornecedor":
                if fornec.empty:
                    st.warning("Nenhum fornecedor ativo cadastrado.")
                else:
                    opc = montar_opcoes(fornec)
                    esc = st.selectbox("Fornecedor (empresa)", list(opc.keys()), key="lote_fornecedor")
                    l = opc[esc]
                    id_cad_l, nome_cad_l, tipo_cad_l = int(l["id_cadastro"]), l["nome"], l["tipo_cadastro"]

            forma_pag_lote = st.selectbox("Forma de pagamento", FORMAS_PAGAMENTO, key="lote_forma_pag")

            st.divider()
            st.markdown("**Adicionar item**")

            subcategoria_lote_item = ""

            if tipo_lote == "Entrada":
                cat_lote_item = st.selectbox("Categoria", CATEGORIAS_ENTRADA, key="lote_cat_item")
            else:
                cat_lote_item = "Despesa"
                st.text_input("Categoria", value="Despesa", disabled=True, key="lote_cat_d_item")

                subcategorias_lote = _subcategorias_despesa_seguras(slug)
                if subcategorias_lote:
                    subcategoria_lote_item = st.selectbox(
                        "Subcategoria",
                        [""] + subcategorias_lote,
                        key="lote_subcat_item",
                    )

            desc_lote_item = st.text_input("Descricao", key="lote_desc_item")
            valor_lote_item = st.number_input("Valor (R$)", min_value=0.0,
                                              step=0.01, format="%.2f", key="lote_valor_item")

            if st.button("Adicionar item ao lote", key="lote_add_item"):
                if valor_lote_item <= 0:
                    st.error("Informe um valor maior que zero.")
                else:
                    st.session_state[lote_itens_key].append({
                        "tipo": tipo_lote,
                        "categoria": cat_lote_item,
                        "subcategoria": subcategoria_lote_item,
                        "descricao": desc_lote_item,
                        "valor": float(valor_lote_item),
                    })
                    st.toast("Item adicionado!")
                    st.rerun()

            if st.session_state[lote_itens_key]:
                st.divider()
                st.markdown("**Itens do lote**")

                total_lote = sum(it["valor"] for it in st.session_state[lote_itens_key])

                for i, item in enumerate(st.session_state[lote_itens_key]):
                    col1, col2, col3, col4 = st.columns([3, 4, 2, 1])
                    with col1:
                        rotulo_item = item["categoria"]
                        if item.get("subcategoria"):
                            rotulo_item += f" / {item['subcategoria']}"
                        st.write(f"**{rotulo_item}**")
                    with col2:
                        st.write(item["descricao"] or "—")
                    with col3:
                        st.write(formatar_moeda(item["valor"]))
                    with col4:
                        if st.button("X", key=f"lote_del_{i}", help="Remover item"):
                            st.session_state[lote_itens_key].pop(i)
                            st.rerun()

                st.markdown(f"### Total: {formatar_moeda(total_lote)}")
                st.caption(f"{len(st.session_state[lote_itens_key])} item(ns) no lote")

                st.divider()
                c_salvar, c_limpar = st.columns(2)

                with c_salvar:
                    if st.button("Salvar todos os lancamentos", type="primary", key="lote_salvar"):
                        if vincular_lote == "Membro" and not id_cad_l:
                            st.error("Selecione um membro para vincular.")
                        elif vincular_lote == "Fornecedor" and not id_cad_l:
                            st.error("Selecione um fornecedor para vincular.")
                        else:
                            itens_salvos = []
                            lancamentos_lote = []
                            erros_lote = []

                            for idx, item in enumerate(st.session_state[lote_itens_key], start=1):
                                lanc = Lancamento(
                                    data=data_lote, tipo=item["tipo"],
                                    categoria=item["categoria"], valor=item["valor"],
                                    descricao=item["descricao"], forma_pagamento=forma_pag_lote,
                                    subcategoria=item.get("subcategoria", ""),
                                    id_cadastro=id_cad_l, nome_cadastro=nome_cad_l,
                                    tipo_cadastro=tipo_cad_l,
                                )
                                erros = lanc.validar()
                                if erros:
                                    erros_lote.extend([f"Item {idx}: {erro}" for erro in erros])
                                else:
                                    lancamentos_lote.append(lanc)
                                    itens_salvos.append(item)

                            if erros_lote:
                                for erro in erros_lote:
                                    st.error(erro)

                            if itens_salvos and not erros_lote:
                                try:
                                    numero_lote, _ = inserir_lancamentos_lote(
                                        slug, lancamentos_lote
                                    )
                                except ValueError as ex:
                                    st.error(str(ex))
                                    return

                                vinc_str = nome_cad_l + (" (" + tipo_cad_l + ")" if tipo_cad_l else "")
                                if not vinc_str:
                                    vinc_str = "Nao vinculado"

                                html_comp = _gerar_html_comprovante_lote(
                                    itens=itens_salvos, igreja=igreja, slug=slug,
                                    data_str=data_lote.strftime("%d/%m/%Y"),
                                    vinc_str=vinc_str, forma_pag=forma_pag_lote,
                                    numero_lote=numero_lote,
                                )
                                st.session_state[lote_comprovante_key] = html_comp
                                st.session_state[lote_itens_key] = []
                                _invalida()
                                st.toast(f"{len(itens_salvos)} lancamentos salvos!")
                                st.rerun()

                with c_limpar:
                    if st.button("Limpar lote", key="lote_limpar"):
                        st.session_state[lote_itens_key] = []
                        st.toast("Lote limpo.")
                        st.rerun()

            if lote_comprovante_key in st.session_state:
                st.divider()
                st.success("Lancamentos salvos! Comprovante consolidado:")
                components.html(st.session_state[lote_comprovante_key], height=700, scrolling=True)
                st.download_button(
                    "Baixar comprovante consolidado",
                    data=st.session_state[lote_comprovante_key],
                    file_name="comprovante_lote.html",
                    mime="text/html",
                    use_container_width=True,
                )
                if st.button("Fechar comprovante", key="lote_fechar_comp"):
                    st.session_state.pop(lote_comprovante_key, None)
                    st.rerun()
    else:
        p_info_l = obter_plano(plano_igreja)
        with st.expander("🔒 Lancamento em lote (apenas Profissional e Premium)", expanded=False):
            st.warning(
                f"O lancamento em lote esta disponivel apenas nos planos "
                f"**Profissional** e **Premium**. Seu plano atual: **{p_info_l['nome']}**."
            )
            st.info(
                f"Faca upgrade para **{proximo_plano(plano_igreja).capitalize()}** "
                f"e ganhe a possibilidade de lancar dizimo + oferta + missao em um unico documento."
            )

    # ─── Ver lancamentos (tabela) ──────────────────────────────────
    total = len(df_lanc)
    with st.expander(f"📋 Ver lancamentos ({total} registros)", expanded=False):
        if df_lanc.empty:
            st.info("Nenhum lancamento ainda.")
        else:
            st.dataframe(preparar_df(df_lanc), use_container_width=True)
            st.download_button(
                "Exportar CSV",
                gerar_csv(preparar_df(df_lanc)),
                "lancamentos.csv",
                "text/csv",
            )

    # ─── ACOES em lancamento existente (3 botoes que abrem modais) ─
    if not df_lanc.empty:
        st.divider()
        st.markdown("### 🎯 Acoes em lancamento existente")

        df_e = df_lanc.copy()
        df_e["data_fmt"] = pd.to_datetime(df_e["data"], errors="coerce").dt.strftime("%d/%m/%Y").fillna("")
        df_e["rotulo"] = df_e.apply(
            lambda r: (f'{int(r["id_lancamento"])} | {r["data_fmt"]} | '
                       f'{r["tipo"]} | {r["categoria"]} | '
                       f'{r["nome_cadastro"] or "Sem vinculo"} | '
                       f'{formatar_moeda(r["valor"])}'),
            axis=1,
        )

        rotulo = st.selectbox(
            "Selecione um lancamento",
            df_e["rotulo"].tolist(),
            key="sel_lanc_acao",
        )
        sel = df_e[df_e["rotulo"] == rotulo].iloc[0]

        c_view, c_edit, c_del = st.columns(3)

        with c_view:
            if st.button(
                "👁️ Visualizar",
                use_container_width=True,
                key="btn_abrir_view_lanc",
            ):
                modal_visualizar_lancamento(sel, igreja, slug, df_cad)

        with c_edit:
            if st.button(
                "✏️ Editar",
                use_container_width=True,
                key="btn_abrir_edit_lanc",
            ):
                modal_editar_lancamento(slug, sel, membros, fornec)

        with c_del:
            if st.button(
                "🗑️ Excluir",
                use_container_width=True,
                key="btn_abrir_del_lanc",
            ):
                modal_excluir_lancamento(slug, sel)

    # ─── Fechamento de caixa (mantido como expander) ───────────────
    with st.expander("📊 2a via do cupom / fechamento de caixa", expanded=False):
        if df_lanc.empty:
            st.info("Nenhum lancamento ainda.")
        else:
            st.caption(
                "Gere uma segunda via consolidada para conferencia e assinatura "
                "do fechamento de caixa."
            )
            df_caixa_base = df_lanc.copy()
            df_caixa_base["data_dt"] = pd.to_datetime(df_caixa_base["data"], errors="coerce")
            datas_validas = df_caixa_base["data_dt"].dropna()
            hoje = datetime.date.today()
            data_min = datas_validas.min().date() if not datas_validas.empty else hoje
            data_max = datas_validas.max().date() if not datas_validas.empty else hoje
            inicio_default = min(max(hoje, data_min), data_max)
            fim_default = inicio_default

            c1, c2, c3 = st.columns(3)
            with c1:
                inicio_caixa = st.date_input(
                    "Data inicial",
                    value=inicio_default,
                    min_value=data_min,
                    max_value=data_max,
                    format="DD/MM/YYYY",
                    key=_sk("caixa_inicio", slug),
                )
            with c2:
                fim_caixa = st.date_input(
                    "Data final",
                    value=fim_default,
                    min_value=data_min,
                    max_value=data_max,
                    format="DD/MM/YYYY",
                    key=_sk("caixa_fim", slug),
                )
            with c3:
                forma_caixa = st.selectbox(
                    "Forma de pagamento",
                    ["Todas"] + FORMAS_PAGAMENTO,
                    key=_sk("caixa_forma", slug),
                )

            if inicio_caixa > fim_caixa:
                st.error("A data inicial nao pode ser posterior a data final.")
            else:
                df_caixa = df_caixa_base[
                    df_caixa_base["data_dt"].between(
                        pd.Timestamp(inicio_caixa),
                        pd.Timestamp(fim_caixa),
                        inclusive="both",
                    )
                ].copy()
                if forma_caixa != "Todas":
                    df_caixa = df_caixa[
                        df_caixa["forma_pagamento"].fillna("").astype(str) == forma_caixa
                    ].copy()

                df_caixa["valor"] = pd.to_numeric(df_caixa["valor"], errors="coerce").fillna(0.0)
                df_caixa["tipo_norm"] = df_caixa["tipo"].fillna("").astype(str).str.upper().str.strip()
                entradas_caixa = float(df_caixa[df_caixa["tipo_norm"] == "ENTRADA"]["valor"].sum())
                saidas_caixa = float(df_caixa[df_caixa["tipo_norm"] == "SAIDA"]["valor"].sum())
                saldo_caixa = entradas_caixa - saidas_caixa

                m1, m2, m3, m4 = st.columns(4)
                m1.metric("Entradas", formatar_moeda(entradas_caixa))
                m2.metric("Saidas", formatar_moeda(saidas_caixa))
                m3.metric("Saldo", formatar_moeda(saldo_caixa))
                m4.metric("Lancamentos", len(df_caixa))

                if df_caixa.empty:
                    st.warning("Nenhum lancamento encontrado para os filtros selecionados.")
                else:
                    if st.button(
                        "Gerar 2a via do fechamento",
                        type="primary",
                        key=_sk("caixa_gerar", slug),
                    ):
                        html_caixa = _gerar_html_fechamento_caixa(
                            df_caixa, igreja, slug,
                            inicio_caixa, fim_caixa,
                            forma_pagamento=forma_caixa,
                        )
                        components.html(html_caixa, height=760, scrolling=True)
                        sufixo_periodo = (
                            f"{inicio_caixa:%Y%m%d}"
                            if inicio_caixa == fim_caixa
                            else f"{inicio_caixa:%Y%m%d}_{fim_caixa:%Y%m%d}"
                        )
                        st.download_button(
                            "Baixar 2a via do fechamento",
                            data=html_caixa,
                            file_name=f"fechamento_caixa_2a_via_{sufixo_periodo}.html",
                            mime="text/html",
                            use_container_width=True,
                        )
