<?php
require($_SERVER['DOCUMENT_ROOT'].'/bitrix/modules/main/include/prolog_before.php');
require_once __DIR__.'/guard.php';
$access = controller_dashboard_require_access();
use Bitrix\Main\Web\HttpClient;
header('Content-Type: application/json; charset=utf-8');
header('Cache-Control: no-store');
$path = (string)($_GET['path'] ?? '');
$method = (string)($_SERVER['REQUEST_METHOD'] ?? 'GET');
if (!(($path === 'items' || $path === 'bootstrap') && $method === 'GET') &&
    !($path === 'protocol-start' && $method === 'POST')) {
    http_response_code(405); echo json_encode(['detail'=>'Unsupported operation']); exit;
}
if ($path === 'bootstrap') {
    echo json_encode(['protocol_enabled' => count($access['protocol_groups']) > 0,
                      'csrf' => bitrix_sessid()], JSON_UNESCAPED_UNICODE);
    exit;
}
if ($path === 'protocol-start' && !check_bitrix_sessid()) {
    http_response_code(403); echo json_encode(['detail'=>'Invalid Bitrix session']); exit;
}
$config = require __DIR__.'/config.php';
$tokenFile = '/etc/bitrix-controller-dashboard/token';
$token = is_readable($tokenFile) ? trim(file_get_contents($tokenFile)) : '';
if (strlen($token) < 32) {
    http_response_code(503); echo json_encode(['detail'=>'Dashboard backend secret not configured']); exit;
}
$client = new HttpClient(['socketTimeout'=>15,'streamTimeout'=>35,'redirect'=>false]);
$client->setHeader('X-Dashboard-Token', $token);
$client->setHeader('X-Bitrix-User', (string)$USER->GetID());
$client->setHeader('X-Allow-Memo', $access['memo'] ? '1' : '0');
$client->setHeader('X-Allowed-Protocol-Groups', implode(',', $access['protocol_groups']));
$client->setHeader('Accept', 'application/json');
$backend = rtrim($config['backend'], '/');
if ($path === 'protocol-start') {
    if (!$access['protocol_groups']) {
        http_response_code(403); echo json_encode(['detail'=>'Protocol groups not authorized']); exit;
    }
    $client->setHeader('Content-Type', 'application/json');
    $reply = $client->post($backend.'/protocol/start',
                           json_encode(['group_ids'=>$access['protocol_groups']]));
    $status = (int)$client->getStatus();
    if ($status === 200) {
        $result = json_decode($reply, true);
        $rid = $result['report_id'] ?? '';
        if (is_string($rid) && preg_match('/^[a-f0-9]{32}$/', $rid)) {
            $_SESSION['controller_dashboard_protocol_report'] = $rid;
        } else {
            http_response_code(502); echo json_encode(['detail'=>'Invalid backend report id']); exit;
        }
    }
} else {
    $rid = (string)($_SESSION['controller_dashboard_protocol_report'] ?? '');
    if (preg_match('/^[a-f0-9]{32}$/', $rid)) {
        $client->setHeader('X-Protocol-Report', $rid);
    }
    $reply = $client->get($backend.'/items');
    $status = (int)$client->getStatus();
}
if ($status <= 0) {
    http_response_code(502); echo json_encode(['detail'=>'Python backend unreachable']); exit;
}
http_response_code($status);
echo $reply;
