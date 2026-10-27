<?php
// v3.9 – authorize each Bitrix group before proxying data.
function controller_dashboard_group_access() {
    global $USER;
    if (!$USER || !$USER->IsAuthorized()) {
        http_response_code(401); exit('Требуется авторизация Битрикс24');
    }
    if (!\Bitrix\Main\Loader::includeModule('socialnetwork')) {
        http_response_code(503); exit('Модуль рабочих групп недоступен');
    }
    $config = require __DIR__.'/config.php';
    $memoGroup = (int)($config['memo_group_id'] ?? 671);
    $protocolGroups = array_values(array_unique(array_filter(array_map('intval', $config['protocol_group_ids'] ?? []))));
    if ($USER->IsAdmin()) {
        return ['memo' => true, 'protocol_groups' => $protocolGroups];
    }
    $allowed = [];
    $groups = array_values(array_unique(array_merge([$memoGroup], $protocolGroups)));
    $records = \Bitrix\Socialnetwork\UserToGroupTable::getList([
        'filter' => ['=USER_ID' => (int)$USER->GetID(), '=GROUP_ID' => $groups, '=ROLE' => ['A','E','K']],
        'select' => ['GROUP_ID', 'ROLE'],
    ]);
    while ($item = $records->fetch()) $allowed[(int)$item['GROUP_ID']] = true;
    return [
        'memo' => isset($allowed[$memoGroup]),
        'protocol_groups' => array_values(array_filter($protocolGroups, function($id) use ($allowed) {
            return isset($allowed[$id]);
        })),
    ];
}
function controller_dashboard_require_access() {
    $access = controller_dashboard_group_access();
    if (!$access['memo'] && !$access['protocol_groups']) {
        http_response_code(403); exit('Нет доступа к группам кабинета контролёра');
    }
    return $access;
}
