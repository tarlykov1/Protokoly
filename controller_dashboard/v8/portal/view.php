<?php if(!isset($public,$csrf)){http_response_code(403);exit;} ?><!doctype html><html lang="ru"><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>Кабинет контролёра</title><link rel="stylesheet" href="style.css">
<main><header><div><small>МЕМО / ПРОТОКОЛЫ</small><h1>Кабинет контролёра</h1></div><button id="refresh">Обновить</button></header>
<p id="sources" role="status"></p><section id="filters"><label>Тип документа<select id="source"><option value="">Все типы</option><option value="memo">МЕМО</option><option value="protocol">Протокол</option></select></label>
<label>Группа<select id="group"><option value="">Все группы</option></select></label>
<label>Мероприятие<input id="event" type="search" list="events"></label><datalist id="events"></datalist>
<label>Исполнитель или соисполнитель<input id="person" type="search" list="people"></label><datalist id="people"></datalist>
<label>Поручение или документ<input id="query" type="search"></label>
<label>Поставлено с<input type="date" id="from"></label><label>по<input type="date" id="until"></label>
<label>Срок с<input type="date" id="dueFrom"></label><label>по<input type="date" id="dueTo"></label><button id="clear">Сбросить</button></section>
<section id="kpis"></section><section><h2>Зоны внимания</h2><div id="zones"></div><p id="stages"></p></section>
<section><h2>Динамика ИД</h2><label>Период <select id="period"><option value="week">Неделя</option><option value="month">Месяц</option><option value="quarter">Квартал</option><option value="year">Год</option></select></label><div id="chart"></div><details><summary>Динамика по главным ответственным</summary><div class="scroll" id="individual"></div></details></section>
<section><h2 id="regTitle">Реестр поручений</h2><div id="upper"><div></div></div><div id="lower" class="scroll"><table><thead><tr><?php foreach(['Поручение','Документ','Мероприятие','Группа','Главный ответственный','Соисполнители','Помощники','Руководитель в задаче','Руководитель по оргструктуре','Стадия','Срок','Состояние','Реакция контролёра','Новый комментарий'] as $s) echo '<th>'.$s.'</th>'; ?></tr></thead><tbody id="body"></tbody></table></div></section>
<dialog id="detail"><button id="close">Закрыть</button><article></article></dialog></main>
<script id="config" type="application/json"><?=json_encode(['groups'=>$public,'csrf'=>$csrf],JSON_HEX_TAG|JSON_HEX_AMP|JSON_THROW_ON_ERROR)?></script><script src="model.js"></script><script src="ui.js"></script></html>
