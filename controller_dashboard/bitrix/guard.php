<?php
// v3.4 temporary single-MEMO-group ACL; multi-group controllers require explicit policy.
function controller_dashboard_require_access() {
    global $USER;
    if (!$USER || !$USER->IsAuthorized()) {
        http_response_code(401);
        exit('Требуется авторизация Битрикс24');
    }
    if ($USER->IsAdmin()) return;
    if (!\Bitrix\Main\Loader::includeModule('socialnetwork')) {
        http_response_code(503);
        exit('Модуль рабочих групп недоступен');
    }
    $config = require __DIR__.'/config.php';
    $groupId = (int)($config['memo_group_id'] ?? 0);
    if ($groupId <= 0) {
        http_response_code(503);
        exit('Группа МЕМО не настроена');
    }
    $membership = \Bitrix\Socialnetwork\UserToGroupTable::getList([
        'filter' => [
            '=GROUP_ID' => $groupId,
            '=USER_ID' => (int)$USER->GetID(),
            '=ROLE' => ['A','E','K'],
        ],
        'select' => ['USER_ID'], 'limit' => 1,
    ])->fetch();
    if (!$membership) {
        http_response_code(403);
        exit('Нет доступа к группе МЕМО');
    }
}
