<?php
// Controller dashboard v3.4. Uses one entry point for the full Bitrix page and iframe.
if (isset($_GET['controller_view']) && $_GET['controller_view'] === '1') {
    require($_SERVER['DOCUMENT_ROOT'].'/bitrix/modules/main/include/prolog_before.php');
    require_once __DIR__.'/guard.php';
    controller_dashboard_require_access();
    header('Content-Type: text/html; charset=utf-8');
    header('Cache-Control: no-store, no-cache, must-revalidate, max-age=0');
    readfile(__DIR__.'/dashboard.html');
    exit;
}
require($_SERVER['DOCUMENT_ROOT'].'/bitrix/header.php');
global $USER, $APPLICATION;
require_once __DIR__.'/guard.php';
controller_dashboard_require_access();
$APPLICATION->SetTitle('Кабинет контролёра');
?>
<div id="controllerDashboardContainer" style="width:100%;min-width:0;overflow:hidden;background:#f3f6fc;border-radius:14px;">
  <iframe src="/controller-dashboard/index.php?controller_view=1&amp;v=3.4" title="Кабинет контролёра" style="width:100%;height:calc(100vh - 185px);min-height:720px;border:0;display:block;" loading="eager"></iframe>
</div>
<?php require($_SERVER['DOCUMENT_ROOT'].'/bitrix/footer.php'); ?>
