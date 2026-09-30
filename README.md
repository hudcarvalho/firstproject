# Controle de Rotina — Escritório Contábil

Sistema web para acompanhar a rotina dos clientes de um escritório contábil:
até quando cada empresa foi escriturada, quais obrigações ela tem e se estão em dia.

## Módulos

O sistema é organizado por **módulos** (áreas do escritório): **Contábil**, **Fiscal**,
**Departamento Pessoal** e **Paralegal**. Por enquanto só o **Contábil** está ativo;
os demais ficam ocultos até serem ativados em *Cadastros → Módulos*.

- O **cadastro do cliente** (dados, CNPJ, tributação) é único e compartilhado.
- Cada módulo tem, por empresa, o seu **responsável** e o seu **controle de andamento**
  (no Contábil, "Escriturada até"; no Fiscal, "Apurado até"; no DP, "Folha fechada até").
- **Obrigações** pertencem a um módulo, e a parametrização Obrigações × Tributação é feita
  por módulo. As obrigações de exemplo do Fiscal e do DP já vêm cadastradas, prontas para
  quando esses módulos forem ativados.
- As telas da rotina ficam sob o código do módulo (`/contabil/`, `/empresas/1/contabil`…);
  ao ativar outro módulo ele ganha o mesmo painel, tela da empresa e parametrização.
  Funcionalidades específicas de cada área podem ser acrescentadas depois sobre essa base.

## Funcionalidades

- **Painel (por módulo)**: lista das empresas ativas com tributação, responsável,
  "escriturada até" (com indicador de atraso) e quantidade de obrigações pendentes.
  Filtros por responsável (inclusive "sem responsável"), tributação e busca por nome/CNPJ.
- **Clientes (empresas)**: cadastro com razão social, nome fantasia, CNPJ (validado),
  inscrições, contato, **tributação**, observações e, para cada módulo ativo,
  **responsável** e competência concluída.
- **Tela da empresa**: situação de cada obrigação (última competência cumprida,
  competência esperada, em dia/pendente), atualização rápida da escrituração,
  registro de cumprimento de obrigações e histórico.
- **Exceções por empresa**: incluir uma obrigação fora do regime ou dispensar uma do regime.
- **Parametrização**:
  - Obrigações (nome, periodicidade, esfera, dia de vencimento, ativa/inativa);
  - Obrigações × Tributação (grade para marcar quais obrigações cada regime exige);
  - Regimes tributários;
  - Responsáveis;
  - Módulos (ativar/desativar e nome do controle de andamento).

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

> Se você usou a primeira versão (sem módulos), apague `instance/controle.db` antes de
> iniciar — o sistema avisa caso encontre o banco antigo.

## Testes

```bash
python -m pytest
```

## Estrutura

```
app/
  __init__.py      # criação do app Flask
  models.py        # Modulo, Empresa, EmpresaModulo, RegimeTributario, Obrigacao,
                   # Responsavel, Entrega, ajustes por empresa
  competencia.py   # utilitários de competência e validação de CNPJ
  routes.py        # telas
  seed.py          # dados iniciais
  templates/       # HTML (Bootstrap 5, servido localmente em static/vendor)
tests/
```
