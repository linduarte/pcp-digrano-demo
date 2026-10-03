
# 🏭 Sistema de PCP - Linha de Alimentos (DiGrano)

Uma aplicação moderna, leve e de alta performance desenvolvida em **Python** para Planejamento e Controle da Produção (PCP). O sistema realiza a explosão instantânea de ordens de produção em insumos e semiacabados (massas, recheios e acabamentos) e calcula o loteamento exato de receitas para a cozinha.

---

## 🌟 Destaques do Projeto

* **Arquitetura NDJSON + DuckDB**: Consultas analíticas em fração de milissegundos sobre dados hierárquicos aninhados (Bill of Materials / Ficha Técnica) sem gargalos de *JOINs* relacionais.
* **Interface Dinâmica (NiceGUI)**: UI reativa e moderna para o operador do PCP lançar ordens de produção por Caixas, Pacotes ou Unidades avulsas.
* **Arredondamento Inteligente de Lotes**: Cálculo automático de receitas necessárias respeitando o lote padrão e a regra de produção (múltiplos de 0,5 receita).
* **Gestão Leve de Dependências**: Configurado e gerenciado com o **`uv`**, dispensando infraestruturas pesadas como Docker ou bases de dados complexas.

---

## 📐 Estrutura do Banco / Modelo de Dados

O projeto adota a separação entre a **Mática de Embalagem** e a **Ficha Técnica de Produção**:

📊 Modelo da Planilha de Origem (Modelo_Ref_PCP_NDJSON.xlsx)
├── Aba 'PRODUTOS' (Cadastro Comercial)
│    └── Codigo_Caixa | Descricao_Caixa | Linha | Pct_Por_Cx | Uni_Por_Pct | Qtd_Por_Tabuleiro
└── Aba 'FICHA_TECNICA' (BOM Normalizado / Long Format)
└── Codigo_Produto | Tipo_Componente | Codigo_Insumo | Peso_Unid_KG | Peso_Lote_Receita_KG

Ao iniciar, o motor de dados aninha as fichas técnicas no formato **NDJSON** em memória no DuckDB:

```json
```json
{
  "codigo_caixa": "101218",
  "descricao_caixa": "(151) CIGARRETE TRADICIONAL CX C/30",
  "linha": "Linha Digrano",
  "pct_por_cx": 3,
  "uni_por_pct": 10,
  "composicoes": [
    {
      "tipo": "MASSA",
      "codigo_insumo": 207006,
      "descricao_insumo": "SEMIACABADO MASSA CIGARRETE",
      "peso_unid_kg": 0.07,
      "peso_lote_receita_kg": 86.55
    },
    {
      "tipo": "RECHEIO",
      "codigo_insumo": 201001,
      "descricao_insumo": "SEMIACABADO PRESUNTO FATIADO",
      "peso_unid_kg": 0.028,
      "peso_lote_receita_kg": 1.0
    }
  ]
}
```
🛠️ Tecnologias Utilizadas
Python 3.12+: Linguagem principal.

uv: Gerenciador de pacotes e ambientes virtuais ultrarrápido.

NiceGUI: Framework web reativo baseado em FastAPI e Vue.js.

DuckDB: Banco de dados colunar analítico operando em memória sobre estruturas JSON/NDJSON.

Pandas & OpenPyXL: Leitura e manipulação de planilhas Excel.

🚀 Como Executar o Projeto Localmente
Pré-requisitos
Certifique-se de ter o Python e o gerenciador uv instalados na máquina.

```Bash
# Instalação do uv (se necessário)
pip install uv
```

Passo a Passo
1 - Clonar o Repositório:

```Powershell
git clone https://github.com/linduarte/pcp-digrano-demo.git
cd pcp-digrano-demo
```

2 - Executar a Aplicação:
O uv irá criar o ambiente virtual e sincronizar todas as dependências do pyproject.toml automaticamente:

```Powershell
uv run app_nicegui_pcp.py
```

3 - Acessar a Interface:
Abra o seu navegador de preferência e acesse:
👉 http://localhost:8085

🖥️ Telas e Uso da Aplicação
Lançamento de Ordens: Selecione o produto desejado na lista, introduza a quantidade pretendida (Caixas, Pacotes e/ou Unidades) e clique em "Adicionar Lote".

1 - Explosão Consolidada: A tabela inferior exibirá em tempo real:

2 - Necessidade Líquida (KG): Peso exato consumido pela demanda.

    Lote Padrão: Tamanho da receita na fábrica.

    Nº de Receitas (0.5): Quantidade ajustada de lotes a serem produzidos (arredondado para o meio lote superior).

    Total Bruto a Preparar (KG): Quantidade final a enviar para a cozinha/misturador.

📄 Licença
Este projeto foi desenvolvido para fins de demonstração técnica e otimização de processos fabris.