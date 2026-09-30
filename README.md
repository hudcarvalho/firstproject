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
  - Módulos (ativar/desativar e nome do controle de andamento);
  - Usuários.
- **Login**: todo acesso exige usuário e senha (ver "Usuários e acesso").

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

Pré-requisito: [Python 3.10+](https://www.python.org/downloads/) (no Windows, marque
"Add Python to PATH" na instalação).

### Jeito mais simples

- **Windows**: dê dois cliques em `iniciar.bat`.
- **Linux/macOS**: execute `./iniciar.sh`.

Na primeira vez ele prepara o ambiente e instala as dependências (leva alguns minutos). Depois
é só abrir o endereço que aparece na janela, por exemplo `http://127.0.0.1:8000`.
**Deixe a janela aberta** enquanto o sistema estiver em uso.

### Manualmente

```bash
python -m venv .venv
.venv\Scripts\activate            # Windows  (Linux/macOS: source .venv/bin/activate)
pip install -r requirements.txt
python serve.py                    # servidor de produção, porta 8000
```

Para desenvolvimento, `python run.py` sobe em modo debug em http://127.0.0.1:5000.

## Usuários e acesso

- No **primeiro acesso** o sistema pede para criar o **administrador**.
- O administrador cadastra os demais em *Cadastros → Usuários*. Cada usuário pode ser ligado a
  um **Responsável**, o que habilita o atalho **Minhas empresas** no menu do módulo.
- Perfis:
  - **Administrador**: tudo, inclusive parametrização (obrigações, matriz), regimes,
    responsáveis, módulos e usuários.
  - **Usuário**: painel, clientes, registro de obrigações e atualização da escrituração;
    vê a parametrização, mas não altera.
- Cada um troca a própria senha no menu com o seu nome (canto superior direito).
- Após 5 senhas erradas seguidas, o login daquele e-mail fica bloqueado por 10 minutos.
- **Esqueceu a senha do administrador?** No computador onde o sistema roda:

  ```bash
  flask --app run redefinir-senha email@do.admin      # pede a nova senha
  flask --app run criar-admin                          # cria outro administrador
  ```

## Usar na rede do escritório

1. Escolha um computador que fique ligado durante o expediente e rode `iniciar.bat` nele.
2. A janela mostra o endereço na rede, por exemplo `http://192.168.0.10:8000`.
   Os colegas acessam esse endereço pelo navegador.
3. Se não abrir nos outros computadores, libere a porta **8000** no Firewall do Windows
   (na primeira execução o Windows costuma perguntar — escolha "Permitir" em rede privada).
4. Para o endereço não mudar, peça para fixar o IP desse computador no roteador.
5. **Backup**: os dados ficam em `instance/controle.db`. Copie esse arquivo regularmente
   (e guarde também `instance/secret_key`).

## Hospedar na internet

O repositório já traz o arquivo `render.yaml` para o [Render](https://render.com):

1. Crie uma conta no Render e conecte o GitHub.
2. *New → Blueprint* e selecione este repositório. Ele cria o site e um banco PostgreSQL.
3. Ao final, abra o endereço `https://….onrender.com` e faça o primeiro acesso.

Os planos (`plan:`) do `render.yaml` podem ser ajustados no painel do Render; há custo mensal.
Em outras hospedagens, basta configurar:

| Variável | Valor |
|---|---|
| `DATABASE_URL` | URL do PostgreSQL (`postgres://…`) |
| `SECRET_KEY` | texto aleatório longo |
| `COOKIE_SECURE` | `1` (site com HTTPS) |
| `PROXY_FIX` | `1` (atrás do proxy da hospedagem) |
| `PORT` | normalmente definido pela hospedagem |

e usar `python serve.py` como comando de inicialização. O endereço `/saude` responde `ok`
para monitoramento.

## Banco de dados e migrações

A estrutura do banco é criada e atualizada automaticamente ao iniciar, pelas migrações em
`migrations/` (Alembic). Assim, atualizar o sistema **não apaga os dados**.

- Bancos criados pela versão com módulos (antes do login) são aproveitados automaticamente.
- Bancos da primeira versão (sem módulos) não são compatíveis: apague `instance/controle.db`.

Para desenvolvedores, ao alterar `app/models.py`:

```bash
flask --app run db migrate -m "descrição"   # gera a migração em migrations/versions
python run.py                               # aplica ao iniciar
```

## Testes

```bash
pip install -r requirements-dev.txt
python -m pytest
```

## Estrutura

```
app/
  __init__.py      # criação do app, configuração e preparo do banco
  auth.py          # login, primeiro acesso, senhas, usuários e permissões
  cli.py           # comandos criar-admin e redefinir-senha
  models.py        # Modulo, Empresa, EmpresaModulo, RegimeTributario, Obrigacao,
                   # Responsavel, Entrega, Usuario, ajustes por empresa
  competencia.py   # utilitários de competência e validação de CNPJ
  routes.py        # telas
  seed.py          # dados iniciais
  templates/       # HTML (Bootstrap 5, servido localmente em static/vendor)
migrations/        # migrações do banco (Alembic)
tests/
serve.py           # servidor de produção (Waitress)
run.py             # servidor de desenvolvimento
iniciar.bat / iniciar.sh
render.yaml        # hospedagem no Render
```
