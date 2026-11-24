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
    'assistant_property'=>0, // Автовыбор единственного поля Сотрудник списка 83.
    'comments_source'=>null, // forum или chat согласно проверенному хранилищу. Допустимо указать по группе.
];
