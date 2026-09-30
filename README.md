# Controle de Rotina — Escritório Contábil

Sistema web para acompanhar a rotina dos clientes de um escritório contábil:
até quando cada empresa foi escriturada, quais obrigações ela tem e se estão em dia.

## Funcionalidades

- **Painel**: lista das empresas ativas com tributação, responsável, "escriturada até"
  (com indicador de atraso) e quantidade de obrigações pendentes. Filtros por
  responsável, tributação e busca por nome/CNPJ.
- **Clientes (empresas)**: cadastro com razão social, nome fantasia, CNPJ (validado),
  inscrições, contato, **tributação**, **responsável**, competência escriturada e observações.
- **Tela da empresa**: situação de cada obrigação (última competência cumprida,
  competência esperada, em dia/pendente), atualização rápida da escrituração,
  registro de cumprimento de obrigações e histórico.
- **Exceções por empresa**: incluir uma obrigação fora do regime ou dispensar uma do regime.
- **Parametrização**:
  - Obrigações (nome, periodicidade, esfera, dia de vencimento, ativa/inativa);
  - Obrigações × Tributação (grade para marcar quais obrigações cada regime exige);
  - Regimes tributários;
  - Responsáveis.

Na primeira execução o banco é criado com os regimes (Simples Nacional, Lucro
Presumido, Lucro Real, MEI, Imune/Isenta) e um conjunto de obrigações de exemplo
(Distribuição de Lucros, IRPJ, CSLL, PIS/COFINS, DCTFWeb, EFD-Reinf, ECD, ECF, DEFIS…),
todos editáveis pelas telas.

### Como a situação "em dia / pendente" é calculada

Para cada obrigação, conforme a periodicidade, o sistema considera a última
competência já encerrada na data de hoje:

| Periodicidade | Competência esperada |
|---|---|
| Mensal | mês anterior |
| Trimestral | último mês do trimestre anterior (03, 06, 09, 12) |
| Anual | dezembro do ano anterior |
| Eventual | não controla |

Se a última competência registrada for igual ou posterior à esperada, a obrigação está em dia.

## Como rodar

```bash
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python run.py
```

Acesse http://127.0.0.1:5000. O banco SQLite fica em `instance/controle.db`
(pode ser trocado pela variável `DATABASE_URL`).

## Testes

```bash
python -m pytest
```

## Estrutura

```
app/
  __init__.py      # criação do app Flask
  models.py        # Empresa, RegimeTributario, Obrigacao, Responsavel, Entrega, ajustes
  competencia.py   # utilitários de competência e validação de CNPJ
  routes.py        # telas
  seed.py          # dados iniciais
  templates/       # HTML (Bootstrap 5, servido localmente em static/vendor)
tests/
```
