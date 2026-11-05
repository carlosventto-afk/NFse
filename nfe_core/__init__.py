"""Núcleo de emissão de NF-e modelo 55 (venda de mercadoria).

Espelha a organização de `nfse_core/` (ver docstring daquele pacote). Este
módulo nasce com a montagem do XML; tarefas seguintes do plano de NF-e
modelo 55 adicionam seus próprios arquivos aqui (assinatura, comunicação
com a SEFAZ, leitura de respostas, cancelamento) e acrescentam seus
próprios exports a este mesmo `__init__.py`.

    nfe.py    monta o XML da NF-e e calcula a chave de acesso
"""

from nfe_core.nfe import NFE_NS, NfeData, NfeItemData, build_nfe_xml, chave_de_acesso

__all__ = [
    # montagem
    "NfeData", "NfeItemData", "build_nfe_xml", "chave_de_acesso", "NFE_NS",
]
