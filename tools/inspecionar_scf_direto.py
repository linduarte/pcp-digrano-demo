"""Diagnóstico direto dos registros do SCF e da estrutura do produto."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType
from typing import Any, Callable, cast

try:
    import pyodbc  # type: ignore[import-not-found]
except ImportError:  # pragma: no cover - depende do driver do SQL Server
    pyodbc = None  # type: ignore[assignment]


ConexaoSql = Callable[[], Any]


def _carregar_obter_conexao_sql() -> ConexaoSql | None:
    """Carrega a função OBTER_CONEXAO_SQL no mesmo diretório do script."""
    caminho_modulo = Path(__file__).resolve().with_name("sincronizar_scf.py")
    if not caminho_modulo.exists():
        return None

    try:
        spec = importlib.util.spec_from_file_location(
            "sincronizar_scf_local", caminho_modulo
        )
        if spec is None or spec.loader is None:
            return None

        modulo: ModuleType = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(modulo)
        funcao = getattr(modulo, "OBTER_CONEXAO_SQL", None)
    except (ImportError, OSError, RuntimeError):
        return None

    return cast(ConexaoSql, funcao) if callable(funcao) else None


def _criar_conexao_sql() -> Any:
    """Cria uma conexão usando a configuração do sincronizador local."""
    if pyodbc is None:
        raise RuntimeError("O pacote pyodbc não está instalado.")

    caminho_modulo = Path(__file__).resolve().with_name("sincronizar_scf.py")
    spec = importlib.util.spec_from_file_location("sincronizar_scf_config", caminho_modulo)
    if spec is None or spec.loader is None:
        raise RuntimeError("Não foi possível carregar a configuração do sincronizador.")

    modulo: ModuleType = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    configuracao = getattr(modulo, "DB_CONFIG", None)
    if not isinstance(configuracao, dict):
        raise RuntimeError("DB_CONFIG não foi encontrada no módulo sincronizar_scf.")

    configuracao_sql = cast(dict[str, str], configuracao)

    connection_string = (
        f"DRIVER={{{configuracao_sql.get('driver', 'SQL Server')}}};"
        f"SERVER={configuracao_sql.get('server', '')};"
        f"DATABASE={configuracao_sql.get('database', '')};"
        f"UID={configuracao_sql.get('user', '')};"
        f"PWD={configuracao_sql.get('password', '')}"
    )
    return pyodbc.connect(connection_string)


OBTER_CONEXAO_SQL = _carregar_obter_conexao_sql()
if OBTER_CONEXAO_SQL is None:
    OBTER_CONEXAO_SQL = _criar_conexao_sql


try:
    conn = OBTER_CONEXAO_SQL()

    cursor = conn.cursor()

    print("\n=== 1. BUSCA POR REGISTROS DO PRESUNTO (201001) NA ESTRUTURA ===")
    cursor.execute("""
        SELECT TOP 20
            e.codigoProduto,
            e.codigoInsumo,
            e.quantidadeInsumo,
            p.partNumber,
            p.nome
        FROM dbo.viewEstruturaProduto e
        LEFT JOIN dbo.produtoGeral p
            ON (RTRIM(e.codigoProduto) = RTRIM(p.partNumber) COLLATE DATABASE_DEFAULT
                OR RTRIM(e.codigoProduto) = CAST(p.codigoInterno AS VARCHAR) COLLATE DATABASE_DEFAULT)
        WHERE e.codigoInsumo LIKE '%201001%' OR e.codigoInsumo LIKE '%PRESUNTO%'
    """)
    rows = cursor.fetchall()

    if not rows:
        print("--> Nenhum registro encontrado para o insumo 201001/PRESUNTO!")
    else:
        for r in rows:
            print(
                f"Pai Estrutura: '{r[0]}' | Insumo: '{r[1]}' | Qtd: {r[2]} | PartNumber: '{r[3]}' | Nome: '{r[4]}'"
            )

    print("\n=== 2. ESTRUTURA DIRETA DO SCF001 OU ID 11810 ===")
    cursor.execute("""
        SELECT codigoProduto, codigoInsumo, quantidadeInsumo
        FROM dbo.viewEstruturaProduto
        WHERE codigoProduto IN ('11810', 'SCF001', '11811', 'SCF002')
    """)
    rows_scf = cursor.fetchall()
    for r in rows_scf:
        print(f"Produto Pai: '{r[0]}' | Insumo Filho: '{r[1]}' | Qtd: {r[2]}")

except RuntimeError as err:
    print(f"\nErro de configuração da conexão: {err}")
except pyodbc.Error as err:  # type: ignore[union-attr]
    print(f"\nErro ao executar diagnóstico no SQL Server: {err}")
