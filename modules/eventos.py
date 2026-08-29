import datetime

import pandas as pd
import streamlit as st

from data.repository import (
    excluir_evento_igreja,
    listar_eventos_igreja,
    obter_evento_cartaz,
    salvar_evento_igreja,
)
from utils.helpers import (
    confirmar_exclusao,
    formatar_data as _fmt_data,
    gerar_csv,
    hoje as _hoje,
    inicio_mes as _inicio_mes,
    slug_da_sessao,
)


VISIBILIDADES = ["Publico", "Membros", "Restrito"]
SITUACOES = ["Programado", "Realizado", "Cancelado"]
TIPOS_EVENTO = [
    "Conscientização Missionária",
    "Consagração",
    "Culto de Ensino",
    "Culto Ministério de Homens",
    "Culto Ministério Família",
    "Culto Ministério Infantil",
    "Culto Ministério Jovens",
    "Culto Ministério Missões",
    "Culto Ministério Mulheres",
    "Dia com Deus",
    "Encontro Unificado",
    "Escola Bíblica",
    "Fraternal",
    "Outros",
    "Vigília",
]


def _parse_data(valor, padrao=None):
    try:
        return datetime.date.fromisoformat(str(valor))
    except Exception:
        return padrao or _hoje()


def _idx(lista, valor, padrao=0):
    try:
        return lista.index(valor)
    except ValueError:
        return padrao


def _render_form(slug):
    st.markdown("### Novo evento")
    st.caption(
        "Eventos publicos aparecem na pagina institucional. Eventos para membros "
        "exigem CPF valido. Eventos restritos ficam apenas dentro do sistema."
    )

    with st.form("form_evento_novo", clear_on_submit=True):
        titulo = st.text_input("Titulo do evento")
        c1, c2, c3 = st.columns(3)
        data = c1.date_input("Data", value=_hoje(), format="DD/MM/YYYY")
        hora_inicio = c2.text_input("Hora inicio", placeholder="19:00")
        hora_fim = c3.text_input("Hora fim", placeholder="21:00")

        c4, c5 = st.columns(2)
        local = c4.text_input("Local", placeholder="Templo sede, congregacao, salao...")
        departamento = c5.selectbox("Departamento / tipo de evento", TIPOS_EVENTO)

        descricao = st.text_area("Descricao")
        c6, c7 = st.columns(2)
        responsavel = c6.text_input("Responsavel")
        contato = c7.text_input("Contato")

        c8, c9 = st.columns(2)
        visibilidade = c8.selectbox("Visibilidade", VISIBILIDADES)
        situacao = c9.selectbox("Situacao", SITUACOES)
        cartaz = st.file_uploader(
            "Cartaz do evento",
            type=["png", "jpg", "jpeg", "webp", "pdf"],
            help="Anexe uma imagem ou PDF do cartaz do evento.",
            key="evento_novo_cartaz",
        )

        if st.form_submit_button("Salvar evento", type="primary", use_container_width=True):
            try:
                salvar_evento_igreja(
                    slug,
                    titulo,
                    data.isoformat(),
                    hora_inicio,
                    hora_fim,
                    local,
                    departamento,
                    descricao,
                    responsavel,
                    contato,
                    visibilidade,
                    situacao,
                    cartaz_nome=cartaz.name if cartaz else "",
                    cartaz_mime=cartaz.type if cartaz else "",
                    cartaz_bytes=cartaz.getvalue() if cartaz else None,
                )
                st.success("Evento salvo com sucesso.")
                st.rerun()
            except Exception as exc:
                st.error(str(exc))


def _render_lista(slug):
    st.markdown("### Eventos cadastrados")
    c1, c2, c3, c4 = st.columns(4)
    inicio = c1.date_input("Data inicial", value=_inicio_mes(), key="eventos_ini", format="DD/MM/YYYY")
    fim = c2.date_input("Data final", value=_hoje() + datetime.timedelta(days=120), key="eventos_fim", format="DD/MM/YYYY")
    vis = c3.selectbox("Visibilidade", ["Todas"] + VISIBILIDADES, key="eventos_vis")
    sit = c4.selectbox("Situacao", ["Todas"] + SITUACOES, key="eventos_sit")

    if inicio > fim:
        st.error("A data inicial nao pode ser maior que a data final.")
        return

    df = listar_eventos_igreja(
        slug,
        inicio.isoformat(),
        fim.isoformat(),
        "" if vis == "Todas" else vis,
        "" if sit == "Todas" else sit,
    )

    if df.empty:
        st.info("Nenhum evento encontrado no periodo.")
        return

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Eventos", len(df))
    c2.metric("Publicos", int((df["visibilidade"] == "Publico").sum()))
    c3.metric("Membros", int((df["visibilidade"] == "Membros").sum()))
    c4.metric("Restritos", int((df["visibilidade"] == "Restrito").sum()))

    exibir = df.copy()
    exibir["data"] = exibir["data"].apply(_fmt_data)
    st.dataframe(
        exibir[[
            "data", "hora_inicio", "titulo", "local", "departamento",
            "visibilidade", "situacao", "responsavel",
        ]],
        use_container_width=True,
        hide_index=True,
    )
    st.download_button(
        "Baixar eventos CSV",
        data=gerar_csv(exibir),
        file_name="agenda_eventos.csv",
        mime="text/csv",
    )

    opcoes = {
        f'{_fmt_data(row["data"])} - {row["titulo"]} ({row["visibilidade"]})': row
        for _, row in df.iterrows()
    }
    escolha = st.selectbox("Selecionar evento para editar", list(opcoes.keys()))
    row = opcoes[escolha]
    id_evento = int(row["id_evento"])

    with st.expander("Editar evento selecionado", expanded=False):
        if int(row.get("tem_cartaz", 0) or 0) == 1:
            cartaz_atual = obter_evento_cartaz(slug, id_evento)
            if cartaz_atual:
                st.download_button(
                    "Baixar cartaz atual",
                    data=cartaz_atual["bytes"],
                    file_name=cartaz_atual["nome"],
                    mime=cartaz_atual["mime"],
                    use_container_width=True,
                    key=f"baixar_cartaz_evento_{id_evento}",
                )

        with st.form(f"form_evento_editar_{id_evento}", clear_on_submit=True):
            titulo = st.text_input("Titulo", value=row["titulo"])
            c1, c2, c3 = st.columns(3)
            data = c1.date_input("Data", value=_parse_data(row["data"]), key=f"evento_data_{id_evento}", format="DD/MM/YYYY")
            hora_inicio = c2.text_input("Hora inicio", value=row["hora_inicio"] or "")
            hora_fim = c3.text_input("Hora fim", value=row["hora_fim"] or "")

            c4, c5 = st.columns(2)
            local = c4.text_input("Local", value=row["local"] or "")
            departamento_atual = row["departamento"] if row["departamento"] in TIPOS_EVENTO else "Outros"
            departamento = c5.selectbox(
                "Departamento / tipo de evento",
                TIPOS_EVENTO,
                index=_idx(TIPOS_EVENTO, departamento_atual),
                key=f"evento_departamento_{id_evento}",
            )

            descricao = st.text_area("Descricao", value=row["descricao"] or "")
            c6, c7 = st.columns(2)
            responsavel = c6.text_input("Responsavel", value=row["responsavel"] or "")
            contato = c7.text_input("Contato", value=row["contato"] or "")

            c8, c9 = st.columns(2)
            visibilidade = c8.selectbox(
                "Visibilidade",
                VISIBILIDADES,
                index=_idx(VISIBILIDADES, row["visibilidade"]),
                key=f"evento_vis_{id_evento}",
            )
            situacao = c9.selectbox(
                "Situacao",
                SITUACOES,
                index=_idx(SITUACOES, row["situacao"]),
                key=f"evento_sit_{id_evento}",
            )
            cartaz = st.file_uploader(
                "Novo cartaz do evento",
                type=["png", "jpg", "jpeg", "webp", "pdf"],
                help="Se nenhum arquivo for enviado, o cartaz atual sera mantido.",
                key=f"evento_cartaz_{id_evento}",
            )

            if st.form_submit_button("Atualizar evento", type="primary"):
                try:
                    salvar_evento_igreja(
                        slug,
                        titulo,
                        data.isoformat(),
                        hora_inicio,
                        hora_fim,
                        local,
                        departamento,
                        descricao,
                        responsavel,
                        contato,
                        visibilidade,
                        situacao,
                        cartaz_nome=cartaz.name if cartaz else "",
                        cartaz_mime=cartaz.type if cartaz else "",
                        cartaz_bytes=cartaz.getvalue() if cartaz else None,
                        id_evento=id_evento,
                    )
                    st.success("Evento atualizado.")
                    st.rerun()
                except Exception as exc:
                    st.error(str(exc))

        if confirmar_exclusao(f"evento_{id_evento}", "Excluir evento selecionado"):
            excluir_evento_igreja(slug, id_evento)
            st.success("Evento excluido.")
            st.rerun()


def render():
    st.subheader("📅 Agenda de Eventos")
    slug = slug_da_sessao()
    if not slug:
        st.error("Sessao invalida. Faca login novamente.")
        return

    tab_novo, tab_lista = st.tabs(["Cadastrar evento", "Eventos"])
    with tab_novo:
        _render_form(slug)
    with tab_lista:
        _render_lista(slug)
