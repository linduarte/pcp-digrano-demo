"""Script para sincronizar produtos do SCF para um arquivo NDJSON."""

import json

import pyodbc  # type: ignore

# Configurações de Conexão ao SQL Server do SCF
db_config = {
    "driver": "{SQL Server}",
    "server": "192.168.0.61",  # IP do SCF via VPN
    "database": "SCF",  # Substituir pelo nome exato do banco
    "user": "SCF_user",
    "password": "As23fZxDcf5"
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


db_config = {
    "driver": "SQL Server",
    "server": "192.168.0.61",
    "database": "SCF",
    "user": "SCF_user",
    "password": "As23fZxDcf5"
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

def executar_sincronizacao():
    """Sincroniza os produtos do SCF para um arquivo NDJSON."""
    # String de conexão sem risco de formatação incorreta de chaves
    driver_str = "{" + db_config["driver"].strip("{}") + "}"
    conn_str = (
        f"DRIVER={driver_str};"
        f"SERVER={db_config['server']};"
        f"DATABASE={db_config['database']};"
        f"UID={db_config['user']};"
        f"PWD={db_config['password']};"
    )

    print(f"Conectando ao SQL Server em {db_config['server']}...")
    with pyodbc.connect(conn_str) as conn:  # pylint: disable=no-member,c-extension-no-member
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
                        "composicoes": clean_comps
                    }
                    f.write(json.dumps(item, ensure_ascii=False) + "\n")
                    total_processado += 1
                except (json.JSONDecodeError, TypeError, ValueError, AttributeError) as e:
                    print(f"Erro ao processar item {row.codigo_caixa}: {e}")

        print(f"Sucesso! {total_processado} produtos sincronizados em '{arquivo_saida}'.")

if __name__ == "__main__":
    executar_sincronizacao()
