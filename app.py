"""
FielMordomo - ponto de entrada da aplicação Streamlit.

Mantém as rotas públicas separadas da área autenticada e carrega os módulos
internos sob demanda para isolar falhas de telas secundarias.

MODIFICADO: adiciona bypass de login para acesso via link de auto-checkin
(?ck=<slug>_<token>).
"""

import base64
import html
import importlib
import logging
import os
import sys
import unicodedata
from urllib.parse import urlsplit

import streamlit as st


LOGGER = logging.getLogger(__name__)
DOMINIO_OFICIAL = "https://fielmordomo.com.br"
DOMINIOS_PERMITIDOS_PADRAO = {
    "fielmordomo.com.br",
    "www.fielmordomo.com.br",
    "localhost",
    "127.0.0.1",
    "0.0.0.0",
    "::1",
}
PAGINAS_INSTITUCIONAIS = {
    "", "inicio", "sobre", "recursos", "contato", "privacidade", "termos",
    "atualizar-cadastro", "pedidos-oracao", "agenda", "leitura-biblica",
}
ROTA_LOGIN = "login"
TAMANHO_MAXIMO_LOGO = 5 * 1024 * 1024
MIMES_LOGO = {
    "png": "image/png",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "webp": "image/webp",
}
PAGINAS_IGREJA = {
    "home": ("Início", "modules.home"),
    "cadastros": ("Membros", "modules.cadastros"),
    "lancamentos": ("Lançamentos", "modules.lancamentos"),
    "relatorios": ("Relatórios", "modules.relatorios"),
    "dashboard": ("Dashboard", "modules.dashboard"),
    "geo_frequencia": ("Monitoramento Geo", "modules.geo_frequencia"),
    "ebd": ("Escola Bíblica", "modules.ebd"),
    "gfc": ("Grupos Familiares", "modules.gfc"),
    "orhafe": ("Círculo de Oração", "modules.orhafe"),
    "obreiros": ("Reunião de Obreiros", "modules.obreiros"),
    "eventos": ("Agenda", "modules.eventos"),
    "visitantes": ("Visitantes", "modules.visitantes"),
    "pedidos_oracao": ("Pedidos de Oração", "modules.pedidos_oracao"),
    "tesoureiros": ("Tesoureiros", "modules.tesoureiros"),
    "aniversariantes": ("Aniversários", "modules.aniversariantes"),
    "backup": ("Backup", "modules.backup"),
    "minha_conta": ("Minha conta", "modules.minha_conta"),
}
PAGINAS_TESOUREIRO = {
    "lancamentos": ("Lançamentos", "modules.lancamentos"),
    "cadastros": ("Membros", "modules.cadastros"),
    "relatorios": ("Relatórios", "modules.relatorios"),
}
PAGINAS_PASTOR_AUXILIAR = {
    "visitantes": ("Visitantes", "modules.visitantes"),
    "pedidos_oracao": ("Pedidos de Oração", "modules.pedidos_oracao"),
    "dashboard": ("Dashboard", "modules.dashboard"),
    "ebd": ("Relatórios Escola Bíblica", "modules.ebd"),
    "orhafe": ("Relatórios Círculo de Oração", "modules.orhafe"),
    "aniversariantes": ("Aniversários", "modules.aniversariantes"),
}
PAGINAS_RECEPCAO = {
    "visitantes": ("Visitantes", "modules.visitantes"),
}
PAGINAS_SECRETARIO_GERAL = {
    "cadastros": ("Membros", "modules.cadastros"),
    "obreiros": ("Chamada de Obreiros", "modules.obreiros"),
    "aniversariantes": ("Aniversários", "modules.aniversariantes"),
}
PAGINAS_EBD = {
    "ebd": ("Escola Bíblica", "modules.ebd"),
}
PAGINAS_LIBERAVEIS = {
    chave: valor
    for chave, valor in PAGINAS_IGREJA.items()
    if chave not in {"home", "backup", "minha_conta", "tesoureiros"}
}

# ═══════════════════════════════════════════════════════════════════════
# NOVO: Icones e agrupamento visual do menu lateral
# ═══════════════════════════════════════════════════════════════════════

ICONES_MENU = {
    "home": "🏠",
    "cadastros": "👥",
    "lancamentos": "💰",
    "relatorios": "📈",
    "dashboard": "📊",
    "geo_frequencia": "📍",
    "ebd": "📚",
    "gfc": "👨‍👩‍👧",
    "orhafe": "🙏",
    "obreiros": "⛪",
    "eventos": "📅",
    "visitantes": "🤝",
    "pedidos_oracao": "🕊️",
    "tesoureiros": "💼",
    "aniversariantes": "🎂",
    "backup": "💾",
    "minha_conta": "👤",
}

# Agrupamento visual da sidebar da igreja (ordem controlada)
# Cada tupla: (titulo_grupo, cor_do_grupo, lista_de_chaves)
GRUPOS_MENU_IGREJA = [
    ("Financeiro", "#10B981", ["lancamentos", "dashboard", "relatorios", "tesoureiros"]),
    ("Cadastros", "#3B82F6", ["cadastros", "visitantes", "aniversariantes"]),
    ("Ministerio", "#8B5CF6", ["ebd", "gfc", "orhafe", "obreiros", "pedidos_oracao"]),
    ("Eventos", "#F59E0B", ["eventos", "geo_frequencia"]),
    ("Sistema", "#6B7280", ["backup", "minha_conta"]),
]

# ═══════════════════════════════════════════════════════════════════════
# NOVO: Modulos onde procurar a implementacao de auto-checkin.
# Tenta cada um em ordem, ate encontrar. O nome oficial e geo_frequencia
# (registrado em PAGINAS_IGREJA); monitoramento_geo e mantido como
# fallback legado.
# ═══════════════════════════════════════════════════════════════════════
MODULOS_AUTO_CHECKIN = (
    "modules.geo_frequencia",
    "modules.monitoramento_geo",
)


_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)


APP_PAGE_TITLE = "FielMordomo - Gestão Financeira para Igrejas"
APP_PAGE_ICON_PATHS = (
    os.path.join(_HERE, "assets", "logo.png"),
    os.path.join(_HERE, "assets", "favicon.png"),
)


def _carregar_page_icon():
    """Carrega o logo usado como ícone da aba do navegador."""
    for caminho in APP_PAGE_ICON_PATHS:
        try:
            with open(caminho, "rb") as arquivo:
                return arquivo.read()
        except OSError:
            continue

    # Fallback caso os arquivos ainda não tenham sido enviados ao servidor.
    return "💰"


st.set_page_config(
    page_title=APP_PAGE_TITLE,
    page_icon=_carregar_page_icon(),
    layout="wide",
    initial_sidebar_state="expanded",
)


def _importar(caminho):
    return importlib.import_module(caminho)


def _repository():
    return _importar("data.repository")


def _auth():
    return _importar("modules.auth")


def _validar_contrato_auth(auth):
    funcoes_obrigatorias = ("tela_login", "modo_atual", "logout")
    ausentes = [
        nome for nome in funcoes_obrigatorias
        if not callable(getattr(auth, nome, None))
    ]
    if not ausentes:
        return
    LOGGER.error(
        "Modulo modules.auth incompativel. Funcoes ausentes: %s.",
        ", ".join(ausentes),
    )
    st.error(
        "A atualizacao do sistema esta incompleta. "
        "Publique tambem o arquivo modules/auth.py atualizado."
    )
    st.stop()


def _dominios_permitidos():
    adicionais = {
        host.strip().lower()
        for host in os.environ.get("FIELMORDOMO_ALLOWED_HOSTS", "").split(",")
        if host.strip()
    }
    return DOMINIOS_PERMITIDOS_PADRAO | adicionais


def _host_atual():
    try:
        bruto = st.context.headers.get("host", "")
    except Exception:
        bruto = ""
    bruto = str(bruto or "").split(",", 1)[0].strip()
    if not bruto or any(c in bruto for c in "\r\n"):
        return ""
    try:
        return str(urlsplit(f"//{bruto}").hostname or "").strip().lower()
    except ValueError:
        return ""


def _bloquear_acesso_fora_do_dominio_oficial():
    """
    Camada complementar de apresentacao.

    A restricao efetiva de hosts deve ser configurada no proxy reverso ou no
    provedor de hospedagem, antes que a requisicao alcance o Streamlit.
    """
    host = _host_atual()
    if not host:
        return
    if host in _dominios_permitidos():
        return
    host_html = html.escape(host, quote=True)
    st.markdown(
        f"""
        <div style="max-width:720px;margin:80px auto;padding:32px;border:1px solid #ddd;
                    border-radius:14px;text-align:center;font-family:Arial,sans-serif;">
            <h2 style="margin-bottom:10px;color:#061B44;">Acesso restrito</h2>
            <p style="font-size:1rem;color:#333;line-height:1.5;">
                O FielMordomo deve ser acessado somente pelo dominio oficial.
            </p>
            <p style="margin-top:18px;">
                <a href="{DOMINIO_OFICIAL}" target="_self"
                   style="display:inline-block;background:#061B44;color:white;text-decoration:none;
                          padding:12px 22px;border-radius:8px;font-weight:700;">
                    Abrir FielMordomo
                </a>
            </p>
            <p style="margin-top:16px;color:#777;font-size:0.85rem;">
                Dominio detectado: {host_html}
            </p>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.stop()


# ═══════════════════════════════════════════════════════════════════════
# NOVO: Deteccao e renderizacao do auto-checkin via link personalizado
# ═══════════════════════════════════════════════════════════════════════

def _rota_auto_checkin():
    """
    Retorna (slug, token) se a URL contem ?ck=<slug>_<token>, senao None.

    O parametro ck permite acesso publico direto a pagina de auto-checkin,
    sem exigir login. O slug identifica o tenant e o token e verificado
    contra a tabela geo_checkin_tokens (uso unico).
    """
    valor = st.query_params.get("ck", "")
    if isinstance(valor, list):
        valor = valor[0] if valor else ""
    valor = str(valor or "").strip()

    if not valor or "_" not in valor:
        return None

    partes = valor.split("_", 1)
    if len(partes) != 2:
        return None

    slug = str(partes[0] or "").strip().lower()
    token = str(partes[1] or "").strip()

    # Validacoes basicas de sanidade
    if not slug or not token:
        return None
    # Slug e alfanumerico + hifens/underscores
    if not all(c.isalnum() or c in "-_" for c in slug):
        return None
    # Token e hex
    if not all(c in "0123456789abcdefABCDEF" for c in token):
        return None
    if len(token) < 8 or len(token) > 64:
        return None

    return slug, token


def _importar_modulo_checkin():
    """
    Importa o modulo de auto-checkin, tentando os nomes conhecidos.
    Retorna o modulo ou None se nao encontrado.
    """
    for nome in MODULOS_AUTO_CHECKIN:
        try:
            return _importar(nome)
        except ImportError:
            continue
        except Exception:
            LOGGER.exception("Erro ao importar %s.", nome)
            continue
    return None


def _renderizar_auto_checkin():
    """
    Renderiza a pagina de auto-checkin publica (sem login).

    Aplica um layout minimalista:
    - Sem sidebar
    - Sem menu de navegacao
    - Container centralizado e compacto (adequado para mobile)

    O modulo de destino le o parametro ?ck= diretamente do query_params
    e faz sua propria logica de renderizacao.
    """
    # CSS minimalista para link publico (sem sidebar, layout centrado)
    st.markdown(
        """
        <meta name="google" content="notranslate">
        <meta name="translate" content="no">
        <style>
        header[data-testid="stHeader"] { display: none !important; }
        section[data-testid="stSidebar"] { display: none !important; }
        [data-testid="stSidebarCollapsedControl"] { display: none !important; }
        #MainMenu, footer { display: none !important; }
        [data-testid="stStatusWidget"] { display: none !important; }
        .block-container {
            padding-top: 1.5rem !important;
            padding-left: 1rem !important;
            padding-right: 1rem !important;
            max-width: 720px !important;
            margin: 0 auto !important;
        }
        html, body, .stApp { background: #F9FAFB; }
        </style>
        """,
        unsafe_allow_html=True,
    )

    modulo = _importar_modulo_checkin()

    if modulo is None:
        st.error(
            "⚠️ Modulo de auto-checkin nao encontrado no servidor. "
            "Contate o administrador do sistema."
        )
        st.markdown(
            f'<p style="text-align:center;margin-top:20px;">'
            f'<a href="{DOMINIO_OFICIAL}" style="color:#0F6E56;">Voltar para o site</a>'
            f'</p>',
            unsafe_allow_html=True,
        )
        return

    try:
        modulo.render()
    except Exception as ex:
        LOGGER.exception("Falha ao renderizar auto-checkin.")
        st.error(
            "❌ Nao foi possivel processar o link de check-in. "
            f"(Erro: {type(ex).__name__})"
        )
        st.markdown(
            f'<p style="text-align:center;margin-top:20px;">'
            f'<a href="{DOMINIO_OFICIAL}" style="color:#0F6E56;">Voltar para o site</a>'
            f'</p>',
            unsafe_allow_html=True,
        )


# ═══════════════════════════════════════════════════════════════════════
# Rotas publicas normais (institucional / login)
# ═══════════════════════════════════════════════════════════════════════

def _pagina_publica_atual():
    pagina = st.query_params.get("pagina", "inicio")
    if isinstance(pagina, list):
        pagina = pagina[0] if pagina else "inicio"
    return str(pagina or "inicio").strip().lower()


def _resolver_rota_publica():
    pagina = _pagina_publica_atual()
    if pagina in PAGINAS_INSTITUCIONAIS:
        _importar("modules.institucional").render_institucional()
        st.stop()
    if pagina == ROTA_LOGIN:
        return
    st.error("Página não encontrada.")
    st.markdown('[Voltar para o início](?pagina=inicio)')
    st.stop()


def _esc(valor):
    return html.escape(str(valor if valor is not None else ""), quote=True)


def _chave_ordenacao_menu(item):
    _chave, (rotulo, _modulo) = item
    texto = unicodedata.normalize("NFKD", str(rotulo or ""))
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    return texto.casefold()


def _paginas_ordenadas(paginas):
    return sorted(paginas.items(), key=_chave_ordenacao_menu)


def _rotulo_menu(chave, rotulo):
    """Concatena icone + rotulo. Icone vem de ICONES_MENU."""
    icone = ICONES_MENU.get(chave, "")
    return f"{icone}  {rotulo}" if icone else rotulo


def _botao_inicio_sidebar(key, pagina_destino):
    # Icone da pagina destino (fallback casa se nao encontrado)
    icone = ICONES_MENU.get(pagina_destino, "🏠")
    rotulo_inicio = f"{icone}  Inicio"
    if st.button(
        rotulo_inicio,
        key=key,
        use_container_width=True,
        type="primary" if st.session_state.get("pagina") == pagina_destino else "secondary",
    ):
        st.session_state["pagina"] = pagina_destino
        st.rerun()


def _injetar_css():
    st.markdown(
        """
        <meta name="google" content="notranslate">
        <meta name="translate" content="no">
        <style>
        html,body,.stApp,[data-testid="stAppViewContainer"] {
            -webkit-locale:"pt-BR";
        }
        .stApp,[data-testid="stAppViewContainer"],
        section[data-testid="stSidebar"],
        [data-testid="stSidebarContent"],
        [data-testid="stMarkdownContainer"],
        label,button,input,textarea,select {
            translate:no;
        }
        .notranslate { translate:no; }
        header[data-testid="stHeader"] {background:transparent!important;height:3rem!important}
        #MainMenu,footer {display:none!important}
        [data-testid="stStatusWidget"] {display:none!important}
        [data-testid="stSidebarCollapsedControl"] {display:flex!important;visibility:visible!important;
            opacity:1!important;position:fixed!important;top:12px!important;left:12px!important;
            z-index:999999!important;background:#061B44!important;border-radius:10px!important;
            padding:6px!important;box-shadow:0 2px 10px rgba(0,0,0,.30)!important}
        [data-testid="stSidebarCollapsedControl"] button,
        [data-testid="stSidebarCollapsedControl"] svg {color:white!important;fill:white!important}
        button[kind="header"] {color:white!important;background:#061B44!important;border-radius:10px!important}
        button[kind="header"] svg {color:white!important;fill:white!important}
        section[data-testid="stSidebar"] {background:linear-gradient(180deg,#061B44 0%,#0A0A0A 100%)!important}
        section[data-testid="stSidebar"] * {color:white!important}
        section[data-testid="stSidebar"] .stButton button {width:100%;background:transparent!important;
            border:none!important;color:rgba(255,255,255,.92)!important;text-align:left!important;
            padding:10px 14px!important;font-size:.85rem!important;font-weight:600!important;
            letter-spacing:.05em!important;text-transform:uppercase!important;
            border-radius:8px!important;margin-bottom:2px!important;transition:.2s;
            justify-content:flex-start!important;display:flex!important}
        section[data-testid="stSidebar"] .stButton button p,
        section[data-testid="stSidebar"] .stButton button div,
        section[data-testid="stSidebar"] .stButton button span {
            text-align:left!important;text-transform:uppercase!important;
            letter-spacing:.05em!important;width:100%!important}
        section[data-testid="stSidebar"] .stButton button:hover {background:rgba(212,175,55,.18)!important;
            color:#D4AF37!important}
        section[data-testid="stSidebar"] .stButton button[kind="primary"] {
            background:rgba(212,175,55,.25)!important;color:#D4AF37!important;font-weight:800!important;
            border-left:3px solid #D4AF37!important;text-align:left!important;
            justify-content:flex-start!important}
        section[data-testid="stSidebar"] .stButton button[kind="primary"] p,
        section[data-testid="stSidebar"] .stButton button[kind="primary"] div,
        section[data-testid="stSidebar"] .stButton button[kind="primary"] span {
            text-align:left!important;text-transform:uppercase!important}
        .sidebar-grupo {
            font-size:.68rem!important;
            color:rgba(212,175,55,.72)!important;
            text-transform:uppercase!important;
            letter-spacing:.14em!important;
            font-weight:700!important;
            margin:16px 4px 6px 8px!important;
            padding:4px 0 4px 10px!important;
            border-left:3px solid var(--grupo-cor, rgba(212,175,55,.5))!important;
            line-height:1.2!important}
        .sidebar-grupo-espaco {height:4px}
        .sidebar-logo {text-align:center;padding:10px 0 16px;border-bottom:1px solid rgba(212,175,55,.35);
            margin-bottom:14px}
        .sidebar-logo img {max-width:140px;max-height:90px;object-fit:contain}
        .sidebar-info {text-align:center;font-size:.78rem;color:rgba(255,255,255,.85)!important;
            margin:0 0 14px;padding:0 6px}
        .sidebar-info b {color:#D4AF37!important}
        .sidebar-info .plano {font-size:.68rem;color:rgba(255,255,255,.65)!important;margin-top:2px}
        .block-container {padding-top:3.5rem!important;padding-left:2rem!important;
            padding-right:2rem!important;max-width:100%!important}
        /* Responsivo mobile */
        @media (max-width: 768px) {
            section[data-testid="stSidebar"] .stButton button {
                font-size:.78rem!important;
                padding:9px 12px!important;
                letter-spacing:.03em!important}
            .sidebar-grupo {
                font-size:.62rem!important;
                margin:12px 2px 4px 6px!important;
                letter-spacing:.10em!important}
            .sidebar-logo img {max-width:110px;max-height:70px}
            .sidebar-info {font-size:.72rem}
            .block-container {padding-left:1rem!important;padding-right:1rem!important}
        }
        </style>
        <script>
        (function () {
            const root = window.parent && window.parent.document
                ? window.parent.document
                : document;
            root.documentElement.setAttribute("lang", "pt-BR");
            root.documentElement.setAttribute("translate", "no");
            root.body && root.body.setAttribute("translate", "no");
            root.body && root.body.classList.add("notranslate");
        })();
        </script>
        """,
        unsafe_allow_html=True,
    )


def _img_b64(dados, extensao):
    extensao = str(extensao or "").strip().lower().replace(".", "")
    mime = MIMES_LOGO.get(extensao)
    if not mime:
        raise ValueError("Formato de logo não permitido.")
    if not isinstance(dados, (bytes, bytearray, memoryview)):
        raise TypeError("Logo inválido.")
    dados = bytes(dados)
    if not dados or len(dados) > TAMANHO_MAXIMO_LOGO:
        raise ValueError("Logo inválido ou maior que 5 MB.")
    return f"data:{mime};base64,{base64.b64encode(dados).decode('ascii')}"


def _logo_sidebar(slug=None):
    repo = _repository()
    if slug:
        return (
            repo.obter_logo_sidebar_igreja(slug)
            or repo.obter_logo_sidebar_sistema()
            or repo.obter_logo_igreja(slug)
            or repo.obter_logo_sistema()
        )
    return repo.obter_logo_sidebar_sistema() or repo.obter_logo_sistema()


def _render_logo_sidebar(slug=None):
    try:
        logo = _logo_sidebar(slug)
        if logo:
            dados, extensao = logo
            src = _img_b64(dados, extensao)
            st.markdown(
                f'<div class="sidebar-logo"><img src="{src}" alt="FielMordomo"></div>',
                unsafe_allow_html=True,
            )
            return
    except Exception:
        LOGGER.exception("Não foi possível renderizar o logo da sidebar.")
    st.markdown(
        '<div class="sidebar-logo" style="font-size:1.4rem;font-weight:700;color:white">'
        "FielMordomo</div>",
        unsafe_allow_html=True,
    )


def _paginas_com_permissoes(paginas_base, tipo_login, usuario):
    paginas = dict(paginas_base)
    try:
        igreja = st.session_state.get("igreja", {})
        slug = igreja.get("slug", "") if isinstance(igreja, dict) else ""
        id_usuario = usuario.get("id") if isinstance(usuario, dict) else None
        if not slug or not id_usuario:
            return paginas
        extras = _repository().obter_permissoes_usuario(slug, tipo_login, id_usuario)
        for modulo in extras:
            if modulo in PAGINAS_LIBERAVEIS:
                paginas[modulo] = PAGINAS_LIBERAVEIS[modulo]
    except Exception:
        LOGGER.exception("Falha ao carregar permissões extras do usuário.")
    return paginas


def _sidebar_igreja(pagina_atual, igreja):
    with st.sidebar:
        _render_logo_sidebar(igreja.get("slug", ""))
        st.markdown(
            '<div class="sidebar-info">'
            f'<b>{_esc(igreja.get("nome", "FielMordomo"))}</b>'
            f'<div class="plano">Plano {_esc(str(igreja.get("plano", "")).capitalize())}</div>'
            "</div>",
            unsafe_allow_html=True,
        )

        # Botao "Inicio" destacado no topo
        if st.button(
            _rotulo_menu("home", "Inicio"),
            key="sb_inicio_igreja",
            use_container_width=True,
            type="primary" if pagina_atual == "home" else "secondary",
        ):
            st.session_state["pagina"] = "home"
            st.rerun()

        # Renderiza cada grupo com seu titulo colorido
        chaves_ja_renderizadas = {"home"}
        for titulo_grupo, cor_grupo, chaves in GRUPOS_MENU_IGREJA:
            # Filtra apenas as chaves que existem em PAGINAS_IGREJA
            chaves_validas = [c for c in chaves if c in PAGINAS_IGREJA]
            if not chaves_validas:
                continue

            # Titulo do grupo com cor especifica
            st.markdown(
                f'<div class="sidebar-grupo" style="--grupo-cor:{cor_grupo}">'
                f'{_esc(titulo_grupo)}</div>',
                unsafe_allow_html=True,
            )

            # Ordena alfabeticamente dentro do grupo
            chaves_ordenadas = sorted(
                chaves_validas,
                key=lambda c: _chave_ordenacao_menu((c, PAGINAS_IGREJA[c])),
            )

            for chave in chaves_ordenadas:
                rotulo, _ = PAGINAS_IGREJA[chave]
                chaves_ja_renderizadas.add(chave)
                if st.button(
                    _rotulo_menu(chave, rotulo),
                    key=f"sb_{chave}",
                    use_container_width=True,
                    type="primary" if pagina_atual == chave else "secondary",
                ):
                    st.session_state["pagina"] = chave
                    st.rerun()

        # Renderiza qualquer chave "orfa" que nao esteja em nenhum grupo
        # (fallback para compatibilidade com futuros modulos)
        chaves_orfas = [
            c for c in PAGINAS_IGREJA.keys() if c not in chaves_ja_renderizadas
        ]
        if chaves_orfas:
            st.markdown(
                '<div class="sidebar-grupo" style="--grupo-cor:#D4AF37">Outros</div>',
                unsafe_allow_html=True,
            )
            for chave in sorted(chaves_orfas, key=lambda c: _chave_ordenacao_menu(
                (c, PAGINAS_IGREJA[c])
            )):
                rotulo, _ = PAGINAS_IGREJA[chave]
                if st.button(
                    _rotulo_menu(chave, rotulo),
                    key=f"sb_orfa_{chave}",
                    use_container_width=True,
                    type="primary" if pagina_atual == chave else "secondary",
                ):
                    st.session_state["pagina"] = chave
                    st.rerun()

        st.divider()
        if st.button("🚪  Sair", key="sb_sair", use_container_width=True):
            _auth().logout()


def _sidebar_admin():
    with st.sidebar:
        _render_logo_sidebar()
        st.markdown(
            '<div class="sidebar-info"><b>Administrador</b>'
            '<div class="plano">Painel do sistema</div></div>',
            unsafe_allow_html=True,
        )
        st.button("🏠  Inicio", key="sb_inicio_admin", use_container_width=True, type="primary")
        st.divider()
        if st.button("🚪  Sair", key="sb_sair_admin", use_container_width=True):
            _auth().logout()


def _sidebar_perfil_simples(
    pagina_atual, igreja, usuario, *,
    tipo_login, paginas_base, pagina_inicio,
    nome_padrao, subtitulo, key_prefix,
):
    """Sidebar padrao para perfis com lista plana de paginas (sem grupos):
    tesoureiro, secretarios de ministerio, pastor auxiliar e recepcao."""
    with st.sidebar:
        _render_logo_sidebar(igreja.get("slug", ""))
        st.markdown(
            '<div class="sidebar-info">'
            f'<b>{_esc(usuario.get("nome", nome_padrao))}</b>'
            f'<div class="plano">{_esc(subtitulo)}</div>'
            "</div>",
            unsafe_allow_html=True,
        )
        paginas = _paginas_com_permissoes(paginas_base, tipo_login, usuario)
        _botao_inicio_sidebar(f"{key_prefix}_inicio", pagina_inicio)
        for chave, (rotulo, _) in _paginas_ordenadas(paginas):
            if chave == pagina_inicio:
                continue
            if st.button(
                _rotulo_menu(chave, rotulo),
                key=f"{key_prefix}_{chave}",
                use_container_width=True,
                type="primary" if pagina_atual == chave else "secondary",
            ):
                st.session_state["pagina"] = chave
                st.rerun()
        st.divider()
        if st.button("🚪  Sair", key=f"{key_prefix}_sair", use_container_width=True):
            _auth().logout()


def _sidebar_tesoureiro(pagina_atual, igreja, tesoureiro):
    _sidebar_perfil_simples(
        pagina_atual, igreja, tesoureiro,
        tipo_login="tesoureiro",
        paginas_base=PAGINAS_TESOUREIRO,
        pagina_inicio="lancamentos",
        nome_padrao="Tesoureiro",
        subtitulo="Acesso restrito operacional",
        key_prefix="sb_tesoureiro",
    )


def _sidebar_secretario_ebd(pagina_atual, igreja, secretario):
    perfil = "Secretário geral" if secretario.get("perfil") == "geral" else "Secretário de classe"
    classe = secretario.get("classe") or "Escola Bíblica"
    _sidebar_perfil_simples(
        pagina_atual, igreja, secretario,
        tipo_login="secretario_ebd",
        paginas_base=PAGINAS_EBD,
        pagina_inicio="ebd",
        nome_padrao="Secretário Escola Bíblica",
        subtitulo=f"{perfil} - {classe}",
        key_prefix="sb_secretario_ebd",
    )


def _sidebar_secretaria_orhafe(pagina_atual, igreja, secretaria):
    perfil = "Secretaria geral" if secretaria.get("perfil") == "geral" else "Secretaria de chamada"
    _sidebar_perfil_simples(
        pagina_atual, igreja, secretaria,
        tipo_login="secretaria_orhafe",
        paginas_base={"orhafe": PAGINAS_IGREJA["orhafe"]},
        pagina_inicio="orhafe",
        nome_padrao="Secretaria Círculo de Oração",
        subtitulo=f"{perfil} - Círculo de Oração",
        key_prefix="sb_secretaria_orhafe",
    )


def _sidebar_secretaria_gfc(pagina_atual, igreja, secretaria):
    perfil = "Secretaria geral" if secretaria.get("perfil") == "geral" else "Secretaria de chamada"
    _sidebar_perfil_simples(
        pagina_atual, igreja, secretaria,
        tipo_login="secretaria_gfc",
        paginas_base={"gfc": PAGINAS_IGREJA["gfc"]},
        pagina_inicio="gfc",
        nome_padrao="Secretaria de Grupos Familiares",
        subtitulo=f"{perfil} - Grupos Familiares",
        key_prefix="sb_secretaria_gfc",
    )


def _sidebar_pastor_auxiliar(pagina_atual, igreja, pastor):
    _sidebar_perfil_simples(
        pagina_atual, igreja, pastor,
        tipo_login="pastor_auxiliar",
        paginas_base=PAGINAS_PASTOR_AUXILIAR,
        pagina_inicio="visitantes",
        nome_padrao="Pastor Auxiliar",
        subtitulo="Acesso restrito pastoral",
        key_prefix="sb_pastor_auxiliar",
    )


def _sidebar_recepcao(pagina_atual, igreja, recepcao):
    _sidebar_perfil_simples(
        pagina_atual, igreja, recepcao,
        tipo_login="recepcao",
        paginas_base=PAGINAS_RECEPCAO,
        pagina_inicio="visitantes",
        nome_padrao="Recepção",
        subtitulo="Acesso restrito a visitantes",
        key_prefix="sb_recepcao",
    )


def _sidebar_secretario_geral(pagina_atual, igreja, secretario):
    _sidebar_perfil_simples(
        pagina_atual, igreja, secretario,
        tipo_login="secretario_geral",
        paginas_base=PAGINAS_SECRETARIO_GERAL,
        pagina_inicio="cadastros",
        nome_padrao="Secretário Geral",
        subtitulo="Acesso restrito de secretaria",
        key_prefix="sb_secretario_geral",
    )


def _renderizar_admin():
    _sidebar_admin()
    try:
        _importar("admin.painel").render()
    except Exception:
        LOGGER.exception("Falha ao carregar o painel administrativo.")
        st.error("Não foi possível carregar o painel administrativo. Consulte o log do sistema.")


def _renderizar_igreja():
    igreja = st.session_state.get("igreja", {})
    if not isinstance(igreja, dict) or not igreja.get("slug"):
        st.error("Sessão inválida. Faça login novamente.")
        if st.button("Voltar ao login"):
            _auth().logout()
        return
    pagina = st.session_state.get("pagina", "home")
    if pagina not in PAGINAS_IGREJA:
        pagina = "home"
        st.session_state["pagina"] = pagina
    _sidebar_igreja(pagina, igreja)
    _, caminho_modulo = PAGINAS_IGREJA[pagina]
    try:
        _importar(caminho_modulo).render()
    except Exception as ex:
        LOGGER.exception("Falha ao carregar a página %s.", pagina)
        st.error(
            "Não foi possível carregar esta página. "
            f"Tipo do erro: {type(ex).__name__}. Consulte o log do sistema."
        )


def _renderizar_tesoureiro():
    igreja = st.session_state.get("igreja", {})
    tesoureiro = st.session_state.get("tesoureiro", {})
    if not isinstance(igreja, dict) or not igreja.get("slug") or not isinstance(tesoureiro, dict):
        st.error("Sessão inválida. Faça login novamente.")
        if st.button("Voltar ao login"):
            _auth().logout()
        return
    paginas = _paginas_com_permissoes(PAGINAS_TESOUREIRO, "tesoureiro", tesoureiro)
    pagina = st.session_state.get("pagina", "lancamentos")
    if pagina not in paginas:
        pagina = "lancamentos"
        st.session_state["pagina"] = pagina
    _sidebar_tesoureiro(pagina, igreja, tesoureiro)
    _, caminho_modulo = paginas[pagina]
    try:
        _importar(caminho_modulo).render()
    except Exception as ex:
        LOGGER.exception("Falha ao carregar a página %s para o tesoureiro.", pagina)
        st.error(
            "Não foi possível carregar esta página. "
            f"Tipo do erro: {type(ex).__name__}. Consulte o log do sistema."
        )


def _renderizar_secretario_ebd():
    igreja = st.session_state.get("igreja", {})
    secretario = st.session_state.get("secretario_ebd", {})
    if not isinstance(igreja, dict) or not igreja.get("slug") or not isinstance(secretario, dict):
        st.error("Sessão inválida. Faça login novamente.")
        if st.button("Voltar ao login"):
            _auth().logout()
        return
    paginas = _paginas_com_permissoes(PAGINAS_EBD, "secretario_ebd", secretario)
    pagina = st.session_state.get("pagina", "ebd")
    if pagina not in paginas:
        pagina = "ebd"
        st.session_state["pagina"] = pagina
    _sidebar_secretario_ebd(pagina, igreja, secretario)
    _, caminho_modulo = paginas[pagina]
    try:
        _importar(caminho_modulo).render()
    except Exception as ex:
        LOGGER.exception("Falha ao carregar Escola Bíblica para secretario.")
        st.error(
            "Não foi possível carregar esta página. "
            f"Tipo do erro: {type(ex).__name__}. Consulte o log do sistema."
        )


def _renderizar_secretaria_orhafe():
    igreja = st.session_state.get("igreja", {})
    secretaria = st.session_state.get("secretaria_orhafe", {})
    if not isinstance(igreja, dict) or not igreja.get("slug") or not isinstance(secretaria, dict):
        st.error("Sessão inválida. Faça login novamente.")
        if st.button("Voltar ao login"):
            _auth().logout()
        return
    paginas = _paginas_com_permissoes({"orhafe": PAGINAS_IGREJA["orhafe"]}, "secretaria_orhafe", secretaria)
    pagina = st.session_state.get("pagina", "orhafe")
    if pagina not in paginas:
        pagina = "orhafe"
        st.session_state["pagina"] = pagina
    _sidebar_secretaria_orhafe(pagina, igreja, secretaria)
    _, caminho_modulo = paginas[pagina]
    try:
        _importar(caminho_modulo).render()
    except Exception as ex:
        LOGGER.exception("Falha ao carregar Círculo de Oração para secretaria.")
        st.error(
            "Não foi possível carregar esta página. "
            f"Tipo do erro: {type(ex).__name__}. Consulte o log do sistema."
        )


def _renderizar_secretaria_gfc():
    igreja = st.session_state.get("igreja", {})
    secretaria = st.session_state.get("secretaria_gfc", {})
    if not isinstance(igreja, dict) or not igreja.get("slug") or not isinstance(secretaria, dict):
        st.error("Sessao invalida. Faca login novamente.")
        if st.button("Voltar ao login"):
            _auth().logout()
        return
    paginas = _paginas_com_permissoes({"gfc": PAGINAS_IGREJA["gfc"]}, "secretaria_gfc", secretaria)
    pagina = st.session_state.get("pagina", "gfc")
    if pagina not in paginas:
        pagina = "gfc"
        st.session_state["pagina"] = pagina
    _sidebar_secretaria_gfc(pagina, igreja, secretaria)
    _, caminho_modulo = paginas[pagina]
    try:
        _importar(caminho_modulo).render()
    except Exception as ex:
        LOGGER.exception("Falha ao carregar Grupos Familiares para secretaria.")
        st.error(
            "Nao foi possivel carregar esta pagina. "
            f"Tipo do erro: {type(ex).__name__}. Consulte o log do sistema."
        )


def _renderizar_pastor_auxiliar():
    igreja = st.session_state.get("igreja", {})
    pastor = st.session_state.get("pastor_auxiliar", {})
    if not isinstance(igreja, dict) or not igreja.get("slug") or not isinstance(pastor, dict):
        st.error("Sessão inválida. Faça login novamente.")
        if st.button("Voltar ao login"):
            _auth().logout()
        return
    paginas = _paginas_com_permissoes(PAGINAS_PASTOR_AUXILIAR, "pastor_auxiliar", pastor)
    pagina = st.session_state.get("pagina", "visitantes")
    if pagina not in paginas:
        pagina = "visitantes"
        st.session_state["pagina"] = pagina
    _sidebar_pastor_auxiliar(pagina, igreja, pastor)
    _, caminho_modulo = paginas[pagina]
    try:
        _importar(caminho_modulo).render()
    except Exception as ex:
        LOGGER.exception("Falha ao carregar a página %s para pastor auxiliar.", pagina)
        st.error(
            "Não foi possível carregar esta página. "
            f"Tipo do erro: {type(ex).__name__}. Consulte o log do sistema."
        )


def _renderizar_recepcao():
    igreja = st.session_state.get("igreja", {})
    recepcao = st.session_state.get("recepcao", {})
    if not isinstance(igreja, dict) or not igreja.get("slug") or not isinstance(recepcao, dict):
        st.error("Sessão inválida. Faça login novamente.")
        if st.button("Voltar ao login"):
            _auth().logout()
        return
    paginas = _paginas_com_permissoes(PAGINAS_RECEPCAO, "recepcao", recepcao)
    pagina = st.session_state.get("pagina", "visitantes")
    if pagina not in paginas:
        pagina = "visitantes"
        st.session_state["pagina"] = pagina
    _sidebar_recepcao(pagina, igreja, recepcao)
    try:
        _, caminho_modulo = paginas[pagina]
        _importar(caminho_modulo).render()
    except Exception as ex:
        LOGGER.exception("Falha ao carregar visitantes para recepção.")
        st.error(
            "Não foi possível carregar esta página. "
            f"Tipo do erro: {type(ex).__name__}. Consulte o log do sistema."
        )


def _renderizar_secretario_geral():
    igreja = st.session_state.get("igreja", {})
    secretario = st.session_state.get("secretario_geral", {})
    if not isinstance(igreja, dict) or not igreja.get("slug") or not isinstance(secretario, dict):
        st.error("Sessão inválida. Faça login novamente.")
        if st.button("Voltar ao login"):
            _auth().logout()
        return
    paginas = _paginas_com_permissoes(PAGINAS_SECRETARIO_GERAL, "secretario_geral", secretario)
    pagina = st.session_state.get("pagina", "cadastros")
    if pagina not in paginas:
        pagina = "cadastros"
        st.session_state["pagina"] = pagina
    _sidebar_secretario_geral(pagina, igreja, secretario)
    _, caminho_modulo = paginas[pagina]
    try:
        _importar(caminho_modulo).render()
    except Exception as ex:
        LOGGER.exception("Falha ao carregar a página %s para secretário geral.", pagina)
        st.error(
            "Não foi possível carregar esta página. "
            f"Tipo do erro: {type(ex).__name__}. Consulte o log do sistema."
        )


def _ocultar_chrome_streamlit():
    """Esconde o menu/rodape/botao Deploy nativos do Streamlit em toda a app,
    inclusive nas telas publicas (login/institucional), que rodam antes de
    _injetar_css()."""
    st.markdown(
        """
        <style>
        #MainMenu, footer {display:none!important}
        [data-testid="stStatusWidget"] {display:none!important}
        [data-testid="stToolbar"] {display:none!important}
        </style>
        """,
        unsafe_allow_html=True,
    )


def _aplicar_tipografia():
    """Tipografia unica do sistema: Fraunces nos titulos, Public Sans no
    corpo. Aplicada antes de qualquer tela (publica ou autenticada) para
    que login, institucional e app interno compartilhem a mesma fonte."""
    st.markdown(
        """
        <link rel="preconnect" href="https://fonts.googleapis.com">
        <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
        <link href="https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,600;9..144,700&family=Public+Sans:wght@400;500;600;700&display=swap" rel="stylesheet">
        <style>
        html, body, [class*="css"] {
            font-family: 'Public Sans', -apple-system, 'Segoe UI', Arial, sans-serif;
        }
        h1, h2, h3 {
            font-family: 'Fraunces', Georgia, 'Times New Roman', serif;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def main():
    _ocultar_chrome_streamlit()
    _aplicar_tipografia()
    _bloquear_acesso_fora_do_dominio_oficial()

    # ═══════════════════════════════════════════════════════════════════
    # NOVO: Bypass de login para link de auto-checkin (?ck=<slug>_<token>)
    # Este bloco DEVE vir antes de _resolver_rota_publica e do login,
    # para permitir acesso publico direto a pagina de check-in.
    # ═══════════════════════════════════════════════════════════════════
    if _rota_auto_checkin():
        _renderizar_auto_checkin()
        st.stop()

    _resolver_rota_publica()
    auth = _auth()
    _validar_contrato_auth(auth)
    if not auth.tela_login():
        st.stop()
    _injetar_css()
    modo = auth.modo_atual()
    if modo == "admin":
        _renderizar_admin()
    elif modo == "igreja":
        _renderizar_igreja()
    elif modo == "tesoureiro":
        _renderizar_tesoureiro()
    elif modo == "secretario_ebd":
        _renderizar_secretario_ebd()
    elif modo == "secretaria_orhafe":
        _renderizar_secretaria_orhafe()
    elif modo == "secretaria_gfc":
        _renderizar_secretaria_gfc()
    elif modo == "pastor_auxiliar":
        _renderizar_pastor_auxiliar()
    elif modo == "recepcao":
        _renderizar_recepcao()
    elif modo == "secretario_geral":
        _renderizar_secretario_geral()
    else:
        st.error("Modo de acesso inválido. Faça login novamente.")
        if st.button("Sair"):
            auth.logout()


if __name__ == "__main__":
    main()
