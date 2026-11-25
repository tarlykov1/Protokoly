<?php
// Копировать вне DOCUMENT_ROOT в /etc/controller-v8/portal.php.
return [
    'backend'=>'http://127.0.0.1:18108', // loopback или HTTPS до отдельного сервера.
    'groups'=>[
        671=>['source'=>'memo','name'=>'МЕМО'],
        734=>['source'=>'protocol','name'=>'Протоколы · группа 734'],
    ],
    // Задать реальные ID двух технических пользователей списка 91 до включения доступа.
    'technical_ids'=>null,
    'assistant_property'=>0, // Поле «Помощник» списка 83.
    'manager_property'=>0, // Поле «Исполнитель (Ответственный руководитель)» списка 83.
    'comments_source'=>null, // null: автоопределение. forum или chat для подтверждённого источника. Допустимо указать по группе.
];
