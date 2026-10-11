"""Script para sincronizar produtos do SCF para um arquivo NDJSON."""

import json
import os

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
SELECT 
    p.codigoInterno AS id_interno_scf,
    ISNULL(NULLIF(RTRIM(p.partNumber), ''), CAST(p.codigoInterno AS VARCHAR)) AS codigo_produto_real,
    p.nome AS descricao_caixa,
    ISNULL(l.nome, 'GERAL') AS linha,
    ISNULL(p.padraoApontamento1, 1) AS pct_por_cx,
    ISNULL(p.padraoApontamento2, 1) AS uni_por_pct,
    ISNULL(p.quantidadeBandeja, 0) AS qtd_por_tabuleiro,
    p.peso AS peso_unitario_kg,
    (
        SELECT 
            ISNULL(c.nome, 'GERAL') AS tipo,
            RTRIM(e.codigoInsumo) AS codigo_insumo,
            COALESCE(
                NULLIF(RTRIM(i.nomeReduzido) COLLATE DATABASE_DEFAULT, ''),
                NULLIF(RTRIM(i_ext.nomeReduzido) COLLATE DATABASE_DEFAULT, ''),
                NULLIF(RTRIM(pg.nome) COLLATE DATABASE_DEFAULT, ''),
                NULLIF(RTRIM(pg_int.nome) COLLATE DATABASE_DEFAULT, ''),
                -- Caso seja embalagem / insumo genérico sem cadastro na tabela insumo
                RTRIM(e.codigoInsumo) COLLATE DATABASE_DEFAULT
            ) AS descricao_insumo,
            e.quantidadeInsumo AS peso_unid_kg,
            e.quantidadeInsumo AS peso_lote_receita_kg,
            e.unidadeMedidaInsumo AS unidade
        FROM dbo.viewEstruturaProduto e
        LEFT JOIN dbo.insumo i 
            ON TRY_CAST(RTRIM(LTRIM(e.codigoInsumo)) AS INT) = i.codigoInterno
        LEFT JOIN dbo.insumo i_ext 
            ON LTRIM(RTRIM(e.codigoInsumo)) COLLATE DATABASE_DEFAULT = LTRIM(RTRIM(i_ext.codigoExterno)) COLLATE DATABASE_DEFAULT
        LEFT JOIN dbo.produtoGeral pg
            ON LTRIM(RTRIM(e.codigoInsumo)) COLLATE DATABASE_DEFAULT = LTRIM(RTRIM(pg.partNumber)) COLLATE DATABASE_DEFAULT
        LEFT JOIN dbo.produtoGeral pg_int
            ON TRY_CAST(LTRIM(RTRIM(e.codigoInsumo)) AS INT) = pg_int.codigoInterno
        LEFT JOIN dbo.categoriaInsumo c 
            ON i.categoriaInsumo = c.codigoInterno OR i_ext.categoriaInsumo = c.codigoInterno
        WHERE 
            LTRIM(RTRIM(e.codigoProduto)) COLLATE DATABASE_DEFAULT = LTRIM(RTRIM(p.partNumber)) COLLATE DATABASE_DEFAULT
            OR LTRIM(RTRIM(e.codigoProduto)) COLLATE DATABASE_DEFAULT = CAST(p.codigoInterno AS VARCHAR) COLLATE DATABASE_DEFAULT
        FOR JSON PATH
    ) AS composicoes_json
FROM dbo.produtoGeral p
LEFT JOIN dbo.linha l 
    ON p.linha = l.codigoInterno;
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

    # Dicionário De-Para para insumos/embalagens que não possuem descrição no SQL
    depara_embalagens = {
        "551035": "SACO PLÁSTICO / EMBALAGEM PRIMÁRIA 180G",
        "552016": "FITA ADESIVA TRANSPARENTE 45MM",
        "552028": "ETIQUETA TÉRMICA PADRÃO FALEIRO 100X50",
    }

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
                # Aplica a substituição para descrições não resolvidas no SQL
                for comp in clean_comps:
                    cod_insumo = str(comp.get("codigo_insumo", "")).strip()
                    desc_insumo = str(comp.get("descricao_insumo", "")).strip()

                    if (desc_insumo == cod_insumo or not desc_insumo) and cod_insumo in depara_embalagens:
                        comp["descricao_insumo"] = depara_embalagens[cod_insumo]
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
