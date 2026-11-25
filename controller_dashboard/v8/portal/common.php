<?php
use Bitrix\Main\Loader;
use Bitrix\Socialnetwork\UserToGroupTable;

function fail8($code, $msg) {
    http_response_code($code);
    echo json_encode(['error'=>$msg], JSON_UNESCAPED_UNICODE); exit;
}
function roster8($list, $property = 0) {
    if (!Loader::includeModule('iblock')) return null;
    $props = CIBlockProperty::GetList([], ['IBLOCK_ID'=>$list, 'ACTIVE'=>'Y']);
    $ids = [];
    while ($p=$props->Fetch()) {
        if ($p['USER_TYPE']==='employee' && (!$property || (int)$p['ID']===$property)) $ids[]=(int)$p['ID'];
    }
    if (count($ids)!==1) return null;
    $field='PROPERTY_'.$ids[0];
    $rs=CIBlockElement::GetList([], ['IBLOCK_ID'=>$list,'ACTIVE'=>'Y'],false,false,['ID',$field]);
    $users=[];
    while ($r=$rs->Fetch()) {
        if (!array_key_exists($field.'_VALUE',$r)) return null;
        foreach ((array)$r[$field.'_VALUE'] as $id) {
        if ($id!==null && $id!=='' && !ctype_digit((string)$id)) return null;
        if ((int)$id>0) $users[(int)$id]=true;
    }
    }
    return $users ?: null;
}
// A list element pairs one responsible manager with one or more assistants.
function assistantPairs8($cfg) {
    if (!Loader::includeModule('iblock')) return null;
    $roles=['manager'=>['Исполнитель (Ответственный руководитель)', (int)($cfg['manager_property'] ?? 0)],
            'assistant'=>['Помощник', (int)($cfg['assistant_property'] ?? 0)]];
    $fields=[];
    $props=CIBlockProperty::GetList([], ['IBLOCK_ID'=>83,'ACTIVE'=>'Y']);
    while ($p=$props->Fetch()) {
        if ($p['USER_TYPE']!=='employee') continue;
        foreach ($roles as $role=>[$name,$configured]) {
            if ($configured ? (int)$p['ID']===$configured : trim($p['NAME'])===$name) {
                if (isset($fields[$role])) return null;
                $fields[$role]='PROPERTY_'.(int)$p['ID'];
            }
        }
    }
    if (count(array_unique($fields))!==2) return null;
    $members=[];
    foreach ($fields as $role=>$field) {
        $rs=CIBlockElement::GetList([],['IBLOCK_ID'=>83,'ACTIVE'=>'Y'],false,false,['ID',$field]);
        while ($r=$rs->Fetch()) {
            if (!array_key_exists($field.'_VALUE',$r)) return null;
            foreach ((array)$r[$field.'_VALUE'] as $user) {
                if ($user===null || $user==='') continue;
                if (!ctype_digit((string)$user) || (int)$user<=0) return null;
                $members[$r['ID']][$role][(int)$user]=true;
            }
        }
    }
    $pairs=[];
    foreach ($members as $row) {
        if (count($row['manager'] ?? [])!==1) return null;
        $manager=key($row['manager']);
        $pairs[$manager]=($pairs[$manager] ?? [])+($row['assistant'] ?? []);
    }
    return $pairs;
}
function context8() {
    global $USER;
    if (!$USER || !$USER->IsAuthorized()) fail8(401,'Войдите в Битрикс24');
    $cfg=require '/etc/controller-v8/portal.php';
    if (!Loader::includeModule('tasks') || !Loader::includeModule('socialnetwork')) fail8(503,'Недоступны модули Битрикс24');
    if (!is_array($cfg['technical_ids'] ?? null)) fail8(503,'Настройте исключения технических учётных записей');
    $url=parse_url($cfg['backend']);
    if (($url['scheme'] ?? '')!=='https' && !(($url['scheme'] ?? '')==='http' && in_array($url['host'] ?? '', ['127.0.0.1','localhost'],true)))
        fail8(503,'Для связи с удалённым сервисом требуется HTTPS');
    $controllers=roster8(91,306);
    foreach ($cfg['technical_ids'] ?? [] as $id) unset($controllers[$id]);
    $groups=access8($USER,$cfg['groups'],$controllers);
    return [$cfg,(int)$USER->GetID(),$groups,$controllers];
}
function access8($USER,$groups,$controllers) {
    $uid=(int)$USER->GetID();
    if (!$USER->IsAdmin() && $controllers===null) fail8(503,'Недоступен список 91');
    if (!$USER->IsAdmin() && !isset($controllers[$uid])) fail8(403,'Нет роли контролёра');
    if (!$USER->IsAdmin()) {
        $rs=UserToGroupTable::getList(['select'=>['GROUP_ID'],'filter'=>['=USER_ID'=>$uid,'@GROUP_ID'=>array_keys($groups),'@ROLE'=>['A','E','K']]]);
        $allowed=[];
        while ($r=$rs->fetch()) $allowed[(int)$r['GROUP_ID']]=true;
        $groups=array_intersect_key($groups,$allowed);
    }
    if (!$groups) fail8(403,'Нет доступных групп');
    return $groups;
}
function backend8($cfg,$uid,$path,$body) {
    $client=new \Bitrix\Main\Web\HttpClient(['socketTimeout'=>6,'streamTimeout'=>45,'redirect'=>false]);
    $client->setHeader('Content-Type','application/json');
    $tokenPath='/etc/controller-v8/token';
    $token=is_readable($tokenPath) ? trim((string)file_get_contents($tokenPath)) : '';
    if(strlen($token)<32) fail8(503,'На веб-сервере портала не настроен или недоступен файл токена кабинета');
    $client->setHeader('X-Dashboard-Token',$token);
    $client->setHeader('X-Bitrix-User',(string)$uid);
    $reply=$client->post(rtrim($cfg['backend'],'/').$path,json_encode($body,JSON_THROW_ON_ERROR));
    $value=json_decode((string)$reply,true);
    $status=(int)$client->getStatus();
    if ($status===0) fail8(503,'Нет соединения от веб-сервера портала до службы кабинета');
    if ($status===401 || $status===403) fail8(503,'Служба отклонила запрос портала. Проверьте токен и права на источник');
    if ($status!==200 || !is_array($value)) fail8(503,'Сервис кабинета или источник данных недоступен');
    return $value;
}
function iso8($date) {
    if (!$date) return null;
    if (is_object($date)) return date('c',$date->getTimestamp());
    $ts=MakeTimeStamp($date);
    return $ts ? date('c',$ts) : null;
}
function names8($ids,$names) {
    return array_map(function($i) use ($names) {return $names[$i] ?? ('ID '.$i);},array_values($ids));
}
function tasks8($ids,$group,$uid,$extra=[]) {
    if (!$ids) return [];
    $out=[];
    foreach (array_chunk($ids,200) as $batch) {
        $rs=CTasks::GetList(['ID'=>'ASC'],['ID'=>$batch,'GROUP_ID'=>$group,'CHECK_PERMISSIONS'=>'Y'],
          array_merge(['ID','GROUP_ID','TITLE','STATUS','REAL_STATUS','RESPONSIBLE_ID','STAGE_ID','DEADLINE',
          'CLOSED_DATE','CREATED_DATE','CHANGED_DATE','FORUM_TOPIC_ID'],$extra),['USER_ID'=>$uid]);
        if (!$rs) throw new RuntimeException();
        while ($r=$rs->Fetch()) {
            if ((int)$r['GROUP_ID']!==$group || !in_array((int)$r['ID'],$batch,true)) throw new RuntimeException();
            $out[(int)$r['ID']]=$r;
        }
    }
    return $out;
}
