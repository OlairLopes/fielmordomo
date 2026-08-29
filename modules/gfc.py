import logging
import datetime

import pandas as pd
import streamlit as st

from data.repository import (
    carregar_cadastros,
    encerrar_gfc_matricula,
    excluir_gfc_coordenador,
    excluir_gfc_grupo,
    excluir_gfc_lider,
    excluir_gfc_matricula,
    excluir_gfc_reuniao,
    inativar_gfc_secretaria,
    listar_gfc_coordenadores,
    listar_gfc_grupos,
    listar_gfc_lideres,
    listar_gfc_matriculas,
    listar_gfc_presencas,
    listar_gfc_reunioes,
    listar_gfc_secretarias,
    salvar_gfc_coordenador,
    salvar_gfc_grupo,
    salvar_gfc_lider,
    salvar_gfc_matricula,
    salvar_gfc_reuniao,
    salvar_gfc_secretaria,
)
from utils.helpers import confirmar_exclusao, gerar_csv, normalizar_data_digitada, slug_da_sessao


TIPOS_CULTO_GFC = [
    "Culto Evangelístico",
    "Culto de Oração",
    "Culto Ação de Graças",
    "Vigília",
]


def _hoje():
    return datetime.date.today()


def _inicio_mes():
    return _hoje().replace(day=1)


def _fmt_data(valor):
    try:
        return datetime.date.fromisoformat(str(valor)).strftime("%d/%m/%Y")
    except Exception:
        return str(valor or "")


def _data_iso(valor):
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


def _grupo_opcoes(grupos):
    return {
        f'{int(row["id_grupo"])} - {row["nome"]} ({row.get("setor", "") or "Sem setor"})': int(row["id_grupo"])
        for _, row in grupos.iterrows()
    }


def _lideres_opcoes(lideres):
    if lideres.empty:
        return {}
    return {
        f'{row["nome"]} ({row.get("setor", "") or "Sem setor"})': row
        for _, row in lideres.sort_values(["setor", "nome"]).iterrows()
    }


def _coordenadores_opcoes(coordenadores):
    if coordenadores.empty:
        return {}
    return {
        f'{row["nome"]} ({row.get("setor", "") or "Sem setor"})': row
        for _, row in coordenadores.sort_values(["ordem", "nome"]).iterrows()
    }


def _indice_por_nome(labels, opcoes, nome):
    nome = str(nome or "").strip()
    if not nome:
        return 0
    for idx, label in enumerate(labels):
        row = opcoes.get(label)
        if row is not None and str(row.get("nome", "") or "").strip() == nome:
            return idx
    return 0


def _render_cards_coordenadores_gfc(slug):
    coordenadores = listar_gfc_coordenadores(slug)
    if coordenadores.empty:
        return

    def _esc_card(valor):
        return (
            str(valor if valor is not None else "")
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;")
            .replace("'", "&#x27;")
        )

    cards = []
    for idx, (_, row) in enumerate(coordenadores.head(2).iterrows(), start=1):
        titulo = f"{idx}º Coordenador"
        nome = _esc_card(row.get("nome", "") or "")
        funcao = _esc_card(row.get("funcao", "") or "Coordenador")
        telefone = _esc_card(row.get("telefone", "") or "")
        cards.append(
            '<div class="gfc-coord-card">'
            f'<span class="gfc-coord-label">{titulo}</span>'
            f'<b>{nome}</b>'
            f'<small>{funcao}</small>'
            f'<small>{telefone}</small>'
            '</div>'
        )

    st.markdown(
        """
        <style>
        .gfc-coord-grid {
            display: grid;
            grid-template-columns: repeat(2, minmax(0, 1fr));
            gap: 12px;
            margin: 8px 0 22px 0;
        }
        .gfc-coord-card {
            border: 1px solid #E2E8F0;
            border-radius: 12px;
            padding: 18px 20px;
            background: #FFFFFF;
            box-shadow: 0 10px 24px rgba(15, 23, 42, 0.06);
            min-height: 92px;
        }
        .gfc-coord-card b {
            display: block;
            color: #0F172A;
            font-size: 1.08rem;
            font-weight: 800;
            margin-bottom: 8px;
        }
        .gfc-coord-label {
            display: block;
            color: #DC2626;
            font-size: 0.76rem;
            font-weight: 800;
            letter-spacing: 0.02em;
            margin-bottom: 8px;
            text-transform: uppercase;
        }
        .gfc-coord-card small {
            display: block;
            color: #64748B;
            font-size: 0.82rem;
            line-height: 1.45;
        }
        @media(max-width: 760px) {
            .gfc-coord-grid { grid-template-columns: 1fr; }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )
    st.markdown(
        f'<div class="gfc-coord-grid">{"".join(cards)}</div>',
        unsafe_allow_html=True,
    )


def _membros_opcoes(slug):
    df = carregar_cadastros(slug)
    if df.empty:
        return {}, df
    df = df.copy()
    for col in ["tipo_cadastro", "situacao", "nome", "cpf"]:
        if col not in df.columns:
            df[col] = ""
    membros = df[
        (df["tipo_cadastro"].fillna("").astype(str).str.upper() == "MEMBRO") &
        (df["situacao"].fillna("").astype(str).str.upper() == "ATIVO")
    ].copy()
    if membros.empty:
        return {}, membros
    membros = membros.sort_values("nome")
    opcoes = {
        f'{row["nome"]} - CPF final {str(row.get("cpf", "") or "")[-4:]}': row
        for _, row in membros.iterrows()
    }
    return opcoes, membros


def _render_grupos(slug):
    st.markdown("### Grupos Familiares")
    st.caption("Cadastre os grupos familiares de crescimento e seus setores.")

    grupos = listar_gfc_grupos(slug, incluir_inativos=True)
    lideres = listar_gfc_lideres(slug)
    op_lideres = _lideres_opcoes(lideres)

    with st.expander("Cadastrar grupo familiar", expanded=grupos.empty):
        if not op_lideres:
            st.warning("Cadastre ao menos um lider ativo na aba Coordenadores e lideres antes de criar grupos.")
        with st.form("form_gfc_grupo"):
            c1, c2 = st.columns(2)
            nome = c1.text_input("Nome do grupo familiar")
            setor = c2.text_input("Setor do grupo familiar")
            c3, c4 = st.columns(2)
            lider_label = c3.selectbox("Lider", list(op_lideres.keys()) if op_lideres else ["Cadastre um lider"])
            lider_row = op_lideres.get(lider_label)
            responsavel = str(lider_row.get("nome", "") or "") if lider_row is not None else ""
            telefone_padrao = str(lider_row.get("telefone", "") or "") if lider_row is not None else ""
            telefone = c4.text_input("Telefone", value=telefone_padrao)
            observacoes = st.text_area("Observações")
            if st.form_submit_button("Salvar grupo", type="primary"):
                if not responsavel:
                    st.error("Cadastre e selecione um lider para o grupo familiar.")
                    return
                try:
                    salvar_gfc_grupo(
                        slug,
                        nome=nome,
                        setor=setor,
                        responsavel=responsavel,
                        telefone=telefone,
                        observacoes=observacoes,
                    )
                    st.success("Grupo familiar salvo.")
                    st.rerun()
                except Exception as exc:
                    st.error(str(exc))

    if grupos.empty:
        st.info("Nenhum grupo familiar cadastrado ainda.")
        return

    exibir = grupos.copy()
    exibir["situação"] = exibir["ativo"].map({1: "Ativo", 0: "Inativo"})
    exibir = exibir.rename(columns={"responsavel": "lider"})
    st.dataframe(
        exibir[["nome", "setor", "lider", "telefone", "situação", "observacoes"]],
        use_container_width=True,
        hide_index=True,
    )

    with st.expander("Editar ou inativar grupo", expanded=False):
        opcoes = {
            f'{int(row["id_grupo"])} - {row["nome"]} ({row.get("setor", "") or "Sem setor"})': row
            for _, row in grupos.iterrows()
        }
        selecionado = st.selectbox("Grupo familiar", ["Selecione"] + list(opcoes.keys()))
        if selecionado != "Selecione":
            row = opcoes[selecionado]
            with st.form(f"form_editar_gfc_grupo_{int(row['id_grupo'])}"):
                c1, c2 = st.columns(2)
                nome = c1.text_input("Nome do grupo familiar", value=str(row.get("nome", "") or ""))
                setor = c2.text_input("Setor do grupo familiar", value=str(row.get("setor", "") or ""))
                c3, c4 = st.columns(2)
                lider_labels = list(op_lideres.keys()) if op_lideres else ["Cadastre um lider"]
                lider_atual = str(row.get("responsavel", "") or "").strip()
                idx_lider = 0
                for idx, label in enumerate(lider_labels):
                    lider_row = op_lideres.get(label)
                    if lider_row is not None and str(lider_row.get("nome", "") or "").strip() == lider_atual:
                        idx_lider = idx
                        break
                lider_label = c3.selectbox(
                    "Lider",
                    lider_labels,
                    index=idx_lider,
                    key=f"gfc_grupo_lider_{int(row['id_grupo'])}",
                )
                lider_row = op_lideres.get(lider_label)
                responsavel = str(lider_row.get("nome", "") or "") if lider_row is not None else lider_atual
                telefone_padrao = str(lider_row.get("telefone", "") or "") if lider_row is not None else str(row.get("telefone", "") or "")
                telefone = c4.text_input("Telefone", value=telefone_padrao)
                ativo = st.selectbox(
                    "Situação",
                    ["Ativo", "Inativo"],
                    index=0 if int(row.get("ativo", 1) or 0) == 1 else 1,
                )
                observacoes = st.text_area("Observações", value=str(row.get("observacoes", "") or ""))
                if st.form_submit_button("Atualizar grupo", type="primary"):
                    if not responsavel:
                        st.error("Cadastre e selecione um lider para o grupo familiar.")
                        return
                    try:
                        salvar_gfc_grupo(
                            slug,
                            nome=nome,
                            setor=setor,
                            responsavel=responsavel,
                            telefone=telefone,
                            observacoes=observacoes,
                            ativo=ativo == "Ativo",
                            id_grupo=int(row["id_grupo"]),
                        )
                        st.success("Grupo familiar atualizado.")
                        st.rerun()
                    except Exception as exc:
                        st.error(str(exc))

            if st.button("Inativar/excluir grupo", key=f"gfc_excluir_grupo_{int(row['id_grupo'])}"):
                removido = excluir_gfc_grupo(slug, int(row["id_grupo"]))
                st.success("Grupo excluído." if removido else "Grupo inativado porque possui histórico.")
                st.rerun()


def _render_matriculas(slug, id_grupo_restrito=None):
    st.markdown("### Matrículas GFC")
    st.caption("Matricule participantes por grupo familiar. A chamada respeita a data de início e encerramento.")

    grupos = listar_gfc_grupos(slug)
    if id_grupo_restrito:
        grupos = grupos[grupos["id_grupo"].astype(int) == int(id_grupo_restrito)].copy()
    if grupos.empty:
        st.warning("Nenhum grupo familiar ativo foi encontrado.")
        return

    op_grupos = _grupo_opcoes(grupos)
    op_membros, _ = _membros_opcoes(slug)

    with st.expander("Nova matrícula", expanded=False):
        with st.form("form_gfc_matricula"):
            grupo_label = st.selectbox("Grupo familiar", list(op_grupos.keys()))
            if not op_membros:
                st.warning("Não há membros ativos disponíveis para matrícula.")
                membro_label = None
            else:
                membro_label = st.selectbox("Membro", list(op_membros.keys()))
            c1, c2 = st.columns(2)
            data_inicio = c1.date_input("Data de início", value=_hoje(), format="DD/MM/YYYY")
            observacoes = c2.text_input("Observações")
            if st.form_submit_button("Matricular", type="primary"):
                if not membro_label:
                    st.error("Selecione um membro.")
                else:
                    membro = op_membros[membro_label]
                    salvar_gfc_matricula(
                        slug,
                        id_grupo=op_grupos[grupo_label],
                        id_cadastro=int(membro["id_cadastro"]),
                        data_inicio=data_inicio.isoformat(),
                        observacoes=observacoes,
                    )
                    st.success("Matrícula GFC salva.")
                    st.rerun()

    grupo_filtro = None
    if id_grupo_restrito:
        grupo_filtro = int(id_grupo_restrito)
    else:
        filtro_label = st.selectbox(
            "Filtrar matrículas por grupo",
            ["Todos"] + list(op_grupos.keys()),
            key="gfc_matriculas_filtro_grupo",
        )
        if filtro_label != "Todos":
            grupo_filtro = op_grupos[filtro_label]

    matriculas = listar_gfc_matriculas(
        slug,
        id_grupo=grupo_filtro,
        incluir_inativas=True,
    )
    if matriculas.empty:
        st.info("Nenhuma matrícula GFC cadastrada.")
        return

    exibir = matriculas.copy()
    exibir["situacao_matricula"] = exibir["ativa"].map({1: "Ativa", 0: "Encerrada"})
    exibir["data_inicio"] = exibir["data_inicio"].apply(_fmt_data)
    exibir["data_fim"] = exibir["data_fim"].apply(_fmt_data)
    st.dataframe(
        exibir[[
            "grupo", "setor", "nome", "telefone", "funcao", "situacao_matricula",
            "data_inicio", "data_fim", "observacoes",
        ]],
        use_container_width=True,
        hide_index=True,
    )

    op_matriculas = {
        f'{int(row["id_matricula"])} - {row["nome"]} ({row["grupo"]})': row
        for _, row in matriculas.iterrows()
    }

    with st.expander("Editar matrícula", expanded=False):
        selecionada = st.selectbox(
            "Matrícula para editar",
            ["Selecione"] + list(op_matriculas.keys()),
            key="gfc_editar_matricula",
        )
        if selecionada != "Selecione":
            row = op_matriculas[selecionada]
            grupo_labels = list(op_grupos.keys())
            grupo_idx = 0
            for idx, label in enumerate(grupo_labels):
                if op_grupos[label] == int(row["id_grupo"]):
                    grupo_idx = idx
                    break
            with st.form(f"form_editar_matricula_gfc_{int(row['id_matricula'])}"):
                grupo_label = st.selectbox("Grupo familiar", grupo_labels, index=grupo_idx)
                c1, c2 = st.columns(2)
                nome = c1.text_input("Nome", value=row.get("nome", ""))
                telefone = c2.text_input("Telefone / WhatsApp", value=row.get("telefone", ""))
                data_inicio = st.text_input(
                    "Data de início",
                    value=str(row.get("data_inicio", "") or ""),
                    placeholder="Ex.: 26/06/2024 ou 26062024",
                )
                ativa = st.selectbox(
                    "Situação",
                    ["Ativa", "Encerrada"],
                    index=0 if int(row.get("ativa", 1) or 0) == 1 else 1,
                )
                observacoes = st.text_area("Observações", value=row.get("observacoes", ""))
                if st.form_submit_button("Atualizar matrícula", type="primary"):
                    salvar_gfc_matricula(
                        slug,
                        id_grupo=op_grupos[grupo_label],
                        nome=nome,
                        id_cadastro=row.get("id_cadastro"),
                        telefone=telefone,
                        data_inicio=_data_iso(normalizar_data_digitada(data_inicio)),
                        observacoes=observacoes,
                        id_matricula=int(row["id_matricula"]),
                        ativa=ativa == "Ativa",
                    )
                    st.success("Matrícula GFC atualizada.")
                    st.rerun()

    ativas = matriculas[matriculas["ativa"] == 1]
    if not ativas.empty:
        op_ativas = [
            f'{int(row["id_matricula"])} - {row["nome"]} ({row["grupo"]})'
            for _, row in ativas.iterrows()
        ]

        with st.expander("Encerrar matrícula", expanded=False):
            st.caption(
                "Use esta opção para remover a pessoa das próximas chamadas "
                "sem apagar o histórico de participação já registrado."
            )
            encerrar = st.selectbox(
                "Matrícula ativa",
                ["Selecione"] + op_ativas,
                key="gfc_encerrar_matricula",
            )
            data_fim = st.date_input(
                "Data de encerramento",
                value=_hoje(),
                format="DD/MM/YYYY",
                key="gfc_data_fim_matricula",
            )
            if encerrar != "Selecione" and confirmar_exclusao(
                f"encerrar_gfc_{encerrar}",
                "Confirmar encerramento da matrícula",
            ):
                encerrar_gfc_matricula(
                    slug,
                    int(encerrar.split(" - ")[0]),
                    data_fim.isoformat(),
                )
                st.success(
                    "Matrícula encerrada. O histórico foi preservado e ela "
                    "não aparecerá nas próximas chamadas após a data de encerramento."
                )
                st.rerun()

        with st.expander("Excluir matrícula sem histórico", expanded=False):
            st.caption(
                "A exclusão definitiva só deve ser usada para cadastro lançado por engano. "
                "Se houver histórico, o sistema encerrará a matrícula em vez de apagar."
            )
            excluir = st.selectbox(
                "Matrícula para excluir",
                ["Selecione"] + op_ativas,
                key="gfc_excluir_matricula",
            )
            if excluir != "Selecione" and confirmar_exclusao(
                f"excluir_gfc_{excluir}",
                "Confirmar exclusão da matrícula sem histórico",
            ):
                removida = excluir_gfc_matricula(
                    slug,
                    int(excluir.split(" - ")[0]),
                    _hoje().isoformat(),
                )
                st.success(
                    "Matrícula excluída."
                    if removida
                    else "Matrícula encerrada porque já possui histórico."
                )
                st.rerun()


def _render_reunioes(slug, id_grupo_restrito=None):
    _render_cards_coordenadores_gfc(slug)
    st.markdown("### Chamada do GFC")
    grupos = listar_gfc_grupos(slug)
    if id_grupo_restrito:
        grupos = grupos[
            grupos["id_grupo"].astype(int) == int(id_grupo_restrito)
        ].copy()
    if grupos.empty:
        st.warning("Nenhum grupo familiar ativo foi encontrado para este acesso.")
        return
    if id_grupo_restrito:
        grupo_sessao = grupos.iloc[0]
        st.info(
            f"Grupo selecionado no login: {grupo_sessao.get('nome', '')} "
            f"({grupo_sessao.get('setor', '') or 'Sem setor'})"
        )

    reunioes_salvas = listar_gfc_reunioes(slug, id_grupo=id_grupo_restrito)
    opcoes_modo = ["Nova chamada", "Editar chamada salva"] if not reunioes_salvas.empty else ["Nova chamada"]
    if st.session_state.get("gfc_modo_reuniao") not in opcoes_modo:
        st.session_state.pop("gfc_modo_reuniao", None)
    modo = st.radio(
        "Modo",
        opcoes_modo,
        horizontal=True,
        key="gfc_modo_reuniao",
    )

    reuniao_atual = None
    if modo == "Editar chamada salva":
        c_ini, c_fim = st.columns(2)
        inicio = c_ini.date_input(
            "Data inicial para localizar registro",
            value=_inicio_mes(),
            key="gfc_edit_ini",
            format="DD/MM/YYYY",
        )
        fim = c_fim.date_input(
            "Data final para localizar registro",
            value=_hoje(),
            key="gfc_edit_fim",
            format="DD/MM/YYYY",
        )
        if inicio > fim:
            st.error("A data inicial não pode ser maior que a data final.")
            return
        reunioes_salvas = listar_gfc_reunioes(
            slug,
            inicio.isoformat(),
            fim.isoformat(),
            id_grupo=id_grupo_restrito,
        )
        if reunioes_salvas.empty:
            st.info("Nenhum registro encontrado no período selecionado.")
            return
        opcoes_reg = {
            f'{int(row["id_reuniao"])} - {_fmt_data(row["data"])} - {row["grupo"]} - {row["tipo_culto"]}': row
            for _, row in reunioes_salvas.iterrows()
        }
        labels = list(opcoes_reg.keys())
        chave = "gfc_editar_reuniao"
        if st.session_state.get(chave) not in labels:
            st.session_state[chave] = labels[0]
        idx_atual = labels.index(st.session_state[chave])
        nav_ant, nav_sel, nav_seg = st.columns([1, 3, 1])
        if nav_ant.button(
            "Dia anterior",
            use_container_width=True,
            disabled=idx_atual >= len(labels) - 1,
            key="gfc_reuniao_anterior",
        ):
            st.session_state[chave] = labels[idx_atual + 1]
        if nav_seg.button(
            "Dia seguinte",
            use_container_width=True,
            disabled=idx_atual <= 0,
            key="gfc_reuniao_seguinte",
        ):
            st.session_state[chave] = labels[idx_atual - 1]
        with nav_sel:
            selecionado = st.selectbox("Registro salvo", labels, key=chave)
        reuniao_atual = opcoes_reg[selecionado]
        data_padrao = datetime.date.fromisoformat(str(reuniao_atual["data"]))
    else:
        data_padrao = _hoje()

    op_grupos = _grupo_opcoes(grupos)
    grupo_index = 0
    if reuniao_atual is not None:
        id_atual = int(reuniao_atual.get("id_grupo", 0) or 0)
        for idx, label in enumerate(op_grupos):
            if op_grupos[label] == id_atual:
                grupo_index = idx
                break

    data = st.date_input(
        "Data da reunião",
        value=data_padrao,
        format="DD/MM/YYYY",
        key=f"gfc_data_reuniao_{int(reuniao_atual['id_reuniao']) if reuniao_atual is not None else 'nova'}",
    )

    grupo_label = st.selectbox(
        "Grupo familiar",
        list(op_grupos.keys()),
        index=grupo_index,
        key=f"gfc_grupo_chamada_{int(reuniao_atual['id_reuniao']) if reuniao_atual is not None else 'nova'}",
    )
    grupo_row = grupos[grupos["id_grupo"].astype(int) == int(op_grupos[grupo_label])].iloc[0]
    setor = str(grupo_row.get("setor", "") or "")
    lider_padrao_grupo = str(grupo_row.get("responsavel", "") or "")

    presencas_salvas = {}
    if reuniao_atual is not None:
        df_pres = listar_gfc_presencas(slug, int(reuniao_atual["id_reuniao"]))
        for _, row in df_pres.iterrows():
            if pd.notna(row.get("id_matricula")):
                presencas_salvas[int(row["id_matricula"])] = bool(row.get("presente", 0))

    acao_presencas = st.radio(
        "Presenças da lista de chamada",
        ["Manter marcação atual", "Marcar todas", "Desmarcar todas"],
        horizontal=True,
        key=f"gfc_acao_presencas_{int(reuniao_atual['id_reuniao']) if reuniao_atual is not None else 'novo'}",
    )

    with st.form("form_gfc_reuniao"):
        c1, c2 = st.columns(2)
        c1.text_input("Setor do grupo familiar", value=setor, disabled=True)
        tipo_atual = (
            str(reuniao_atual.get("tipo_culto", TIPOS_CULTO_GFC[0]))
            if reuniao_atual is not None
            else TIPOS_CULTO_GFC[0]
        )
        tipo_idx = TIPOS_CULTO_GFC.index(tipo_atual) if tipo_atual in TIPOS_CULTO_GFC else 0
        tipo_culto = c2.selectbox("Tipo de culto", TIPOS_CULTO_GFC, index=tipo_idx)

        coordenador1_nome = ""
        coordenador2_nome = ""
        id_grupo_reuniao_atual = (
            int(reuniao_atual.get("id_grupo", 0) or 0)
            if reuniao_atual is not None else 0
        )
        lider_nome_salvo = (
            str(reuniao_atual.get("lider_nome", "") or "")
            if reuniao_atual is not None else ""
        )
        lider_nome = (
            lider_nome_salvo
            if lider_nome_salvo.strip() and int(op_grupos[grupo_label]) == id_grupo_reuniao_atual
            else lider_padrao_grupo
        )
        st.text_input("Líder", value=lider_nome, disabled=True)

        tema = st.text_input(
            "Tema/observação breve",
            value=str(reuniao_atual.get("tema", "") or "") if reuniao_atual is not None else "",
        )

        matriculas_chamada = listar_gfc_matriculas(
            slug,
            id_grupo=int(op_grupos[grupo_label]),
            incluir_inativas=True,
        )
        matriculas_chamada = _filtrar_matriculas_validas_na_data(matriculas_chamada, data)
        if matriculas_chamada.empty:
            st.info(
                "Nenhuma matrícula ativa para este grupo na data selecionada. "
                "Use a aba Matrículas para incluir participantes."
            )
            editado = pd.DataFrame(columns=["id_matricula", "id_cadastro", "nome", "presente"])
        else:
            dados = matriculas_chamada[["id_matricula", "id_cadastro", "nome"]].copy()
            dados["id_matricula"] = pd.to_numeric(dados["id_matricula"], errors="coerce").fillna(0).astype(int)
            dados["id_cadastro"] = pd.to_numeric(dados["id_cadastro"], errors="coerce").fillna(0).astype(int)
            if acao_presencas == "Marcar todas":
                dados["presente"] = True
            elif acao_presencas == "Desmarcar todas":
                dados["presente"] = False
            else:
                dados["presente"] = dados["id_matricula"].apply(
                    lambda x: presencas_salvas.get(int(x), False)
                )
            with st.expander("Lista de chamada", expanded=True):
                st.caption("Marque os matriculados presentes no culto do grupo familiar.")
                editado = st.data_editor(
                    dados,
                    hide_index=True,
                    use_container_width=True,
                    disabled=["id_matricula", "id_cadastro", "nome"],
                    key=f"gfc_editor_chamada_{data.isoformat()}_{int(op_grupos[grupo_label])}_{acao_presencas}",
                    column_config={
                        "id_matricula": st.column_config.NumberColumn("Matrícula"),
                        "id_cadastro": st.column_config.NumberColumn("ID"),
                        "nome": st.column_config.TextColumn("Nome"),
                        "presente": st.column_config.CheckboxColumn("Presente"),
                    },
                )

        qtd_participantes = int(len(editado))
        qtd_presentes = int(editado["presente"].fillna(False).astype(bool).sum()) if not editado.empty else 0
        qtd_ausentes = max(qtd_participantes - qtd_presentes, 0)
        mc1, mc2, mc3 = st.columns(3)
        mc1.metric("Na chamada", qtd_participantes)
        mc2.metric("Presentes", qtd_presentes)
        mc3.metric("Ausentes", qtd_ausentes)

        c3, c4, c5 = st.columns(3)
        qtd_pessoas = c3.number_input(
            "Quantidade de pessoas",
            min_value=0,
            step=1,
            value=int(reuniao_atual.get("qtd_pessoas", 0) or 0) if reuniao_atual is not None else qtd_presentes,
        )
        qtd_nao_crentes = c4.number_input(
            "Quantidade de pessoas não crentes",
            min_value=0,
            step=1,
            value=int(reuniao_atual.get("qtd_nao_crentes", 0) or 0) if reuniao_atual is not None else 0,
        )
        qtd_conversoes = c5.number_input(
            "Quantidade de conversões a Cristo",
            min_value=0,
            step=1,
            value=int(reuniao_atual.get("qtd_conversoes", 0) or 0) if reuniao_atual is not None else 0,
        )
        observacoes = st.text_area(
            "Observações",
            value=str(reuniao_atual.get("observacoes", "") or "") if reuniao_atual is not None else "",
        )

        if st.form_submit_button("Salvar chamada GFC", type="primary"):
            try:
                presencas = []
                if not editado.empty:
                    for _, row in editado.iterrows():
                        nome_presenca = str(row.get("nome", "") or "").strip()
                        if not nome_presenca:
                            continue
                        presencas.append({
                            "id_matricula": int(row.get("id_matricula", 0) or 0),
                            "id_cadastro": int(row.get("id_cadastro", 0) or 0),
                            "nome": nome_presenca,
                            "presente": bool(row.get("presente", False)),
                        })
                salvar_gfc_reuniao(
                    slug,
                    data=data.isoformat(),
                    id_grupo=op_grupos[grupo_label],
                    tipo_culto=tipo_culto,
                    tema=tema,
                    coordenador1_nome=coordenador1_nome,
                    coordenador2_nome=coordenador2_nome,
                    lider_nome=lider_nome,
                    qtd_pessoas=qtd_pessoas,
                    qtd_nao_crentes=qtd_nao_crentes,
                    qtd_conversoes=qtd_conversoes,
                    observacoes=observacoes,
                    presencas=presencas,
                    id_reuniao=int(reuniao_atual["id_reuniao"]) if reuniao_atual is not None else None,
                )
                st.success("Chamada GFC salva.")
                st.rerun()
            except Exception as exc:
                st.error(str(exc))


def _render_relatorios(slug):
    st.markdown("### Relatórios GFC")
    c1, c2, c3 = st.columns(3)
    inicio = c1.date_input("Data inicial", value=_inicio_mes(), key="gfc_rel_ini", format="DD/MM/YYYY")
    fim = c2.date_input("Data final", value=_hoje(), key="gfc_rel_fim", format="DD/MM/YYYY")
    tipo = c3.selectbox("Tipo de culto", ["Todos"] + TIPOS_CULTO_GFC, key="gfc_rel_tipo")

    grupos = listar_gfc_grupos(slug, incluir_inativos=True)
    setores = sorted([
        s for s in grupos["setor"].fillna("").astype(str).str.strip().unique().tolist()
        if s
    ]) if not grupos.empty else []
    setor = st.selectbox("Setor", ["Todos"] + setores, key="gfc_rel_setor")

    if inicio > fim:
        st.error("A data inicial não pode ser maior que a data final.")
        return

    reunioes = listar_gfc_reunioes(
        slug,
        inicio.isoformat(),
        fim.isoformat(),
        setor="" if setor == "Todos" else setor,
        tipo_culto="" if tipo == "Todos" else tipo,
    )

    if reunioes.empty:
        st.info("Nenhum registro GFC encontrado no período.")
        return

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Cultos registrados", int(reunioes["id_reuniao"].nunique()))
    m2.metric("Pessoas", int(pd.to_numeric(reunioes["qtd_pessoas"], errors="coerce").fillna(0).sum()))
    m3.metric("Não crentes", int(pd.to_numeric(reunioes["qtd_nao_crentes"], errors="coerce").fillna(0).sum()))
    m4.metric("Conversões", int(pd.to_numeric(reunioes["qtd_conversoes"], errors="coerce").fillna(0).sum()))

    tabela = reunioes.copy()
    tabela["data"] = tabela["data"].apply(_fmt_data)
    tabela = tabela.rename(columns={
        "data": "Data",
        "grupo": "Grupo familiar",
        "setor": "Setor",
        "tipo_culto": "Tipo de culto",
        "tema": "Tema",
        "qtd_pessoas": "Pessoas",
        "qtd_nao_crentes": "Não crentes",
        "qtd_conversoes": "Conversões",
        "observacoes": "Observações",
    })
    st.dataframe(
        tabela[[
            "Data", "Grupo familiar", "Setor", "Tipo de culto", "Tema",
            "Pessoas", "Não crentes", "Conversões", "Observações",
        ]],
        use_container_width=True,
        hide_index=True,
    )
    st.download_button(
        "Baixar relatório GFC CSV",
        data=gerar_csv(tabela),
        file_name="relatorio_gfc.csv",
        mime="text/csv",
    )

    with st.expander("Excluir registro GFC", expanded=False):
        opcoes = {
            f'{int(row["id_reuniao"])} - {_fmt_data(row["data"])} - {row["grupo"]} - {row["tipo_culto"]}': int(row["id_reuniao"])
            for _, row in reunioes.iterrows()
        }
        escolha = st.selectbox("Registro", ["Selecione"] + list(opcoes.keys()), key="gfc_excluir_reuniao")
        if escolha != "Selecione" and st.button("Excluir registro selecionado", type="primary"):
            excluir_gfc_reuniao(slug, opcoes[escolha])
            st.success("Registro excluído.")
            st.rerun()


def _dados_membro(row_membro, funcao_padrao):
    return {
        "id_cadastro": int(row_membro["id_cadastro"]),
        "nome": str(row_membro.get("nome", "") or ""),
        "telefone": str(row_membro.get("telefone", "") or ""),
        "funcao": str(row_membro.get("funcao", "") or funcao_padrao),
        "setor": str(row_membro.get("congregacao", "") or ""),
    }


def _render_form_pessoa_gfc(slug, tipo, op_membros, salvar_fn, expandido=False):
    funcao_padrao = "Coordenador" if tipo == "Coordenador" else "Lider"
    with st.expander(f"Cadastrar {tipo.lower()}", expanded=expandido):
        origem = st.radio(
            f"Origem do {tipo.lower()}",
            ["Cadastro de membro", "Inserir manualmente"],
            horizontal=True,
            key=f"gfc_{tipo.lower()}_origem",
        )
        id_cadastro = None
        nome = ""
        telefone = ""
        funcao = funcao_padrao
        setor = ""

        if origem == "Cadastro de membro":
            if not op_membros:
                st.warning("Nao ha membros ativos disponiveis no cadastro.")
            else:
                membro_label = st.selectbox(
                    tipo,
                    list(op_membros.keys()),
                    key=f"gfc_{tipo.lower()}_membro",
                )
                dados = _dados_membro(op_membros[membro_label], funcao_padrao)
                id_cadastro = dados["id_cadastro"]
                nome = dados["nome"]
                telefone = dados["telefone"]
                funcao = dados["funcao"]
                setor = dados["setor"]
                c1, c2 = st.columns(2)
                c1.text_input("Nome", value=nome, disabled=True, key=f"gfc_{tipo.lower()}_nome_auto")
                c2.text_input("Telefone", value=telefone, disabled=True, key=f"gfc_{tipo.lower()}_tel_auto")
        else:
            c1, c2 = st.columns(2)
            nome = c1.text_input(f"Nome do {tipo.lower()}", key=f"gfc_{tipo.lower()}_nome_manual")
            telefone = c2.text_input("Telefone / WhatsApp", key=f"gfc_{tipo.lower()}_telefone_manual")

        with st.form(f"form_gfc_{tipo.lower()}_novo"):
            c3, c4 = st.columns(2)
            funcao = c3.text_input("Funcao", value=funcao)
            setor = c4.text_input("Setor", value=setor)
            ordem = st.number_input("Ordem", min_value=0, max_value=999, value=0, step=1)
            observacoes = st.text_area("Observacoes")
            if st.form_submit_button(f"Salvar {tipo.lower()}", type="primary"):
                try:
                    salvar_fn(
                        slug,
                        nome=nome,
                        id_cadastro=id_cadastro,
                        telefone=telefone,
                        funcao=funcao,
                        setor=setor,
                        ordem=ordem,
                        ativo=True,
                        observacoes=observacoes,
                    )
                    st.success(f"{tipo} salvo.")
                    st.rerun()
                except Exception as exc:
                    st.error(str(exc))


def _render_tabela_pessoa_gfc(slug, titulo, dados, id_col, salvar_fn, excluir_fn):
    if dados.empty:
        st.info(f"Nenhum {titulo.lower()} cadastrado ainda.")
        return

    st.markdown(f"#### {titulo}")
    st.dataframe(
        dados[["id_cadastro", "nome", "telefone", "funcao", "setor", "ordem", "ativo", "observacoes"]],
        use_container_width=True,
        hide_index=True,
    )

    with st.expander(f"Editar ou inativar {titulo.lower()}", expanded=False):
        opcoes = {
            f'{int(row[id_col])} - {row["nome"]}': row
            for _, row in dados.iterrows()
        }
        selecionado = st.selectbox(
            titulo,
            ["Selecione"] + list(opcoes.keys()),
            key=f"gfc_edit_{id_col}",
        )
        if selecionado == "Selecione":
            return

        row = opcoes[selecionado]
        with st.form(f"form_gfc_edit_{id_col}_{int(row[id_col])}"):
            c1, c2 = st.columns(2)
            nome = c1.text_input("Nome", value=str(row.get("nome", "") or ""))
            telefone = c2.text_input("Telefone / WhatsApp", value=str(row.get("telefone", "") or ""))
            c3, c4 = st.columns(2)
            funcao = c3.text_input("Funcao", value=str(row.get("funcao", "") or ""))
            setor = c4.text_input("Setor", value=str(row.get("setor", "") or ""))
            c5, c6 = st.columns(2)
            ordem = c5.number_input(
                "Ordem",
                min_value=0,
                max_value=999,
                value=int(row.get("ordem", 0) or 0),
                step=1,
            )
            situacao = c6.selectbox(
                "Situacao",
                ["Ativo", "Inativo"],
                index=0 if int(row.get("ativo", 1) or 0) == 1 else 1,
            )
            observacoes = st.text_area("Observacoes", value=str(row.get("observacoes", "") or ""))
            if st.form_submit_button("Atualizar", type="primary"):
                try:
                    salvar_fn(
                        slug,
                        nome=nome,
                        id_cadastro=int(row["id_cadastro"]) if pd.notna(row.get("id_cadastro")) else None,
                        telefone=telefone,
                        funcao=funcao,
                        setor=setor,
                        ordem=ordem,
                        ativo=situacao == "Ativo",
                        observacoes=observacoes,
                        **{id_col: int(row[id_col])},
                    )
                    st.success("Cadastro atualizado.")
                    st.rerun()
                except Exception as exc:
                    st.error(str(exc))

        if st.button("Inativar cadastro", key=f"gfc_inativar_{id_col}_{int(row[id_col])}"):
            excluir_fn(slug, int(row[id_col]))
            st.success("Cadastro inativado.")
            st.rerun()


def _render_coordenadores_lideres(slug):
    st.markdown("### Coordenadores e lideres")
    st.caption("Organize a estrutura de acompanhamento dos Grupos Familiares de Crescimento.")

    coordenadores = listar_gfc_coordenadores(slug, incluir_inativos=True)
    lideres = listar_gfc_lideres(slug, incluir_inativos=True)
    op_membros, _ = _membros_opcoes(slug)

    _render_form_pessoa_gfc(
        slug,
        "Coordenador",
        op_membros,
        salvar_gfc_coordenador,
        expandido=coordenadores.empty,
    )
    _render_tabela_pessoa_gfc(
        slug,
        "Coordenadores cadastrados",
        coordenadores,
        "id_coordenador",
        salvar_gfc_coordenador,
        excluir_gfc_coordenador,
    )

    st.divider()

    _render_form_pessoa_gfc(
        slug,
        "Lider",
        op_membros,
        salvar_gfc_lider,
        expandido=lideres.empty,
    )
    _render_tabela_pessoa_gfc(
        slug,
        "Lideres cadastrados",
        lideres,
        "id_lider",
        salvar_gfc_lider,
        excluir_gfc_lider,
    )


def _render_secretarias(slug):
    st.markdown("### Secretarias GFC")
    st.caption("Cadastre os usuarios que poderao acessar o modulo GFC com igreja, usuario e 4 ultimos digitos do CPF.")

    secretarias = listar_gfc_secretarias(slug, incluir_inativas=True)
    op_membros, _ = _membros_opcoes(slug)

    with st.expander("Cadastrar secretaria GFC", expanded=secretarias.empty):
        if not op_membros:
            st.warning("Cadastre membros ativos com CPF antes de criar logins por CPF para o GFC.")

        origem = st.radio(
            "Origem do usuario",
            ["Cadastro de membro", "Nome manual"],
            horizontal=True,
            key="gfc_sec_origem",
        )
        id_cadastro = None
        nome = ""
        telefone = ""
        pin = ""

        if origem == "Cadastro de membro" and op_membros:
            membro_label = st.selectbox("Membro vinculado", list(op_membros.keys()), key="gfc_sec_membro")
            membro = op_membros[membro_label]
            id_cadastro = int(membro["id_cadastro"])
            nome = str(membro.get("nome", "") or "")
            telefone = str(membro.get("telefone", "") or "")
            cpf_digitos = "".join(c for c in str(membro.get("cpf", "") or "") if c.isdigit())
            pin = cpf_digitos[-4:] if len(cpf_digitos) >= 4 else ""
            st.info(f"Login por CPF habilitado para: {nome}")
        else:
            nome = st.text_input("Nome da secretaria", key="gfc_sec_nome_manual")

        with st.form("form_gfc_secretaria_nova"):
            usuario = st.text_input(
                "Usuario",
                help="Use letras, numeros, ponto, hifen ou underline. Exemplo: maria.gfc",
            )
            perfil_label = st.selectbox("Perfil", ["Secretaria de chamada", "Secretaria geral"])
            if id_cadastro:
                st.caption("O PIN de acesso sera validado pelos 4 ultimos digitos do CPF do membro vinculado.")
            else:
                st.warning("Para login por CPF, a secretaria precisa estar vinculada a um membro cadastrado.")
            email = st.text_input("E-mail")
            telefone_form = st.text_input("Telefone", value=telefone)
            observacoes = st.text_area("Observacoes")

            if st.form_submit_button("Salvar secretaria", type="primary"):
                if not id_cadastro:
                    st.error("Selecione um membro vinculado para habilitar o login por CPF.")
                elif len(pin) != 4:
                    st.error("O membro vinculado precisa ter CPF cadastrado para gerar o PIN de acesso.")
                else:
                    try:
                        salvar_gfc_secretaria(
                            slug,
                            nome=nome,
                            usuario=usuario,
                            senha=pin,
                            id_cadastro=id_cadastro,
                            perfil="geral" if perfil_label == "Secretaria geral" else "chamada",
                            telefone=telefone_form,
                            email=email,
                            observacoes=observacoes,
                        )
                        st.success("Secretaria GFC cadastrada.")
                        st.rerun()
                    except Exception as exc:
                        st.error(str(exc))

    if secretarias.empty:
        st.info("Nenhuma secretaria GFC cadastrada ainda.")
        return

    tabela = secretarias.copy()
    tabela["perfil"] = tabela["perfil"].map({
        "chamada": "Secretaria de chamada",
        "geral": "Secretaria geral",
    }).fillna(tabela["perfil"])
    st.dataframe(
        tabela[["nome", "usuario", "perfil", "telefone", "email", "situacao", "observacoes"]],
        use_container_width=True,
        hide_index=True,
    )

    with st.expander("Editar secretaria GFC", expanded=False):
        opcoes = {
            f'{int(row["id_secretaria"])} - {row["nome"]} ({row["usuario"]})': row
            for _, row in secretarias.iterrows()
        }
        selecionada = st.selectbox("Secretaria", ["Selecione"] + list(opcoes.keys()), key="gfc_sec_edit_sel")
        if selecionada != "Selecione":
            row = opcoes[selecionada]
            with st.form(f"form_gfc_secretaria_edit_{int(row['id_secretaria'])}"):
                nome_edit = st.text_input("Nome", value=str(row.get("nome", "") or ""))
                usuario_edit = st.text_input("Usuario", value=str(row.get("usuario", "") or ""))
                perfil_atual = "Secretaria geral" if row.get("perfil") == "geral" else "Secretaria de chamada"
                perfil_edit = st.selectbox(
                    "Perfil",
                    ["Secretaria de chamada", "Secretaria geral"],
                    index=1 if perfil_atual == "Secretaria geral" else 0,
                )
                situacao_edit = st.selectbox(
                    "Situacao",
                    ["Ativo", "Inativo"],
                    index=0 if str(row.get("situacao", "Ativo")) == "Ativo" else 1,
                )
                novo_pin = st.text_input("Novo PIN de 4 digitos (opcional)", type="password", max_chars=4)
                telefone_edit = st.text_input("Telefone", value=str(row.get("telefone", "") or ""))
                email_edit = st.text_input("E-mail", value=str(row.get("email", "") or ""))
                obs_edit = st.text_area("Observacoes", value=str(row.get("observacoes", "") or ""))

                if st.form_submit_button("Atualizar secretaria", type="primary"):
                    try:
                        salvar_gfc_secretaria(
                            slug,
                            nome=nome_edit,
                            usuario=usuario_edit,
                            senha=novo_pin,
                            id_cadastro=int(row["id_cadastro"]) if pd.notna(row.get("id_cadastro")) else None,
                            perfil="geral" if perfil_edit == "Secretaria geral" else "chamada",
                            telefone=telefone_edit,
                            email=email_edit,
                            situacao=situacao_edit,
                            observacoes=obs_edit,
                            id_secretaria=int(row["id_secretaria"]),
                        )
                        st.success("Secretaria GFC atualizada.")
                        st.rerun()
                    except Exception as exc:
                        st.error(str(exc))

            if st.button("Inativar secretaria", key=f"gfc_sec_inativar_{int(row['id_secretaria'])}"):
                inativar_gfc_secretaria(slug, int(row["id_secretaria"]))
                st.success("Secretaria GFC inativada.")
                st.rerun()


def render():
    slug = slug_da_sessao()
    modo = st.session_state.get("modo", "")
    secretaria = st.session_state.get("secretaria_gfc", {})
    perfil_secretaria = secretaria.get("perfil") if isinstance(secretaria, dict) else ""
    st.subheader("GFC - Grupos Familiares de Crescimento")
    st.caption("Primeira etapa: cadastro dos grupos, registro dos cultos e relatório básico.")

    if modo == "secretaria_gfc" and perfil_secretaria != "geral":
        tab_matriculas_sec, tab_reunioes_sec = st.tabs([
            "Matrículas",
            "Registro de culto",
        ])
        with tab_matriculas_sec:
            _render_matriculas(slug, id_grupo_restrito=secretaria.get("id_grupo"))
        with tab_reunioes_sec:
            _render_reunioes(slug, id_grupo_restrito=secretaria.get("id_grupo"))
        return

    incluir_secretarias = modo != "secretaria_gfc" or perfil_secretaria == "geral"
    if incluir_secretarias:
        tab_grupos, tab_matriculas, tab_reunioes, tab_relatorios, tab_coord_lideres, tab_secretarias = st.tabs([
            "Grupos",
            "Matrículas",
            "Registro de culto",
            "Relatórios",
            "Coordenadores e lideres",
            "Secretarias",
        ])
    else:
        tab_grupos, tab_matriculas, tab_reunioes, tab_relatorios = st.tabs([
            "Grupos",
            "Matrículas",
            "Registro de culto",
            "Relatórios",
        ])

    with tab_grupos:
        _render_grupos(slug)
    with tab_matriculas:
        _render_matriculas(slug)
    with tab_reunioes:
        _render_reunioes(slug)
    with tab_relatorios:
        _render_relatorios(slug)
    if incluir_secretarias:
        with tab_coord_lideres:
            _render_coordenadores_lideres(slug)
        with tab_secretarias:
            _render_secretarias(slug)

