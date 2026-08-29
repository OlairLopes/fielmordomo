import base64
import datetime
import html
import logging
from pathlib import Path

import streamlit as st

from utils.helpers import normalizar_data_digitada


AZUL_PRINCIPAL = "#0B3A66"
AZUL_ESCURO = "#082A4A"
AZUL_PROFUNDO = "#061F35"
AZUL_CLARO = "#EAF2FB"
DOURADO = "#D4AF37"
CINZA_TEXTO = "#1F2933"
CINZA_SUAVE = "#F5F7FA"
LOGGER = logging.getLogger(__name__)
TAMANHO_MAXIMO_LOGO = 5 * 1024 * 1024
MIMES_LOGO_PERMITIDOS = {
    "gif": "image/gif",
    "jpeg": "image/jpeg",
    "jpg": "image/jpeg",
    "png": "image/png",
    "webp": "image/webp",
}


def _pagina_atual():
    pagina = st.query_params.get("pagina", "inicio")
    if isinstance(pagina, list):
        pagina = pagina[0] if pagina else "inicio"
    return str(pagina or "inicio").strip().lower()


def _img_b64(dados, ext):
    ext = str(ext or "png").lower().replace(".", "")
    mime = MIMES_LOGO_PERMITIDOS.get(ext)
    if not mime:
        raise ValueError(f"Formato de logo não permitido: {ext}")

    if not isinstance(dados, (bytes, bytearray, memoryview)):
        raise TypeError("Os dados do logo devem estar em formato binário.")

    if len(dados) > TAMANHO_MAXIMO_LOGO:
        raise ValueError("O logo excede o limite de 5 MB.")

    return "data:" + mime + ";base64," + base64.b64encode(dados).decode("utf-8")


def _logo_sistema_src():
    """
    Tenta carregar o logo oficial do FielMordomo.
    Ordem:
    1. Logo cadastrado no painel admin/sistema.
    2. Arquivos locais comuns em assets/static.
    3. Fallback textual.
    """
    # 1. Logo salvo no banco/configuração do sistema
    try:
        from data.repository import obter_logo_sistema, obter_logo_sidebar_sistema

        logo = obter_logo_sistema() or obter_logo_sidebar_sistema()
        if logo:
            dados, ext = logo
            return _img_b64(dados, ext)
    except Exception:
        LOGGER.exception("Não foi possível carregar o logo configurado no sistema.")

    # 2. Logo em arquivo local, caso exista no projeto
    try:
        base = Path(__file__).resolve().parents[1]
        candidatos = [
            base / "assets" / "logo_fielmordomo.png",
            base / "assets" / "logo.png",
            base / "static" / "logo_fielmordomo.png",
            base / "static" / "logo.png",
            base / "logo_fielmordomo.png",
            base / "logo.png",
        ]

        for arq in candidatos:
            if arq.exists() and arq.is_file():
                ext = arq.suffix.replace(".", "") or "png"
                return _img_b64(arq.read_bytes(), ext)
    except Exception:
        LOGGER.exception("Não foi possível carregar um logo local.")

    return ""


def _marca_fielmordomo_html():
    logo_src = _logo_sistema_src()

    if logo_src:
        return (
            '<a class="fm-logo fm-logo-com-imagem" href="?pagina=inicio" target="_top">'
            f'<img class="fm-logo-img" src="{logo_src}" alt="FielMordomo">'
            '</a>'
        )

    # Fallback textual corrigido: sem "Campo+Mordomo" e sem "Fiel+Mordomo".
    return '<a class="fm-logo" href="?pagina=inicio" target="_top">FielMordomo</a>'


def _css_base():
    return f"""
    <meta name="google" content="notranslate">
    <meta name="translate" content="no">
    <style>
        * {{
            box-sizing: border-box;
            translate: no;
        }}

        html {{
            scroll-behavior: smooth;
            -webkit-locale: "pt-BR";
        }}

        body {{
            margin: 0;
        }}

        .fm-page {{
            width: 100%;
            min-height: 100vh;
            background: {CINZA_SUAVE};
            color: {CINZA_TEXTO};
            font-family: "Public Sans", -apple-system, BlinkMacSystemFont, "Segoe UI", Arial, sans-serif;
        }}

        .fm-navbar-wrap {{
            width: 100%;
            background: rgba(255, 255, 255, 0.97);
            border-bottom: 1px solid rgba(8, 42, 74, 0.08);
            position: sticky;
            top: 0;
            z-index: 999;
            backdrop-filter: blur(12px);
        }}

        .fm-navbar {{
            max-width: 1180px;
            margin: 0 auto;
            padding: 16px 24px;
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 24px;
        }}

        .fm-logo {{
            font-size: 30px;
            font-weight: 800;
            color: {AZUL_ESCURO};
            letter-spacing: -0.8px;
            text-decoration: none;
            display: inline-flex;
            align-items: center;
            gap: 4px;
            white-space: nowrap;
        }}

        .fm-logo span {{
            color: {DOURADO};
            font-weight: 900;
        }}

        .fm-logo-img {{
            display: block;
            width: auto;
            height: auto;
            max-width: 240px;
            max-height: 72px;
            object-fit: contain;
        }}

        .fm-menu {{
            display: flex;
            align-items: center;
            gap: 22px;
            flex-wrap: wrap;
        }}

        .fm-menu a {{
            color: {AZUL_ESCURO};
            text-decoration: none;
            font-size: 15px;
            font-weight: 650;
        }}

        .fm-menu a:hover {{
            color: {DOURADO};
        }}

        .fm-btn-login {{
            background: {AZUL_PRINCIPAL};
            color: white !important;
            padding: 10px 18px;
            border-radius: 10px;
            box-shadow: 0 8px 20px rgba(11, 58, 102, 0.22);
        }}

        .fm-hero {{
            max-width: 1180px;
            margin: 0 auto;
            padding: 68px 24px 44px;
            display: grid;
            grid-template-columns: 1.02fr 0.98fr;
            gap: 54px;
            align-items: center;
            position: relative;
        }}

        .fm-hero::before {{
            content: "";
            position: absolute;
            left: -80px;
            top: 105px;
            width: 360px;
            height: 360px;
            background:
                radial-gradient(circle at center, rgba(11,58,102,0.10), transparent 60%),
                linear-gradient(135deg, rgba(212,175,55,0.08), transparent);
            border-radius: 50%;
            z-index: 0;
        }}

        .fm-hero-text {{
            position: relative;
            z-index: 1;
        }}

        .fm-eyebrow {{
            display: inline-flex;
            align-items: center;
            gap: 8px;
            background: {AZUL_CLARO};
            color: {AZUL_PRINCIPAL};
            border: 1px solid rgba(11,58,102,0.12);
            padding: 7px 12px;
            border-radius: 999px;
            font-size: 13px;
            font-weight: 750;
            margin-bottom: 18px;
        }}

        .fm-hero h1 {{
            color: {AZUL_ESCURO};
            font-size: 48px;
            line-height: 1.08;
            letter-spacing: -1.6px;
            margin: 0 0 22px;
            font-weight: 850;
        }}

        .fm-hero p {{
            color: #405064;
            font-size: 18px;
            line-height: 1.7;
            margin-bottom: 30px;
            max-width: 610px;
        }}

        .fm-actions {{
            display: flex;
            gap: 14px;
            flex-wrap: wrap;
            align-items: center;
        }}

        .fm-primary {{
            background: {AZUL_PRINCIPAL};
            color: white !important;
            text-decoration: none;
            padding: 14px 22px;
            border-radius: 12px;
            font-weight: 750;
            box-shadow: 0 12px 28px rgba(11,58,102,0.24);
            display: inline-flex;
            gap: 10px;
            align-items: center;
        }}

        .fm-secondary {{
            background: white;
            color: {AZUL_PRINCIPAL} !important;
            text-decoration: none;
            padding: 13px 22px;
            border-radius: 12px;
            font-weight: 750;
            border: 1px solid rgba(11,58,102,0.22);
            display: inline-flex;
            gap: 10px;
            align-items: center;
        }}

        .fm-dashboard {{
            background: linear-gradient(145deg, {AZUL_ESCURO}, {AZUL_PROFUNDO});
            border-radius: 24px;
            padding: 14px;
            box-shadow: 0 24px 55px rgba(8,42,74,0.24);
            position: relative;
        }}

        .fm-dashboard-inner {{
            background: #ffffff;
            border-radius: 16px;
            overflow: hidden;
            min-height: 360px;
            display: grid;
            grid-template-columns: 150px 1fr;
        }}

        .fm-sidebar {{
            background: linear-gradient(180deg, {AZUL_ESCURO}, {AZUL_PROFUNDO});
            color: white;
            padding: 18px 14px;
        }}

        .fm-side-logo {{
            font-weight: 800;
            font-size: 15px;
            margin-bottom: 22px;
        }}

        .fm-side-item {{
            font-size: 12px;
            padding: 8px 6px;
            color: rgba(255,255,255,0.82);
            display: flex;
            gap: 8px;
            align-items: center;
        }}

        .fm-main-panel {{
            padding: 18px;
            background: #F8FAFC;
        }}

        .fm-panel-top {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 16px;
        }}

        .fm-panel-top h3 {{
            color: {AZUL_ESCURO};
            font-size: 18px;
            margin: 0;
        }}

        .fm-kpis {{
            display: grid;
            grid-template-columns: repeat(4, 1fr);
            gap: 10px;
            margin-bottom: 12px;
        }}

        .fm-kpi {{
            background: white;
            border-radius: 10px;
            padding: 12px;
            border: 1px solid #EDF1F5;
        }}

        .fm-kpi small {{
            color: #64748B;
            font-size: 10px;
        }}

        .fm-kpi strong {{
            display: block;
            color: {AZUL_PRINCIPAL};
            font-size: 15px;
            margin-top: 4px;
        }}

        .fm-charts {{
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 12px;
            margin-bottom: 12px;
        }}

        .fm-chart-box {{
            background: white;
            border-radius: 12px;
            padding: 14px;
            border: 1px solid #EDF1F5;
            min-height: 118px;
        }}

        .fm-chart-title {{
            color: {AZUL_ESCURO};
            font-size: 12px;
            font-weight: 800;
            margin-bottom: 12px;
        }}

        .fm-bars {{
            display: flex;
            gap: 10px;
            align-items: end;
            height: 70px;
        }}

        .fm-bar {{
            width: 15px;
            border-radius: 5px 5px 0 0;
            background: {AZUL_PRINCIPAL};
        }}

        .fm-bar.gold {{
            background: {DOURADO};
        }}

        .fm-donut {{
            width: 82px;
            height: 82px;
            border-radius: 50%;
            background: conic-gradient({AZUL_PRINCIPAL} 0 58%, {DOURADO} 58% 80%, #9DB6D3 80% 92%, #D7E3F0 92% 100%);
            margin: 4px auto;
            position: relative;
        }}

        .fm-donut::after {{
            content: "";
            position: absolute;
            width: 38px;
            height: 38px;
            border-radius: 50%;
            background: white;
            left: 22px;
            top: 22px;
        }}

        .fm-table {{
            background: white;
            border-radius: 12px;
            padding: 12px;
            border: 1px solid #EDF1F5;
        }}

        .fm-table-line {{
            display: grid;
            grid-template-columns: 0.8fr 1.8fr 1fr 1fr;
            gap: 8px;
            font-size: 10px;
            padding: 6px 0;
            border-bottom: 1px solid #EEF2F6;
            color: #475569;
        }}

        .fm-cards {{
            max-width: 1180px;
            margin: 0 auto;
            padding: 18px 24px 36px;
            display: grid;
            grid-template-columns: repeat(3, 1fr);
            gap: 22px;
        }}

        .fm-card {{
            background: white;
            border-radius: 18px;
            padding: 26px;
            border: 1px solid rgba(8,42,74,0.07);
            box-shadow: 0 14px 34px rgba(8,42,74,0.08);
        }}

        .fm-icon {{
            width: 54px;
            height: 54px;
            border-radius: 16px;
            background: {AZUL_CLARO};
            color: {AZUL_PRINCIPAL};
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 25px;
            margin-bottom: 16px;
        }}

        .fm-card h3 {{
            color: {AZUL_ESCURO};
            margin: 0 0 10px;
            font-size: 20px;
        }}

        .fm-card p {{
            color: #516173;
            line-height: 1.65;
            margin: 0;
            font-size: 15px;
        }}

        .fm-section {{
            background: white;
            padding: 58px 24px;
        }}

        .fm-section-inner {{
            max-width: 1180px;
            margin: 0 auto;
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 60px;
        }}

        .fm-section h2 {{
            color: {AZUL_ESCURO};
            font-size: 30px;
            margin: 0 0 16px;
        }}

        .fm-section p {{
            color: #4B5563;
            line-height: 1.75;
            font-size: 16px;
        }}

        .fm-list {{
            display: grid;
            grid-template-columns: 1fr;
            gap: 13px;
            margin-top: 18px;
        }}

        .fm-list div {{
            display: flex;
            align-items: center;
            gap: 10px;
            color: #334155;
            font-weight: 650;
        }}

        .fm-check {{
            width: 22px;
            height: 22px;
            background: {AZUL_PRINCIPAL};
            color: white;
            border-radius: 50%;
            display: inline-flex;
            align-items: center;
            justify-content: center;
            font-size: 13px;
            flex-shrink: 0;
        }}

        .fm-cta {{
            background: linear-gradient(135deg, {AZUL_ESCURO}, {AZUL_PROFUNDO});
            padding: 48px 24px;
            color: white;
        }}

        .fm-cta-inner {{
            max-width: 1180px;
            margin: 0 auto;
            display: flex;
            justify-content: space-between;
            align-items: center;
            gap: 30px;
        }}

        .fm-cta h2 {{
            color: white;
            margin: 0 0 8px;
            font-size: 30px;
        }}

        .fm-cta p {{
            color: rgba(255,255,255,0.82);
            margin: 0;
            font-size: 16px;
        }}

        .fm-gold-btn {{
            background: {DOURADO};
            color: {AZUL_PROFUNDO} !important;
            text-decoration: none;
            padding: 14px 24px;
            border-radius: 12px;
            font-weight: 800;
            white-space: nowrap;
        }}

        .fm-footer {{
            background: {AZUL_PROFUNDO};
            color: rgba(255,255,255,0.78);
            padding: 22px 24px;
            border-top: 1px solid rgba(255,255,255,0.08);
        }}

        .fm-footer-inner {{
            max-width: 1180px;
            margin: 0 auto;
            display: flex;
            justify-content: space-between;
            gap: 20px;
            flex-wrap: wrap;
            font-size: 14px;
        }}

        .fm-footer a {{
            color: rgba(255,255,255,0.78);
            text-decoration: none;
            margin-left: 18px;
        }}

        .fm-footer a:hover {{
            color: {DOURADO};
        }}

        .fm-simple-page {{
            max-width: 920px;
            margin: 0 auto;
            padding: 58px 24px 80px;
        }}

        .fm-simple-card {{
            background: white;
            border-radius: 20px;
            padding: 38px;
            box-shadow: 0 14px 38px rgba(8,42,74,0.08);
            border: 1px solid rgba(8,42,74,0.08);
        }}

        .fm-simple-card h1 {{
            color: {AZUL_ESCURO};
            font-size: 36px;
            margin-top: 0;
        }}

        .fm-simple-card h2 {{
            color: {AZUL_PRINCIPAL};
            font-size: 22px;
            margin-top: 26px;
        }}

        .fm-simple-card p, .fm-simple-card li {{
            color: #4B5563;
            line-height: 1.75;
            font-size: 16px;
        }}

        .fm-update-page {{
            max-width: 920px;
            margin: 0 auto;
            padding: 14px 24px 6px;
        }}

        .fm-page.fm-page-update {{
            min-height: auto;
            background: {CINZA_SUAVE};
        }}

        .fm-update-card {{
            background: white;
            border-radius: 18px;
            padding: 16px 24px;
            box-shadow: 0 10px 26px rgba(8,42,74,0.06);
            border: 1px solid rgba(8,42,74,0.08);
            margin-bottom: 0;
        }}

        .fm-update-card h1 {{
            color: {AZUL_ESCURO};
            font-size: 26px;
            margin: 0 0 6px;
        }}

        .fm-update-card p {{
            color: #4B5563;
            line-height: 1.55;
            font-size: 15px;
            margin: 0;
        }}

        @media (max-width: 900px) {{
            .fm-navbar {{
                align-items: flex-start;
                flex-direction: column;
            }}

            .fm-logo-img {{
                max-width: 190px;
                max-height: 58px;
            }}

            .fm-hero {{
                grid-template-columns: 1fr;
                padding-top: 42px;
            }}

            .fm-hero h1 {{
                font-size: 38px;
            }}

            .fm-cards {{
                grid-template-columns: 1fr;
            }}

            .fm-section-inner {{
                grid-template-columns: 1fr;
            }}

            .fm-cta-inner {{
                flex-direction: column;
                align-items: flex-start;
            }}

            .fm-dashboard-inner {{
                grid-template-columns: 1fr;
            }}

            .fm-sidebar {{
                display: none;
            }}

            .fm-kpis {{
                grid-template-columns: repeat(2, 1fr);
            }}

            .fm-charts {{
                grid-template-columns: 1fr;
            }}
        }}
    </style>
    """


def _navbar():
    return f"""
    <div class="fm-navbar-wrap">
        <div class="fm-navbar">
            {_marca_fielmordomo_html()}

            <div class="fm-menu">
                <a href="?pagina=inicio#sobre" target="_top">Sobre</a>
                <a href="?pagina=inicio#recursos" target="_top">Recursos</a>
                <a href="?pagina=agenda" target="_top">Agenda</a>
                <a href="?pagina=atualizar-cadastro" target="_top">Atualizar cadastro</a>
                <a href="?pagina=pedidos-oracao" target="_top">Pedidos de oração</a>
                <a href="?pagina=contato" target="_top">Contato</a>
                <a href="?pagina=privacidade" target="_top">Privacidade LGPD</a>
                <a class="fm-btn-login" href="?pagina=login" target="_top">🔒 Acessar Sistema</a>
            </div>
        </div>
    </div>
    """


def _footer():
    return """
    <div class="fm-footer">
        <div class="fm-footer-inner">
            <div>FielMordomo © 2026 — Sistema de Gestão Financeira para Igrejas.</div>
            <div>
                <a href="?pagina=contato" target="_top">Contato</a>
                <a href="?pagina=agenda" target="_top">Agenda</a>
                <a href="?pagina=atualizar-cadastro" target="_top">Atualizar cadastro</a>
                <a href="?pagina=pedidos-oracao" target="_top">Pedidos de oração</a>
                <a href="?pagina=privacidade" target="_top">Privacidade LGPD</a>
                <a href="?pagina=termos" target="_top">Termos de Uso</a>
            </div>
        </div>
    </div>
    """


def _home():
    return """
    <section class="fm-hero">
        <div class="fm-hero-text">
            <div class="fm-eyebrow">✦ Gestão Financeira para Igrejas</div>

            <h1>Gestão financeira simples, segura e organizada para Igrejas</h1>

            <p>
                Controle dízimos, ofertas, campanhas, missões, despesas, comprovantes
                e relatórios em uma única plataforma, com mais clareza para a tesouraria
                e mais transparência para a liderança.
            </p>

            <div class="fm-actions">
                <a class="fm-primary" href="?pagina=login" target="_top">🔒 Acessar Sistema</a>
                <a class="fm-secondary" href="#sobre">ⓘ Conheça o FielMordomo</a>
            </div>
        </div>

        <div class="fm-dashboard">
            <div class="fm-dashboard-inner">
                <div class="fm-sidebar">
                    <div class="fm-side-logo">FielMordomo</div>
                    <div class="fm-side-item">▣ Dashboard</div>
                    <div class="fm-side-item">◈ Contribuições</div>
                    <div class="fm-side-item">◇ Despesas</div>
                    <div class="fm-side-item">▤ Comprovantes</div>
                    <div class="fm-side-item">▥ Relatórios</div>
                    <div class="fm-side-item">⚙ Configurações</div>
                </div>

                <div class="fm-main-panel">
                    <div class="fm-panel-top">
                        <h3>Dashboard</h3>
                        <small>Igreja Exemplo ⌄</small>
                    </div>

                    <div class="fm-kpis">
                        <div class="fm-kpi"><small>Dízimos e Ofertas</small><strong>R$ 45.320,50</strong></div>
                        <div class="fm-kpi"><small>Campanhas e Missões</small><strong>R$ 12.680,75</strong></div>
                        <div class="fm-kpi"><small>Despesas</small><strong>R$ 18.540,30</strong></div>
                        <div class="fm-kpi"><small>Saldo do Período</small><strong>R$ 39.460,95</strong></div>
                    </div>

                    <div class="fm-charts">
                        <div class="fm-chart-box">
                            <div class="fm-chart-title">Receitas x Despesas</div>
                            <div class="fm-bars">
                                <div class="fm-bar" style="height:55px"></div>
                                <div class="fm-bar gold" style="height:32px"></div>
                                <div class="fm-bar" style="height:48px"></div>
                                <div class="fm-bar gold" style="height:28px"></div>
                                <div class="fm-bar" style="height:64px"></div>
                                <div class="fm-bar gold" style="height:36px"></div>
                                <div class="fm-bar" style="height:58px"></div>
                                <div class="fm-bar gold" style="height:30px"></div>
                            </div>
                        </div>

                        <div class="fm-chart-box">
                            <div class="fm-chart-title">Distribuição das Receitas</div>
                            <div class="fm-donut"></div>
                        </div>
                    </div>

                    <div class="fm-table">
                        <div class="fm-table-line"><strong>Data</strong><strong>Descrição</strong><strong>Categoria</strong><strong>Valor</strong></div>
                        <div class="fm-table-line"><span>10/06</span><span>Dízimo - João Silva</span><span>Dízimos</span><span>R$ 250,00</span></div>
                        <div class="fm-table-line"><span>10/06</span><span>Oferta - Culto</span><span>Ofertas</span><span>R$ 180,00</span></div>
                        <div class="fm-table-line"><span>09/06</span><span>Conta de Luz</span><span>Despesa</span><span>R$ 320,00</span></div>
                    </div>
                </div>
            </div>
        </div>
    </section>

    <section class="fm-cards">
        <div class="fm-card">
            <div class="fm-icon">▤</div>
            <h3>Controle Financeiro</h3>
            <p>Gerencie dízimos, ofertas, campanhas, missões e despesas com praticidade e confiança.</p>
        </div>

        <div class="fm-card">
            <div class="fm-icon">▥</div>
            <h3>Relatórios Claros</h3>
            <p>Relatórios completos e visuais que facilitam a análise e a prestação de contas à liderança.</p>
        </div>

        <div class="fm-card">
            <div class="fm-icon">♢</div>
            <h3>Segurança e Organização</h3>
            <p>Dados protegidos, acessos controlados e informações organizadas para maior transparência.</p>
        </div>
    </section>

    <section class="fm-section" id="sobre">
        <div class="fm-section-inner">
            <div>
                <h2>Sobre o FielMordomo</h2>
                <p>
                    O FielMordomo é uma plataforma de gestão financeira desenvolvida para apoiar igrejas,
                    congregações e ministérios na boa administração dos recursos confiados à sua responsabilidade.
                </p>
                <p>
                    O sistema auxilia tesourarias, secretarias, pastores e equipes administrativas no controle
                    de lançamentos, emissão de comprovantes, acompanhamento de relatórios e organização das
                    informações financeiras da igreja.
                </p>
            </div>

            <div id="recursos">
                <h2>Recursos principais</h2>
                <div class="fm-list">
                    <div><span class="fm-check">✓</span> Cadastro de membros e contribuintes</div>
                    <div><span class="fm-check">✓</span> Controle de dízimos, ofertas, campanhas e missões</div>
                    <div><span class="fm-check">✓</span> Registro de despesas e saídas</div>
                    <div><span class="fm-check">✓</span> Emissão de comprovantes</div>
                    <div><span class="fm-check">✓</span> Relatórios financeiros</div>
                    <div><span class="fm-check">✓</span> Backup e recuperação de dados</div>
                </div>
            </div>
        </div>
    </section>

    <section class="fm-cta">
        <div class="fm-cta-inner">
            <div>
                <h2>Pronto para organizar a gestão financeira da sua igreja?</h2>
                <p>
                    Mais controle, mais transparência e mais tempo para o que realmente importa:
                    o Reino de Deus.
                </p>
            </div>

            <a class="fm-gold-btn" href="?pagina=login" target="_top">🔒 Acessar Sistema</a>
        </div>
    </section>
    """


def _contato():
    return """
    <div class="fm-simple-page">
        <div class="fm-simple-card">
            <h1>Contato</h1>

            <p>
                Para dúvidas, suporte, sugestões ou informações sobre o FielMordomo,
                entre em contato pelos canais oficiais da administração do sistema.
            </p>

            <h2>Canais de atendimento</h2>

            <p><strong>E-mail:</strong> suporte@fielmordomo.com.br</p>
            <p><strong>Site:</strong> https://fielmordomo.com.br</p>

            <p>
                As solicitações serão analisadas pela equipe responsável, especialmente em casos relacionados
                a acesso, cadastro de igrejas, planos, backup, restauração de dados e orientações de uso.
            </p>
        </div>
    </div>
    """


def _privacidade():
    return """
    <div class="fm-simple-page">
        <div class="fm-simple-card">
            <h1>Pol&iacute;tica de Privacidade</h1>

            <p>
                O FielMordomo respeita a privacidade dos usuários e das instituições cadastradas.
                As informações inseridas no sistema são utilizadas para fins de gestão administrativa
                e financeira da igreja cadastrada.
            </p>

            <h2>1. Dados coletados</h2>
            <p>
                O sistema pode armazenar dados como nome da igreja, identificação da congregação,
                membros, lançamentos financeiros, categorias, formas de pagamento, datas, valores
                e demais informações necessárias à administração financeira.
            </p>

            <h2>2. Uso das informações</h2>
            <p>
                Os dados são utilizados para geração de relatórios, controle financeiro, emissão de comprovantes,
                acompanhamento de receitas e despesas, backup e organização administrativa.
            </p>

            <h2>3. Segurança</h2>
            <p>
                O acesso ao sistema é restrito a usuários autorizados. Recomenda-se que cada igreja mantenha
                suas credenciais protegidas e conceda acesso apenas a pessoas devidamente autorizadas.
            </p>

            <h2>4. Compartilhamento de dados</h2>
            <p>
                O FielMordomo não tem por finalidade vender, divulgar ou compartilhar dados das igrejas
                com terceiros para fins comerciais. As informações pertencem à instituição cadastrada.
            </p>

            <h2>5. Backup e recuperação</h2>
            <p>
                O sistema pode disponibilizar recursos de backup e restauração para proteger as informações
                administrativas, conforme o plano ou configuração utilizada.
            </p>

            <h2>6. Atualizações</h2>
            <p>
                Esta política poderá ser atualizada sempre que houver melhorias no sistema, alterações legais
                ou mudanças nas funcionalidades oferecidas.
            </p>
        </div>
    </div>
    """


def _termos():
    return """
    <div class="fm-simple-page">
        <div class="fm-simple-card">
            <h1>Termos de Uso</h1>

            <p>
                Ao utilizar o FielMordomo, o usuário declara estar ciente de que o sistema é uma ferramenta
                de apoio à gestão financeira e administrativa de igrejas, congregações e ministérios.
            </p>

            <h2>1. Responsabilidade pelo uso</h2>
            <p>
                A igreja ou instituição cadastrada é responsável pelas informações inseridas, conferência dos
                lançamentos, controle de usuários e validação dos relatórios gerados.
            </p>

            <h2>2. Acesso ao sistema</h2>
            <p>
                O acesso deve ser feito apenas por pessoas autorizadas. Cada usuário deve preservar suas
                credenciais e evitar compartilhamento indevido de login e senha.
            </p>

            <h2>3. Finalidade</h2>
            <p>
                O FielMordomo foi desenvolvido para registrar receitas, despesas, dízimos, ofertas, campanhas,
                missões, relatórios, comprovantes e demais informações relacionadas à administração financeira.
            </p>

            <h2>4. Integridade das informações</h2>
            <p>
                A precisão dos dados depende do correto preenchimento pelos usuários. A conferência periódica
                dos lançamentos é recomendada para manter a confiabilidade das informações.
            </p>

            <h2>5. Disponibilidade</h2>
            <p>
                O sistema poderá passar por atualizações, manutenções ou ajustes técnicos, visando preservar
                a segurança e estabilidade da aplicação.
            </p>

            <h2>6. Aceitação</h2>
            <p>
                O uso contínuo do sistema representa concordância com estes termos e com a política de
                privacidade aplicável.
            </p>
        </div>
    </div>
    """


def _render_atualizar_cadastro_publico():
    from data.repository import (
        atualizar_cadastro_publico,
        criar_pre_cadastro_publico,
        localizar_cadastro_publico,
        validar_codigo_atualizacao_cadastral,
    )

    def _parse_data_nascimento(valor):
        texto = normalizar_data_digitada(str(valor or "").strip())
        if not texto:
            return ""
        for formato in ("%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d"):
            try:
                return datetime.datetime.strptime(texto, formato).date().isoformat()
            except ValueError:
                continue
        return ""

    def _formatar_data_br(valor):
        texto = str(valor or "").strip()
        if not texto:
            return ""
        for formato in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
            try:
                return datetime.datetime.strptime(texto, formato).date().strftime("%d/%m/%Y")
            except ValueError:
                continue
        return texto

    def _parse_data_opcional(valor):
        texto = str(valor or "").strip()
        if not texto:
            return ""
        return _parse_data_nascimento(texto)

    estado_civil_opcoes = ["", "Solteiro(a)", "Casado(a)", "Divorciado(a)", "Viuvo(a)", "Uniao estavel"]
    tipo_membro_opcoes = ["", "Membro", "Congregado"]
    funcao_opcoes = [
        "", "Membro", "Congregado", "Auxiliar", "Pastor", "Diacono",
        "Diaconisa", "Presbitero", "Evangelista", "Cooperador",
        "Dirigente", "Secretario", "Tesoureiro", "Professor", "Lider",
        "Missionario(a)",
    ]

    st.markdown(
        """
        <div class="fm-update-page">
          <div class="fm-update-card">
            <h1>Atualização de cadastro</h1>
            <p>
              Informe os dados de identificação para localizar seu cadastro.
              O CPF e a data de nascimento são usados apenas para confirmar sua identidade.
              Caso seu cadastro ainda não exista, você poderá enviar um pré-cadastro
              para análise da secretaria da igreja.
            </p>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    with st.form("form_localizar_cadastro_publico"):
        c1, c2 = st.columns(2)
        slug = c1.text_input("Identificador da igreja", placeholder="ex: ad-serrinha")
        codigo = c2.text_input("Codigo de atualizacao cadastral", type="password")
        c3, c4 = st.columns(2)
        cpf = c3.text_input("CPF")
        data_nascimento_txt = c4.text_input(
            "Data de nascimento",
            placeholder="Ex.: 26/06/1979 ou 26061979",
            help="Informe no formato dia/mes/ano.",
        )
        if st.form_submit_button("Localizar cadastro", type="primary"):
            data_nascimento = _parse_data_nascimento(data_nascimento_txt)
            data_nascimento_br = _formatar_data_br(data_nascimento)
            if not slug or not codigo or not cpf or not data_nascimento:
                st.error("Informe igreja, codigo, CPF e data de nascimento.")
            else:
                slug_limpo = slug.strip().lower()
                if not validar_codigo_atualizacao_cadastral(slug_limpo, codigo):
                    st.error("Codigo de atualizacao cadastral invalido.")
                    return
                try:
                    cadastro = localizar_cadastro_publico(
                        slug_limpo,
                        cpf,
                        data_nascimento,
                    )
                except Exception:
                    LOGGER.exception("Falha ao localizar cadastro publico.")
                    cadastro = None
                if not cadastro:
                    st.warning(
                        "Cadastro nao localizado. Voce pode conferir os dados ou "
                        "enviar um pre-cadastro para analise da secretaria."
                    )
                    st.session_state["cadastro_publico_slug"] = slug_limpo
                    st.session_state["cadastro_publico_cpf"] = "".join(
                        c for c in str(cpf) if c.isdigit()
                    )
                    st.session_state["cadastro_publico_data"] = data_nascimento
                    st.session_state["cadastro_publico_data_br"] = data_nascimento_br
                    st.session_state["cadastro_publico_dados"] = None
                    st.session_state["mostrar_pre_cadastro_publico"] = True
                    st.rerun()
                else:
                    st.session_state["cadastro_publico_slug"] = slug_limpo
                    st.session_state["cadastro_publico_cpf"] = "".join(
                        c for c in str(cpf) if c.isdigit()
                    )
                    st.session_state["cadastro_publico_data"] = data_nascimento
                    st.session_state["cadastro_publico_data_br"] = data_nascimento_br
                    st.session_state["cadastro_publico_dados"] = cadastro
                    st.session_state["mostrar_pre_cadastro_publico"] = False
                    st.success("Cadastro localizado. Confira e atualize seus dados abaixo.")
                    st.rerun()

    cadastro = st.session_state.get("cadastro_publico_dados")
    slug_salvo = st.session_state.get("cadastro_publico_slug", "")
    cpf_salvo = st.session_state.get("cadastro_publico_cpf", "")
    data_salva = st.session_state.get("cadastro_publico_data", "")
    data_salva_br = st.session_state.get("cadastro_publico_data_br", _formatar_data_br(data_salva))
    if not cadastro and st.session_state.get("mostrar_pre_cadastro_publico"):
        info_col1, info_col2 = st.columns(2)
        with info_col1:
            st.markdown("### Enviar pre-cadastro")
        with info_col2:
            st.caption(
                "Seu pre-cadastro sera enviado para analise. A secretaria da igreja "
                "precisara aprovar antes de virar cadastro oficial."
            )
            st.info(f"Data de nascimento informada: {data_salva_br}")
        with st.form("form_pre_cadastro_publico"):
            nome = st.text_input("Nome completo")
            c1, c2, c3 = st.columns(3)
            sexo = c1.selectbox("Sexo", ["", "Masculino", "Feminino"])
            estado_civil = c2.selectbox("Estado civil", estado_civil_opcoes)
            tipo_membro = c3.selectbox("Tipo", tipo_membro_opcoes)
            funcao = st.selectbox("Funcao ministerial", funcao_opcoes)
            b1, b2, b3 = st.columns(3)
            batismo_aguas_txt = b1.text_input("Data de batismo nas aguas", placeholder="Ex.: 26/06/1979 ou 26061979")
            batismo_espirito_txt = b2.text_input("Data de batismo no Espirito Santo", placeholder="Ex.: 26/06/1979 ou 26061979")
            telefone = b3.text_input("Telefone / WhatsApp")
            st.markdown("**Endereco**")
            c3, c4 = st.columns([3, 1])
            logradouro = c3.text_input("Logradouro")
            numero = c4.text_input("Numero")
            c5, c6, c7 = st.columns(3)
            bairro = c5.text_input("Bairro")
            cidade = c6.text_input("Cidade")
            cep = c7.text_input("CEP")
            observacoes = st.text_area("Observacoes")
            if st.form_submit_button("Enviar pre-cadastro", type="primary"):
                batismo_aguas = _parse_data_opcional(batismo_aguas_txt)
                batismo_espirito = _parse_data_opcional(batismo_espirito_txt)
                if batismo_aguas_txt.strip() and not batismo_aguas:
                    st.error("Data de batismo nas aguas invalida. Use DD/MM/AAAA.")
                    return
                if batismo_espirito_txt.strip() and not batismo_espirito:
                    st.error("Data de batismo no Espirito Santo invalida. Use DD/MM/AAAA.")
                    return
                try:
                    criar_pre_cadastro_publico(
                        slug_salvo,
                        {
                            "nome": nome,
                            "cpf": cpf_salvo,
                            "data_nascimento": data_salva,
                            "sexo": sexo,
                            "estado_civil": estado_civil,
                            "tipo_membro": tipo_membro,
                            "funcao": funcao,
                            "data_batismo_aguas": batismo_aguas,
                            "data_batismo_espirito_santo": batismo_espirito,
                            "telefone": telefone,
                            "logradouro": logradouro,
                            "numero": numero,
                            "bairro": bairro,
                            "cidade": cidade,
                            "cep": cep,
                            "observacoes": observacoes,
                        },
                    )
                except Exception as exc:
                    st.error(str(exc))
                else:
                    st.success("Pre-cadastro enviado para analise da secretaria.")
                    st.session_state["mostrar_pre_cadastro_publico"] = False
        return

    if not cadastro:
        return

    info_col1, info_col2 = st.columns(2)
    with info_col1:
        st.markdown("### Atualizar cadastro")
    with info_col2:
        st.info(f"Igreja: {cadastro.get('igreja_nome', slug_salvo)}")
        st.caption(f"Data de nascimento confirmada: {data_salva_br}")
    with st.form("form_atualizar_cadastro_publico"):
        nome = st.text_input("Nome completo", value=cadastro.get("nome", ""))
        c1, c2 = st.columns(2)
        sexo = c1.selectbox(
            "Sexo",
            ["", "Masculino", "Feminino"],
            index=["", "Masculino", "Feminino"].index(cadastro.get("sexo", ""))
            if cadastro.get("sexo", "") in ["", "Masculino", "Feminino"] else 0,
        )
        estado_civil_atual = cadastro.get("estado_civil", "")
        estado_civil = c2.selectbox(
            "Estado civil",
            estado_civil_opcoes,
            index=estado_civil_opcoes.index(estado_civil_atual)
            if estado_civil_atual in estado_civil_opcoes else 0,
        )
        c_tipo, c_funcao = st.columns(2)
        tipo_atual = cadastro.get("tipo_membro", "")
        tipo_membro = c_tipo.selectbox(
            "Tipo",
            tipo_membro_opcoes,
            index=tipo_membro_opcoes.index(tipo_atual) if tipo_atual in tipo_membro_opcoes else 0,
        )
        funcao_atual = cadastro.get("funcao", "")
        funcao = c_funcao.selectbox(
            "Funcao ministerial",
            funcao_opcoes,
            index=funcao_opcoes.index(funcao_atual) if funcao_atual in funcao_opcoes else 0,
        )
        b1, b2, b3 = st.columns(3)
        batismo_aguas_txt = b1.text_input(
            "Data de batismo nas aguas",
            value=_formatar_data_br(cadastro.get("data_batismo_aguas", "")),
            placeholder="Ex.: 26/06/1979 ou 26061979",
        )
        batismo_espirito_txt = b2.text_input(
            "Data de batismo no Espirito Santo",
            value=_formatar_data_br(cadastro.get("data_batismo_espirito_santo", "")),
            placeholder="Ex.: 26/06/1979 ou 26061979",
        )
        telefone = b3.text_input("Telefone / WhatsApp", value=cadastro.get("telefone", ""))
        st.markdown("**Endereco**")
        c3, c4 = st.columns([3, 1])
        logradouro = c3.text_input("Logradouro", value=cadastro.get("logradouro", ""))
        numero = c4.text_input("Numero", value=cadastro.get("numero", ""))
        c5, c6, c7 = st.columns(3)
        bairro = c5.text_input("Bairro", value=cadastro.get("bairro", ""))
        cidade = c6.text_input("Cidade", value=cadastro.get("cidade", ""))
        cep = c7.text_input("CEP", value=cadastro.get("cep", ""))

        st.caption("CPF e data de nascimento nao sao alterados por este formulario.")
        if st.form_submit_button("Salvar atualizacao", type="primary"):
            batismo_aguas = _parse_data_opcional(batismo_aguas_txt)
            batismo_espirito = _parse_data_opcional(batismo_espirito_txt)
            if batismo_aguas_txt.strip() and not batismo_aguas:
                st.error("Data de batismo nas aguas invalida. Use DD/MM/AAAA.")
                return
            if batismo_espirito_txt.strip() and not batismo_espirito:
                st.error("Data de batismo no Espirito Santo invalida. Use DD/MM/AAAA.")
                return
            try:
                atualizar_cadastro_publico(
                    slug_salvo,
                    cadastro["id_cadastro"],
                    cpf_salvo,
                    data_salva,
                    {
                        "nome": nome,
                        "sexo": sexo,
                        "estado_civil": estado_civil,
                        "tipo_membro": tipo_membro,
                        "funcao": funcao,
                        "data_batismo_aguas": batismo_aguas,
                        "data_batismo_espirito_santo": batismo_espirito,
                        "telefone": telefone,
                        "logradouro": logradouro,
                        "numero": numero,
                        "bairro": bairro,
                        "cidade": cidade,
                        "cep": cep,
                    },
                )
            except Exception as exc:
                st.error(str(exc))
            else:
                st.success("Cadastro atualizado com sucesso.")
                st.session_state.pop("cadastro_publico_dados", None)

    if st.button("Limpar e localizar outro cadastro"):
        for key in (
            "cadastro_publico_slug",
            "cadastro_publico_cpf",
            "cadastro_publico_data",
            "cadastro_publico_data_br",
            "cadastro_publico_dados",
            "mostrar_pre_cadastro_publico",
        ):
            st.session_state.pop(key, None)
        st.rerun()


def _css_base():
    """Identidade visual da pagina institucional alinhada ao sistema."""
    return f"""
    <meta name="google" content="notranslate">
    <meta name="translate" content="no">
    <style>
        :root {{
            --fm-navy: #061B44;
            --fm-navy-deep: #041127;
            --fm-ink: #10213A;
            --fm-gold: #D4AF37;
            --fm-red: #FF4B55;
            --fm-line: #DCE4EE;
            --fm-muted: #607089;
            --fm-surface: #F6F8FB;
        }}

        * {{ box-sizing: border-box; }}
        html {{ scroll-behavior: smooth; -webkit-locale: "pt-BR"; }}
        body {{ margin: 0; }}
        .fm-page {{
            width: 100%;
            min-height: 100vh;
            overflow-x: hidden;
            background: #FFFFFF;
            color: var(--fm-ink);
            font-family: "Public Sans", -apple-system, BlinkMacSystemFont, "Segoe UI", Arial, sans-serif;
        }}

        .fm-navbar-wrap {{
            position: sticky;
            top: 0;
            z-index: 999;
            width: 100%;
            background: rgba(255,255,255,.97);
            border-bottom: 1px solid var(--fm-line);
            backdrop-filter: blur(12px);
        }}
        .fm-navbar {{
            position: relative;
            width: min(1180px, calc(100% - 32px));
            min-height: 76px;
            margin: 0 auto;
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 28px;
        }}
        .fm-logo {{
            display: inline-flex;
            align-items: center;
            color: var(--fm-navy);
            font-size: 1.55rem;
            font-weight: 800;
            letter-spacing: 0;
            text-decoration: none;
            white-space: nowrap;
        }}
        .fm-logo-img {{ display: block; max-width: 210px; max-height: 58px; object-fit: contain; }}
        .fm-menu {{ display: flex; align-items: center; justify-content: flex-end; gap: 20px; }}
        .fm-menu a {{
            color: var(--fm-ink);
            font-size: .88rem;
            font-weight: 650;
            text-decoration: none;
            white-space: nowrap;
        }}
        .fm-menu a:hover {{ color: var(--fm-gold); }}
        .fm-btn-login {{
            padding: 11px 16px;
            border-radius: 8px;
            background: var(--fm-navy);
            color: #FFFFFF !important;
        }}
        .fm-menu-toggle-input {{ position: absolute; opacity: 0; pointer-events: none; }}
        .fm-menu-toggle {{
            display: none;
            flex-direction: column;
            justify-content: center;
            gap: 5px;
            width: 30px;
            height: 24px;
            cursor: pointer;
        }}
        .fm-menu-toggle span {{
            display: block;
            height: 2px;
            width: 100%;
            background: var(--fm-navy);
            border-radius: 2px;
            transition: transform .2s ease, opacity .2s ease;
        }}
        .fm-menu-toggle-input:checked + .fm-menu-toggle span:nth-child(1) {{ transform: translateY(7px) rotate(45deg); }}
        .fm-menu-toggle-input:checked + .fm-menu-toggle span:nth-child(2) {{ opacity: 0; }}
        .fm-menu-toggle-input:checked + .fm-menu-toggle span:nth-child(3) {{ transform: translateY(-7px) rotate(-45deg); }}

        .fm-hero-new {{
            position: relative;
            min-height: 760px;
            padding: 64px 24px 56px;
            overflow: hidden;
            background: var(--fm-navy);
            color: #FFFFFF;
        }}
        .fm-hero-copy {{
            position: relative;
            z-index: 2;
            width: min(900px, 100%);
            margin: 0 auto 42px;
            text-align: center;
        }}
        .fm-eyebrow {{
            display: inline-flex;
            align-items: center;
            gap: 8px;
            margin-bottom: 16px;
            color: #F2D36B;
            font-size: .78rem;
            font-weight: 800;
            letter-spacing: .08em;
            text-transform: uppercase;
        }}
        .fm-hero-new h1 {{
            max-width: 850px;
            margin: 0 auto 18px;
            color: #FFFFFF;
            font-size: clamp(2.45rem, 5vw, 4.35rem);
            line-height: 1.03;
            letter-spacing: 0;
        }}
        .fm-hero-new h1 span {{ color: #F2D36B; }}
        .fm-hero-new p {{
            max-width: 720px;
            margin: 0 auto;
            color: #C9D5E8;
            font-size: 1.08rem;
            line-height: 1.65;
        }}
        .fm-actions {{ display: flex; justify-content: center; gap: 12px; flex-wrap: wrap; margin-top: 28px; }}
        .fm-actions a {{
            min-height: 46px;
            padding: 13px 19px;
            border-radius: 8px;
            font-weight: 750;
            text-decoration: none;
        }}
        .fm-primary {{ background: var(--fm-red); color: #FFFFFF; }}
        .fm-secondary {{ border: 1px solid #6F82A3; color: #FFFFFF; background: transparent; }}

        .fm-product-stage {{
            position: relative;
            z-index: 2;
            width: min(1120px, 100%);
            height: 390px;
            margin: 0 auto;
            display: grid;
            grid-template-columns: 208px 1fr;
            overflow: hidden;
            border: 1px solid rgba(255,255,255,.18);
            border-radius: 8px;
            background: #FFFFFF;
            box-shadow: 0 28px 70px rgba(0,0,0,.28);
            text-align: left;
        }}
        .fm-product-nav {{ padding: 18px 15px; background: var(--fm-navy-deep); color: #FFFFFF; }}
        .fm-product-brand {{
            padding: 4px 8px 16px;
            margin-bottom: 12px;
            border-bottom: 1px solid rgba(212,175,55,.45);
            color: #F2D36B;
            font-size: .82rem;
            font-weight: 800;
        }}
        .fm-product-group {{ margin: 13px 8px 5px; color: #8EACC9; font-size: .53rem; font-weight: 800; text-transform: uppercase; }}
        .fm-product-link {{
            display: flex;
            align-items: center;
            gap: 8px;
            min-height: 27px;
            padding: 6px 9px;
            border-radius: 6px;
            color: #E5ECF7;
            font-size: .62rem;
            font-weight: 700;
        }}
        .fm-product-link.active {{ background: rgba(212,175,55,.20); color: #F2D36B; }}
        .fm-dot {{ width: 7px; height: 7px; border-radius: 2px; flex: 0 0 7px; background: #55D6BE; }}
        .fm-dot.gold {{ background: #F2C94C; }} .fm-dot.red {{ background: #FF6B70; }}
        .fm-dot.purple {{ background: #A88BFA; }} .fm-dot.blue {{ background: #69A7FF; }}
        .fm-product-main {{ padding: 28px; background: #F7F9FC; color: var(--fm-ink); }}
        .fm-product-top {{ display: flex; justify-content: space-between; align-items: center; margin-bottom: 24px; }}
        .fm-product-top strong {{ color: var(--fm-navy); font-size: 1.15rem; }}
        .fm-product-top span {{ color: var(--fm-muted); font-size: .72rem; }}
        .fm-kpis {{ display: grid; grid-template-columns: repeat(4, minmax(0,1fr)); gap: 12px; }}
        .fm-kpi {{ padding: 15px; border: 1px solid var(--fm-line); border-radius: 7px; background: #FFFFFF; }}
        .fm-kpi small {{ display: block; margin-bottom: 8px; color: var(--fm-muted); font-size: .65rem; }}
        .fm-kpi strong {{ color: var(--fm-navy); font-size: .95rem; }}
        .fm-product-lower {{ display: grid; grid-template-columns: 1.55fr .85fr; gap: 14px; margin-top: 14px; }}
        .fm-product-panel {{ min-height: 180px; padding: 16px; border: 1px solid var(--fm-line); border-radius: 7px; background: #FFFFFF; }}
        .fm-product-panel h3 {{ margin: 0 0 18px; color: var(--fm-navy); font-size: .75rem; }}
        .fm-bars-new {{ height: 112px; display: flex; align-items: flex-end; gap: 11px; border-bottom: 1px solid var(--fm-line); }}
        .fm-bars-new i {{ flex: 1; min-width: 8px; background: #1D9E75; border-radius: 3px 3px 0 0; }}
        .fm-bars-new i:nth-child(even) {{ background: var(--fm-red); }}
        .fm-ring {{ width: 120px; height: 120px; margin: 6px auto 0; border: 22px solid #1D9E75; border-right-color: #F2C94C; border-bottom-color: var(--fm-red); border-radius: 50%; }}

        .fm-intro-band {{ padding: 44px 24px; border-bottom: 1px solid var(--fm-line); background: #FFFFFF; }}
        .fm-intro-grid {{
            width: min(1120px, 100%);
            margin: 0 auto;
            display: grid;
            grid-template-columns: repeat(3, minmax(0,1fr));
            gap: 28px;
        }}
        .fm-intro-item {{ display: grid; grid-template-columns: 42px 1fr; gap: 13px; }}
        .fm-intro-icon {{
            width: 42px; height: 42px; display: grid; place-items: center;
            border-radius: 8px; background: #EAF1FA; color: var(--fm-navy); font-size: 1.1rem;
        }}
        .fm-intro-item h3 {{ margin: 1px 0 5px; color: var(--fm-navy); font-size: .98rem; }}
        .fm-intro-item p {{ margin: 0; color: var(--fm-muted); font-size: .86rem; line-height: 1.55; }}

        .fm-section-new {{ padding: 74px 24px; background: var(--fm-surface); }}
        .fm-section-head {{ width: min(760px,100%); margin: 0 auto 38px; text-align: center; }}
        .fm-section-head small {{ color: #B18412; font-size: .72rem; font-weight: 850; letter-spacing: .08em; text-transform: uppercase; }}
        .fm-section-head h2 {{ margin: 10px 0 12px; color: var(--fm-navy); font-size: clamp(1.9rem,4vw,2.7rem); letter-spacing: 0; }}
        .fm-section-head p {{ margin: 0; color: var(--fm-muted); line-height: 1.65; }}
        .fm-module-groups {{ width: min(1120px,100%); margin: 0 auto; display: grid; gap: 16px; }}
        .fm-module-row {{
            display: grid;
            grid-template-columns: 165px 1fr;
            min-height: 118px;
            overflow: hidden;
            border: 1px solid var(--fm-line);
            border-radius: 8px;
            background: #FFFFFF;
        }}
        .fm-module-label {{ padding: 22px; border-right: 1px solid var(--fm-line); background: var(--fm-navy); color: #FFFFFF; }}
        .fm-module-label span {{ display: block; color: #F2D36B; font-size: 1.2rem; margin-bottom: 8px; }}
        .fm-module-label strong {{ font-size: .82rem; letter-spacing: .05em; text-transform: uppercase; }}
        .fm-module-list {{ display: grid; grid-template-columns: repeat(4,minmax(0,1fr)); }}
        .fm-module {{ padding: 20px 18px; border-right: 1px solid var(--fm-line); }}
        .fm-module:last-child {{ border-right: 0; }}
        .fm-module b {{ display: block; margin-bottom: 6px; color: var(--fm-navy); font-size: .88rem; }}
        .fm-module p {{ margin: 0; color: var(--fm-muted); font-size: .75rem; line-height: 1.45; }}

        .fm-about {{ padding: 72px 24px; background: #FFFFFF; }}
        .fm-about-inner {{ width: min(1120px,100%); margin: 0 auto; display: grid; grid-template-columns: .85fr 1.15fr; gap: 72px; align-items: start; }}
        .fm-about h2 {{ margin: 0 0 15px; color: var(--fm-navy); font-size: 2.25rem; letter-spacing: 0; }}
        .fm-about p {{ color: var(--fm-muted); line-height: 1.75; }}
        .fm-check-list {{ display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }}
        .fm-check-item {{ padding: 14px 15px; border-left: 3px solid var(--fm-gold); background: var(--fm-surface); color: var(--fm-ink); font-size: .86rem; }}

        .fm-cta-new {{ padding: 58px 24px; background: var(--fm-navy); color: #FFFFFF; }}
        .fm-cta-inner {{ width: min(1120px,100%); margin: 0 auto; display: flex; align-items: center; justify-content: space-between; gap: 30px; }}
        .fm-cta-new h2 {{ margin: 0 0 8px; color: #FFFFFF; font-size: 2rem; letter-spacing: 0; }}
        .fm-cta-new p {{ margin: 0; color: #C9D5E8; }}
        .fm-gold-btn {{ padding: 14px 20px; border-radius: 8px; background: var(--fm-gold); color: #172238; font-weight: 800; text-decoration: none; white-space: nowrap; }}

        .fm-footer {{ padding: 30px 24px; background: var(--fm-navy-deep); color: #AFC0D6; }}
        .fm-footer-inner {{ width: min(1120px,100%); margin: 0 auto; display: flex; justify-content: space-between; gap: 24px; font-size: .78rem; }}
        .fm-footer a {{ margin-left: 16px; color: #DCE6F3; text-decoration: none; }}

        .fm-page-update {{ background: var(--fm-surface); }}
        .fm-public-shell, .fm-legal, .fm-contact {{ color: var(--fm-ink); }}
        .fm-simple-page {{ min-height: 70vh; padding: 58px 24px; background: var(--fm-surface); }}
        .fm-simple-card {{
            width: min(880px, 100%);
            margin: 0 auto;
            padding: 38px;
            border: 1px solid var(--fm-line);
            border-radius: 8px;
            background: #FFFFFF;
            box-shadow: 0 16px 38px rgba(6,27,68,.07);
        }}
        .fm-simple-card h1 {{ margin: 0 0 18px; color: var(--fm-navy); font-size: 2.25rem; letter-spacing: 0; }}
        .fm-simple-card h2 {{ margin: 28px 0 10px; color: var(--fm-navy); font-size: 1.08rem; }}
        .fm-simple-card p {{ color: var(--fm-muted); line-height: 1.72; }}
        .fm-update-page {{ padding: 12px 24px 2px; }}
        .fm-update-card {{ width: min(920px,100%); margin: 0 auto; }}
        .fm-update-card h1 {{ margin: 0 0 10px; color: var(--fm-navy); font-size: 2.15rem; letter-spacing: 0; }}
        .fm-update-card p {{ max-width: 760px; margin: 0; color: var(--fm-muted); line-height: 1.65; }}

        @media (max-width: 980px) {{
            .fm-menu-toggle {{ display: flex; }}
            .fm-menu {{
                position: absolute;
                top: 100%;
                left: 0;
                right: 0;
                flex-direction: column;
                align-items: stretch;
                gap: 0;
                background: #FFFFFF;
                border-bottom: 1px solid var(--fm-line);
                box-shadow: 0 16px 30px rgba(6,27,68,.12);
                max-height: 0;
                overflow: hidden;
                transition: max-height .25s ease;
            }}
            .fm-menu a:not(.fm-btn-login) {{
                display: block;
                padding: 14px 24px;
                border-bottom: 1px solid var(--fm-line);
            }}
            .fm-btn-login {{ margin: 14px 24px; text-align: center; }}
            .fm-menu-toggle-input:checked ~ .fm-menu {{ max-height: 70vh; overflow-y: auto; }}
            .fm-product-stage {{ grid-template-columns: 170px 1fr; }}
            .fm-kpis {{ grid-template-columns: repeat(2,minmax(0,1fr)); }}
            .fm-module-list {{ grid-template-columns: repeat(2,minmax(0,1fr)); }}
            .fm-module:nth-child(2) {{ border-right: 0; }}
            .fm-module:nth-child(-n+2) {{ border-bottom: 1px solid var(--fm-line); }}
            .fm-about-inner {{ grid-template-columns: 1fr; gap: 32px; }}
        }}
        @media (max-width: 700px) {{
            .fm-navbar {{ min-height: 66px; }}
            .fm-logo-img {{ max-width: 155px; max-height: 48px; }}
            .fm-btn-login {{ padding: 10px 12px; font-size: .78rem !important; }}
            .fm-hero-new {{ min-height: auto; padding: 44px 16px 32px; }}
            .fm-hero-new h1 {{ font-size: 2.5rem; }}
            .fm-product-stage {{ height: 340px; grid-template-columns: 92px 1fr; }}
            .fm-product-nav {{ padding: 12px 7px; }}
            .fm-product-brand {{ padding: 3px 3px 11px; font-size: .58rem; }}
            .fm-product-group {{ margin: 9px 3px 3px; font-size: .39rem; }}
            .fm-product-link {{ min-height: 22px; padding: 4px; gap: 4px; font-size: .43rem; }}
            .fm-dot {{ width: 5px; height: 5px; flex-basis: 5px; }}
            .fm-product-main {{ padding: 15px 12px; }}
            .fm-kpis {{ gap: 7px; }}
            .fm-kpi {{ padding: 10px 8px; }}
            .fm-kpi strong {{ font-size: .7rem; }}
            .fm-product-lower {{ grid-template-columns: 1fr; }}
            .fm-product-panel:last-child {{ display: none; }}
            .fm-intro-grid {{ grid-template-columns: 1fr; }}
            .fm-section-new, .fm-about {{ padding: 54px 16px; }}
            .fm-module-row {{ grid-template-columns: 1fr; }}
            .fm-module-label {{ border-right: 0; padding: 15px 17px; }}
            .fm-module-label span {{ display: inline; margin-right: 8px; }}
            .fm-module-list {{ grid-template-columns: 1fr; }}
            .fm-module {{ border-right: 0; border-bottom: 1px solid var(--fm-line); }}
            .fm-module:last-child {{ border-bottom: 0; }}
            .fm-module:nth-child(-n+2) {{ border-bottom: 1px solid var(--fm-line); }}
            .fm-check-list {{ grid-template-columns: 1fr; }}
            .fm-cta-inner, .fm-footer-inner {{ align-items: flex-start; flex-direction: column; }}
            .fm-footer a {{ display: inline-block; margin: 7px 13px 0 0; }}
            .fm-simple-page {{ padding: 32px 16px; }}
            .fm-simple-card {{ padding: 24px 20px; }}
            .fm-update-page {{ padding: 10px 18px 2px; }}
        }}
    </style>
    """


def _navbar():
    return f"""
    <header class="fm-navbar-wrap">
        <nav class="fm-navbar" aria-label="Navegação principal">
            {_marca_fielmordomo_html()}
            <input type="checkbox" id="fm-menu-toggle" class="fm-menu-toggle-input">
            <label for="fm-menu-toggle" class="fm-menu-toggle" aria-label="Abrir menu">
                <span></span><span></span><span></span>
            </label>
            <div class="fm-menu">
                <a href="?pagina=inicio#modulos" target="_top">Módulos</a>
                <a href="?pagina=agenda" target="_top">Agenda</a>
                <a href="?pagina=leitura-biblica" target="_top">Plano de Leitura</a>
                <a href="?pagina=atualizar-cadastro" target="_top">Atualizar cadastro</a>
                <a href="?pagina=pedidos-oracao" target="_top">Pedidos de oração</a>
                <a href="?pagina=contato" target="_top">Contato</a>
                <a class="fm-btn-login" href="?pagina=login" target="_top">Acessar sistema</a>
            </div>
        </nav>
    </header>
    """


def _footer():
    return """
    <footer class="fm-footer">
        <div class="fm-footer-inner">
            <div>FielMordomo © 2026. Gestão integrada para igrejas.</div>
            <div>
                <a href="?pagina=agenda" target="_top">Agenda</a>
                <a href="?pagina=leitura-biblica" target="_top">Plano de Leitura</a>
                <a href="?pagina=contato" target="_top">Contato</a>
                <a href="?pagina=privacidade" target="_top">Privacidade e LGPD</a>
                <a href="?pagina=termos" target="_top">Termos de uso</a>
            </div>
        </div>
    </footer>
    """


def _home():
    return """
    <main>
        <section class="fm-hero-new">
            <div class="fm-hero-copy">
                <div class="fm-eyebrow">Gestão completa para igrejas</div>
                <h1>FielMordomo: organização para <span>servir melhor</span></h1>
                <p>Finanças, membros, ministérios, eventos e acompanhamento pastoral reunidos em uma plataforma segura, clara e preparada para a rotina da igreja.</p>
                <div class="fm-actions">
                    <a class="fm-primary" href="?pagina=login" target="_top">Acessar sistema</a>
                    <a class="fm-secondary" href="#modulos">Conhecer os módulos</a>
                </div>
            </div>

            <div class="fm-product-stage" aria-label="Visão do sistema FielMordomo">
                <aside class="fm-product-nav">
                    <div class="fm-product-brand">FielMordomo</div>
                    <div class="fm-product-link active"><i class="fm-dot gold"></i>Início</div>
                    <div class="fm-product-group">Financeiro</div>
                    <div class="fm-product-link"><i class="fm-dot"></i>Dashboard</div>
                    <div class="fm-product-link"><i class="fm-dot gold"></i>Lançamentos</div>
                    <div class="fm-product-link"><i class="fm-dot blue"></i>Relatórios</div>
                    <div class="fm-product-group">Cadastros</div>
                    <div class="fm-product-link"><i class="fm-dot red"></i>Aniversários</div>
                    <div class="fm-product-link"><i class="fm-dot purple"></i>Membros</div>
                    <div class="fm-product-group">Ministério</div>
                    <div class="fm-product-link"><i class="fm-dot blue"></i>Círculo de Oração</div>
                    <div class="fm-product-link"><i class="fm-dot"></i>Escola Bíblica</div>
                    <div class="fm-product-link"><i class="fm-dot gold"></i>GFC</div>
                    <div class="fm-product-group">Eventos</div>
                    <div class="fm-product-link"><i class="fm-dot purple"></i>Agenda</div>
                </aside>
                <div class="fm-product-main">
                    <div class="fm-product-top"><strong>Dashboard financeiro</strong><span>Visão do mês</span></div>
                    <div class="fm-kpis">
                        <div class="fm-kpi"><small>Entradas</small><strong>R$ 45.320,50</strong></div>
                        <div class="fm-kpi"><small>Despesas</small><strong>R$ 18.540,30</strong></div>
                        <div class="fm-kpi"><small>Saldo</small><strong>R$ 26.780,20</strong></div>
                        <div class="fm-kpi"><small>Membros ativos</small><strong>248</strong></div>
                    </div>
                    <div class="fm-product-lower">
                        <div class="fm-product-panel">
                            <h3>Movimento financeiro</h3>
                            <div class="fm-bars-new">
                                <i style="height:45%"></i><i style="height:26%"></i>
                                <i style="height:62%"></i><i style="height:31%"></i>
                                <i style="height:78%"></i><i style="height:38%"></i>
                                <i style="height:68%"></i><i style="height:29%"></i>
                            </div>
                        </div>
                        <div class="fm-product-panel"><h3>Distribuição das receitas</h3><div class="fm-ring"></div></div>
                    </div>
                </div>
            </div>
        </section>

        <section class="fm-intro-band" aria-label="Benefícios principais">
            <div class="fm-intro-grid">
                <div class="fm-intro-item"><div class="fm-intro-icon">✓</div><div><h3>Rotinas centralizadas</h3><p>As áreas da igreja trabalham em um ambiente único e organizado.</p></div></div>
                <div class="fm-intro-item"><div class="fm-intro-icon">▣</div><div><h3>Informação confiável</h3><p>Indicadores, históricos e relatórios apoiam decisões responsáveis.</p></div></div>
                <div class="fm-intro-item"><div class="fm-intro-icon">◆</div><div><h3>Acessos controlados</h3><p>Cada perfil visualiza somente os recursos necessários à sua função.</p></div></div>
            </div>
        </section>

        <section class="fm-section-new" id="modulos">
            <div class="fm-section-head">
                <small>Estrutura do sistema</small>
                <h2>Uma plataforma para toda a administração</h2>
                <p>A organização segue a mesma lógica da barra lateral do sistema, facilitando o acesso e a aprendizagem de cada equipe.</p>
            </div>
            <div class="fm-module-groups">
                <div class="fm-module-row">
                    <div class="fm-module-label"><span>▥</span><strong>Financeiro</strong></div>
                    <div class="fm-module-list">
                        <div class="fm-module"><b>Dashboard</b><p>Indicadores, comparativos e saúde financeira.</p></div>
                        <div class="fm-module"><b>Lançamentos</b><p>Dízimos, ofertas, receitas, despesas e comprovantes.</p></div>
                        <div class="fm-module"><b>Relatórios</b><p>Prestação de contas com filtros e exportações.</p></div>
                        <div class="fm-module"><b>Tesoureiros</b><p>Perfis e autorizações para a equipe financeira.</p></div>
                    </div>
                </div>
                <div class="fm-module-row">
                    <div class="fm-module-label"><span>●</span><strong>Cadastros</strong></div>
                    <div class="fm-module-list">
                        <div class="fm-module"><b>Aniversários</b><p>Agenda e comunicação com aniversariantes.</p></div>
                        <div class="fm-module"><b>Membros</b><p>Cadastro completo e histórico congregacional.</p></div>
                        <div class="fm-module"><b>Visitantes</b><p>Recepção, origem e acompanhamento de visitas.</p></div>
                    </div>
                </div>
                <div class="fm-module-row">
                    <div class="fm-module-label"><span>✦</span><strong>Ministério</strong></div>
                    <div class="fm-module-list">
                        <div class="fm-module"><b>Círculo de Oração</b><p>Matrículas, chamadas, líderes e relatórios.</p></div>
                        <div class="fm-module"><b>Escola Bíblica</b><p>Classes, alunos, escalas e frequência.</p></div>
                        <div class="fm-module"><b>Grupos Familiares</b><p>GFCs, cultos, líderes e participantes.</p></div>
                        <div class="fm-module"><b>Outros ministérios</b><p>Pedidos de oração e reunião de obreiros.</p></div>
                    </div>
                </div>
                <div class="fm-module-row">
                    <div class="fm-module-label"><span>▤</span><strong>Eventos</strong></div>
                    <div class="fm-module-list">
                        <div class="fm-module"><b>Agenda</b><p>Eventos, cartazes, responsáveis e divulgação.</p></div>
                        <div class="fm-module"><b>Monitoramento Geo</b><p>Frequência com consentimento e geolocalização.</p></div>
                        <div class="fm-module"><b>Backup</b><p>Proteção e recuperação das informações.</p></div>
                        <div class="fm-module"><b>Minha conta</b><p>Preferências, segurança e configurações.</p></div>
                    </div>
                </div>
            </div>
        </section>

        <section class="fm-about" id="sobre">
            <div class="fm-about-inner">
                <div><h2>Feito para a realidade da igreja</h2><p>O FielMordomo conecta tesouraria, secretaria, liderança e ministérios sem perder a simplicidade necessária ao trabalho diário.</p><p>As informações permanecem separadas por igreja e os acessos respeitam as responsabilidades de cada usuário.</p></div>
                <div class="fm-check-list">
                    <div class="fm-check-item">Controle financeiro e prestação de contas</div>
                    <div class="fm-check-item">Cadastros e acompanhamento de membros</div>
                    <div class="fm-check-item">Chamadas e matrículas por ministério</div>
                    <div class="fm-check-item">Agenda pública com cartazes</div>
                    <div class="fm-check-item">Comunicação por WhatsApp</div>
                    <div class="fm-check-item">Backup e isolamento de dados</div>
                </div>
            </div>
        </section>

        <section class="fm-cta-new">
            <div class="fm-cta-inner">
                <div><h2>Administração clara. Ministério fortalecido.</h2><p>Acesse sua igreja e continue o trabalho de onde parou.</p></div>
                <a class="fm-gold-btn" href="?pagina=login" target="_top">Entrar no FielMordomo</a>
            </div>
        </section>
    </main>
    """


def _conteudo_da_pagina():
    pagina = _pagina_atual()

    if pagina in ("", "inicio", "sobre", "recursos"):
        return _navbar() + _home() + _footer()

    if pagina == "contato":
        return _navbar() + _contato() + _footer()

    if pagina == "privacidade":
        return _navbar() + _privacidade() + _footer()

    if pagina == "termos":
        return _navbar() + _termos() + _footer()

    return _navbar() + _home() + _footer()


def _render_html(html_final: str):
    """
    Usa st.html quando disponivel para os links funcionarem no proprio app.
    Se a versao do Streamlit for antiga, usa st.markdown como alternativa.
    """
    if hasattr(st, "html"):
        st.html(html_final)
    else:
        st.markdown(html_final, unsafe_allow_html=True)


def _html_sem_indentacao(html_final: str) -> str:
    return "\n".join(linha.strip() for linha in str(html_final).splitlines() if linha.strip())


def _fmt_data_evento(valor):
    try:
        return datetime.date.fromisoformat(str(valor)).strftime("%d/%m/%Y")
    except Exception:
        return str(valor or "")


def _cartaz_evento_html(slug, id_evento):
    if not slug or not id_evento:
        return ""
    try:
        from data.repository import obter_evento_cartaz

        cartaz = obter_evento_cartaz(slug, int(id_evento))
    except Exception:
        LOGGER.exception("Não foi possível carregar o cartaz do evento.")
        return ""
    if not cartaz:
        return ""

    mime = str(cartaz.get("mime", "") or "application/octet-stream")
    nome = html.escape(str(cartaz.get("nome", "") or "cartaz-evento"), quote=True)
    b64 = base64.b64encode(cartaz.get("bytes", b"")).decode("utf-8")
    if mime.startswith("image/"):
        return (
            '<div class="fm-event-poster">'
            f'<img src="data:{mime};base64,{b64}" alt="Cartaz do evento">'
            '</div>'
        )
    return (
        '<div class="fm-event-poster-download">'
        f'<a href="data:{mime};base64,{b64}" download="{nome}">'
        'Baixar cartaz do evento</a>'
        '</div>'
    )


def _render_cards_eventos(df, titulo, slug=None):
    st.markdown(f"### {titulo}")
    if df.empty:
        st.info("Nenhum evento encontrado.")
        return
    for _, row in df.iterrows():
        data = html.escape(_fmt_data_evento(row.get("data", "")))
        hora_inicio = html.escape(str(row.get("hora_inicio", "") or ""))
        hora_fim = html.escape(str(row.get("hora_fim", "") or ""))
        horario = hora_inicio if not hora_fim else f"{hora_inicio} as {hora_fim}"
        horario = html.escape(horario)
        titulo_evento = html.escape(str(row.get("titulo", "") or "Evento"))
        local = html.escape(str(row.get("local", "") or "Local a confirmar"))
        departamento = html.escape(str(row.get("departamento", "") or ""))
        descricao = html.escape(str(row.get("descricao", "") or ""))
        visibilidade = html.escape(str(row.get("visibilidade", "") or "Público"))
        responsavel = html.escape(str(row.get("responsavel", "") or ""))
        contato = html.escape(str(row.get("contato", "") or ""))
        cartaz_html = ""
        if int(row.get("tem_cartaz", 0) or 0) == 1:
            cartaz_html = _cartaz_evento_html(slug, row.get("id_evento"))
        meta_extra = ""
        if departamento:
            meta_extra += f"<span>{departamento}</span>"
        if responsavel:
            meta_extra += f"<span>Responsável: {responsavel}</span>"
        if contato:
            meta_extra += f"<span>Contato: {contato}</span>"
        st.markdown(
            _html_sem_indentacao(f"""
            <div class="fm-event-card">
                <div class="fm-event-date">
                    <strong>{data}</strong>
                    <small>{horario or "Horário a confirmar"}</small>
                </div>
                <div class="fm-event-body">
                    {cartaz_html}
                    <div class="fm-event-top">
                        <div class="fm-event-title">{titulo_evento}</div>
                        <span>{visibilidade}</span>
                    </div>
                    <p class="fm-event-local">{local}</p>
                    <p>{descricao}</p>
                    <div class="fm-event-meta">{meta_extra}</div>
                </div>
            </div>
            """),
            unsafe_allow_html=True,
        )


def _render_agenda_publica():
    from data.repository import (
        listar_eventos_publicos,
        listar_igrejas,
        validar_membro_eventos_por_cpf,
    )

    st.markdown(
        """
        <style>
            .fm-public-shell {
                max-width: 1040px;
                margin: 8px auto 28px;
                padding: 0 18px;
            }
            .fm-public-hero {
                background: #FFFFFF;
                border: 1px solid #E5E7EB;
                border-radius: 12px;
                padding: 18px 24px;
                box-shadow: 0 18px 45px rgba(6, 27, 68, .08);
                margin-bottom: 10px;
            }
            .fm-public-hero h1 {
                color: #061B44;
                margin: 0 0 8px;
                font-size: 2rem;
            }
            .fm-public-hero p {
                color: #475569;
                margin: 0;
                line-height: 1.55;
            }
            .fm-event-card {
                display: grid;
                grid-template-columns: 150px 1fr;
                gap: 18px;
                background: #FFFFFF;
                border: 1px solid #E5E7EB;
                border-radius: 18px;
                padding: 18px;
                margin: 12px 0;
                box-shadow: 0 14px 32px rgba(6, 27, 68, .07);
            }
            .fm-event-date {
                background: #061B44;
                color: #FFFFFF;
                border-radius: 15px;
                padding: 16px;
                text-align: center;
                align-self: start;
            }
            .fm-event-date strong {
                display: block;
                font-size: 1.1rem;
            }
            .fm-event-date small {
                color: rgba(255,255,255,.78);
            }
            .fm-event-top {
                display: flex;
                justify-content: space-between;
                gap: 12px;
                align-items: flex-start;
            }
            .fm-event-top .fm-event-title {
                margin: 0 0 4px;
                color: #061B44;
                font-size: 1.17rem;
                font-weight: 800;
                line-height: 1.3;
            }
            .fm-event-top span {
                background: #EAF2FB;
                color: #0B3A66;
                border-radius: 999px;
                padding: 5px 10px;
                font-size: .78rem;
                font-weight: 700;
                white-space: nowrap;
            }
            .fm-event-body p {
                color: #475569;
                margin: 6px 0;
                line-height: 1.5;
            }
            .fm-event-poster {
                width: 100%;
                margin: 0 0 14px;
                border-radius: 14px;
                overflow: hidden;
                border: 1px solid #E2E8F0;
                background: #F8FAFC;
            }
            .fm-event-poster img {
                display: block;
                width: 100%;
                max-height: 520px;
                object-fit: contain;
                background: #F8FAFC;
            }
            .fm-event-poster-download {
                margin: 0 0 14px;
            }
            .fm-event-poster-download a {
                display: inline-block;
                background: #061B44;
                color: #FFFFFF;
                text-decoration: none;
                border-radius: 999px;
                padding: 9px 14px;
                font-weight: 800;
                font-size: .86rem;
            }
            .fm-event-local {
                font-weight: 700;
                color: #1F2933 !important;
            }
            .fm-event-meta {
                display: flex;
                flex-wrap: wrap;
                gap: 8px;
                margin-top: 10px;
            }
            .fm-event-meta span {
                background: #F8FAFC;
                border: 1px solid #E2E8F0;
                color: #475569;
                border-radius: 999px;
                padding: 5px 10px;
                font-size: .82rem;
            }
            @media (max-width: 720px) {
                .fm-event-card {
                    grid-template-columns: 1fr;
                }
                .fm-event-date {
                    text-align: left;
                }
            }
        </style>
        <div class="fm-public-shell">
            <div class="fm-public-hero">
                <h1>Agenda da Igreja</h1>
                <p>
                    Consulte os próximos eventos públicos. Membros podem informar o CPF
                    para visualizar também os eventos internos liberados para a membresia.
                    Eventos restritos não são exibidos nesta página.
                </p>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    igrejas = listar_igrejas()
    igrejas = igrejas[igrejas["ativa"].fillna(0).astype(int) == 1] if not igrejas.empty else igrejas
    if igrejas.empty:
        st.info("Nenhuma igreja ativa encontrada para exibir agenda.")
        return

    opcoes = {
        f'{row["nome"]} ({row["slug"]})': row["slug"]
        for _, row in igrejas.iterrows()
    }
    escolha = st.selectbox("Selecione a igreja", list(opcoes.keys()), key="agenda_publica_igreja")
    slug = opcoes[escolha]
    hoje = datetime.date.today().isoformat()

    chave_validado = f"agenda_membro_validado_{slug}"
    chave_nome = f"agenda_membro_nome_{slug}"
    incluir_membros = bool(st.session_state.get(chave_validado))

    with st.form("form_agenda_membro"):
        cpf = st.text_input(
            "CPF do membro para acessar eventos internos",
            placeholder="Digite apenas números",
            type="password",
        )
        enviado = st.form_submit_button("Validar CPF", type="primary")
        if enviado:
            try:
                membro = validar_membro_eventos_por_cpf(slug, cpf)
                if membro:
                    st.session_state[chave_validado] = True
                    st.session_state[chave_nome] = membro.get("nome", "")
                    st.success("CPF validado. Eventos para membros foram liberados.")
                    st.rerun()
                else:
                    st.error("CPF não localizado no cadastro de membros ativos desta igreja.")
            except Exception as exc:
                st.error(str(exc))

    if incluir_membros:
        nome = st.session_state.get(chave_nome, "membro")
        st.info(f"Acesso de membro validado para {nome}. Eventos restritos continuam ocultos.")
        if st.button("Encerrar acesso de membro", key=f"agenda_limpar_{slug}"):
            st.session_state.pop(chave_validado, None)
            st.session_state.pop(chave_nome, None)
            st.rerun()

    eventos = listar_eventos_publicos(slug, incluir_membros=incluir_membros, data_inicio=hoje)
    titulo = "Eventos públicos e eventos para membros" if incluir_membros else "Eventos públicos"
    _render_cards_eventos(eventos, titulo, slug=slug)


def render_institucional():
    st.markdown(
        """
        <meta name="google" content="notranslate">
        <meta name="translate" content="no">
        <style>
            .block-container {
                padding: 0 !important;
                max-width: 100% !important;
            }

            header[data-testid="stHeader"],
            #MainMenu,
            footer {
                display: none !important;
                visibility: hidden !important;
            }

            section[data-testid="stSidebar"] {
                display: none !important;
            }
        </style>
        """,
        unsafe_allow_html=True,
    )

    if _pagina_atual() == "atualizar-cadastro":
        st.markdown(
            """
            <style>
                .stApp {
                    background: #F5F7FA !important;
                }
                .block-container {
                    padding: 0 0 1rem 0 !important;
                    margin: 0 !important;
                    max-width: 100% !important;
                }
                main .block-container > div:first-child {
                    margin-top: 0 !important;
                    padding-top: 0 !important;
                }
                div[data-testid="stVerticalBlock"] {
                    gap: 0 !important;
                }
                div[data-testid="stVerticalBlock"] > div {
                    padding-top: 0 !important;
                    margin-top: 0 !important;
                }
                div[data-testid="stHtml"] {
                    margin: 0 !important;
                    padding: 0 !important;
                }
                div[data-testid="stHtml"] iframe {
                    min-height: 0 !important;
                }
                div[data-testid="stForm"] {
                    max-width: 920px;
                    margin: 16px auto 8px auto !important;
                    padding: 0 24px !important;
                }
                div[data-testid="stAlert"] {
                    max-width: 920px;
                    margin: 8px auto !important;
                }
            </style>
            """,
            unsafe_allow_html=True,
        )
        st.markdown(
            _html_sem_indentacao(
                _css_base()
                + _navbar()
            ),
            unsafe_allow_html=True,
        )
        _render_atualizar_cadastro_publico()
        st.markdown(_html_sem_indentacao(_footer()), unsafe_allow_html=True)
        return

    if _pagina_atual() == "pedidos-oracao":
        st.markdown(
            """
            <style>
                .stApp {
                    background: #F5F7FA !important;
                }
                .block-container {
                    padding: 0 0 1rem 0 !important;
                    margin: 0 !important;
                    max-width: 100% !important;
                }
                div[data-testid="stForm"],
                div[data-testid="stAlert"],
                div[data-testid="stMarkdownContainer"],
                div[data-testid="stSuccess"] {
                    max-width: 920px;
                    margin-left: auto !important;
                    margin-right: auto !important;
                }
                div[data-testid="stVerticalBlock"] {
                    gap: .25rem !important;
                }
                div[data-testid="stForm"] {
                    margin-top: 0 !important;
                    margin-bottom: 8px !important;
                }
                main .block-container > div:first-child {
                    margin-top: 0 !important;
                    padding-top: 0 !important;
                }
            </style>
            """,
            unsafe_allow_html=True,
        )
        st.markdown(
            _html_sem_indentacao(
                _css_base()
                + _navbar()
            ),
            unsafe_allow_html=True,
        )
        from modules.pedidos_oracao import render_publico

        render_publico()
        st.markdown(_html_sem_indentacao(_footer()), unsafe_allow_html=True)
        return

    if _pagina_atual() == "agenda":
        st.markdown(
            """
            <style>
                .stApp {
                    background: #F5F7FA !important;
                }
                .block-container {
                    padding: 0 0 1rem 0 !important;
                    margin: 0 !important;
                    max-width: 100% !important;
                }
                div[data-testid="stForm"],
                div[data-testid="stAlert"],
                div[data-testid="stMarkdownContainer"],
                div[data-testid="stSelectbox"] {
                    max-width: 1040px;
                    margin-left: auto !important;
                    margin-right: auto !important;
                }
                div[data-testid="stSelectbox"] {
                    padding-left: 18px !important;
                    padding-right: 18px !important;
                    box-sizing: border-box !important;
                }
                div[data-testid="stForm"] {
                    box-sizing: border-box !important;
                    margin-top: 0 !important;
                    margin-bottom: 8px !important;
                }
                div[data-testid="stVerticalBlock"] {
                    gap: .25rem !important;
                }
                main .block-container > div:first-child {
                    margin-top: 0 !important;
                    padding-top: 0 !important;
                }
            </style>
            """,
            unsafe_allow_html=True,
        )
        st.markdown(
            _html_sem_indentacao(
                _css_base()
                + _navbar()
            ),
            unsafe_allow_html=True,
        )
        _render_agenda_publica()
        st.markdown(_html_sem_indentacao(_footer()), unsafe_allow_html=True)
        return

    if _pagina_atual() == "leitura-biblica":
        st.markdown(
            """
            <style>
                .stApp {
                    background: #F5F7FA !important;
                }
                .block-container {
                    padding: 0 0 1rem 0 !important;
                    margin: 0 !important;
                    max-width: 100% !important;
                }
                div[data-testid="stForm"],
                div[data-testid="stElementContainer"] {
                    max-width: 920px;
                    margin-left: auto !important;
                    margin-right: auto !important;
                }
                div[data-testid="stButton"] button {
                    width: 100%;
                }
                div[data-testid="stVerticalBlock"] {
                    gap: .25rem !important;
                }
                div[data-testid="stForm"] {
                    margin-top: 0 !important;
                    margin-bottom: 8px !important;
                }
                main .block-container > div:first-child {
                    margin-top: 0 !important;
                    padding-top: 0 !important;
                }
                .leitura-hero {
                    background: linear-gradient(135deg, #061B44 0%, #0B3A66 100%);
                    border-radius: 20px;
                    padding: 34px 32px;
                    margin: 4px 0 18px;
                    color: #FFFFFF;
                }
                .leitura-hero-eyebrow {
                    display: block;
                    color: #F2D36B;
                    font-size: .78rem;
                    font-weight: 800;
                    letter-spacing: .08em;
                    text-transform: uppercase;
                    margin-bottom: 14px;
                }
                .leitura-hero-badges {
                    display: flex;
                    gap: 8px;
                    flex-wrap: wrap;
                    margin-bottom: 16px;
                }
                .leitura-hero-badge {
                    padding: 6px 14px;
                    border-radius: 999px;
                    background: rgba(255,255,255,.14);
                    border: 1px solid rgba(255,255,255,.25);
                    color: #FFFFFF;
                    font-size: .8rem;
                    font-weight: 700;
                }
                .leitura-hero-title {
                    margin: 0 0 8px;
                    font-size: 2.15rem;
                    font-weight: 800;
                    color: #FFFFFF;
                    line-height: 1.2;
                }
                .leitura-hero-subtitle {
                    margin: 0;
                    color: rgba(255,255,255,.82);
                    font-size: 1rem;
                }
                .leitura-card {
                    background: #FFFFFF;
                    border-radius: 16px;
                    border: 1px solid #E3E8F0;
                    box-shadow: 0 10px 30px rgba(6,27,68,.08);
                    padding: 22px 26px;
                    margin: 4px 0 14px;
                }
                .leitura-card-header {
                    display: flex;
                    align-items: center;
                    justify-content: space-between;
                    flex-wrap: wrap;
                    gap: 10px;
                    margin-bottom: 14px;
                }
                .leitura-day-badge {
                    display: inline-flex;
                    align-items: center;
                    padding: 6px 14px;
                    border-radius: 999px;
                    background: #061B44;
                    color: #FFFFFF;
                    font-weight: 800;
                    font-size: .92rem;
                }
                .leitura-date {
                    color: #607089;
                    font-size: .9rem;
                    font-weight: 600;
                }
                .leitura-tema {
                    margin: 0 0 12px;
                    color: #061B44;
                    font-size: 1rem;
                    font-weight: 700;
                }
                .leitura-passagens-label {
                    color: #607089;
                    font-size: .75rem;
                    font-weight: 700;
                    text-transform: uppercase;
                    letter-spacing: .06em;
                    margin: 0 0 10px;
                }
                .leitura-passagens {
                    display: flex;
                    flex-wrap: wrap;
                    gap: 8px;
                }
                .leitura-pill {
                    padding: 8px 14px;
                    border-radius: 10px;
                    background: #F5F7FA;
                    border: 1px solid #E3E8F0;
                    color: #10213A;
                    font-size: .86rem;
                    font-weight: 650;
                }
            </style>
            """,
            unsafe_allow_html=True,
        )
        st.markdown(
            _html_sem_indentacao(
                _css_base()
                + _navbar()
            ),
            unsafe_allow_html=True,
        )
        from modules.leitura_biblica import render_publico

        render_publico()
        st.markdown(_html_sem_indentacao(_footer()), unsafe_allow_html=True)
        return

    html_final = (
        _css_base()
        + '<div class="fm-page notranslate" translate="no" lang="pt-BR">'
        + _conteudo_da_pagina()
        + "</div>"
    )
    _render_html(html_final)
