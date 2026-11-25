<?php
if (!isset($public,$csrf)) { http_response_code(403); exit; }
?>
<!doctype html>
<html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Кабинет контролёра</title>
<?php
if (class_exists('CJSCore') && isset($GLOBALS['APPLICATION'])) {
    CJSCore::Init(['sidepanel']);
    $GLOBALS['APPLICATION']->ShowHead();
}
?><link rel="stylesheet" href="style.css?rev=loading9"></head>
<body><main>
<h1 class="sr-only">Кабинет контролёра</h1>
<section id="filters" class="filters">
  <header class="toolbar"><details class="freshness"><summary>Актуальность данных</summary><p id="sources" role="status"></p></details>
    <div class="actions"><span id="volume"></span><a class="registry-link" href="#registry">Реестр поручений</a><button id="refresh">Обновить</button><button id="csv" class="primary">Скачать CSV</button></div></header>
  <div class="load-status" id="loadStatus">
    <div><b id="loadSummary" role="status">Загрузка групп…</b><small id="loadTime"></small></div>
    <progress id="loadProgress" aria-labelledby="loadSummary" max="1" value="0"></progress>
    <small id="loadGroup"></small>
  </div>
  <div class="filter-grid">
    <label>Тип документа<select id="source"><option value="">Все документы</option><option value="memo">МЕМО</option><option value="protocol">Протоколы</option></select></label>
    <label>Исполнитель или соисполнитель<input id="person" type="search" list="people" placeholder="Поиск по ФИО"></label><datalist id="people"></datalist>
    <label>Период динамики<select id="period" aria-label="Период динамики"><option value="week">Неделя</option><option value="month">Месяц</option><option value="quarter">Квартал</option><option value="year">Год</option></select></label>
    <label>Группа<select id="group"><option value="">Все группы</option></select></label>
    <label>Мероприятие<input id="event" type="search" list="events" placeholder="Все мероприятия"></label><datalist id="events"></datalist>
    <label class="query">Поручение или документ<input id="query" type="search" placeholder="Номер или название"></label>
    <details class="dates"><summary>Фильтр по датам</summary><div class="date-grid">
      <label>Поставлено с<input type="date" id="from"></label><label>Поставлено по<input type="date" id="until"></label>
      <label>Срок с<input type="date" id="dueFrom"></label><label>Срок по<input type="date" id="dueTo"></label>
    </div></details><button id="clear">Сбросить</button>
  </div>
</section>
<section id="overview" aria-label="Показатели"><p id="partialScope" hidden></p><div id="kpis"></div></section>
<section><h2>Структура портфеля</h2><div id="portfolio"></div></section>
<div class="two-col">
  <section><h2>Исполнительская дисциплина по группам</h2><div id="groupDiscipline"></div></section>
  <section id="trends"><div class="panel-head"><h2>Динамика исполнения</h2>
    <div id="periodButtons" class="segments" aria-label="Период"><?php foreach (['week'=>'Неделя','month'=>'Месяц','quarter'=>'Квартал','year'=>'Год'] as $key=>$label) echo '<button data-period="'.$key.'">'.$label.'</button>'; ?></div>

    </div><h3>Закрытые поручения, шт.</h3><div id="closedChart"></div>
    <details><summary>Динамика ИД и главные ответственные</summary><div id="chart"></div><div class="scroll" id="individual"></div></details>
  </section>
</div>
<section id="stages"><div class="panel-head"><h2>Стадии и состояние задач</h2><small id="stageVolume"></small></div><div class="stage-layout"><div id="stageRing"></div><div id="stageCards" class="stage-cards"></div></div></section>
<section><h2>Зоны внимания</h2><div id="zones"></div>
  <h3 class="risk-title">Просроченные по стадиям</h3><div id="riskChips"></div>
  <div class="attention"><span><b>Требуют внимания</b> · просрочка более 7 дней</span><strong id="attentionCount">—</strong><button id="attentionOpen">Показать в реестре</button></div>
</section>
<details class="additional"><summary>Статусы, сроки и участие контролёров</summary><div class="two-col">
  <section><h2>Статусы Битрикс24</h2><div id="statusGraph"></div></section>
  <section><h2>Контроль сроков</h2><div id="dueGraph"></div></section>
  <section><h2>Контролёры и помощники</h2><div id="controlGraph"></div></section>
  <section><h2>Просрочка по стадиям МЕМО</h2><div id="stageGraph"></div></section>
</div></details>
<section id="registry"><div class="panel-head"><h2 id="regTitle">Реестр поручений</h2><button id="registryReset">Сбросить</button></div>
  <div class="registry-tools"><div class="registry-summary"><b id="registryCount" aria-live="polite"></b><small>По умолчанию – проблемные</small></div><label>Поиск в реестре<input type="search" id="registryQuery" placeholder="Найти среди выбранных задач"></label>
    <label>Показать<select id="registryMode"><option value="all">Все поручения</option><option value="problems" selected>Требуют внимания</option><option value="overdue">Просроченные</option></select></label>
    <label>Порядок<select id="registryOrder"><option value="source">Как в источнике</option><option value="risk" selected>Сначала проблемные</option><option value="due">По сроку</option><option value="assigned">По дате поручения</option></select></label></div>
  <div id="upper" tabindex="0" role="region" aria-label="Верхняя горизонтальная прокрутка"><div></div></div>
  <input type="range" class="scroll-fallback" id="scrollTopRange" aria-label="Горизонтальная прокрутка сверху" min="0" max="0" value="0" hidden>
  <div id="lower" class="scroll" tabindex="0" role="region" aria-label="Строки реестра поручений"><table><thead><tr>
<?php foreach (['Дата поручения','Крайний срок','Сигналы','Ответственный / соисполнители','Помощник','Поручение / документ','Действия контролёра','Мероприятие','Группа','Руководитель в задаче','Руководитель по оргструктуре','Стадия','Состояние','Новый комментарий'] as $s) echo '<th>'.$s.'</th>'; ?>
  </tr></thead><tbody id="body"></tbody></table></div>
  <input type="range" class="scroll-fallback" id="scrollBottomRange" aria-label="Горизонтальная прокрутка снизу" min="0" max="0" value="0" hidden>
</section>
<dialog id="detail"><button id="close">Закрыть</button><article></article></dialog></main>
<script id="config" type="application/json"><?=json_encode(['groups'=>$public,'csrf'=>$csrf,'userId'=>(int)(isset($GLOBALS['USER']) ? $GLOBALS['USER']->GetID() : 0)],JSON_HEX_TAG|JSON_HEX_AMP|JSON_THROW_ON_ERROR)?></script>
<script src="model.js?rev=loading9"></script><script src="registry.js?rev=loading9"></script><script src="ui.js?rev=loading9"></script></body></html>
