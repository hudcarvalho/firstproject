/* Filtro de seleção múltipla, como o filtro do Excel.
 *
 * Transforma um <select> cuja primeira opção tem value="" (ex.: "Todas") numa caixa com uma lista de
 * opções para marcar/desmarcar, "(Selecionar tudo)" e busca (listas grandes: o que for digitado já filtra,
 * como no Excel). O <select> fica oculto
 * e continua recebendo o evento "change".
 *
 *   FiltroMulti.criar(select)          cria o filtro
 *   FiltroMulti.valores(select)        null = sem filtro (tudo marcado); senão a lista dos valores marcados
 *   FiltroMulti.definir(select, lista) marca só esses valores (null = tudo)
 */
(function () {
  const estados = new WeakMap();

  function opcoes(select) {
    return Array.from(select.options).filter(o => o.value !== '').map(o => ({ valor: o.value, rotulo: o.text }));
  }

  function resumo(select, est) {
    const todos = select.options[0] ? select.options[0].text : 'Todos';
    if (!est.marcados) return todos;
    if (est.marcados.size === 0) return '(nenhum)';
    const lista = opcoes(select).filter(o => est.marcados.has(o.valor));
    if (lista.length === 1) return lista[0].rotulo;
    return lista.length + ' selecionados';
  }

  function atualizar(select) {
    const est = estados.get(select);
    const lista = opcoes(select);
    // tudo marcado = sem filtro
    if (est.marcados && lista.every(o => est.marcados.has(o.valor))) est.marcados = null;
    est.botao.textContent = resumo(select, est);
    est.botao.title = est.botao.textContent;
    est.botao.classList.toggle('filtro-ativo', !!est.marcados);
    est.caixas.forEach(cx => { cx.checked = !est.marcados || est.marcados.has(cx.value); });
    // com pesquisa, "(Selecionar tudo)" se refere só aos itens que estão aparecendo
    const visiveis = est.caixas.filter(cx => !cx.closest('label').classList.contains('d-none'));
    const marcadas = visiveis.filter(cx => cx.checked).length;
    est.todos.checked = marcadas === visiveis.length;
    est.todos.indeterminate = marcadas > 0 && marcadas < visiveis.length;
  }

  function avisar(select) {
    select.dispatchEvent(new Event('change', { bubbles: true }));
  }

  function criar(select) {
    if (estados.has(select)) return;
    const pequeno = select.classList.contains('form-select-sm');
    const caixa = document.createElement('div');
    caixa.className = 'dropdown filtro-multi';
    const botao = document.createElement('button');
    botao.type = 'button';
    botao.className = 'form-select text-start text-truncate' + (pequeno ? ' form-select-sm' : '');
    botao.setAttribute('data-bs-toggle', 'dropdown');
    botao.setAttribute('data-bs-auto-close', 'outside');
    botao.setAttribute('aria-label', select.getAttribute('aria-label') || select.title || 'Filtro');
    const menu = document.createElement('div');
    menu.className = 'dropdown-menu p-2 shadow filtro-multi-menu';
    const lista = opcoes(select);
    let busca = null;
    if (lista.length > 8) {
      busca = document.createElement('input');
      busca.type = 'search';
      busca.className = 'form-control form-control-sm mb-2';
      busca.placeholder = 'Pesquisar…';
      menu.appendChild(busca);
    }
    const linha = (rotulo, valor) => {
      const l = document.createElement('label');
      l.className = 'dropdown-item d-flex align-items-center gap-2 py-1 px-2';
      const cx = document.createElement('input');
      cx.type = 'checkbox';
      cx.className = 'form-check-input m-0';
      if (valor !== undefined) cx.value = valor;
      const t = document.createElement('span');
      t.textContent = rotulo;
      l.append(cx, t);
      return [l, cx];
    };
    const [lTodos, todos] = linha('(Selecionar tudo)');
    lTodos.classList.add('fw-semibold', 'border-bottom', 'mb-1');
    menu.appendChild(lTodos);
    const area = document.createElement('div');
    area.className = 'filtro-multi-opcoes';
    const caixas = lista.map(o => {
      const [l, cx] = linha(o.rotulo, o.valor);
      area.appendChild(l);
      return cx;
    });
    menu.appendChild(area);
    caixa.append(botao, menu);
    select.classList.add('d-none');
    select.after(caixa);
    // posição fixa: o menu não fica cortado dentro de tabelas com rolagem
    if (window.bootstrap) new bootstrap.Dropdown(botao, { autoClose: 'outside', popperConfig: { strategy: 'fixed' } });
    const est = { marcados: null, botao, caixas, todos };
    estados.set(select, est);

    todos.addEventListener('change', () => {
      const visiveis = caixas.filter(cx => !cx.closest('label').classList.contains('d-none'));
      if (busca && busca.value && visiveis.length < caixas.length) {
        // com pesquisa: marca/desmarca só o que está aparecendo
        const atual = est.marcados ? new Set(est.marcados) : new Set(caixas.map(cx => cx.value));
        visiveis.forEach(cx => (todos.checked ? atual.add(cx.value) : atual.delete(cx.value)));
        est.marcados = atual;
      } else {
        est.marcados = todos.checked ? null : new Set();
      }
      atualizar(select);
      avisar(select);
    });
    caixas.forEach(cx => cx.addEventListener('change', () => {
      const atual = est.marcados ? new Set(est.marcados) : new Set(caixas.map(c => c.value));
      cx.checked ? atual.add(cx.value) : atual.delete(cx.value);
      est.marcados = atual;
      atualizar(select);
      avisar(select);
    }));
    if (busca) {
      // Como no Excel: ao digitar, a lista mostra só o que combina e o filtro passa a ser só esses
      // itens, na hora; apagar a pesquisa volta à marcação de antes. Enter confirma e fecha.
      const normal = t => t.normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase();
      busca.addEventListener('input', () => {
        const t = normal(busca.value.trim());
        if (t && est.antesBusca === undefined) est.antesBusca = est.marcados ? new Set(est.marcados) : null;
        const visiveis = [];
        caixas.forEach(cx => {
          const combina = !t || normal(cx.nextSibling.textContent).includes(t);
          cx.closest('label').classList.toggle('d-none', !combina);
          if (combina) visiveis.push(cx.value);
        });
        if (t) {
          if (!visiveis.length) return;  // nada combina: mantém o filtro atual
          est.marcados = new Set(visiveis);
        } else if (est.antesBusca !== undefined) {
          est.marcados = est.antesBusca;
          delete est.antesBusca;
        }
        atualizar(select);
        avisar(select);
      });
      busca.addEventListener('keydown', ev => {
        if (ev.key === 'Enter') {
          ev.preventDefault();
          const dd = window.bootstrap && bootstrap.Dropdown.getInstance(botao);
          if (dd) dd.hide();
        } else if (ev.key === 'Escape' && busca.value) {
          ev.stopPropagation();
          busca.value = '';
          busca.dispatchEvent(new Event('input'));
        }
      });
      caixa.addEventListener('shown.bs.dropdown', () => busca.focus());
      // ao fechar, a pesquisa é limpa (a seleção feita continua valendo)
      caixa.addEventListener('hidden.bs.dropdown', () => {
        busca.value = '';
        delete est.antesBusca;
        caixas.forEach(cx => cx.closest('label').classList.remove('d-none'));
      });
    }
    // valor já escolhido no <select> (ex.: vindo do endereço) vira a marcação inicial
    if (select.value !== '') est.marcados = new Set([select.value]);
    atualizar(select);
  }

  function valores(select) {
    const est = estados.get(select);
    if (!est) return select.value === '' ? null : [select.value];
    return est.marcados ? Array.from(est.marcados) : null;
  }

  function definir(select, lista) {
    const est = estados.get(select);
    if (!est) { select.value = lista && lista.length ? lista[0] : ''; return; }
    const validos = new Set(opcoes(select).map(o => o.valor));
    est.marcados = lista ? new Set(lista.filter(v => validos.has(v))) : null;
    if (est.marcados && est.marcados.size === 0 && lista.length) est.marcados = null;
    atualizar(select);
  }

  window.FiltroMulti = { criar, valores, definir };
})();
