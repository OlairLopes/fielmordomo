"""Painel do super admin — gerencia igrejas, planos, senhas, logos, backup e restauracao."""
import logging

import streamlit as st
import pandas as pd

from data.models import Igreja
from data.repository import (
    listar_igrejas, criar_igreja, atualizar_igreja,
    excluir_igreja, redefinir_senha_igreja,
    slugify, hash_senha, alterar_senha_super_admin,
    salvar_logo_sistema, obter_logo_sistema,
    salvar_logo_igreja, obter_logo_igreja,
    salvar_logo_sidebar_sistema, obter_logo_sidebar_sistema,
    salvar_logo_sidebar_igreja, obter_logo_sidebar_igreja,
    listar_subcategorias_despesa, adicionar_subcategoria_despesa,
    excluir_subcategoria_despesa,
    restaurar_backup_zip,
)
from utils.helpers import confirmar_exclusao
from admin.dashboard_geral import render_dashboard_geral

PLANOS = ["basico", "profissional", "premium"]


def render():
    st.title("FielMordomo — Painel Admin")
    st.caption("Gerenciamento de igrejas e planos")

    aba1, aba2, aba3, aba4, aba5, aba6, aba7 = st.tabs([
        "Igrejas", "Nova igreja", "Logos", "Subcategorias", "Backup", "Configuracoes",
        "📊 Dashboard Geral"
    ])

    with aba1:
        _listar_igrejas()
    with aba2:
        _criar_igreja()
    with aba3:
        _gerenciar_logos()
    with aba4:
        _gerenciar_subcategorias()
    with aba5:
        _backup_admin()
    with aba6:
        _configuracoes()
    with aba7:
        render_dashboard_geral()


def _listar_igrejas():
    df = listar_igrejas()
    if df.empty:
        st.info("Nenhuma igreja cadastrada ainda.")
        return

    df_show = df.copy()
    df_show["ativa"] = df_show["ativa"].map({1: "Sim", 0: "Nao"})
    st.dataframe(df_show, use_container_width=True)

    st.divider()
    st.subheader("Editar igreja")

    df_e = df.copy()
    df_e["rotulo"] = df_e.apply(
        lambda r: f'{int(r["id"])} | {r["nome"]} | {r["slug"]} | {r["plano"]}',
        axis=1,
    )

    rotulo = st.selectbox(
        "Selecione a igreja",
        df_e["rotulo"].tolist(),
        key="sel_igreja_edit",
    )

    sel = df_e[df_e["rotulo"] == rotulo].iloc[0]

    id_ig = int(sel["id"])
    slug = str(sel["slug"])

    kp = f"_edit_igreja_{id_ig}_"

    nome_e = st.text_input(
        "Nome da igreja",
        value=str(sel["nome"]),
        key=kp + "nome",
    )

    email_e = st.text_input(
        "E-mail do admin",
        value=str(sel["email_admin"]),
        key=kp + "email",
    )

    plano_atual = str(sel["plano"])
    plano_e = st.selectbox(
        "Plano",
        PLANOS,
        index=PLANOS.index(plano_atual) if plano_atual in PLANOS else 0,
        key=kp + "plano",
    )

    ativa_atual = (
        bool(int(sel["ativa"]))
        if str(sel["ativa"]).isdigit()
        else str(sel["ativa"]).lower() in ["sim", "true", "1"]
    )

    ativa_e = st.toggle(
        "Igreja ativa",
        value=ativa_atual,
        key=kp + "ativa",
    )

    c1, c2, c3 = st.columns(3)

    with c1:
        if st.button("Salvar alteracoes", type="primary", key=kp + "btn_upd"):
            atualizar_igreja(id_ig, nome_e, email_e, plano_e, ativa_e)

            for k in list(st.session_state.keys()):
                if k.startswith("_edit_igreja_"):
                    st.session_state.pop(k, None)

            st.toast("Igreja atualizada!")
            st.rerun()

    with c2:
        st.write("**Redefinir senha**")

        nova_senha = st.text_input(
            "Nova senha",
            type="password",
            key=kp + "nova_senha",
        )

        if st.button("Redefinir senha", key=kp + "btn_reset_senha"):
            if len(nova_senha) < 6:
                st.error("Senha deve ter ao menos 6 caracteres.")
            else:
                redefinir_senha_igreja(id_ig, nova_senha)

                for k in list(st.session_state.keys()):
                    if k.startswith("_edit_igreja_"):
                        st.session_state.pop(k, None)

                st.toast("Senha redefinida!")
                st.rerun()

    with c3:
        if confirmar_exclusao(f"del_ig_{id_ig}", "Excluir igreja"):
            excluir_igreja(id_ig, slug)

            for k in list(st.session_state.keys()):
                if k.startswith("_edit_igreja_") or k == "sel_igreja_edit":
                    st.session_state.pop(k, None)

            st.toast("Igreja excluida.")
            st.rerun()


def _criar_igreja():
    st.subheader("Cadastrar nova igreja")

    with st.form("form_nova_ig", clear_on_submit=True):
        nome = st.text_input("Nome da igreja")
        slug_sugerido = st.text_input(
            "Identificador (slug)",
            placeholder="ex: ad-serrinha",
            help="Letras minusculas, numeros e hifens. Sera o login da igreja.",
        )
        email = st.text_input("E-mail do tesoureiro")
        senha = st.text_input("Senha inicial", type="password")
        plano = st.selectbox("Plano", PLANOS)

        if st.form_submit_button("Criar igreja", type="primary"):
            slug = slugify(slug_sugerido or nome)

            ig = Igreja(
                nome=nome,
                slug=slug,
                email_admin=email,
                senha_hash=hash_senha(senha),
                plano=plano,
            )

            erros = ig.validar()

            if not senha or len(senha) < 6:
                erros.append("Senha deve ter ao menos 6 caracteres.")

            if erros:
                for e in erros:
                    st.error(e)
            else:
                try:
                    id_novo = criar_igreja(ig)
                    st.toast(f"Igreja criada! ID: {id_novo} | Slug: {slug}")

                    for k in list(st.session_state.keys()):
                        if k.startswith("df_") or k.startswith("admin_"):
                            st.session_state.pop(k, None)

                    st.rerun()

                except Exception as ex:
                    if "UNIQUE" in str(ex):
                        st.error(f"Slug '{slug}' ja existe. Escolha outro identificador.")
                    else:
                        st.error(f"Erro: {ex}")


def _gerenciar_logos():
    st.subheader("Logos do sistema")

    # ═══ LOGO PRINCIPAL DO SISTEMA ═══════════════════════════════════════
    st.markdown("#### Logo principal do FielMordomo")
    st.caption("Aparece na tela de login e como fallback geral.")

    logo_sis = obter_logo_sistema()

    if logo_sis:
        dados, ext = logo_sis
        st.image(dados, width=200, caption="Logo principal do FielMordomo")
        st.caption(f"Formato atual: {ext.upper()}")
    else:
        st.info("Nenhum logo principal cadastrado ainda.")

    if "logo_sis_counter" not in st.session_state:
        st.session_state["logo_sis_counter"] = 0

    arquivo_sis = st.file_uploader(
        "Enviar logo principal",
        type=["png", "jpg", "jpeg", "webp"],
        key=f"upload_logo_sis_{st.session_state['logo_sis_counter']}",
    )

    if arquivo_sis:
        ext = arquivo_sis.name.rsplit(".", 1)[-1].lower()
        salvar_logo_sistema(arquivo_sis.read(), ext)

        st.toast("Logo principal salvo!")
        st.session_state["logo_sis_counter"] += 1
        st.rerun()

    st.divider()

    # ═══ LOGO DA SIDEBAR (SISTEMA) ═══════════════════════════════════════
    st.markdown("#### Logo da sidebar (sistema)")
    st.caption(
        "Logo padrao da barra lateral de menus. "
        "Usado quando uma igreja nao tem seu proprio logo de sidebar."
    )

    logo_sb_sis = obter_logo_sidebar_sistema()

    if logo_sb_sis:
        dados, ext = logo_sb_sis
        st.image(dados, width=160, caption="Logo da sidebar do sistema")
        st.caption(f"Formato atual: {ext.upper()}")
    else:
        st.info("Nenhum logo de sidebar do sistema cadastrado.")

    if "logo_sb_sis_counter" not in st.session_state:
        st.session_state["logo_sb_sis_counter"] = 0

    arquivo_sb_sis = st.file_uploader(
        "Enviar logo da sidebar (sistema)",
        type=["png", "jpg", "jpeg", "webp"],
        key=f"upload_logo_sb_sis_{st.session_state['logo_sb_sis_counter']}",
    )

    if arquivo_sb_sis:
        ext = arquivo_sb_sis.name.rsplit(".", 1)[-1].lower()
        salvar_logo_sidebar_sistema(arquivo_sb_sis.read(), ext)

        st.toast("Logo da sidebar do sistema salvo!")
        st.session_state["logo_sb_sis_counter"] += 1
        st.rerun()

    st.divider()
    st.markdown("#### Logos por igreja")

    df = listar_igrejas()

    if df.empty:
        st.info("Nenhuma igreja cadastrada ainda.")
        return

    opcoes_ig = df.apply(
        lambda r: f'{r["nome"]} ({r["slug"]})',
        axis=1,
    ).tolist()

    ig_sel = st.selectbox("Selecione a igreja", opcoes_ig, key="sel_ig_logo")

    idx = opcoes_ig.index(ig_sel)
    slug = str(df.iloc[idx]["slug"])

    # ═══ LOGO PRINCIPAL DA IGREJA ════════════════════════════════════════
    st.markdown("##### Logo principal da igreja")
    st.caption("Aparece na home grande e como fallback da sidebar.")

    logo_ig = obter_logo_igreja(slug)

    if logo_ig:
        dados, ext = logo_ig
        st.image(dados, width=200, caption=f"Logo principal de {ig_sel}")
        st.caption(f"Formato atual: {ext.upper()}")
    else:
        st.info(f"Nenhum logo principal cadastrado para {ig_sel}.")

    counter_key = f"logo_ig_counter_{slug}"

    if counter_key not in st.session_state:
        st.session_state[counter_key] = 0

    arquivo_ig = st.file_uploader(
        f"Enviar logo principal de: {ig_sel}",
        type=["png", "jpg", "jpeg", "webp"],
        key=f"upload_logo_ig_{slug}_{st.session_state[counter_key]}",
    )

    if arquivo_ig:
        ext = arquivo_ig.name.rsplit(".", 1)[-1].lower()
        salvar_logo_igreja(slug, arquivo_ig.read(), ext)

        st.toast(f"Logo principal de {ig_sel} salvo!")
        st.session_state[counter_key] += 1
        st.rerun()

    st.divider()

    # ═══ LOGO DA SIDEBAR (IGREJA) ════════════════════════════════════════
    st.markdown("##### Logo da sidebar da igreja")
    st.caption(
        "Logo exibido na barra lateral apos o login desta igreja. "
        "Se vazio, usa o logo da sidebar do sistema."
    )

    logo_sb_ig = obter_logo_sidebar_igreja(slug)

    if logo_sb_ig:
        dados, ext = logo_sb_ig
        st.image(dados, width=160, caption=f"Logo da sidebar de {ig_sel}")
        st.caption(f"Formato atual: {ext.upper()}")
    else:
        st.info(f"Nenhum logo de sidebar cadastrado para {ig_sel}.")

    counter_sb_key = f"logo_sb_ig_counter_{slug}"

    if counter_sb_key not in st.session_state:
        st.session_state[counter_sb_key] = 0

    arquivo_sb_ig = st.file_uploader(
        f"Enviar logo da sidebar de: {ig_sel}",
        type=["png", "jpg", "jpeg", "webp"],
        key=f"upload_logo_sb_ig_{slug}_{st.session_state[counter_sb_key]}",
    )

    if arquivo_sb_ig:
        ext = arquivo_sb_ig.name.rsplit(".", 1)[-1].lower()
        salvar_logo_sidebar_igreja(slug, arquivo_sb_ig.read(), ext)

        st.toast(f"Logo da sidebar de {ig_sel} salvo!")
        st.session_state[counter_sb_key] += 1
        st.rerun()


def _gerenciar_subcategorias():
    st.subheader("Subcategorias de despesa")
    st.caption(
        "Estas subcategorias aparecem no lancamento de saidas (despesas) "
        "para todas as igrejas. A categoria principal continua sendo 'Despesa'."
    )

    subcategorias = listar_subcategorias_despesa()

    if subcategorias:
        st.markdown(f"**{len(subcategorias)} subcategoria(s) cadastrada(s):**")
        st.markdown("")

        for sub in subcategorias:
            col_nome, col_btn = st.columns([5, 1])

            with col_nome:
                st.markdown(
                    f"<div style='background:#f8f9fa;padding:10px 14px;"
                    f"border-radius:8px;margin-bottom:6px;"
                    f"border-left:3px solid #C62828'>"
                    f"📂 {sub}</div>",
                    unsafe_allow_html=True,
                )

            with col_btn:
                st.markdown("<div style='margin-top:6px'></div>", unsafe_allow_html=True)
                if st.button(
                    "🗑️",
                    key=f"del_sub_{sub}",
                    help=f"Excluir '{sub}'",
                    use_container_width=True,
                ):
                    excluir_subcategoria_despesa(sub)
                    st.toast(f"Subcategoria '{sub}' excluida.")
                    st.rerun()
    else:
        st.info("Nenhuma subcategoria cadastrada.")

    st.divider()
    st.markdown("**Adicionar nova subcategoria**")

    with st.form("form_nova_sub", clear_on_submit=True):
        nova_sub = st.text_input(
            "Nome da subcategoria",
            placeholder="Ex: Equipamentos de som",
            help="Use letras, numeros e espacos. Sem acentos quando possivel.",
        )

        if st.form_submit_button("Adicionar", type="primary"):
            if not nova_sub.strip():
                st.error("Informe o nome da subcategoria.")
            else:
                if adicionar_subcategoria_despesa(nova_sub):
                    st.toast(f"Subcategoria '{nova_sub}' adicionada!")
                    st.rerun()
                else:
                    st.error("Esta subcategoria ja existe.")


def _backup_admin():
    import io
    import zipfile
    import pandas as _pd

    from data.repository import (
        carregar_cadastros, carregar_lancamentos, _tenant_db,
        MASTER_DB, LOGOS_DIR,
    )

    st.subheader("Backup e Restauracao")

    # ═══ GERAR BACKUP COMPLETO ═══════════════════════════════════════════
    st.markdown("#### 📦 Gerar backup completo do sistema")
    st.caption(
        "Inclui: bancos de todas as igrejas, configuracoes do sistema, "
        "subcategorias, logos e o banco master (senhas, planos, super admin)."
    )

    df_igrejas = listar_igrejas()

    if df_igrejas.empty:
        st.info("Nenhuma igreja cadastrada.")
        info_qtd = "0 igreja(s)"
    else:
        info_qtd = f"{len(df_igrejas)} igreja(s)"

    qtd_logos = len(list(LOGOS_DIR.glob("*"))) if LOGOS_DIR.exists() else 0

    col_info1, col_info2, col_info3 = st.columns(3)
    col_info1.metric("Igrejas", info_qtd)
    col_info2.metric("Logos", str(qtd_logos))
    col_info3.metric("Master.db", "OK" if MASTER_DB.exists() else "Ausente")

    if st.button("Gerar backup completo", type="primary", key="btn_backup_admin"):
        buf = io.BytesIO()
        falhas = []

        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            # ─── 1. MASTER.DB (senhas, planos, configs, subcategorias) ────
            try:
                if MASTER_DB.exists():
                    zf.writestr("master.db", MASTER_DB.read_bytes())
            except Exception as exc:
                logging.exception("Falha ao incluir master.db no backup completo.")
                falhas.append(("master.db", str(exc)))

            # ─── 2. LOGOS (sistema, igrejas, sidebar) ──────────────────────
            if LOGOS_DIR.exists():
                for logo_file in LOGOS_DIR.glob("*"):
                    if logo_file.is_file():
                        try:
                            zf.writestr(
                                f"logos/{logo_file.name}",
                                logo_file.read_bytes(),
                            )
                        except Exception as exc:
                            logging.exception("Falha ao incluir logo %s no backup completo.", logo_file.name)
                            falhas.append((f"logos/{logo_file.name}", str(exc)))

            # ─── 3. BANCOS TENANT + CSVs por igreja ────────────────────────
            for _, row in df_igrejas.iterrows():
                slug = str(row["slug"])

                try:
                    df_c = carregar_cadastros(slug)
                    zf.writestr(
                        f"{slug}/cadastros.csv",
                        df_c.to_csv(index=False, encoding="utf-8-sig"),
                    )
                except Exception as exc:
                    logging.exception("Falha ao exportar cadastros da igreja %s no backup completo.", slug)
                    falhas.append((f"{slug}/cadastros.csv", str(exc)))

                try:
                    df_l = carregar_lancamentos(slug)
                    if not df_l.empty and "data" in df_l.columns:
                        df_l = df_l.copy()
                        df_l["data"] = (
                            _pd.to_datetime(df_l["data"], errors="coerce")
                            .dt.strftime("%d/%m/%Y")
                            .fillna("")
                        )
                    zf.writestr(
                        f"{slug}/lancamentos.csv",
                        df_l.to_csv(index=False, encoding="utf-8-sig"),
                    )
                except Exception as exc:
                    logging.exception("Falha ao exportar lancamentos da igreja %s no backup completo.", slug)
                    falhas.append((f"{slug}/lancamentos.csv", str(exc)))

                try:
                    db = _tenant_db(slug)
                    if db.exists():
                        zf.writestr(f"{slug}/banco_{slug}.db", db.read_bytes())
                except Exception as exc:
                    logging.exception("Falha ao incluir o banco da igreja %s no backup completo.", slug)
                    falhas.append((f"{slug}/banco_{slug}.db", str(exc)))

        buf.seek(0)
        st.session_state["backup_admin_dados"] = buf.read()
        st.session_state["backup_admin_nome"] = (
            f"fielmordomo_backup_completo_{_pd.Timestamp.now().strftime('%Y%m%d_%H%M%S')}.zip"
        )
        st.session_state["backup_admin_falhas"] = falhas
        if falhas:
            st.warning(
                f"⚠️ Backup gerado, mas {len(falhas)} item(ns) falharam e podem "
                "estar ausentes do ZIP. Veja a lista abaixo."
            )
        else:
            st.toast("Backup completo gerado!")

    if st.session_state.get("backup_admin_falhas"):
        with st.expander(
            f"⚠️ {len(st.session_state['backup_admin_falhas'])} falha(s) no ultimo backup completo",
            expanded=False,
        ):
            for item, erro in st.session_state["backup_admin_falhas"]:
                st.caption(f"• **{item}**: {erro}")

    if "backup_admin_dados" in st.session_state:
        tam_mb = len(st.session_state["backup_admin_dados"]) / (1024 * 1024)
        st.success(f"âœ… Backup pronto ({tam_mb:.2f} MB)")
        st.download_button(
            "📥 Baixar backup completo",
            data=st.session_state["backup_admin_dados"],
            file_name=st.session_state["backup_admin_nome"],
            mime="application/zip",
            key="dl_backup_admin",
            type="primary",
            use_container_width=True,
        )

    st.divider()

    # ═══ RESTAURAR BACKUP ════════════════════════════════════════════════
    st.markdown("#### â™»ï¸ Restaurar backup completo")
    st.caption(
        "Envie o arquivo ZIP de backup. O sistema restaurara tudo: "
        "tenants, master.db, logos e configuracoes. "
        "Backups automaticos de seguranca sao feitos antes de sobrescrever."
    )

    st.warning(
        "âš ï¸ **Atencao:** esta operacao sobrescreve dados atuais do sistema "
        "(igrejas, senhas, planos, configuracoes, logos e subcategorias). "
        "Bancos atuais sao salvos automaticamente em `backups/` no servidor."
    )

    if "restaurar_counter" not in st.session_state:
        st.session_state["restaurar_counter"] = 0

    arquivo_zip = st.file_uploader(
        "Arquivo ZIP de backup",
        type=["zip"],
        key=f"upload_restore_{st.session_state['restaurar_counter']}",
        help="Aceita ZIPs gerados pela funcao 'Gerar backup completo' acima.",
    )

    if arquivo_zip:
        tam_mb_up = arquivo_zip.size / (1024 * 1024)
        st.info(
            f"📦 Arquivo recebido: **{arquivo_zip.name}** ({tam_mb_up:.2f} MB)"
        )

        col_r1, col_r2 = st.columns([1, 3])

        with col_r1:
            confirmar_restauracao = st.button(
                "âœ… Restaurar agora",
                type="primary",
                key="btn_confirmar_restauracao",
                use_container_width=True,
            )

        with col_r2:
            if st.button(
                "âŒ Cancelar",
                key="btn_cancelar_restauracao",
                use_container_width=True,
            ):
                st.session_state["restaurar_counter"] += 1
                st.rerun()

        if confirmar_restauracao:
            with st.spinner("Restaurando backup completo..."):
                resultado = restaurar_backup_zip(arquivo_zip.read())

            # Resumo geral
            total_ok = (
                len(resultado["sucesso_tenants"]) +
                (1 if resultado["master_restaurado"] else 0) +
                resultado["logos_restaurados"]
            )

            if total_ok > 0:
                st.success(f"✅ Restauracao concluida — {total_ok} item(ns) restaurado(s).")

            # Master.db
            if resultado["master_restaurado"]:
                st.markdown(
                    "✅ **Banco master.db restaurado** — "
                    "senhas, planos, subcategorias e configuracoes do sistema."
                )

            # Logos
            if resultado["logos_restaurados"] > 0:
                st.markdown(
                    f"✅ **{resultado['logos_restaurados']} logo(s) restaurado(s)** — "
                    "sistema, igrejas e sidebar."
                )

            # Tenants
            if resultado["sucesso_tenants"]:
                with st.expander(
                    f"✅ {len(resultado['sucesso_tenants'])} igreja(s) restaurada(s) — ver detalhes",
                    expanded=False,
                ):
                    for slug_r in resultado["sucesso_tenants"]:
                        st.markdown(f"- `{slug_r}`")

            # Igrejas recriadas (placeholder)
            if resultado["igrejas_recriadas"]:
                st.info(
                    f"â„¹ï¸ **{len(resultado['igrejas_recriadas'])} igreja(s) recriada(s) no sistema:**"
                )
                with st.expander("Ver detalhes", expanded=False):
                    st.caption(
                        "Estas igrejas nao existiam no sistema atual e foram "
                        "registradas com plano **basico** e senha padrao "
                        "**fielmordomo2024**. Recomenda-se redefinir senha e plano."
                    )
                    for slug_r in resultado["igrejas_recriadas"]:
                        st.markdown(f"- 🆕 `{slug_r}`")

            # Erros
            if resultado["erros"]:
                st.error(
                    f"âš ï¸ **{len(resultado['erros'])} erro(s) durante a restauracao:**"
                )
                with st.expander("Ver erros", expanded=True):
                    for erro in resultado["erros"]:
                        st.markdown(f"- âŒ {erro}")

            if total_ok == 0 and not resultado["erros"]:
                st.warning("Nenhum item restaurado. Verifique o arquivo ZIP.")

            # Limpa cache
            for k in list(st.session_state.keys()):
                if k.startswith("df_") or k.startswith("admin_") or k.startswith("logo_"):
                    st.session_state.pop(k, None)

            st.session_state["restaurar_counter"] += 1

            st.markdown("---")
            if st.button("Continuar", type="primary", key="btn_continuar_pos_restore"):
                st.rerun()


def _configuracoes():
    from data.repository import obter_config, salvar_config

    st.subheader("Configuracoes do sistema")

    st.markdown("#### Contato para recuperacao de senha")
    st.caption(
        "Estas informacoes aparecem na tela de login quando o usuario "
        "clica em 'Esqueci minha senha'."
    )

    contato_email = obter_config("contato_email", "admin@fielmordomo.com")
    contato_whatsapp = obter_config("contato_whatsapp", "")
    contato_mensagem = obter_config(
        "contato_mensagem",
        "Entre em contato com o administrador do sistema para redefinir sua senha.",
    )

    with st.form("form_contato"):
        email_novo = st.text_input(
            "E-mail de contato",
            value=contato_email,
            placeholder="admin@fielmordomo.com",
        )

        wpp_novo = st.text_input(
            "WhatsApp (com DDD)",
            value=contato_whatsapp,
            placeholder="62999999999",
            help="Apenas numeros, ex: 62999999999",
        )

        msg_nova = st.text_area(
            "Mensagem na tela de login",
            value=contato_mensagem,
            height=80,
        )

        if st.form_submit_button("Salvar configuracoes", type="primary"):
            salvar_config("contato_email", email_novo.strip())
            salvar_config(
                "contato_whatsapp",
                "".join(c for c in wpp_novo if c.isdigit()),
            )
            salvar_config("contato_mensagem", msg_nova.strip())

            st.toast("Configuracoes salvas!")
            st.rerun()

    st.divider()

    st.markdown("#### Alterar senha do administrador")

    with st.form("form_senha_admin"):
        nova = st.text_input("Nova senha", type="password")
        conf = st.text_input("Confirmar nova senha", type="password")

        if st.form_submit_button("Alterar senha", type="primary"):
            if len(nova) < 6:
                st.error("Senha deve ter ao menos 6 caracteres.")
            elif nova != conf:
                st.error("As senhas nao coincidem.")
            else:
                alterar_senha_super_admin("admin", nova)
                st.toast("Senha alterada!")
