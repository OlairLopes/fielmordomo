"""
Autenticação do FielMordomo.
"""
import logging

import base64
import hashlib
import hmac
import html
import json
import os
import re
import time
import urllib.parse
import streamlit as st
from streamlit_cookies_controller import CookieController

from data.repository import (
    autenticar_super_admin, autenticar_igreja, autenticar_tesoureiro,
    autenticar_gfc_secretaria, autenticar_gfc_secretaria_por_cpf4,
    autenticar_ebd_secretario, autenticar_orhafe_secretaria,
    autenticar_orhafe_secretaria_por_cpf4,
    autenticar_pastor_auxiliar, autenticar_recepcao,
    autenticar_recepcao_por_cpf4, autenticar_secretario_geral,
    carregar_tesoureiros, inicializar_master, listar_ebd_secretarios,
    formatar_telefone,
    listar_gfc_grupos, listar_gfc_secretarias, listar_igrejas, listar_orhafe_secretarias, listar_pastores_auxiliares,
    listar_recepcao_usuarios, listar_secretarios_gerais,
    obter_logo_sistema, obter_config,
)


EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

SESSAO_COOKIE_NOME = "fm_sessao"
SESSAO_COOKIE_KEY = "fm_cookies"
SESSAO_TTL_SEGUNDOS = 12 * 3600
_CAMPOS_SESSAO = (
    "modo", "igreja", "tesoureiro", "secretario_ebd", "secretaria_orhafe",
    "secretaria_gfc", "pastor_auxiliar", "recepcao", "secretario_geral",
)


def _cookie_controller():
    return CookieController(key=SESSAO_COOKIE_KEY)


def _sessao_secret() -> str:
    try:
        segredo = str(st.secrets.get("auth", {}).get("session_secret", "") or "")
    except Exception:
        segredo = ""
    if segredo:
        return segredo
    return str(os.environ.get("SESSION_SECRET", "") or "")


def _gerar_token_sessao(dados: dict) -> str:
    segredo = _sessao_secret()
    if not segredo:
        return ""
    corpo = {chave: valor for chave, valor in dados.items() if valor is not None}
    corpo["exp"] = int(time.time()) + SESSAO_TTL_SEGUNDOS
    payload_json = json.dumps(corpo, separators=(",", ":"), sort_keys=True, default=str)
    payload_b64 = base64.urlsafe_b64encode(payload_json.encode("utf-8")).decode("ascii")
    assinatura = hmac.new(segredo.encode("utf-8"), payload_b64.encode("ascii"), hashlib.sha256).hexdigest()
    return f"{payload_b64}.{assinatura}"


def _validar_token_sessao(token: str):
    segredo = _sessao_secret()
    if not segredo or not token or "." not in token:
        return None
    payload_b64, _, assinatura = token.partition(".")
    esperada = hmac.new(segredo.encode("utf-8"), payload_b64.encode("ascii"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(assinatura, esperada):
        return None
    try:
        corpo = json.loads(base64.urlsafe_b64decode(payload_b64.encode("ascii")).decode("utf-8"))
    except Exception:
        return None
    if int(corpo.get("exp", 0)) < int(time.time()):
        return None
    return corpo


def _persistir_sessao_cookie(**dados):
    if not _sessao_secret():
        return
    token = _gerar_token_sessao(dados)
    if not token:
        return
    try:
        _cookie_controller().set(
            SESSAO_COOKIE_NOME,
            token,
            max_age=SESSAO_TTL_SEGUNDOS,
            same_site="lax",
            secure=True,
        )
    except Exception:
        logging.exception("Erro ignorado silenciosamente")


def _remover_sessao_cookie():
    try:
        _cookie_controller().remove(SESSAO_COOKIE_NOME)
    except Exception:
        logging.exception("Erro ignorado silenciosamente")


def _tela_carregando_sessao():
    st.markdown(
        """
        <div style="display:flex;justify-content:center;align-items:center;height:60vh">
          <span style="color:#64748B;font-size:.95rem">Carregando sessão...</span>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _restaurar_sessao_por_cookie() -> bool:
    if not _sessao_secret():
        return False
    cookies_ja_carregados = SESSAO_COOKIE_KEY in st.session_state
    controller = _cookie_controller()
    if not cookies_ja_carregados:
        _tela_carregando_sessao()
        st.stop()
    token = controller.get(SESSAO_COOKIE_NOME)
    dados = _validar_token_sessao(token)
    if not dados:
        return False
    modo = dados.pop("modo", None)
    dados.pop("exp", None)
    if not modo:
        return False
    dados = {chave: valor for chave, valor in dados.items() if chave in _CAMPOS_SESSAO}
    _iniciar_sessao(modo, **dados)
    return True


def _normalizar_email(email: str) -> str:
    email = str(email or "").strip()
    return email if EMAIL_RE.fullmatch(email) else ""


def _normalizar_whatsapp(numero: str) -> str:
    numero = "".join(c for c in str(numero or "") if c.isdigit())
    if numero and not numero.startswith("55"):
        numero = f"55{numero}"
    return numero


def _iniciar_sessao(
    modo: str,
    igreja=None,
    tesoureiro=None,
    secretario_ebd=None,
    secretaria_orhafe=None,
    secretaria_gfc=None,
    pastor_auxiliar=None,
    recepcao=None,
    secretario_geral=None,
):
    _limpar_sessao()
    st.session_state["autenticado"] = True
    st.session_state["modo"] = modo
    if igreja is not None:
        st.session_state["igreja"] = igreja
    if tesoureiro is not None:
        st.session_state["tesoureiro"] = tesoureiro
    if secretario_ebd is not None:
        st.session_state["secretario_ebd"] = secretario_ebd
    if secretaria_orhafe is not None:
        st.session_state["secretaria_orhafe"] = secretaria_orhafe
    if secretaria_gfc is not None:
        st.session_state["secretaria_gfc"] = secretaria_gfc
    if pastor_auxiliar is not None:
        st.session_state["pastor_auxiliar"] = pastor_auxiliar
    if recepcao is not None:
        st.session_state["recepcao"] = recepcao
    if secretario_geral is not None:
        st.session_state["secretario_geral"] = secretario_geral
    _persistir_sessao_cookie(
        modo=modo,
        igreja=igreja,
        tesoureiro=tesoureiro,
        secretario_ebd=secretario_ebd,
        secretaria_orhafe=secretaria_orhafe,
        secretaria_gfc=secretaria_gfc,
        pastor_auxiliar=pastor_auxiliar,
        recepcao=recepcao,
        secretario_geral=secretario_geral,
    )


def _limpar_sessao():
    for key in (
        "autenticado", "modo", "igreja", "tesoureiro", "secretario_ebd",
        "secretaria_orhafe", "secretaria_gfc", "pastor_auxiliar", "recepcao", "secretario_geral",
        "pagina", "mostrar_recuperacao", "recuperacao_modo", "_login_acesso_url_aplicado",
    ):
        st.session_state.pop(key, None)
    for key in list(st.session_state.keys()):
        if key.startswith(("df_", "lote_", "nl_counter_", "dashboard_", "_auth_", "_edit_", "_del_")):
            st.session_state.pop(key, None)


def _exibir_logo_sistema():
    resultado = obter_logo_sistema()
    if resultado:
        dados, _ext = resultado
        st.image(dados, width=150, caption="Logotipo do sistema")
    else:
        st.markdown(
            """
            <div style="text-align:center;padding:1rem 0 0.5rem">
              <span style="font-size:2.2rem;font-weight:600;
                           color:var(--color-text-primary)">
                FielMordomo
              </span>
            </div>
            """,
            unsafe_allow_html=True,
        )


def _logo_login_src():
    resultado = obter_logo_sistema()
    if not resultado:
        return ""
    dados, ext = resultado
    mime = {
        "png": "image/png",
        "jpg": "image/jpeg",
        "jpeg": "image/jpeg",
        "webp": "image/webp",
        "gif": "image/gif",
    }.get(str(ext or "png").lower().replace(".", ""), "image/png")
    return f"data:{mime};base64,{base64.b64encode(dados).decode('utf-8')}"


LOGIN_OPCOES = [
    ("Gestor/Pastor", "Acesso principal", "Gestão completa da igreja"),
    ("Pastor Auxiliar", "Acesso pastoral", "Visitantes, pedidos e relatórios permitidos"),
    ("Tesoureiro", "Financeiro", "Lançamentos, membros e relatórios"),
    ("Recepcao", "Visitantes", "Registro de visitantes"),
    ("Secretario Geral", "Secretaria geral", "Membros, obreiros e aniversários"),
    ("Escola Biblica", "Secretaria", "Chamada e gestão da Escola Bíblica"),
    ("Circulo de Oracao", "Secretaria", "Chamada e relatórios do Círculo de Oração"),
    ("GFC", "Secretaria", "Registro dos Grupos Familiares de Crescimento"),
    ("Administrador do sistema", "Admin", "Painel geral da plataforma"),
]

LOGIN_ROTULOS = {
    "Recepcao": "Recepção",
    "Secretario Geral": "Secretário Geral",
    "Escola Biblica": "Escola Bíblica",
    "Circulo de Oracao": "Círculo de Oração",
}


def _rotulo_login(modo):
    return LOGIN_ROTULOS.get(modo, modo)


def _login_css():
    st.markdown(
        """
        <style>
            .block-container {
                padding-top: 2.8rem !important;
                max-width: 1260px !important;
            }
            div[data-testid="stForm"] {
                background: #FFFFFF;
                border: 1px solid #E5E7EB;
                border-radius: 18px;
                padding: 1.4rem 1.5rem 1.5rem;
                box-shadow: 0 20px 45px rgba(6, 27, 68, .10);
            }
            .fm-login-side {
                background: linear-gradient(180deg, #061B44 0%, #0A0A0A 100%);
                border-radius: 24px;
                padding: 28px 22px 24px;
                min-height: 660px;
                margin-top: 34px;
                margin-bottom: 18px;
                box-shadow: 0 24px 54px rgba(6, 27, 68, .28);
                overflow: visible;
                position: relative;
                box-sizing: border-box;
            }
            .fm-login-side * {
                color: #FFFFFF;
            }
            .fm-login-logo {
                display: flex;
                justify-content: center;
                align-items: center;
                padding: 0 0 20px;
                margin: -48px -10px 18px;
                border-bottom: 1px solid rgba(255,255,255,.14);
                overflow: visible;
                position: relative;
                z-index: 10;
            }
            .fm-login-logo img {
                width: 240px;
                max-width: 118%;
                height: auto;
                object-fit: contain;
                position: relative;
                z-index: 11;
                filter: drop-shadow(0 10px 18px rgba(0,0,0,.28));
            }
            .fm-login-logo-fallback {
                width: 82px;
                height: 82px;
                border-radius: 22px;
                display: flex;
                align-items: center;
                justify-content: center;
                border: 1px solid rgba(212,175,55,.55);
                color: #D4AF37 !important;
                font-size: 1.6rem;
                font-weight: 850;
            }
            .fm-login-side-label {
                color: rgba(255,255,255,.72) !important;
                font-size: .78rem;
                font-weight: 800;
                text-transform: uppercase;
                letter-spacing: .08em;
                margin: 18px 4px 10px;
            }
            .fm-login-link {
                display: block;
                width: 100%;
                border-radius: 13px;
                padding: .78rem .82rem;
                margin-bottom: .52rem;
                text-align: left;
                color: rgba(255,255,255,.92) !important;
                background: rgba(255,255,255,.06);
                font-weight: 700;
                font-size: .86rem;
                line-height: 1.25;
                white-space: normal;
                overflow-wrap: anywhere;
                word-break: normal;
                text-decoration: none !important;
                transition: .18s ease;
                box-sizing: border-box;
            }
            .fm-login-link:hover {
                background: rgba(212, 175, 55, .22);
                color: #D4AF37 !important;
            }
            .fm-login-link.active {
                background: rgba(212, 175, 55, .28);
                color: #D4AF37 !important;
                border-left: 4px solid #D4AF37;
            }
            .fm-login-heading {
                color: #061B44;
                font-size: 1.75rem;
                font-weight: 850;
                margin: 18px 0 6px;
            }
            .fm-login-muted {
                color: #64748B;
                font-size: .95rem;
                margin-bottom: 20px;
            }
            .fm-login-select-anchor {
                display: none;
            }
            div[data-testid="stHorizontalBlock"] > div[data-testid="column"]:nth-child(2) div[data-testid="stSelectbox"] {
                background: #FFFFFF;
                border: 1px solid #E5E7EB;
                border-radius: 18px;
                padding: 1rem;
                margin-bottom: 1rem;
                box-shadow: 0 12px 30px rgba(6, 27, 68, .08);
            }
            div[data-testid="stHorizontalBlock"] > div[data-testid="column"]:first-child {
                padding-top: 4px !important;
                overflow: visible !important;
            }
            @media (max-width: 760px) {
                .block-container {
                    padding: .8rem .7rem 1.2rem !important;
                }
                div[data-testid="stHorizontalBlock"] > div[data-testid="column"]:first-child {
                    display: none !important;
                }
                div[data-testid="column"] {
                    width: 100% !important;
                    flex: 1 1 100% !important;
                }
                div[data-testid="stHorizontalBlock"] {
                    gap: .75rem !important;
                }
                .fm-login-side {
                    padding: 20px 14px 16px;
                    min-height: auto;
                    border-radius: 18px;
                    margin-top: 28px;
                }
                .fm-login-logo {
                    margin: -38px -6px 14px;
                    padding-bottom: 14px;
                }
                .fm-login-logo img {
                    width: 205px;
                    max-width: 112%;
                }
                .fm-login-link {
                    padding: .68rem .68rem;
                    font-size: .8rem;
                    line-height: 1.18;
                    margin-bottom: .42rem;
                    max-width: 100%;
                }
                .fm-login-side-label {
                    font-size: .68rem;
                    margin: 12px 4px 8px;
                }
                .fm-login-heading {
                    font-size: 1.45rem;
                }
                div[data-testid="stForm"] {
                    padding: 1rem !important;
                    border-radius: 14px;
                }
            }
        </style>
        """,
        unsafe_allow_html=True,
    )


def _modo_login_atual():
    modos = [item[0] for item in LOGIN_OPCOES]
    acesso_url = st.query_params.get("acesso", "")
    if isinstance(acesso_url, list):
        acesso_url = acesso_url[0] if acesso_url else ""
    acesso_url = urllib.parse.unquote(str(acesso_url or ""))
    modo_select = st.session_state.get("login_modo_select")
    acesso_url_aplicado = st.session_state.get("_login_acesso_url_aplicado", "")
    if acesso_url in modos and acesso_url != acesso_url_aplicado:
        modo = acesso_url
        st.session_state["_login_acesso_url_aplicado"] = acesso_url
    else:
        modo = modo_select if modo_select in modos else st.session_state.get("login_modo", modos[0])
    if modo not in modos:
        modo = modos[0]
    st.session_state["login_modo"] = modo
    st.session_state["login_modo_select"] = modo
    return modo


def _selecionar_modo_login(modo):
    st.session_state["login_modo"] = modo
    st.session_state["login_modo_select"] = modo
    st.session_state["mostrar_recuperacao"] = False
    try:
        st.query_params["pagina"] = "login"
        st.query_params["acesso"] = modo
        st.session_state["_login_acesso_url_aplicado"] = modo
    except Exception:
        logging.exception("Erro ignorado silenciosamente")
    st.rerun()


def _sidebar_login(modo_atual):
    logo_src = _logo_login_src()
    if logo_src:
        logo_html = f'<img src="{html.escape(logo_src, quote=True)}" alt="Logo">'
    else:
        logo_html = '<div class="fm-login-logo-fallback">FM</div>'
    links = []
    for modo, titulo, descricao in LOGIN_OPCOES:
        label = _rotulo_login(modo)
        classe = "fm-login-link active" if modo == modo_atual else "fm-login-link"
        href = f"?pagina=login&acesso={urllib.parse.quote(modo)}"
        links.append(
            f'<a class="{classe}" href="{html.escape(href, quote=True)}" '
            f'target="_top" title="{html.escape(descricao, quote=True)}">'
            f'{html.escape(label)}</a>'
        )
    st.markdown(
        f"""
        <div class="fm-login-side">
            <div class="fm-login-logo">{logo_html}</div>
            <a class="fm-login-link" href="?pagina=inicio" target="_top"
               title="Voltar para a página inicial">Início</a>
            <div class="fm-login-side-label">Tipo de acesso</div>
            {''.join(links)}
        </div>
        """,
        unsafe_allow_html=True,
    )


def _render_login_por_modo(modo):
    if modo == "Gestor/Pastor":
        _login_igreja()
    elif modo == "Pastor Auxiliar":
        _login_pastor_auxiliar()
    elif modo == "Tesoureiro":
        _login_tesoureiro()
    elif modo == "Recepcao":
        _login_recepcao()
    elif modo == "Secretario Geral":
        _login_secretario_geral()
    elif modo == "Escola Biblica":
        _login_ebd()
    elif modo == "Circulo de Oracao":
        _login_orhafe()
    elif modo == "GFC":
        _login_gfc()
    else:
        _login_admin()


def _seletor_login(modo_atual):
    opcoes = [item[0] for item in LOGIN_OPCOES]
    indice = opcoes.index(modo_atual) if modo_atual in opcoes else 0
    if st.session_state.get("login_modo_select") not in opcoes:
        st.session_state["login_modo_select"] = modo_atual
    st.markdown('<span class="fm-login-select-anchor"></span>', unsafe_allow_html=True)
    novo_modo = st.selectbox(
        "Tipo de acesso",
        opcoes,
        index=indice,
        key="login_modo_select",
        format_func=_rotulo_login,
    )
    if novo_modo != modo_atual:
        _selecionar_modo_login(novo_modo)


def _mostrar_recuperacao_senha():
    """Tela com contato do admin para recuperação de senha."""
    modo_recuperacao = st.session_state.get("recuperacao_modo") or st.session_state.get("login_modo", "acesso")
    modo_recuperacao_txt = _rotulo_login(modo_recuperacao)
    email_admin  = _normalizar_email(obter_config("contato_email", "admin@fielmordomo.com"))
    wpp_admin    = _normalizar_whatsapp(obter_config("contato_whatsapp", ""))
    mensagem     = obter_config(
        "contato_mensagem",
        "Entre em contato com o administrador do sistema para redefinir sua senha."
    )

    st.markdown("### Recuperar senha")
    st.caption(f"Perfil selecionado: **{modo_recuperacao_txt}**")
    st.info(mensagem)

    st.markdown("**Canais de contato:**")

    if email_admin:
        assunto = urllib.parse.quote("Solicitação de redefinição de senha - FielMordomo")
        corpo = urllib.parse.quote(
            "Olá,\n\n"
            "Solicito a redefinição de senha/acesso no sistema FielMordomo.\n\n"
            f"Tipo de acesso: {modo_recuperacao_txt}\n"
            "Identificador da igreja (slug): \n"
            "Nome da igreja/congregação: \n"
            "Usuário, quando houver: \n"
            "Motivo: \n\n"
            "Obrigado!"
        )
        email_link = urllib.parse.quote(email_admin, safe="@._+-")
        link_email = html.escape(
            f"mailto:{email_link}?subject={assunto}&body={corpo}", quote=True
        )
        st.markdown(
            f'<a href="{link_email}" '
            f'style="display:inline-block;background:#061B44;color:white;'
            f'padding:10px 20px;border-radius:8px;text-decoration:none;'
            f'font-weight:600;margin:4px 4px 4px 0">'
            f'📧 Enviar e-mail ao administrador</a>',
            unsafe_allow_html=True,
        )
        st.caption(f"E-mail: **{email_admin}**")

    if wpp_admin:
        msg_wpp = urllib.parse.quote(
            f"Olá! Preciso de ajuda para redefinir meu acesso no FielMordomo. Tipo de acesso: {modo_recuperacao_txt}. "
            "Pode me ajudar?"
        )
        wpp_link = html.escape(f"https://wa.me/{wpp_admin}?text={msg_wpp}", quote=True)
        st.markdown(
            f'<a href="{wpp_link}" target="_blank" rel="noopener noreferrer" '
            f'style="display:inline-block;background:#25D366;color:white;'
            f'padding:10px 20px;border-radius:8px;text-decoration:none;'
            f'font-weight:600;margin:4px 4px 4px 0">'
            f'💬 Falar pelo WhatsApp</a>',
            unsafe_allow_html=True,
        )
        st.caption(f"WhatsApp: **{formatar_telefone(wpp_admin)}**")

    st.divider()

    if st.button("Voltar para o login", use_container_width=True):
        st.session_state["mostrar_recuperacao"] = False
        st.session_state.pop("recuperacao_modo", None)
        st.rerun()


def _botao_recuperar_senha(modo, key):
    col1, col2 = st.columns(2)
    with col1:
        if st.button("Esqueci minha senha", use_container_width=True, key=key):
            st.session_state["recuperacao_modo"] = modo
            st.session_state["mostrar_recuperacao"] = True
            st.rerun()
    with col2:
        st.caption("Não tem acesso? Entre em contato com o administrador.")


def tela_login():
    if st.session_state.get("autenticado"):
        return True

    if _restaurar_sessao_por_cookie():
        return True

    inicializar_master()
    _login_css()
    modo = _modo_login_atual()

    col_side, col_main = st.columns([1.18, 2.05], gap="large")
    with col_side:
        _sidebar_login(modo)

    with col_main:
        _seletor_login(modo)
        st.markdown(
            """
            <div class="fm-login-heading">Acessar Sistema</div>
            <div class="fm-login-muted">
                Escolha o perfil de acesso na barra lateral e informe suas credenciais.
            </div>
            """,
            unsafe_allow_html=True,
        )

        if st.session_state.get("mostrar_recuperacao"):
            _mostrar_recuperacao_senha()
            return False

        _render_login_por_modo(modo)

    return False

def _login_igreja():
    with st.form("form_login_igreja"):
        st.markdown("#### Acesso do Gestor/Pastor")
        slug = _selectbox_igreja_login("login_igreja_slug")
        senha = st.text_input("Senha", type="password", autocomplete="off")

        if st.form_submit_button("Entrar", type="primary", use_container_width=True):
            slug = str(slug or "").strip().lower()
            if not slug or not senha:
                st.error("Preencha todos os campos.")
                return
            igreja = autenticar_igreja(slug, senha)
            if igreja:
                _iniciar_sessao("igreja", igreja)
                st.toast(f"Bem-vindo, {igreja['nome']}!")
                st.rerun()
            else:
                st.error("Identificador ou senha incorretos, ou igreja inativa.")

    _botao_recuperar_senha("Gestor/Pastor", "btn_esqueci_igreja")


def _login_admin():
    with st.form("form_login_admin"):
        st.markdown("#### Administrador do sistema")
        usuario = st.text_input("Usuário")
        senha   = st.text_input("Senha", type="password", autocomplete="off")

        if st.form_submit_button("Entrar", type="primary", use_container_width=True):
            usuario = usuario.strip()
            if not usuario or not senha:
                st.error("Preencha todos os campos.")
                return
            if autenticar_super_admin(usuario, senha):
                _iniciar_sessao("admin")
                st.toast("Acesso de administrador autorizado.")
                st.rerun()
            else:
                st.error("Credenciais inválidas.")

    _botao_recuperar_senha("Administrador do sistema", "btn_esqueci_admin")



def _login_tesoureiro():
    st.markdown("#### Acesso restrito do tesoureiro")
    st.caption("Este acesso permite somente registrar e consultar lançamentos.")
    slug = _selectbox_igreja_login("login_tesoureiro_igreja")
    usuario = _selectbox_usuario_login(
        slug,
        "tesoureiro",
        "Usuário do tesoureiro",
        f"login_tesoureiro_usuario_{slug or 'sem_igreja'}",
    )

    with st.form("form_login_tesoureiro"):
        senha = st.text_input("Senha", type="password", autocomplete="off")
        if st.form_submit_button("Entrar", type="primary", use_container_width=True):
            slug = str(slug or "").strip().lower()
            usuario = str(usuario or "").strip().lower()
            if not slug or not usuario or not senha:
                st.error("Preencha todos os campos.")
                return
            acesso = autenticar_tesoureiro(slug, usuario, senha)
            if acesso:
                _iniciar_sessao(
                    "tesoureiro",
                    igreja=acesso["igreja"],
                    tesoureiro=acesso["tesoureiro"],
                )
                st.toast(f"Bem-vindo, {acesso['tesoureiro']['nome']}!")
                st.rerun()
            else:
                st.error("Identificador, usuário ou senha incorretos, ou acesso inativo.")

    _botao_recuperar_senha("Tesoureiro", "btn_esqueci_tesoureiro")


def _login_pastor_auxiliar():
    st.markdown("#### Acesso do Pastor Auxiliar")
    st.caption("Acesso restrito a visitantes, aniversários, relatórios ministeriais e dashboard limitado.")
    slug = _selectbox_igreja_login("login_pastor_auxiliar_igreja")
    usuario = _selectbox_usuario_login(
        slug,
        "pastor_auxiliar",
        "Usuário do Pastor Auxiliar",
        f"login_pastor_auxiliar_usuario_{slug or 'sem_igreja'}",
    )

    with st.form("form_login_pastor_auxiliar"):
        senha = st.text_input("Senha", type="password", autocomplete="off")
        if st.form_submit_button("Entrar", type="primary", use_container_width=True):
            slug = str(slug or "").strip().lower()
            usuario = str(usuario or "").strip().lower()
            if not slug or not usuario or not senha:
                st.error("Preencha todos os campos.")
                return
            acesso = autenticar_pastor_auxiliar(slug, usuario, senha)
            if acesso:
                _iniciar_sessao(
                    "pastor_auxiliar",
                    igreja=acesso["igreja"],
                    pastor_auxiliar=acesso["pastor_auxiliar"],
                )
                st.toast(f"Bem-vindo, {acesso['pastor_auxiliar']['nome']}!")
                st.rerun()
            else:
                st.error("Identificador, usuário ou senha incorretos, ou acesso inativo.")

    _botao_recuperar_senha("Pastor Auxiliar", "btn_esqueci_pastor_auxiliar")


@st.cache_data(ttl=120, show_spinner=False)
def _opcoes_igrejas_ativas():
    try:
        igrejas = listar_igrejas()
    except Exception:
        return {}, "Não foi possível carregar as igrejas."
    if igrejas is None or igrejas.empty:
        return {}, "Nenhuma igreja cadastrada."
    try:
        igrejas = igrejas[igrejas["ativa"].fillna(0).astype(int) == 1].copy()
    except Exception:
        igrejas = igrejas.copy()
    if igrejas.empty:
        return {}, "Nenhuma igreja ativa encontrada."
    opcoes = {
        str(row["slug"]): str(row["nome"])
        for _, row in igrejas.sort_values("nome").iterrows()
    }
    return opcoes, ""


def _opcoes_recepcao(slug):
    return _opcoes_usuarios_por_perfil(slug, "recepcao")


@st.cache_data(ttl=120, show_spinner=False)
def _opcoes_usuarios_por_perfil(slug, perfil):
    if not slug:
        return {}, "Selecione uma igreja."
    try:
        if perfil == "tesoureiro":
            usuarios = carregar_tesoureiros(slug)
            id_col = "id_tesoureiro"
        elif perfil == "pastor_auxiliar":
            usuarios = listar_pastores_auxiliares(slug, incluir_inativos=False)
            id_col = "id_pastor_auxiliar"
        elif perfil == "recepcao":
            usuarios = listar_recepcao_usuarios(slug, incluir_inativos=False)
            id_col = "id_recepcao"
        elif perfil == "secretario_geral":
            usuarios = listar_secretarios_gerais(slug, incluir_inativos=False)
            id_col = "id_secretario_geral"
        elif perfil == "ebd":
            usuarios = listar_ebd_secretarios(slug, incluir_inativos=False)
            id_col = "id_secretario"
        elif perfil == "orhafe":
            usuarios = listar_orhafe_secretarias(slug, incluir_inativas=False)
            id_col = "id_secretaria"
        elif perfil == "gfc":
            usuarios = listar_gfc_secretarias(slug, incluir_inativas=False)
            id_col = "id_secretaria"
        else:
            return {}, "Perfil de acesso inválido."
    except Exception:
        return {}, "Não foi possível carregar os usuários deste perfil."
    if usuarios is None or usuarios.empty:
        return {}, "Nenhum usuário ativo encontrado para esta igreja."
    if "situacao" in usuarios.columns:
        usuarios = usuarios[usuarios["situacao"].astype(str).str.upper() == "ATIVO"].copy()
    if usuarios.empty:
        return {}, "Nenhum usuário ativo encontrado para esta igreja."
    opcoes = {
        str(row["usuario"]).strip(): str(row["usuario"]).strip()
        for _, row in usuarios.sort_values("usuario").iterrows()
        if str(row.get("usuario", "") or "").strip()
    }
    if not opcoes:
        return {}, "Nenhum usuário ativo encontrado para esta igreja."
    return opcoes, ""


def _selectbox_igreja_login(key):
    op_igrejas, erro_igrejas = _opcoes_igrejas_ativas()
    if erro_igrejas:
        st.warning(erro_igrejas)
        return ""

    slugs = list(op_igrejas.keys())
    return st.selectbox(
        "Identificador da igreja",
        slugs,
        key=key,
        format_func=lambda slug: slug,
        help="Selecione o identificador da igreja.",
    )


def _selectbox_usuario_login(slug, perfil, label, key):
    slug = str(slug or "").strip().lower()
    op_usuarios, erro_usuarios = _opcoes_usuarios_por_perfil(slug, perfil)
    if erro_usuarios:
        st.warning(erro_usuarios)
        return ""

    usuarios = list(op_usuarios.values())
    return st.selectbox(
        label,
        usuarios,
        key=key,
        format_func=lambda usuario: usuario,
        help="Selecione o usuário cadastrado para este perfil.",
    )


def _selectbox_recepcao_usuario_login(slug):
    return _selectbox_usuario_login(
        slug,
        "recepcao",
        "Usuário da Recepção",
        f"login_recepcao_usuario_{slug or 'sem_igreja'}",
    )



@st.cache_data(ttl=120, show_spinner=False)
def _opcoes_grupos_gfc(slug):
    if not slug:
        return {}, "Selecione uma igreja."
    try:
        grupos = listar_gfc_grupos(slug, incluir_inativos=False)
    except Exception:
        return {}, "Nao foi possivel carregar os grupos GFC desta igreja."
    if grupos is None or grupos.empty:
        return {}, "Nenhum grupo GFC ativo encontrado para esta igreja."
    opcoes = {
        f'{int(row["id_grupo"])} | {row["nome"]} ({row.get("setor", "") or "Sem setor"})': {
            "id_grupo": int(row["id_grupo"]),
            "nome": str(row.get("nome", "") or ""),
            "setor": str(row.get("setor", "") or ""),
            "responsavel": str(row.get("responsavel", "") or ""),
        }
        for _, row in grupos.sort_values(["setor", "nome"]).iterrows()
    }
    return opcoes, ""


@st.cache_data(ttl=120, show_spinner=False)
def _grupo_gfc_do_usuario(slug, usuario):
    slug = str(slug or "").strip().lower()
    usuario = str(usuario or "").strip().lower()
    if not slug or not usuario:
        return None
    try:
        secretarias = listar_gfc_secretarias(slug, incluir_inativas=False)
        grupos = listar_gfc_grupos(slug, incluir_inativos=False)
    except Exception:
        return None
    if secretarias is None or secretarias.empty or grupos is None or grupos.empty:
        return None

    sec = secretarias[
        secretarias["usuario"].fillna("").astype(str).str.strip().str.lower() == usuario
    ]
    if sec.empty:
        return None

    nome_sec = str(sec.iloc[0].get("nome", "") or "").strip().lower()
    if not nome_sec:
        return None

    grupos = grupos.copy()
    grupos["responsavel_norm"] = grupos["responsavel"].fillna("").astype(str).str.strip().str.lower()
    vinculados = grupos[grupos["responsavel_norm"] == nome_sec]
    if vinculados.empty:
        return None

    row = vinculados.sort_values(["setor", "nome"]).iloc[0]
    return {
        "id_grupo": int(row["id_grupo"]),
        "nome": str(row.get("nome", "") or ""),
        "setor": str(row.get("setor", "") or ""),
        "responsavel": str(row.get("responsavel", "") or ""),
    }


def _login_recepcao():
    st.markdown("#### Acesso da Recepção")
    st.caption("Acesso restrito somente ao registro de visitantes.")

    slug = _selectbox_igreja_login("login_recepcao_igreja")
    slug_normalizado = str(slug or "").strip().lower()
    usuario = _selectbox_recepcao_usuario_login(slug_normalizado) if slug_normalizado else ""

    with st.form("form_login_recepcao"):
        senha = st.text_input(
            "PIN de 4 dígitos",
            type="password",
            autocomplete="off",
            max_chars=4,
            help="Informe o PIN de 4 dígitos cadastrado.",
        )
        if st.form_submit_button("Entrar", type="primary", use_container_width=True):
            slug = str(slug or "").strip().lower()
            usuario = str(usuario or "").strip().lower()
            senha = "".join(c for c in str(senha or "") if c.isdigit())
            if not slug or not usuario or not senha:
                st.error("Preencha todos os campos.")
                return
            if len(senha) != 4:
                st.error("Informe exatamente os 4 dígitos do PIN.")
                return
            acesso = autenticar_recepcao(slug, usuario, senha)
            if acesso:
                _iniciar_sessao(
                    "recepcao",
                    igreja=acesso["igreja"],
                    recepcao=acesso["recepcao"],
                )
                st.toast(f"Bem-vindo, {acesso['recepcao']['nome']}!")
                st.rerun()
            else:
                st.error("Identificador, usuário ou PIN incorretos, ou acesso inativo.")

    _botao_recuperar_senha("Recepcao", "btn_esqueci_recepcao")


def _login_secretario_geral():
    st.markdown("#### Acesso do Secretário Geral")
    st.caption("Acesso restrito a membros, aniversários e chamada de obreiros.")
    slug = _selectbox_igreja_login("login_secretario_geral_igreja")
    usuario = _selectbox_usuario_login(
        slug,
        "secretario_geral",
        "Usuário do Secretário Geral",
        f"login_secretario_geral_usuario_{slug or 'sem_igreja'}",
    )

    with st.form("form_login_secretario_geral"):
        senha = st.text_input("Senha", type="password", autocomplete="off")
        if st.form_submit_button("Entrar", type="primary", use_container_width=True):
            slug = str(slug or "").strip().lower()
            usuario = str(usuario or "").strip().lower()
            if not slug or not usuario or not senha:
                st.error("Preencha todos os campos.")
                return
            acesso = autenticar_secretario_geral(slug, usuario, senha)
            if acesso:
                _iniciar_sessao(
                    "secretario_geral",
                    igreja=acesso["igreja"],
                    secretario_geral=acesso["secretario_geral"],
                )
                st.toast(f"Bem-vindo, {acesso['secretario_geral']['nome']}!")
                st.rerun()
            else:
                st.error("Identificador, usuário ou senha incorretos, ou acesso inativo.")

    _botao_recuperar_senha("Secretario Geral", "btn_esqueci_secretario_geral")


def _login_ebd():
    st.markdown("#### Acesso da Escola Bíblica")
    st.caption("Secretário de classe acessa somente chamada. Secretário geral acessa todo o módulo Escola Bíblica.")
    slug = _selectbox_igreja_login("login_ebd_igreja")
    usuario = _selectbox_usuario_login(
        slug,
        "ebd",
        "Usuário da Escola Bíblica",
        f"login_ebd_usuario_{slug or 'sem_igreja'}",
    )

    with st.form("form_login_ebd"):
        senha = st.text_input("PIN de 4 dígitos", type="password", max_chars=4, autocomplete="off")
        if st.form_submit_button("Entrar", type="primary", use_container_width=True):
            slug = str(slug or "").strip().lower()
            usuario = str(usuario or "").strip().lower()
            if not slug or not usuario or not senha:
                st.error("Preencha todos os campos.")
                return
            acesso = autenticar_ebd_secretario(slug, usuario, senha)
            if acesso:
                _iniciar_sessao(
                    "secretario_ebd",
                    igreja=acesso["igreja"],
                    secretario_ebd=acesso["secretario_ebd"],
                )
                st.toast(f"Bem-vindo, {acesso['secretario_ebd']['nome']}!")
                st.rerun()
            else:
                st.error("Identificador, usuário ou PIN incorretos, ou acesso inativo.")

    _botao_recuperar_senha("Escola Biblica", "btn_esqueci_ebd")


def _login_orhafe():
    st.markdown("#### Acesso do Círculo de Oração")
    st.caption("Secretária de chamada acessa somente a chamada. Secretária geral acessa todo o módulo Círculo de Oração.")
    slug = _selectbox_igreja_login("login_orhafe_igreja")
    usuario = _selectbox_usuario_login(
        slug,
        "orhafe",
        "Usuário do Círculo de Oração",
        f"login_orhafe_usuario_{slug or 'sem_igreja'}",
    )

    with st.form("form_login_orhafe"):
        cpf4 = st.text_input(
            "4 últimos dígitos do CPF",
            type="password",
            autocomplete="off",
            max_chars=4,
            help="Informe os 4 últimos dígitos do CPF cadastrado para esta secretária.",
        )
        if st.form_submit_button("Entrar", type="primary", use_container_width=True):
            slug = str(slug or "").strip().lower()
            usuario = str(usuario or "").strip().lower()
            cpf4 = "".join(c for c in str(cpf4 or "") if c.isdigit())
            if not slug or not usuario or not cpf4:
                st.error("Preencha todos os campos.")
                return
            if len(cpf4) != 4:
                st.error("Informe exatamente os 4 últimos dígitos do CPF.")
                return
            acesso = autenticar_orhafe_secretaria_por_cpf4(slug, usuario, cpf4)
            if acesso:
                _iniciar_sessao(
                    "secretaria_orhafe",
                    igreja=acesso["igreja"],
                    secretaria_orhafe=acesso["secretaria_orhafe"],
                )
                st.toast(f"Bem-vinda, {acesso['secretaria_orhafe']['nome']}!")
                st.rerun()
            else:
                st.error("Identificador, usuário ou CPF incorretos, ou acesso inativo.")

    _botao_recuperar_senha("Circulo de Oracao", "btn_esqueci_orhafe")


def _login_gfc():
    st.markdown("#### Acesso GFC")
    st.caption("Secretaria de chamada acessa os registros. Secretaria geral acessa todo o modulo GFC.")
    slug = _selectbox_igreja_login("login_gfc_igreja")
    usuario = _selectbox_usuario_login(
        slug,
        "gfc",
        "Usuario do GFC",
        f"login_gfc_usuario_{slug or 'sem_igreja'}",
    )
    slug_normalizado = str(slug or "").strip().lower()
    op_grupos, erro_grupos = _opcoes_grupos_gfc(slug_normalizado)
    grupo_sel = ""
    grupo_dados = _grupo_gfc_do_usuario(slug_normalizado, usuario)
    if erro_grupos:
        st.warning(erro_grupos)
    elif grupo_dados:
        grupo_sel = (
            f'{grupo_dados["id_grupo"]} | {grupo_dados["nome"]} '
            f'({grupo_dados["setor"] or "Sem setor"})'
        )
        st.text_input(
            "Grupo familiar de atuação",
            value=grupo_sel,
            disabled=True,
            key=f"login_gfc_grupo_auto_{slug_normalizado or 'sem_igreja'}",
            help="Grupo preenchido automaticamente pelo lider vinculado ao grupo.",
        )
    else:
        st.caption("Nao foi encontrado grupo vinculado automaticamente a esta secretaria. Selecione o grupo manualmente.")
        grupo_sel = st.selectbox(
            "Grupo familiar de atuação",
            list(op_grupos.keys()),
            key=f"login_gfc_grupo_{slug_normalizado or 'sem_igreja'}",
            help="Selecione o grupo familiar em que esta secretaria atuara.",
        )
        grupo_dados = op_grupos.get(grupo_sel)

    with st.form("form_login_gfc"):
        cpf4 = st.text_input(
            "PIN - 4 ultimos digitos do CPF",
            type="password",
            autocomplete="off",
            max_chars=4,
            help="Informe os 4 ultimos digitos do CPF do membro vinculado a esta secretaria.",
        )
        if st.form_submit_button("Entrar", type="primary", use_container_width=True):
            slug = str(slug or "").strip().lower()
            usuario = str(usuario or "").strip().lower()
            cpf4 = "".join(c for c in str(cpf4 or "") if c.isdigit())
            if not slug or not usuario or not cpf4 or not grupo_dados:
                st.error("Preencha todos os campos.")
                return
            if len(cpf4) != 4:
                st.error("Informe exatamente os 4 ultimos digitos do CPF.")
                return
            acesso = autenticar_gfc_secretaria_por_cpf4(slug, usuario, cpf4)
            if acesso:
                acesso["secretaria_gfc"]["id_grupo"] = grupo_dados["id_grupo"]
                acesso["secretaria_gfc"]["grupo"] = grupo_dados["nome"]
                acesso["secretaria_gfc"]["setor_grupo"] = grupo_dados["setor"]
                _iniciar_sessao(
                    "secretaria_gfc",
                    igreja=acesso["igreja"],
                    secretaria_gfc=acesso["secretaria_gfc"],
                )
                st.toast(f"Bem-vinda, {acesso['secretaria_gfc']['nome']}!")
                st.rerun()
            else:
                st.error("Identificador, usuario ou CPF incorretos, ou acesso inativo.")

    _botao_recuperar_senha("GFC", "btn_esqueci_gfc")


def logout():
    _remover_sessao_cookie()
    _limpar_sessao()
    st.rerun()


def exigir_autenticacao() -> bool:
    return st.session_state.get("autenticado", False)


def modo_atual() -> str:
    return st.session_state.get("modo", "")


