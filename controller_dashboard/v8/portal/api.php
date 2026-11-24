<?php
require $_SERVER['DOCUMENT_ROOT'].'/bitrix/modules/main/include/prolog_before.php';
require_once __DIR__.'/common.php';
require_once __DIR__.'/data.php';
header('Content-Type: application/json; charset=utf-8'); header('Cache-Control: private,no-store');
try {
    [$cfg,$uid,$groups,$controllers]=context8();
    if($_SERVER['REQUEST_METHOD']!=='POST' || !check_bitrix_sessid()) fail8(403,'Сессия истекла');
    $op=$_POST['op'] ?? ''; $group=(int)($_POST['group'] ?? 0);
    if(!isset($groups[$group])) fail8(403,'Нет прав на группу');
    $spec=$groups[$group]; $channel=$spec['comments_source'] ?? $cfg['comments_source'] ?? 'unknown';
    if($op==='detail'){
        $id=(int)($_POST['task'] ?? 0);
        if(!isset($_SESSION['controller_v8_tasks'][$uid][$group][$id])) fail8(403,'Поручение не входит в реестр');
        $task=tasks8([$id],$group,$uid);
        if(!isset($task[$id])) fail8(403,'Нет доступа к задаче');
        $messages=messages8($task,$channel);
        $result=['comments'=>null,'marker'=>null];
        if(isset($messages[$id])){
            $items=$messages[$id];
            [$names]=employees8(array_column($items,'AUTHOR_ID'));
            $comments=[]; $last=0;
            foreach($items as $m){
                if(!empty($m['SERVICE_TYPE']) || $m['NEW_TOPIC']==='Y') continue;
                $author=(int)$m['AUTHOR_ID']; $last=(int)$m['ID'];
                $comments[]=['author'=>$names[$author] ?? ('ID '.$author),'at'=>iso8($m['POST_DATE']),'text'=>(string)$m['POST_MESSAGE']];
            }
            $result=['comments'=>$comments,'marker'=>$last];
            $_SESSION['controller_v8_shown'][$uid][$group][$channel][$id]=$last;
        }
    } elseif($op==='mark'){
        $id=(int)($_POST['task'] ?? 0); $marker=filter_var($_POST['marker'] ?? null,FILTER_VALIDATE_INT);
        $cap=$_SESSION['controller_v8_shown'][$uid][$group][$channel][$id] ?? null;
        if($marker===false || $cap===null || $marker>$cap || !tasks8([$id],$group,$uid)) fail8(403,'Нет доступа к отметке');
        $result=backend8($cfg,$uid,'/view',['task'=>$id,'marker'=>$marker,'channel'=>$channel]);
    } elseif($op==='group'){
        $pending=(!empty($_POST['poll'])) ? ($_SESSION['controller_v8_pending'][$uid][$group] ?? null) : null;
        $source=backend8($cfg,$uid,'/source',['group'=>$group,'source'=>$spec['source'],'report'=>$pending]);
        $_SESSION['controller_v8_pending'][$uid][$group]=$source['report'] ?? null;
        $result=['status'=>$source['status']];
        if($source['status']==='ready'){
            $seed=$source['tasks']; $tasks=tasks8(array_map('intval',array_keys($seed)),$group,$uid);
            $result+=assemble8($cfg,$uid,$group,$spec,$seed,$tasks,$controllers);
            $result['at']=$source['at'];
            $_SESSION['controller_v8_tasks'][$uid][$group]=array_fill_keys(array_keys($tasks),true);
        }
    } else fail8(400,'Неизвестная операция');
    echo json_encode($result,JSON_THROW_ON_ERROR|JSON_UNESCAPED_UNICODE);
} catch(Throwable $e){fail8(503,'Ошибка загрузки кабинета. Проверьте настройку источников и журнал сервера.');}
