import logging
import datetime
import html
import sqlite3

import streamlit as st
import pandas as pd
import streamlit.components.v1 as components

from data.models import Cadastro, limpar_documento
from data.repository import (
    carregar_cadastros, inserir_cadastro, atualizar_cadastro,
    excluir_cadastro, cadastro_em_uso, cpf_existe, LimiteMembrosExcedido,
    aprovar_pre_cadastro_membro, atualizar_status_pre_cadastro,
    listar_pre_cadastros_membros,
)
from utils.helpers import confirmar_exclusao, slug_da_sessao, solicitar_autorizacao
from utils.planos import obter_plano, pode_cadastrar_membro, proximo_plano


FUNCOES = [
    "Membro", "Congregado", "Auxiliar", "Pastor", "Diacono", "Diaconisa",
    "Presbitero", "Evangelista", "Cooperador", "Dirigente",
    "Secretario", "Tesoureiro", "Professor", "Lider", "Missionário (a)", "",
]

SEXO_OPC = ["Masculino", "Feminino", ""]
TIPOS_CADASTRO = ["Membro", "Fornecedor"]

# ═══════════════════════════════════════════════════════════════════════
# Historico do membro - tipos de ocorrencia padronizados
# Formato: (codigo, rotulo, categoria)  -> categoria: Entrada | Saida | Normal
# ═══════════════════════════════════════════════════════════════════════
TIPOS_HISTORICO = [
    (1, "Conversão", "Entrada"),
    (2, "Batismo nas Águas", "Entrada"),
    (3, "Batismo com o Espírito Santo", "Normal"),
    (4, "Consagrado a Diácono", "Normal"),
    (5, "Consagrado a Presbítero", "Normal"),
    (6, "Consagrado a Evangelista", "Normal"),
    (7, "Consagrado a Pastor", "Normal"),
    (8, "Consagrado a Bispo", "Normal"),
    (9, "Ordenação Ministerial", "Normal"),
    (10, "Casamento", "Normal"),
    (11, "Dedicação de Filho(a)", "Normal"),
    (12, "Excluído por Disciplina", "Saída"),
    (13, "Reconciliado", "Entrada"),
    (14, "Falecimento", "Saída"),
    (15, "Desligamento a Pedido", "Saída"),
    (16, "Mudança de Função Ministerial", "Normal"),
    (17, "Separado para Auxiliar na Obra", "Normal"),
    (18, "Separado para Obreiro", "Normal"),
    (19, "Licenciado Ministerialmente", "Normal"),
    (20, "Afastado Temporariamente", "Saída"),
    (21, "Retorno de Afastamento", "Entrada"),
    (30, "Transferência Recebida de Outra Igreja", "Entrada"),
    (31, "Transferências entre Congregações", "Normal"),
    (32, "Transferência Enviada para Outra Igreja", "Saída"),
    (99, "Outro (especificar na observação)", "Normal"),
]

CATEGORIA_COR = {
    "Entrada": "#10B981",
    "Saída": "#EF4444",
    "Normal": "#3B82F6",
}


# ═══════════════════════════════════════════════════════════════════════
# Helpers de formatacao
# ═══════════════════════════════════════════════════════════════════════

def _rotulo_tipo_cadastro(tipo):
    return "Fornecedor (empresa)" if tipo == "Fornecedor" else tipo


def _formatar_cpf(cpf):
    digits = "".join(c for c in cpf if c.isdigit())
    if len(digits) == 11:
        return f"{digits[:3]}.{digits[3:6]}.{digits[6:9]}-{digits[9:]}"
    return cpf


def _formatar_cnpj(cnpj):
    digits = "".join(c for c in cnpj if c.isdigit())
    if len(digits) == 14:
        return f"{digits[:2]}.{digits[2:5]}.{digits[5:8]}/{digits[8:12]}-{digits[12:]}"
    return cnpj


def _formatar_doc(doc, tipo):
    if tipo == "Fornecedor":
        return _formatar_cnpj(doc)
    return _formatar_cpf(doc)


def _formatar_cep(cep):
    digits = "".join(c for c in cep if c.isdigit())
    if len(digits) == 8:
        return f"{digits[:5]}-{digits[5:]}"
    return cep


def _formatar_tel(tel):
    digits = "".join(c for c in tel if c.isdigit())
    if digits.startswith("55") and len(digits) in (12, 13):
        digits = digits[2:]
    if len(digits) == 11:
        return f"({digits[:2]}) {digits[2]} {digits[3:7]}-{digits[7:]}"
    if len(digits) == 10:
        return f"({digits[:2]}) {digits[2:6]}-{digits[6:]}"
    return tel


def _formatar_data(data_str):
    try:
        return datetime.date.fromisoformat(data_str).strftime("%d/%m/%Y")
    except Exception:
        return data_str


def _cache_key(slug):
    return f"df_cad_{slug}"


def _get(slug):
    k = _cache_key(slug)
    if k not in st.session_state:
        st.session_state[k] = carregar_cadastros(slug)
    return st.session_state[k]


def _invalida(slug):
    st.session_state.pop(_cache_key(slug), None)


def _val(row, col):
    v = row.get(col, "") if isinstance(row, dict) else getattr(row, col, "")
    return "" if pd.isna(v) else str(v).strip()


def _congregacao_da_sessao(slug, igreja):
    if not isinstance(igreja, dict):
        igreja = {}
    return str(
        igreja.get("identificador")
        or igreja.get("slug")
        or slug
        or ""
    ).strip()


# ═══════════════════════════════════════════════════════════════════════
# Historico do membro: acesso ao banco (tabela historico_membros)
# ═══════════════════════════════════════════════════════════════════════

def _tenant_db_path(slug):
    """Import defensivo de _tenant_db (nome interno do repository).
    Isola o restante do modulo de uma eventual mudanca de assinatura."""
    from data.repository import _tenant_db
    return _tenant_db(slug)


def _garantir_tabela_historico(slug):
    """Cria a tabela historico_membros se ainda nao existir (auto-migracao).
    Cacheia por sessao para evitar checagem repetida a cada rerun."""
    flag = f"_hist_membro_tabela_ok_{slug}"
    if st.session_state.get(flag):
        return
    try:
        db_path = _tenant_db_path(slug)
        with sqlite3.connect(db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS historico_membros (
                    id_historico INTEGER PRIMARY KEY AUTOINCREMENT,
                    id_cadastro INTEGER NOT NULL,
                    data_ocorrencia TEXT NOT NULL,
                    codigo_tipo INTEGER,
                    ocorrencia TEXT NOT NULL,
                    categoria TEXT,
                    localidade TEXT,
                    observacao TEXT,
                    criado_em TEXT
                )
            """)
            conn.commit()
        st.session_state[flag] = True
    except Exception:
        logging.exception("Erro ignorado silenciosamente")


def _listar_historico(slug, id_cadastro):
    """Retorna DataFrame com o historico do membro, mais recente primeiro."""
    _garantir_tabela_historico(slug)
    try:
        db_path = _tenant_db_path(slug)
        with sqlite3.connect(db_path) as conn:
            df = pd.read_sql_query(
                """SELECT id_historico, data_ocorrencia, codigo_tipo,
                          ocorrencia, categoria, localidade, observacao
                   FROM historico_membros
                   WHERE id_cadastro = ?
                   ORDER BY data_ocorrencia DESC, id_historico DESC""",
                conn,
                params=(int(id_cadastro),),
            )
        return df
    except Exception:
        return pd.DataFrame(columns=[
            "id_historico", "data_ocorrencia", "codigo_tipo",
            "ocorrencia", "categoria", "localidade", "observacao",
        ])


def _inserir_historico(slug, id_cadastro, data_ocorrencia, codigo_tipo,
                        ocorrencia, categoria, localidade, observacao):
    _garantir_tabela_historico(slug)
    db_path = _tenant_db_path(slug)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """INSERT INTO historico_membros
               (id_cadastro, data_ocorrencia, codigo_tipo, ocorrencia,
                categoria, localidade, observacao, criado_em)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                int(id_cadastro),
                data_ocorrencia,
                codigo_tipo,
                ocorrencia,
                categoria,
                localidade,
                observacao,
                datetime.datetime.now().isoformat(timespec="seconds"),
            ),
        )
        conn.commit()


def _excluir_historico(slug, id_historico):
    _garantir_tabela_historico(slug)
    db_path = _tenant_db_path(slug)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "DELETE FROM historico_membros WHERE id_historico = ?",
            (int(id_historico),),
        )
        conn.commit()


def _rotulo_tipo_historico(codigo, ocorrencia, categoria):
    return f"{codigo} - {ocorrencia} - {categoria}"


def _html(valor):
    return html.escape(str(valor if valor is not None else ""), quote=True)


def _campo_linha(rotulo, valor):
    valor = _html(valor or "")
    return (
        '<div class="campo">'
        f'<div class="rotulo">{_html(rotulo)}</div>'
        f'<div class="valor">{valor}</div>'
        '</div>'
    )


# ═══════════════════════════════════════════════════════════════════════
# HTML do formulario para impressao (inalterado)
# ═══════════════════════════════════════════════════════════════════════

def _gerar_html_formulario_membro(row, igreja):
    igreja = igreja if isinstance(igreja, dict) else {}
    nome_igreja = igreja.get("nome") or igreja.get("slug") or "Igreja"
    tipo = _val(row, "tipo_cadastro")
    documento = _formatar_doc(_val(row, "cpf"), tipo)
    nascimento = _formatar_data(_val(row, "data_nascimento"))
    telefone = _formatar_tel(_val(row, "telefone"))
    cep = _formatar_cep(_val(row, "cep"))
    endereco = " ".join(
        p for p in [
            _val(row, "logradouro"),
            _val(row, "numero"),
        ]
        if p
    )
    emitido = datetime.datetime.now().strftime("%d/%m/%Y %H:%M")

    return f"""
<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="UTF-8"/>
<title>Formulario de cadastro - {_html(_val(row, "nome"))}</title>
<style>
* {{ box-sizing: border-box; }}
body {{ margin: 0; padding: 18px; background: #f3f4f6; color: #111827; font-family: Arial, Helvetica, sans-serif; }}
.toolbar {{ text-align: center; margin-bottom: 14px; }}
.toolbar button {{ background: #061B44; color: white; border: 0; border-radius: 8px; padding: 10px 22px; font-size: 14px; font-weight: 700; cursor: pointer; }}
.folha {{ width: 210mm; min-height: 297mm; margin: 0 auto; background: white; padding: 16mm; border: 1px solid #d1d5db; }}
.cabecalho {{ text-align: center; border-bottom: 2px solid #111827; padding-bottom: 10px; margin-bottom: 16px; }}
.igreja {{ font-size: 18px; font-weight: 800; text-transform: uppercase; }}
.titulo {{ font-size: 15px; font-weight: 700; margin-top: 6px; }}
.emitido {{ font-size: 11px; color: #6b7280; margin-top: 4px; }}
.secao {{ margin-top: 16px; }}
.secao h2 {{ font-size: 13px; text-transform: uppercase; border-bottom: 1px solid #9ca3af; padding-bottom: 4px; margin: 0 0 8px; }}
.grid {{ display: grid; grid-template-columns: repeat(2, 1fr); gap: 8px 12px; }}
.grid-3 {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px 12px; }}
.campo {{ min-height: 42px; border: 1px solid #d1d5db; border-radius: 6px; padding: 6px 8px; }}
.campo.full {{ grid-column: 1 / -1; }}
.rotulo {{ font-size: 10px; color: #6b7280; text-transform: uppercase; margin-bottom: 4px; }}
.valor {{ font-size: 13px; font-weight: 600; min-height: 16px; word-break: break-word; }}
.observacoes {{ height: 80px; border: 1px solid #d1d5db; border-radius: 6px; padding: 8px; }}
.assinaturas {{ display: grid; grid-template-columns: repeat(2, 1fr); gap: 32px; margin-top: 42px; }}
.assinatura {{ border-top: 1px solid #111827; text-align: center; padding-top: 6px; font-size: 12px; }}
@media print {{
    body {{ background: white; padding: 0; }}
    .toolbar {{ display: none !important; }}
    .folha {{ width: 100%; min-height: auto; margin: 0; border: 0; padding: 12mm; }}
}}
</style>
</head>
<body>
<div class="toolbar">
    <button onclick="window.print()">Imprimir formulario</button>
</div>
<main class="folha">
    <header class="cabecalho">
        <div class="igreja">{_html(nome_igreja)}</div>
        <div class="titulo">Formulario de Cadastro de Membro</div>
        <div class="emitido">Emitido em {emitido}</div>
    </header>
    <section class="secao">
        <h2>Dados principais</h2>
        <div class="grid">
            {_campo_linha("Nome completo", _val(row, "nome"))}
            {_campo_linha("Tipo de cadastro", tipo)}
            {_campo_linha("CPF", documento)}
            {_campo_linha("Data de nascimento", nascimento)}
            {_campo_linha("Sexo", _val(row, "sexo"))}
            {_campo_linha("Situacao", _val(row, "situacao"))}
            {_campo_linha("Funcao ministerial", _val(row, "funcao"))}
            {_campo_linha("Congregacao", _val(row, "congregacao"))}
        </div>
    </section>
    <section class="secao">
        <h2>Contato</h2>
        <div class="grid">
            {_campo_linha("Telefone / WhatsApp", telefone)}
            {_campo_linha("CEP", cep)}
        </div>
    </section>
    <section class="secao">
        <h2>Endereco</h2>
        <div class="grid">
            {_campo_linha("Rua / Avenida", endereco)}
            {_campo_linha("Bairro", _val(row, "bairro"))}
            {_campo_linha("Cidade", _val(row, "cidade"))}
            {_campo_linha("Numero", _val(row, "numero"))}
        </div>
    </section>
    <section class="secao">
        <h2>Observacoes</h2>
        <div class="observacoes"></div>
    </section>
    <section class="assinaturas">
        <div class="assinatura">Assinatura do membro</div>
        <div class="assinatura">Responsavel pelo cadastro</div>
    </section>
</main>
</body>
</html>
"""


# ═══════════════════════════════════════════════════════════════════════
# MODAL: Novo cadastro
# ═══════════════════════════════════════════════════════════════════════

@st.dialog("➕ Novo cadastro", width="large")
def modal_novo_cadastro(slug, plano, p_info, congregacao_fixa, bloqueado, limite):
    """Modal para criar novo membro ou fornecedor."""

    # Version counter para limpar widgets apos salvar
    if "mnc_ver" not in st.session_state:
        st.session_state["mnc_ver"] = 0
    ver = st.session_state["mnc_ver"]

    st.markdown("**Dados principais**")

    tipo = st.selectbox(
        "Tipo",
        TIPOS_CADASTRO,
        format_func=_rotulo_tipo_cadastro,
        key=f"mnc_tipo_v{ver}",
    )

    if tipo == "Membro" and bloqueado:
        st.error(
            f"⚠️ Voce atingiu o limite de **{limite} membros** do plano "
            f"**{p_info['nome']}**. Faca upgrade para "
            f"**{proximo_plano(plano).capitalize()}** para cadastrar mais membros."
        )
        st.info("Entre em contato com o administrador para upgrade do plano.")
        if st.button("Fechar", use_container_width=True, key=f"mnc_fechar_v{ver}"):
            st.rerun()
        return

    nome = st.text_input("Nome completo", key=f"mnc_nome_v{ver}")

    doc_label = "CPF *" if tipo == "Membro" else "CNPJ *"
    doc_placeholder = "000.000.000-00" if tipo == "Membro" else "00.000.000/0000-00"
    cpf = st.text_input(
        doc_label,
        placeholder=doc_placeholder,
        help="Obrigatorio.",
        key=f"mnc_cpf_v{ver}",
    )

    dt_nasc = st.date_input(
        "Data de nascimento" if tipo == "Membro" else "Data de fundacao",
        value=None,
        format="DD/MM/YYYY",
        key=f"mnc_dn_v{ver}",
        min_value=datetime.date(1900, 1, 1),
        max_value=datetime.date.today(),
    )

    if tipo == "Membro":
        sexo = st.selectbox("Sexo", SEXO_OPC, key=f"mnc_sexo_v{ver}")
        funcao = st.selectbox("Funcao", FUNCOES, key=f"mnc_funcao_v{ver}")
    else:
        sexo, funcao = "", ""

    st.text_input(
        "Congregacao",
        value=congregacao_fixa,
        disabled=True,
        key=f"mnc_cong_v{ver}",
        help="Definida automaticamente pelo identificador da igreja logada.",
    )

    sit = st.selectbox("Situacao", ["Ativo", "Inativo"], key=f"mnc_sit_v{ver}")

    st.markdown("**Contato**")
    telefone = st.text_input(
        "Telefone / WhatsApp",
        placeholder="(00) 00000-0000",
        key=f"mnc_tel_v{ver}",
    )

    st.markdown("**Endereco**")
    col1, col2 = st.columns([3, 1])
    with col1:
        logradouro = st.text_input(
            "Rua / Avenida",
            placeholder="Ex: Rua das Flores",
            key=f"mnc_log_v{ver}",
        )
    with col2:
        numero = st.text_input(
            "Numero",
            placeholder="123",
            key=f"mnc_num_v{ver}",
        )

    bairro = st.text_input(
        "Bairro",
        placeholder="Ex: Setor Central",
        key=f"mnc_bai_v{ver}",
    )

    col3, col4 = st.columns([2, 1])
    with col3:
        cidade = st.text_input("Cidade", value="Minacu", key=f"mnc_cid_v{ver}")
    with col4:
        cep = st.text_input("CEP", value="76450-000", key=f"mnc_cep_v{ver}")

    st.divider()

    c_salvar, c_cancelar = st.columns(2)
    with c_salvar:
        salvar = st.button(
            "💾 Salvar",
            type="primary",
            use_container_width=True,
            key=f"mnc_salvar_v{ver}",
        )
    with c_cancelar:
        cancelar = st.button(
            "Cancelar",
            use_container_width=True,
            key=f"mnc_cancelar_v{ver}",
        )

    if cancelar:
        st.session_state["mnc_ver"] += 1
        st.rerun()

    if salvar:
        dn_str = dt_nasc.isoformat() if dt_nasc else ""

        c = Cadastro(
            nome=nome,
            tipo_cadastro=tipo,
            funcao=funcao,
            congregacao=congregacao_fixa,
            cpf=cpf,
            situacao=sit,
            data_nascimento=dn_str,
            sexo=sexo,
            telefone=telefone,
            logradouro=logradouro,
            numero=numero,
            bairro=bairro,
            cidade=cidade,
            cep=cep,
        )

        erros = c.validar()

        doc_limpo = limpar_documento(cpf)
        if doc_limpo and cpf_existe(slug, doc_limpo):
            doc_tipo = "CPF" if tipo == "Membro" else "CNPJ"
            erros.append(doc_tipo + " ja cadastrado.")

        if erros:
            for e in erros:
                st.error(e)
        else:
            try:
                inserir_cadastro(slug, c)
            except LimiteMembrosExcedido as ex:
                st.error(str(ex))
            else:
                _invalida(slug)
                st.session_state["mnc_ver"] += 1
                st.toast("✅ Cadastro salvo!")
                st.rerun()


# ═══════════════════════════════════════════════════════════════════════
# MODAL: Editar cadastro
# ═══════════════════════════════════════════════════════════════════════

@st.dialog("✏️ Editar cadastro", width="large")
def modal_editar_cadastro(slug, sel, plano, p_info, congregacao_fixa, bloqueado):
    """Modal para editar cadastro existente."""

    id_sel = int(sel["id_cadastro"])
    kp = f"medit_{id_sel}_"

    st.markdown(f"**Editando:** {_val(sel, 'nome')} (ID #{id_sel})")
    st.divider()

    st.markdown("**Dados principais**")

    tipo_atual = _val(sel, "tipo_cadastro") or "Membro"
    tipo_edit = st.selectbox(
        "Tipo",
        TIPOS_CADASTRO,
        format_func=_rotulo_tipo_cadastro,
        index=TIPOS_CADASTRO.index(tipo_atual) if tipo_atual in TIPOS_CADASTRO else 0,
        key=kp + "tipo",
    )

    nome_edit = st.text_input(
        "Nome completo",
        value=_val(sel, "nome"),
        key=kp + "nome",
    )

    cpf_atual = _val(sel, "cpf")
    doc_label_e = "CPF *" if tipo_edit == "Membro" else "CNPJ *"
    doc_placeholder_e = "000.000.000-00" if tipo_edit == "Membro" else "00.000.000/0000-00"
    cpf_edit = st.text_input(
        doc_label_e,
        value=_formatar_doc(cpf_atual, tipo_edit) if cpf_atual else "",
        placeholder=doc_placeholder_e,
        key=kp + "cpf",
        help="Obrigatorio.",
    )

    dn_atual = _val(sel, "data_nascimento")
    try:
        dn_value = datetime.date.fromisoformat(dn_atual) if dn_atual else None
    except Exception:
        dn_value = None

    dt_nasc_edit = st.date_input(
        "Data de nascimento" if tipo_edit == "Membro" else "Data de fundacao",
        value=dn_value,
        format="DD/MM/YYYY",
        key=kp + "dt_nasc",
        min_value=datetime.date(1900, 1, 1),
        max_value=datetime.date.today(),
    )

    if tipo_edit == "Membro":
        sexo_atual = _val(sel, "sexo")
        idx_sexo = SEXO_OPC.index(sexo_atual) if sexo_atual in SEXO_OPC else 2
        sexo_edit = st.selectbox(
            "Sexo",
            SEXO_OPC,
            index=idx_sexo,
            key=kp + "sexo",
        )

        funcao_atual = _val(sel, "funcao")
        funcao_edit = st.selectbox(
            "Funcao",
            FUNCOES,
            index=FUNCOES.index(funcao_atual) if funcao_atual in FUNCOES else 0,
            key=kp + "funcao",
        )
    else:
        sexo_edit, funcao_edit = "", ""

    cong_edit = _val(sel, "congregacao") or congregacao_fixa
    st.text_input(
        "Congregacao",
        value=cong_edit,
        disabled=True,
        key=kp + "cong_fixo",
        help="Definida automaticamente pelo identificador da igreja logada.",
    )

    sit_opc = ["Ativo", "Inativo"]
    sit_edit = st.selectbox(
        "Situacao",
        sit_opc,
        index=sit_opc.index(sel["situacao"]) if sel["situacao"] in sit_opc else 0,
        key=kp + "sit",
    )

    st.markdown("**Contato**")
    tel_atual = _val(sel, "telefone")
    tel_edit = st.text_input(
        "Telefone / WhatsApp",
        value=_formatar_tel(tel_atual) if tel_atual else "",
        placeholder="(00) 00000-0000",
        key=kp + "tel",
    )

    st.markdown("**Endereco**")
    col1, col2 = st.columns([3, 1])
    with col1:
        log_edit = st.text_input(
            "Rua / Avenida",
            value=_val(sel, "logradouro"),
            key=kp + "log",
        )
    with col2:
        num_edit = st.text_input(
            "Numero",
            value=_val(sel, "numero"),
            key=kp + "num",
        )

    bai_edit = st.text_input(
        "Bairro",
        value=_val(sel, "bairro"),
        key=kp + "bai",
    )

    col3, col4 = st.columns([2, 1])
    with col3:
        cid_edit = st.text_input(
            "Cidade",
            value=_val(sel, "cidade"),
            key=kp + "cid",
        )
    with col4:
        cep_atual = _val(sel, "cep")
        cep_edit = st.text_input(
            "CEP",
            value=_formatar_cep(cep_atual) if cep_atual else "",
            key=kp + "cep",
        )

    st.divider()

    # Botoes
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
        # Limpa todas as keys do modal
        for k in list(st.session_state.keys()):
            if k.startswith(kp):
                st.session_state.pop(k, None)
        st.rerun()

    if salvar:
        dn_edit_str = dt_nasc_edit.isoformat() if dt_nasc_edit else ""

        c = Cadastro(
            id_cadastro=id_sel,
            nome=nome_edit,
            tipo_cadastro=tipo_edit,
            funcao=funcao_edit,
            congregacao=cong_edit,
            cpf=cpf_edit,
            situacao=sit_edit,
            data_nascimento=dn_edit_str,
            sexo=sexo_edit,
            telefone=tel_edit,
            logradouro=log_edit,
            numero=num_edit,
            bairro=bai_edit,
            cidade=cid_edit,
            cep=cep_edit,
        )

        erros = c.validar()

        doc_limpo_e = limpar_documento(cpf_edit)

        # Verifica limite de membros se mudou tipo para Membro
        if (
            tipo_edit == "Membro"
            and sel["tipo_cadastro"] != "Membro"
            and bloqueado
        ):
            erros.append(
                f"O plano {p_info['nome']} atingiu o limite de membros."
            )

        if doc_limpo_e and cpf_existe(slug, doc_limpo_e, id_excluir=id_sel):
            doc_tipo_e = "CPF" if tipo_edit == "Membro" else "CNPJ"
            erros.append(doc_tipo_e + " ja cadastrado em outro registro.")

        if erros:
            for e in erros:
                st.error(e)
        else:
            try:
                atualizar_cadastro(slug, c)
            except LimiteMembrosExcedido as ex:
                st.error(str(ex))
            else:
                _invalida(slug)
                # Limpa keys do modal
                for k in list(st.session_state.keys()):
                    if k.startswith(kp) or k.startswith("_auth_"):
                        st.session_state.pop(k, None)
                st.toast("✅ Cadastro alterado!")
                st.rerun()


# ═══════════════════════════════════════════════════════════════════════
# MODAL: Visualizar cadastro (somente leitura)
# ═══════════════════════════════════════════════════════════════════════

@st.dialog("👁️ Visualizar cadastro", width="large")
def modal_visualizar_cadastro(sel, igreja):
    """Modal para visualizar dados do cadastro em modo leitura."""

    slug = slug_da_sessao()
    nome = _val(sel, "nome") or "(sem nome)"
    tipo = _val(sel, "tipo_cadastro") or "Membro"
    id_sel = int(sel["id_cadastro"])
    situacao = _val(sel, "situacao") or "Ativo"

    # Header com nome + badge de tipo e situacao
    cor_situacao = "#10B981" if situacao == "Ativo" else "#EF4444"
    cor_tipo = "#3B82F6" if tipo == "Membro" else "#F59E0B"

    st.markdown(
        f"""
        <div style="margin-bottom:16px;">
            <div style="font-size:22px;font-weight:700;margin-bottom:6px;">{_html(nome)}</div>
            <span style="background:{cor_tipo}22;color:{cor_tipo};padding:3px 10px;
                         border-radius:12px;font-size:12px;font-weight:600;margin-right:6px;">
                {_html(_rotulo_tipo_cadastro(tipo))}
            </span>
            <span style="background:{cor_situacao}22;color:{cor_situacao};padding:3px 10px;
                         border-radius:12px;font-size:12px;font-weight:600;margin-right:6px;">
                {_html(situacao)}
            </span>
            <span style="color:#6b7280;font-size:12px;">ID #{id_sel}</span>
        </div>
        """,
        unsafe_allow_html=True,
    )

    # Tabs: Dados / Contato / Endereco / (Historico - apenas para Membro)
    rotulos_tabs = ["📋 Dados principais", "📞 Contato", "🏠 Endereco"]
    if tipo == "Membro":
        rotulos_tabs.append("🕰️ Historico")
        tab_dados, tab_contato, tab_endereco, tab_historico = st.tabs(rotulos_tabs)
    else:
        tab_dados, tab_contato, tab_endereco = st.tabs(rotulos_tabs)
        tab_historico = None

    with tab_dados:
        c1, c2 = st.columns(2)
        with c1:
            st.markdown("**CPF / CNPJ**")
            doc = _formatar_doc(_val(sel, "cpf"), tipo)
            st.code(doc if doc else "(nao informado)", language=None)

            st.markdown("**Data de nascimento**")
            st.code(_formatar_data(_val(sel, "data_nascimento")) or "(nao informado)", language=None)

            st.markdown("**Funcao ministerial**")
            st.code(_val(sel, "funcao") or "(nao informado)", language=None)

        with c2:
            st.markdown("**Sexo**")
            st.code(_val(sel, "sexo") or "(nao informado)", language=None)

            st.markdown("**Congregacao**")
            st.code(_val(sel, "congregacao") or "(nao informado)", language=None)

    with tab_contato:
        st.markdown("**Telefone / WhatsApp**")
        tel = _formatar_tel(_val(sel, "telefone"))
        st.code(tel if tel else "(nao informado)", language=None)

        # Link WhatsApp se houver telefone
        tel_digitos = "".join(c for c in _val(sel, "telefone") if c.isdigit())
        if tel_digitos:
            if not tel_digitos.startswith("55"):
                tel_digitos = "55" + tel_digitos
            link_wa = f"https://wa.me/{tel_digitos}"
            st.markdown(
                f'<a href="{link_wa}" target="_blank" '
                f'style="display:inline-block;background:#25D366;color:white;'
                f'padding:8px 18px;border-radius:6px;text-decoration:none;'
                f'font-weight:600;margin-top:8px;">'
                f'💬 Abrir conversa no WhatsApp</a>',
                unsafe_allow_html=True,
            )

    with tab_endereco:
        c1, c2 = st.columns(2)
        with c1:
            st.markdown("**CEP**")
            st.code(_formatar_cep(_val(sel, "cep")) or "(nao informado)", language=None)

            st.markdown("**Rua / Avenida**")
            st.code(_val(sel, "logradouro") or "(nao informado)", language=None)

            st.markdown("**Numero**")
            st.code(_val(sel, "numero") or "(nao informado)", language=None)

        with c2:
            st.markdown("**Bairro**")
            st.code(_val(sel, "bairro") or "(nao informado)", language=None)

            st.markdown("**Cidade**")
            st.code(_val(sel, "cidade") or "(nao informado)", language=None)

        # Botao para abrir no Google Maps
        endereco_completo = ", ".join(filter(None, [
            _val(sel, "logradouro"),
            _val(sel, "numero"),
            _val(sel, "bairro"),
            _val(sel, "cidade"),
        ]))
        if endereco_completo.strip():
            import urllib.parse
            link_maps = "https://www.google.com/maps/search/?api=1&query=" + urllib.parse.quote_plus(endereco_completo)
            st.markdown(
                f'<a href="{link_maps}" target="_blank" '
                f'style="display:inline-block;background:#061B44;color:white;'
                f'padding:8px 18px;border-radius:6px;text-decoration:none;'
                f'font-weight:600;margin-top:8px;">'
                f'🗺️ Abrir no Google Maps</a>',
                unsafe_allow_html=True,
            )

    if tab_historico is not None:
        with tab_historico:
            st.caption(
                "Registre os marcos e movimentacoes do membro na igreja: conversao, "
                "batismo, consagracoes, transferencias, desligamentos, etc."
            )

            # ─── Formulario para adicionar nova ocorrencia ───────────────
            with st.expander("➕ Adicionar ocorrencia", expanded=False):
                opcoes_tipo = {
                    _rotulo_tipo_historico(codigo, ocorrencia, categoria): (codigo, ocorrencia, categoria)
                    for codigo, ocorrencia, categoria in TIPOS_HISTORICO
                }
                col_data, col_tipo = st.columns([1, 2])
                with col_data:
                    data_hist = st.date_input(
                        "Data",
                        value=datetime.date.today(),
                        format="DD/MM/YYYY",
                        key=f"mhist_data_{id_sel}",
                    )
                with col_tipo:
                    escolha_tipo = st.selectbox(
                        "Tipo de ocorrencia",
                        list(opcoes_tipo.keys()),
                        key=f"mhist_tipo_{id_sel}",
                    )
                codigo_sel, ocorrencia_sel, categoria_sel = opcoes_tipo[escolha_tipo]

                localidade_padrao = _val(sel, "congregacao")
                localidade_hist = st.text_input(
                    "Localidade / Congregacao",
                    value=localidade_padrao,
                    key=f"mhist_local_{id_sel}",
                    help="Congregacao ou igreja relacionada a esta ocorrencia.",
                )
                observacao_hist = st.text_area(
                    "Observacao (opcional)",
                    key=f"mhist_obs_{id_sel}",
                    height=80,
                )

                if st.button(
                    "💾 Salvar ocorrencia",
                    type="primary",
                    use_container_width=True,
                    key=f"mhist_salvar_{id_sel}",
                ):
                    try:
                        _inserir_historico(
                            slug=slug,
                            id_cadastro=id_sel,
                            data_ocorrencia=data_hist.isoformat(),
                            codigo_tipo=codigo_sel,
                            ocorrencia=ocorrencia_sel,
                            categoria=categoria_sel,
                            localidade=localidade_hist,
                            observacao=observacao_hist,
                        )
                    except Exception as exc:
                        st.error(f"Nao foi possivel salvar a ocorrencia: {exc}")
                    else:
                        st.toast("✅ Ocorrencia registrada!")
                        st.rerun()

            st.divider()

            # ─── Tabela de historico existente ───────────────────────────
            df_hist = _listar_historico(slug, id_sel)

            if df_hist.empty:
                st.info("Nenhuma ocorrencia registrada ainda para este membro.")
            else:
                for _, linha in df_hist.iterrows():
                    categoria_h = linha.get("categoria") or "Normal"
                    cor_cat = CATEGORIA_COR.get(categoria_h, "#3B82F6")
                    data_fmt = _formatar_data(linha.get("data_ocorrencia", ""))
                    ocorrencia_txt = linha.get("ocorrencia", "") or ""
                    localidade_txt = linha.get("localidade", "") or "(nao informado)"
                    observacao_txt = linha.get("observacao", "") or ""
                    id_hist = int(linha["id_historico"])

                    col_txt, col_del = st.columns([9, 1])
                    with col_txt:
                        obs_html = (
                            f'<div style="color:#6b7280;font-size:12px;margin-top:3px;">'
                            f'{_html(observacao_txt)}</div>'
                            if observacao_txt else ""
                        )
                        st.markdown(
                            f"""
                            <div style="padding:10px 12px;border-left:3px solid {cor_cat};
                                        background:{cor_cat}10;border-radius:6px;margin-bottom:8px;">
                                <div style="display:flex;justify-content:space-between;flex-wrap:wrap;">
                                    <strong style="font-size:13px;">{_html(data_fmt)}</strong>
                                    <span style="background:{cor_cat}22;color:{cor_cat};
                                                 padding:1px 8px;border-radius:10px;font-size:11px;
                                                 font-weight:600;">{_html(categoria_h)}</span>
                                </div>
                                <div style="margin-top:4px;font-size:13px;">{_html(ocorrencia_txt)}</div>
                                <div style="color:#6b7280;font-size:12px;margin-top:2px;">
                                    📍 {_html(localidade_txt)}
                                </div>
                                {obs_html}
                            </div>
                            """,
                            unsafe_allow_html=True,
                        )
                    with col_del:
                        if st.button(
                            "🗑️",
                            key=f"mhist_del_{id_hist}",
                            help="Excluir esta ocorrencia",
                        ):
                            st.session_state[f"mhist_confirmar_del_{id_hist}"] = True
                            st.rerun()

                    if st.session_state.get(f"mhist_confirmar_del_{id_hist}"):
                        st.warning(
                            f"Confirma a exclusao da ocorrencia "
                            f"**{ocorrencia_txt}** de {data_fmt}?"
                        )
                        cc1, cc2 = st.columns(2)
                        with cc1:
                            if st.button(
                                "Sim, excluir",
                                type="primary",
                                use_container_width=True,
                                key=f"mhist_del_sim_{id_hist}",
                            ):
                                try:
                                    _excluir_historico(slug, id_hist)
                                except Exception as exc:
                                    st.error(f"Nao foi possivel excluir: {exc}")
                                else:
                                    st.session_state.pop(f"mhist_confirmar_del_{id_hist}", None)
                                    st.toast("Ocorrencia excluida.")
                                    st.rerun()
                        with cc2:
                            if st.button(
                                "Cancelar",
                                use_container_width=True,
                                key=f"mhist_del_nao_{id_hist}",
                            ):
                                st.session_state.pop(f"mhist_confirmar_del_{id_hist}", None)
                                st.rerun()

    st.divider()

    if st.button("Fechar", use_container_width=True, key=f"mview_fechar_{id_sel}"):
        st.rerun()


# ═══════════════════════════════════════════════════════════════════════
# MODAL: Excluir cadastro
# ═══════════════════════════════════════════════════════════════════════

@st.dialog("🗑️ Excluir cadastro", width="small")
def modal_excluir_cadastro(slug, sel):
    """Modal para confirmar exclusao do cadastro."""

    id_sel = int(sel["id_cadastro"])
    nome = _val(sel, "nome")
    tipo = _val(sel, "tipo_cadastro")

    # Verifica se esta em uso
    em_uso = cadastro_em_uso(slug, id_sel)

    if em_uso:
        st.error(
            f"❌ **Nao e possivel excluir.**\n\n"
            f"O cadastro **{nome}** esta vinculado a lancamentos. "
            f"Para excluir, primeiro remova ou altere todos os lancamentos vinculados."
        )

        if st.button("Fechar", use_container_width=True, key=f"mexc_fechar_{id_sel}"):
            st.rerun()
        return

    st.warning(
        f"⚠️ Voce esta prestes a excluir:\n\n"
        f"**{nome}** ({_rotulo_tipo_cadastro(tipo)})\n\n"
        f"Esta acao **nao pode ser desfeita**."
    )

    confirmar = st.checkbox(
        f"Confirmo a exclusao de {nome}",
        key=f"mexc_conf_{id_sel}",
    )

    c1, c2 = st.columns(2)
    with c1:
        excluir = st.button(
            "🗑️ Excluir definitivamente",
            type="primary",
            use_container_width=True,
            disabled=not confirmar,
            key=f"mexc_excluir_{id_sel}",
        )
    with c2:
        cancelar = st.button(
            "Cancelar",
            use_container_width=True,
            key=f"mexc_cancelar_{id_sel}",
        )

    if cancelar:
        st.session_state.pop(f"mexc_conf_{id_sel}", None)
        st.rerun()

    if excluir:
        try:
            excluir_cadastro(slug, id_sel)
            _invalida(slug)
            # Limpa keys
            for k in list(st.session_state.keys()):
                if (k.startswith("mexc_")
                    or k.startswith("_auth_")
                    or k == "sel_cad_acao"):
                    st.session_state.pop(k, None)
            st.toast(f"✅ Cadastro de {nome} excluido!")
            st.rerun()
        except Exception as exc:
            st.error(f"❌ Erro ao excluir: {exc}")


# ═══════════════════════════════════════════════════════════════════════
# Funcao principal: render()
# ═══════════════════════════════════════════════════════════════════════

def render():
    slug = slug_da_sessao()
    st.subheader("👥 Membros e fornecedores")
    df = _get(slug)

    igreja = st.session_state.get("igreja", {})
    plano = igreja.get("plano", "basico")
    p_info = obter_plano(plano)

    congregacao_fixa = _congregacao_da_sessao(slug, igreja)

    # ─── Pre-cadastros pendentes (mantido como expander) ────────────
    with st.expander("Pre-cadastros pendentes", expanded=False):
        try:
            pre = listar_pre_cadastros_membros(slug, "Pendente")
        except Exception:
            pre = pd.DataFrame()
            st.error("Nao foi possivel carregar os pre-cadastros.")
        if pre.empty:
            st.info("Nenhum pre-cadastro pendente.")
        else:
            exibir_pre = pre.copy()
            exibir_pre["cpf"] = exibir_pre["cpf"].apply(_formatar_cpf)
            exibir_pre["data_nascimento"] = exibir_pre["data_nascimento"].apply(_formatar_data)
            st.dataframe(
                exibir_pre[[
                    "id_pre_cadastro", "nome", "cpf", "data_nascimento",
                    "sexo", "estado_civil", "tipo_membro", "funcao",
                    "telefone", "cidade", "status", "criado_em",
                ]],
                use_container_width=True,
                hide_index=True,
            )
            op_pre = {
                f'{int(row["id_pre_cadastro"])} | {row["nome"]} | {row["cpf"]}': row
                for _, row in pre.iterrows()
            }
            selecionado_pre = st.selectbox(
                "Selecionar pre-cadastro",
                ["Selecione"] + list(op_pre.keys()),
                key="sel_pre_cadastro",
            )
            if selecionado_pre != "Selecione":
                row_pre = op_pre[selecionado_pre]
                st.write(row_pre.to_dict())
                c_aprovar, c_rejeitar, c_dup = st.columns(3)
                with c_aprovar:
                    if st.button("Aprovar como membro", type="primary"):
                        try:
                            aprovar_pre_cadastro_membro(slug, int(row_pre["id_pre_cadastro"]))
                        except Exception as exc:
                            st.error(str(exc))
                        else:
                            _invalida(slug)
                            st.success("Pre-cadastro aprovado e membro criado.")
                            st.rerun()
                with c_rejeitar:
                    if st.button("Rejeitar"):
                        atualizar_status_pre_cadastro(
                            slug, int(row_pre["id_pre_cadastro"]), "Rejeitado"
                        )
                        st.success("Pre-cadastro rejeitado.")
                        st.rerun()
                with c_dup:
                    if st.button("Marcar duplicado"):
                        atualizar_status_pre_cadastro(
                            slug, int(row_pre["id_pre_cadastro"]), "Duplicado"
                        )
                        st.success("Pre-cadastro marcado como duplicado.")
                        st.rerun()

    # ─── Barra de progresso de membros ──────────────────────────────
    if not df.empty and "tipo_cadastro" in df.columns:
        tipos = df["tipo_cadastro"].fillna("").astype(str).str.strip().str.upper()
        qtd_membros = len(df[tipos == "MEMBRO"])
    else:
        qtd_membros = 0

    limite = p_info["limite_membros"]
    bloqueado = not pode_cadastrar_membro(plano, qtd_membros)

    if limite:
        pct = min(100, int((qtd_membros / limite) * 100))
        cor_barra = "#D85A30" if pct >= 90 else ("#F5A623" if pct >= 70 else "#1D9E75")
        st.markdown(f"""
        <div style="background:#f8f9fa;padding:10px 14px;border-radius:8px;margin-bottom:14px">
            <div style="display:flex;justify-content:space-between;font-size:0.85rem;margin-bottom:4px">
                <span><b>Plano {p_info['nome']}:</b> {qtd_membros} de {limite} membros</span>
                <span style="color:{cor_barra};font-weight:600">{pct}%</span>
            </div>
            <div style="background:#e9ecef;height:6px;border-radius:3px;overflow:hidden">
                <div style="background:{cor_barra};height:100%;width:{pct}%"></div>
            </div>
        </div>
        """, unsafe_allow_html=True)

    # ─── BOTAO PRINCIPAL: Novo cadastro ─────────────────────────────
    if st.button(
        "➕ Novo cadastro",
        type="primary",
        use_container_width=True,
        key="btn_abrir_novo",
    ):
        modal_novo_cadastro(slug, plano, p_info, congregacao_fixa, bloqueado, limite)

    # ─── Tabela de cadastros ────────────────────────────────────────
    total = len(df)
    with st.expander(f"📋 Ver cadastros ({total} registros)", expanded=False):
        if df.empty:
            st.info("Nenhum cadastro ainda.")
        else:
            df_view = df.copy()

            for col in [
                "cpf", "cep", "telefone", "logradouro", "numero", "bairro",
                "cidade", "data_nascimento", "sexo"
            ]:
                if col not in df_view.columns:
                    df_view[col] = ""

            if "tipo_cadastro" in df_view.columns:
                df_view["cpf"] = df_view.apply(
                    lambda r: _formatar_doc(
                        str(r["cpf"]),
                        str(r["tipo_cadastro"])
                    ) if str(r["cpf"]).strip() else "",
                    axis=1,
                )
            else:
                df_view["cpf"] = df_view["cpf"].apply(
                    lambda x: _formatar_cpf(str(x)) if str(x).strip() else ""
                )

            df_view["cep"] = df_view["cep"].apply(
                lambda x: _formatar_cep(str(x)) if str(x).strip() else ""
            )
            df_view["telefone"] = df_view["telefone"].apply(
                lambda x: _formatar_tel(str(x)) if str(x).strip() else ""
            )
            df_view["data_nascimento"] = df_view["data_nascimento"].apply(
                lambda x: _formatar_data(str(x)) if str(x).strip() else ""
            )

            df_view = df_view.rename(columns={"cpf": "documento"})
            st.dataframe(df_view, use_container_width=True)

    # ─── Acoes em cadastros existentes (Visualizar/Editar/Excluir) ──
    if not df.empty:
        st.divider()
        st.markdown("### 🎯 Acoes em cadastro existente")

        df_r = df.reset_index(drop=True)
        df_r["rotulo"] = df_r.apply(
            lambda r: f'{int(r["id_cadastro"])} | {r["tipo_cadastro"]} | {r["nome"]} | {r["situacao"]}',
            axis=1,
        )

        rotulo = st.selectbox(
            "Selecione um cadastro",
            df_r["rotulo"].tolist(),
            key="sel_cad_acao",
        )

        sel = df_r[df_r["rotulo"] == rotulo].iloc[0]

        c_view, c_edit, c_del = st.columns(3)

        with c_view:
            if st.button(
                "👁️ Visualizar",
                use_container_width=True,
                key="btn_abrir_view",
            ):
                modal_visualizar_cadastro(sel, igreja)

        with c_edit:
            if st.button(
                "✏️ Editar",
                use_container_width=True,
                key="btn_abrir_edit",
            ):
                modal_editar_cadastro(slug, sel, plano, p_info, congregacao_fixa, bloqueado)

        with c_del:
            if st.button(
                "🗑️ Excluir",
                use_container_width=True,
                key="btn_abrir_del",
            ):
                modal_excluir_cadastro(slug, sel)

    # ─── Imprimir formulario (mantido como expander) ────────────────
    with st.expander("🖨️ Imprimir formulario de cadastro de membro", expanded=False):
        tipo_formulario = st.radio(
            "Tipo de formulario",
            ["Em branco", "Preenchido com dados de um membro"],
            horizontal=True,
            key="tipo_formulario_impressao_membro",
        )

        if tipo_formulario == "Em branco":
            row_imp = {
                "nome": "",
                "tipo_cadastro": "Membro",
                "cpf": "",
                "data_nascimento": "",
                "sexo": "",
                "situacao": "",
                "funcao": "",
                "congregacao": congregacao_fixa,
                "telefone": "",
                "cep": "",
                "logradouro": "",
                "numero": "",
                "bairro": "",
                "cidade": "",
            }
            html_form = _gerar_html_formulario_membro(row_imp, igreja)
            components.html(html_form, height=760, scrolling=True)
            st.download_button(
                "Baixar formulario em branco HTML",
                data=html_form,
                file_name="formulario_cadastro_membro_em_branco.html",
                mime="text/html",
                use_container_width=True,
            )
        elif df.empty:
            st.info("Nenhum cadastro ainda.")
        else:
            df_membros = (
                df[df["tipo_cadastro"].fillna("").astype(str).str.strip().str.upper() == "MEMBRO"].copy()
                if "tipo_cadastro" in df.columns
                else pd.DataFrame()
            )

            if df_membros.empty:
                st.info("Nenhum membro cadastrado para impressao.")
            else:
                df_membros = df_membros.sort_values("nome")
                op_membros = {
                    f'{int(row["id_cadastro"])} | {row["nome"]} | {row["situacao"]}': row
                    for _, row in df_membros.iterrows()
                }
                membro_imp = st.selectbox(
                    "Selecione o membro",
                    list(op_membros.keys()),
                    key="sel_membro_impressao_formulario",
                )
                row_imp = op_membros[membro_imp]
                html_form = _gerar_html_formulario_membro(row_imp, igreja)
                components.html(html_form, height=760, scrolling=True)
                nome_arquivo = (
                    "formulario_cadastro_"
                    + str(row_imp.get("nome", "membro")).strip().replace(" ", "_").lower()
                    + ".html"
                )
                st.download_button(
                    "Baixar formulario HTML",
                    data=html_form,
                    file_name=nome_arquivo,
                    mime="text/html",
                    use_container_width=True,
                )