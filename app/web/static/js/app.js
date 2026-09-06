document.addEventListener('click',(e)=>{const t=e.target.closest('[data-toggle-sidebar]');if(t){document.querySelector('.sidebar')?.classList.toggle('open')}});

(() => {
  const labels = new Map(Object.entries({
    draft:'Черновик', review:'На проверке', approved:'Утверждён', validation_required:'Требует проверки',
    ready:'Готов', error:'С ошибками', uploaded:'Импортирован', parsed:'Импортирован', confirmed:'Импортирован',
    published:'Опубликован', success:'Успешно', partial:'Частично выполнено', cancelled:'Отменён', failed:'С ошибками',
    completed:'Выполнено', new:'Новая', pending:'Ожидает выполнения', in_progress:'В работе', waiting_control:'Ожидает контроля',
    overdue:'Просрочено', rejected:'Возвращено на доработку', control:'На контроле', needs_review:'Требует проверки',
    found:'Найден', not_found:'Не найден', multiple_matches:'Найдено несколько совпадений', not_in_bitrix:'Не найден в Bitrix24',
    fake:'Тестовый режим', rest:'Bitrix24 REST', demo:'Демонстрационный режим', in_person:'Очно', video:'ВКС', hybrid:'Смешанный',
    memo_protocol:'МЕМО', universal_protocol:'Протокол', protocol:'Протокол', memo:'МЕМО'
  }));

  const phraseReplacements = [
    [/\bconfidence\s+([0-9.]+)/gi, 'точность распознавания $1'],
    [/Demo actions are disabled/gi, 'Демонстрационные действия отключены'],
    [/\bWorkflow\b/g, 'Этап обработки']
  ];

  const replaceText = text => {
    const trimmed = text.trim();
    if (labels.has(trimmed)) return text.replace(trimmed, labels.get(trimmed));
    let result = text;
    phraseReplacements.forEach(([pattern, replacement]) => { result = result.replace(pattern, replacement); });
    return result;
  };

  const localizeElement = root => {
    root.querySelectorAll('option').forEach(option => {
      const key = option.textContent.trim();
      if (labels.has(key)) option.textContent = labels.get(key);
    });
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, {
      acceptNode(node) {
        const parent = node.parentElement;
        if (!parent || ['SCRIPT','STYLE','CODE','PRE'].includes(parent.tagName)) return NodeFilter.FILTER_REJECT;
        return NodeFilter.FILTER_ACCEPT;
      }
    });
    const nodes = [];
    while (walker.nextNode()) nodes.push(walker.currentNode);
    nodes.forEach(node => {
      const next = replaceText(node.nodeValue);
      if (next !== node.nodeValue) node.nodeValue = next;
    });
  };

  document.addEventListener('DOMContentLoaded', () => localizeElement(document.body));
  const observer = new MutationObserver(records => records.forEach(record => record.addedNodes.forEach(node => {
    if (node.nodeType === Node.ELEMENT_NODE) localizeElement(node);
    else if (node.nodeType === Node.TEXT_NODE && node.parentElement) {
      const next = replaceText(node.nodeValue);
      if (next !== node.nodeValue) node.nodeValue = next;
    }
  })));
  document.addEventListener('DOMContentLoaded', () => observer.observe(document.body, {childList:true, subtree:true}));
})();
