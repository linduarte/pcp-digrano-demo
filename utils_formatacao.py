"""
utils_formatacao.py
Módulo utilitário para tratamento e conversão de separadores decimais e de milhar
entre o padrão internacional (Python/DuckDB/AtacK) e o padrão brasileiro PT-BR (SCF).
"""

from typing import Any, Union


def formatar_para_scf(valor: Union[float, int, None], casas_decimais: int = 2) -> str:
    """
    Converte um número (float/int) para string no padrão PT-BR esperado pelo SCF.
    Exemplo: 4300.5 -> "4.300,50"
    """
    if valor is None:
        return f"0,{ '0' * casas_decimais }"

    try:
        valor_float = float(valor)
    except (ValueError, TypeError):
        return f"0,{ '0' * casas_decimais }"

    # Formata com vírgula para milhar e ponto para decimal temporariamente
    texto_formatado = f"{valor_float:,.{casas_decimais}f}"

    # Inverte os separadores para o padrão PT-BR
    return texto_formatado.replace(",", "X").replace(".", ",").replace("X", ".")


def converter_para_float(valor_raw: Any) -> float:
    """
    Sanitiza e converte qualquer entrada (string PT-BR ou com ponto) para float nativo.
    Exemplo: "4.300,50" -> 4300.5
    """
    if valor_raw is None:
        return 0.0

    if isinstance(valor_raw, (float, int)):
        return float(valor_raw)

    texto = str(valor_raw).strip()
    if not texto:
        return 0.0

    # Se contém vírgula, trata o padrão PT-BR (remove pontos de milhar e troca vírgula por ponto)
    if "," in texto:
        texto = texto.replace(".", "").replace(",", ".")

    try:
        return float(texto)
    except ValueError:
        return 0.0
