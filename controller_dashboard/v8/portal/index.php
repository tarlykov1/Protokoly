<?php
require $_SERVER['DOCUMENT_ROOT'].'/bitrix/modules/main/include/prolog_before.php';
require_once __DIR__.'/common.php';
header('Cache-Control: private,no-store');
[$cfg,$uid,$groups]=context8();
$public=[];
foreach($groups as $id=>$g) $public[]=['id'=>(int)$id,'name'=>$g['name'],'source'=>$g['source']];
$csrf=bitrix_sessid();
require __DIR__.'/view.php';
