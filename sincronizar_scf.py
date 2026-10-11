"""Script para sincronizar produtos do SCF para um arquivo NDJSON."""

import json
import os
import re

import pyodbc  # type: ignore[import-not-found]
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


# 1. Consulta SQL simplificada e abrangente
QUERY_SCF = """
WITH CTE_ArvoreBOM AS (
    SELECT 
        RTRIM(e.codigoProduto) COLLATE DATABASE_DEFAULT AS codigo_pai_raiz,
        RTRIM(e.codigoInsumo) COLLATE DATABASE_DEFAULT AS codigo_filho,
        CAST(e.quantidadeInsumo AS FLOAT) AS qtd_acumulada,
        e.unidadeMedidaInsumo AS unidade,
        1 AS profundidade
    FROM dbo.viewEstruturaProduto e

    UNION ALL

    SELECT 
        a.codigo_pai_raiz,
        RTRIM(e2.codigoInsumo) COLLATE DATABASE_DEFAULT AS codigo_filho,
        CAST(a.qtd_acumulada * e2.quantidadeInsumo AS FLOAT) AS qtd_acumulada,
        e2.unidadeMedidaInsumo AS unidade,
        a.profundidade + 1
    FROM CTE_ArvoreBOM a
    INNER JOIN dbo.viewEstruturaProduto e2 
        ON a.codigo_filho = RTRIM(e2.codigoProduto) COLLATE DATABASE_DEFAULT
    WHERE a.profundidade < 6
)
SELECT 
    p.codigoInterno AS id_interno_scf,
    ISNULL(NULLIF(RTRIM(p.partNumber), ''), CAST(p.codigoInterno AS VARCHAR)) AS codigo_produto_real,
    p.nome AS descricao_caixa,
    ISNULL(l.nome, 'GERAL') AS linha,
    ISNULL(NULLIF(p.padraoApontamento1, 0), 3) AS pct_por_cx,
    ISNULL(NULLIF(p.padraoApontamento2, 0), 10) AS uni_por_pct,
    ISNULL(p.quantidadeBandeja, 0) AS qtd_por_tabuleiro,
    p.peso AS peso_unitario_kg,
    (
        SELECT DISTINCT
            ISNULL(MAX(c.nome), 'SEMIACABADOS') AS tipo,
            RTRIM(a.codigo_filho) AS codigo_insumo,
            COALESCE(
                NULLIF(RTRIM(MAX(i.nomeReduzido)) COLLATE DATABASE_DEFAULT, ''),
                NULLIF(RTRIM(MAX(pg.nome)) COLLATE DATABASE_DEFAULT, ''),
                RTRIM(a.codigo_filho) COLLATE DATABASE_DEFAULT
            ) AS descricao_insumo,
            MAX(a.qtd_acumulada) AS peso_unid_kg,
            MAX(a.qtd_acumulada) AS peso_lote_receita_kg,
            MAX(a.unidade) AS unidade
        FROM CTE_ArvoreBOM a
        LEFT JOIN dbo.produtoGeral pg
            ON (RTRIM(a.codigo_filho) = CAST(pg.codigoInterno AS VARCHAR) COLLATE DATABASE_DEFAULT 
                OR RTRIM(a.codigo_filho) = RTRIM(pg.partNumber) COLLATE DATABASE_DEFAULT)
        LEFT JOIN dbo.insumo i 
            ON (RTRIM(a.codigo_filho) = RTRIM(i.codigoExterno) COLLATE DATABASE_DEFAULT 
                OR RTRIM(a.codigo_filho) = CAST(i.codigoInterno AS VARCHAR(50)) COLLATE DATABASE_DEFAULT)
        LEFT JOIN dbo.categoriaInsumo c 
            ON i.categoriaInsumo = c.codigoInterno
        WHERE 
            (RTRIM(a.codigo_pai_raiz) = RTRIM(p.partNumber) COLLATE DATABASE_DEFAULT
             OR RTRIM(a.codigo_pai_raiz) = CAST(p.codigoInterno AS VARCHAR) COLLATE DATABASE_DEFAULT)
            AND RTRIM(a.codigo_filho) LIKE '20%'
            AND (
                NULLIF(RTRIM(pg.nome) COLLATE DATABASE_DEFAULT, '') IS NOT NULL 
                OR NULLIF(RTRIM(i.nomeReduzido) COLLATE DATABASE_DEFAULT, '') IS NOT NULL
            )
        GROUP BY RTRIM(a.codigo_filho)
        FOR JSON PATH
    ) AS composicoes_json
FROM dbo.produtoGeral p
LEFT JOIN dbo.linha l ON p.linha = l.codigoInterno
WHERE RTRIM(p.partNumber) LIKE '10%' OR RTRIM(p.partNumber) LIKE 'SCF%';
"""


def executar_sincronizacao():
    """Sincroniza os produtos do SCF para um ficheiro NDJSON."""
    connection_string = (
        f"DRIVER={{{DB_CONFIG['driver']}}};"
        f"SERVER={DB_CONFIG['server']};"
        f"DATABASE={DB_CONFIG['database']};"
        f"UID={DB_CONFIG['user']};"
        f"PWD={DB_CONFIG['password']}"
    )
    connection = pyodbc.connect(connection_string)  # pylint: disable=c-extension-no-member
    cursor = connection.cursor()
    cursor.execute(QUERY_SCF)
    rows = cursor.fetchall()



    produtos = []
    for row in rows:
        # Acesso seguro por índice para evitar erros de atributo do pyodbc
        id_interno = str(row[0]) if row[0] is not None else ""
        part_num = str(row[1]).strip() if row[1] is not None else id_interno
        desc_caixa = str(row[2]).strip() if row[2] is not None else ""
        nome_linha = str(row[3]).strip() if row[3] is not None else "GERAL"
        pct_cx = int(row[4]) if row[4] is not None else 1
        uni_pct = int(row[5]) if row[5] is not None else 1
        qtd_tab = int(row[6]) if row[6] is not None else 0
        json_comps = row[8] if len(row) > 8 else None

        clean_comps = []
        if json_comps:
            try:
                clean_comps = json.loads(json_comps)
                for comp in clean_comps:
                    desc_insumo = str(comp.get("descricao_insumo", "")).strip()
                    match = re.search(r"-\s*([\d,.]+)\s*(?:KG)?\s*-", desc_insumo)
                    if match:
                        try:
                            peso_lote = float(match.group(1).replace(",", "."))
                            comp["peso_lote_receita_kg"] = peso_lote
                        except ValueError:
                            pass
            except json.JSONDecodeError:
                clean_comps = []

        produtos.append(
            {
                "codigo_caixa": part_num,
                "codigo_interno_scf": id_interno,
                "descricao_caixa": desc_caixa,
                "linha": nome_linha,
                "pct_por_cx": pct_cx,
                "uni_por_pct": uni_pct,
                "qtd_por_tabuleiro": qtd_tab,
                "composicoes": clean_comps,
            }
        )

    # Gravação do NDJSON
    with open("fichas_tecnicas_scf.ndjson", "w", encoding="utf-8") as f:
        for p in produtos:
            f.write(json.dumps(p, ensure_ascii=False) + "\n")

    print(
        f"Sucesso! {len(produtos)} produtos sincronizados em 'fichas_tecnicas_scf.ndjson'."
    )


if __name__ == "__main__":
    executar_sincronizacao()
