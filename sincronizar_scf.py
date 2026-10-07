"""Script para sincronizar produtos do SCF para um arquivo NDJSON."""

import json
import os

import pyodbc  # type: ignore
from dotenv import load_dotenv

# Carrega as variáveis de ambiente do ficheiro .env
load_dotenv()

# Configurações lidas do ambiente com valores padrão de segurança
DB_CONFIG = {
    "driver": os.getenv("SCF_DB_DRIVER", "SQL Server"),
    "server": os.getenv("SCF_DB_SERVER", "192.168.0.61"),
    "database": os.getenv("SCF_DB_NAME", "SCF"),
    "user": os.getenv("SCF_DB_USER", "SCF_user"),
    "password": os.getenv("SCF_DB_PASS", ""),
}

query_scf = """
SELECT 
    p.codigoInterno AS codigo_caixa,
    p.nome AS descricao_caixa,
    l.nome AS linha,
    ISNULL(p.padraoApontamento1, 1) AS pct_por_cx,
    ISNULL(p.padraoApontamento2, 1) AS uni_por_pct,
    ISNULL(p.quantidadeBandeja, 0) AS qtd_por_tabuleiro,
    p.peso AS peso_unitario_kg,
    (
        SELECT 
            ISNULL(c.nome, 'GERAL') AS tipo,
            RTRIM(e.codigoInsumo) AS codigo_insumo,
            ISNULL(i.nomeReduzido, RTRIM(e.codigoInsumo)) AS descricao_insumo,
            e.quantidadeInsumo AS peso_unid_kg,
            e.unidadeMedidaInsumo AS unidade
        FROM dbo.viewEstruturaProduto e
        LEFT JOIN dbo.insumo i 
            ON (RTRIM(e.codigoInsumo) COLLATE DATABASE_DEFAULT = CAST(i.codigoInterno AS VARCHAR) COLLATE DATABASE_DEFAULT 
                OR RTRIM(e.codigoInsumo) COLLATE DATABASE_DEFAULT = RTRIM(i.codigoExterno) COLLATE DATABASE_DEFAULT)
        LEFT JOIN dbo.categoriaInsumo c 
            ON i.categoriaInsumo = c.codigoInterno
        WHERE 
            RTRIM(e.codigoProduto) COLLATE DATABASE_DEFAULT = RTRIM(p.partNumber) COLLATE DATABASE_DEFAULT
            OR RTRIM(e.codigoProduto) COLLATE DATABASE_DEFAULT = CAST(p.codigoInterno AS VARCHAR) COLLATE DATABASE_DEFAULT
        FOR JSON PATH
    ) AS composicoes_json
FROM dbo.produtoGeral p
LEFT JOIN dbo.linha l 
    ON p.linha = l.codigoInterno;
"""


query_scf = """
SELECT 
    p.codigoInterno AS codigo_caixa,
    p.nome AS descricao_caixa,
    l.nome AS linha,
    ISNULL(p.padraoApontamento1, 1) AS pct_por_cx,
    ISNULL(p.padraoApontamento2, 1) AS uni_por_pct,
    ISNULL(p.quantidadeBandeja, 0) AS qtd_por_tabuleiro,
    p.peso AS peso_unitario_kg,
    (
        SELECT 
            ISNULL(c.nome, 'GERAL') AS tipo,
            RTRIM(e.codigoInsumo) AS codigo_insumo,
            ISNULL(i.nomeReduzido, RTRIM(e.codigoInsumo)) AS descricao_insumo,
            e.quantidadeInsumo AS peso_unid_kg,
            e.unidadeMedidaInsumo AS unidade
        FROM dbo.viewEstruturaProduto e
        LEFT JOIN dbo.insumo i 
            ON (RTRIM(e.codigoInsumo) COLLATE DATABASE_DEFAULT = CAST(i.codigoInterno AS VARCHAR) COLLATE DATABASE_DEFAULT 
                OR RTRIM(e.codigoInsumo) COLLATE DATABASE_DEFAULT = RTRIM(i.codigoExterno) COLLATE DATABASE_DEFAULT)
        LEFT JOIN dbo.categoriaInsumo c 
            ON i.categoriaInsumo = c.codigoInterno
        WHERE 
            RTRIM(e.codigoProduto) COLLATE DATABASE_DEFAULT = RTRIM(p.partNumber) COLLATE DATABASE_DEFAULT
            OR RTRIM(e.codigoProduto) COLLATE DATABASE_DEFAULT = CAST(p.codigoInterno AS VARCHAR) COLLATE DATABASE_DEFAULT
        FOR JSON PATH
    ) AS composicoes_json
FROM dbo.produtoGeral p
LEFT JOIN dbo.linha l 
    ON p.linha = l.codigoInterno;
"""


def executar_sincronizacao():
    """Sincroniza os produtos do SCF para um ficheiro NDJSON."""
    driver_str = "{" + DB_CONFIG["driver"].strip("{}") + "}"
    conn_str = (
        f"DRIVER={driver_str};"
        f"SERVER={DB_CONFIG['server']};"
        f"DATABASE={DB_CONFIG['database']};"
        f"UID={DB_CONFIG['user']};"
        f"PWD={DB_CONFIG['password']};"
    )

    print(f"Conectando ao SQL Server em {DB_CONFIG['server']}...")
    connect = getattr(pyodbc, "connect")
    with connect(conn_str) as conn:
        cursor = conn.cursor()
        cursor.execute(query_scf)
        rows = cursor.fetchall()

        arquivo_saida = "fichas_tecnicas_scf.ndjson"
        total_processado = 0

        with open(arquivo_saida, "w", encoding="utf-8") as f:
            for row in rows:
                if not row.composicoes_json:
                    continue

                try:
                    comps = json.loads(row.composicoes_json)
                    clean_comps = [
                        {
                            "tipo": c.get("tipo", "").strip(),
                            "codigo_insumo": c.get("codigo_insumo", "").strip(),
                            "descricao_insumo": c.get("descricao_insumo", "").strip(),
                            "peso_unid_kg": float(c.get("peso_unid_kg", 0.0)),
                            "peso_lote_receita_kg": float(c.get("peso_unid_kg", 0.0)), # Adicionado para compatibilidade
                            "unidade": c.get("unidade", "").strip()
                        }
                        for c in comps
                    ]

                    item = {
                        "codigo_caixa": str(row.codigo_caixa),
                        "descricao_caixa": str(row.descricao_caixa).strip(),
                        "linha": str(row.linha).strip() if row.linha else "GERAL",
                        "pct_por_cx": int(row.pct_por_cx),
                        "uni_por_pct": int(row.uni_por_pct),
                        "qtd_por_tabuleiro": int(row.qtd_por_tabuleiro),
                        "composicoes": clean_comps,
                    }
                    f.write(json.dumps(item, ensure_ascii=False) + "\n")
                    total_processado += 1
                except (TypeError, ValueError, json.JSONDecodeError) as exc:
                    print(f"Erro ao processar item {row.codigo_caixa}: {exc}")

        print(
            f"Sucesso! {total_processado} produtos sincronizados em '{arquivo_saida}'."
        )


if __name__ == "__main__":
    executar_sincronizacao()
