"""
Definicao dos planos do FielMordomo e regras de acesso.
"""

PLANOS = {
    "basico": {
        "nome": "Basico",
        "preco": "R$ 29,90/mes",
        "limite_membros": 50,
        "lancamento_lote": False,
        "backup_automatico": False,
        "cor": "#64748B",
        "cor_fim": "#475569",
    },
    "profissional": {
        "nome": "Profissional",
        "preco": "R$ 59,90/mes",
        "limite_membros": 250,
        "lancamento_lote": True,
        "backup_automatico": True,
        "cor": "#1D9E75",
        "cor_fim": "#0F6E56",
    },
    "premium": {
        "nome": "Premium",
        "preco": "R$ 90,90/mes",
        "limite_membros": None,
        "lancamento_lote": True,
        "backup_automatico": True,
        "cor": "#D4AF37",
        "cor_fim": "#9C7317",
    },
}


def _slug_plano(plano) -> str:
    return str(plano or "basico").strip().lower()


def obter_plano(slug_plano):
    return PLANOS.get(_slug_plano(slug_plano), PLANOS["basico"])


def pode_cadastrar_membro(plano, qtd_atual):
    limite = obter_plano(plano)["limite_membros"]
    if limite is None:
        return True
    return max(0, int(qtd_atual or 0)) < limite


def texto_limite(plano):
    limite = obter_plano(plano)["limite_membros"]
    return "ilimitado" if limite is None else str(limite)


def tem_lancamento_lote(plano):
    return obter_plano(plano)["lancamento_lote"]


def tem_backup_automatico(plano):
    return obter_plano(plano)["backup_automatico"]


def proximo_plano(plano):
    slug = _slug_plano(plano)
    if slug == "basico":
        return "profissional"
    return "premium"
