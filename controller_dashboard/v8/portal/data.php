<?php
use Bitrix\Tasks\Internals\Task\MemberTable;
use Bitrix\Tasks\Internals\Task\LogTable;
use Bitrix\Tasks\Kanban\StagesTable;
use Bitrix\Forum\MessageTable;

function related8($class,$key,$ids,$select,$filter=[], $order=[]) {
    $out=[];
    foreach(array_chunk(array_values(array_unique($ids)),200) as $chunk) {
        $rs=$class::getList(['select'=>$select,'filter'=>array_merge(['@'.$key=>$chunk],$filter),'order'=>$order]);
        while($r=$rs->fetch()) $out[(int)$r[$key]][]=$r;
    }
    return $out;
}
function history8($logs,$responsible) {
    $creation=false; $started=null; $submitted=false; $dates=[]; $changes=[]; $moves=0;
    foreach($logs as $l) {
        $field=$l['FIELD']; $old=(string)$l['FROM_VALUE']; $new=(string)$l['TO_VALUE'];
        $at=iso8($l['CREATED_DATE']);
        if(in_array($field,['NEW','CREATED_DATE'],true)) $creation=true;
        if($field==='STATUS') {
            if(in_array($new,['1','2','3','6','7'],true)) $submitted=false;
            if((int)$l['USER_ID']===$responsible) {
                if($new==='3' && !$started) $started=$at;
                if(in_array($new,['4','5'],true)) $submitted=true;
            }
        }
        if($field==='DEADLINE') {
            $dates[]=['at'=>$at,'from'=>$old,'to'=>$new];
            if ($old!=='' && $new!=='' && $old!==$new) $moves++;
        }
        if(!in_array($field,['COMMENT','NEW'],true)) $changes[]=['at'=>$at,'field'=>$field];
    }
    return compact('creation','started','submitted','dates','moves','changes');
}
function chatMessages8($chat,$detail) {
    if(!\Bitrix\Im\Dialog::hasAccess('chat'.$chat)) return null;
    $messages=[]; $options=['LIMIT'=>50,'JSON'=>'Y']; $cursor=null;
    do {
        $page=\Bitrix\Im\Chat::getMessages($chat,null,$options);
        $batch=$page['messages'] ?? null;
        if(!is_array($batch)) return null;
        if(!$batch) break;
        $ids=[];
        foreach($batch as $m){
            $id=(int)($m['id'] ?? 0);
            if(!$id || ($cursor!==null && $id >= $cursor) || !isset($m['author_id'],$m['date'])) return null;
            $ids[]=$id;
            if((int)$m['author_id']<=0 || ($m['params']['IS_SYSTEM'] ?? 'N')==='Y') continue;
            $messages[$id]=['ID'=>$id,'AUTHOR_ID'=>(int)$m['author_id'],
                'POST_DATE'=>new DateTimeImmutable($m['date']),'POST_MESSAGE'=>$detail ? ($m['text'] ?? '') : '',
                'NEW_TOPIC'=>'N','SERVICE_TYPE'=>0];
        }
        $cursor=min($ids); $options['LAST_ID']=$cursor;
    } while(count($batch)===50);
    ksort($messages,SORT_NUMERIC); return $messages;
}
function messages8($tasks,$mode,$detail=false) {
    $out=[];
    if($mode==='chat'){
        if(!\Bitrix\Main\Loader::includeModule('im')) return [];
        $map=related8(\Bitrix\Im\Model\ChatTable::class,'ENTITY_ID',array_keys($tasks),
            ['ID','ENTITY_ID'],['=ENTITY_TYPE'=>'TASKS_TASK']);
        foreach($map as $task=>$chats) if(count($chats)===1) {
            try {$out[$task]=chatMessages8((int)$chats[0]['ID'],$detail);}
            catch(Throwable $e){$out[$task]=null;}
        }
        return $out;
    }
    if($mode!=='forum' || !\Bitrix\Main\Loader::includeModule('forum')) return [];
    $topics=array_filter(array_column($tasks,'FORUM_TOPIC_ID'));
    $fields=['TOPIC_ID','ID','AUTHOR_ID','POST_DATE','SERVICE_TYPE','NEW_TOPIC'];
    if($detail) $fields[]='POST_MESSAGE';
    $byTopic=related8(MessageTable::class,'TOPIC_ID',$topics,$fields,
        ['=APPROVED'=>'Y'],['ID'=>'ASC']);
    foreach($tasks as $task=>$r) if(array_key_exists('FORUM_TOPIC_ID',$r))
        $out[$task]=$byTopic[(int)$r['FORUM_TOPIC_ID']] ?? [];
    return $out;
}
function employees8($ids) {
    $ids=array_values(array_unique(array_filter($ids))); $names=[]; $depts=[];
    foreach(array_chunk($ids,200) as $chunk) {
        $by='ID'; $order='ASC';
        $rs=CUser::GetList($by,$order,['ID'=>implode('|',$chunk)],['FIELDS'=>['ID','NAME','LAST_NAME','SECOND_NAME'],'SELECT'=>['UF_DEPARTMENT']]);
        while($r=$rs->Fetch()){
            $id=(int)$r['ID']; $name=trim(implode(' ',array_filter([$r['LAST_NAME'],$r['NAME'],$r['SECOND_NAME']])));
            if($name!=='') $names[$id]=$name;
            $depts[$id]=array_filter((array)($r['UF_DEPARTMENT'] ?? []));
        }
    }
    return [$names,$depts];
}
function assemble8($cfg,$uid,$group,$spec,$seed,$tasks,$controllers) {
    $ids=array_keys($tasks);
    $members=related8(MemberTable::class,'TASK_ID',$ids,['TASK_ID','USER_ID','TYPE']);
    try {$logs=related8(LogTable::class,'TASK_ID',$ids,['TASK_ID','ID','USER_ID','FIELD','FROM_VALUE','TO_VALUE','CREATED_DATE'],[],['CREATED_DATE'=>'ASC','ID'=>'ASC']);}
    catch(Throwable $e){
        $logs=[];
        foreach($ids as $id) {
            try {
                $rs=CTaskLog::GetList(['CREATED_DATE'=>'ASC','ID'=>'ASC'],['TASK_ID'=>$id]);
                if(!$rs) throw new RuntimeException();
                while($l=$rs->Fetch()) $logs[$id][]=$l;
            } catch(Throwable $failure){$logs[$id]=null;}
        }
    }
    try {$messages=messages8($tasks,$spec['comments_source'] ?? $cfg['comments_source'] ?? null);}catch(Throwable $e){$messages=null;}
    $users=array_column($tasks,'RESPONSIBLE_ID');
    foreach($members as $list) foreach($list as $m) $users[]=$m['USER_ID'];
    foreach($seed as $r) if(ctype_digit((string)$r['leader'])) $users[]=$r['leader'];
    [$names,$departments]=employees8($users);
    $heads=[]; $org=(int)COption::GetOptionString('intranet','iblock_structure','0');
    $deptIds=[]; foreach($departments as $list) foreach($list as $d) $deptIds[]=$d;
    if($org && $deptIds) {
        $rs=CIBlockSection::GetList([],['IBLOCK_ID'=>$org,'ID'=>array_unique($deptIds)],false,['ID','UF_HEAD']);
        while($r=$rs->Fetch()) if(!empty($r['UF_HEAD'])) $heads[$r['ID']]=(int)$r['UF_HEAD'];
        $names+=employees8(array_values($heads))[0];
    }
    $assistants=roster8(83,(int)($cfg['assistant_property'] ?? 0));
    $rows=[]; $observations=[];
    $stages=related8(StagesTable::class,'ID',array_filter(array_column($tasks,'STAGE_ID')),['ID','TITLE']);
    foreach($tasks as $id=>$r){
        $meta=$seed[$id]; $resp=(int)$r['RESPONSIBLE_ID']; $acc=[]; $aud=[];
        foreach($members[$id] ?? [] as $m) {
            if($m['TYPE']==='A') $acc[]=(int)$m['USER_ID'];
            if($m['TYPE']==='U') $aud[]=(int)$m['USER_ID'];
        }
        $managers=[]; foreach($departments[$resp] ?? [] as $d) if(isset($heads[$d]) && $heads[$d]!==$resp) $managers[]=$heads[$d];
        $h=array_key_exists($id,$logs) && $logs[$id]===null ? null : history8($logs[$id] ?? [],$resp);
        $stage=$stages[(int)$r['STAGE_ID']][0]['TITLE'] ?? $meta['stage'];
        $status=(string)($r['REAL_STATUS'] ?? $r['STATUS']);
        $state=null;
        if(preg_match('/неактуаль|отмен/iu',(string)$stage.' '.(string)$meta['source_status']) ||
           in_array((int)$r['STAGE_ID'],$spec['obsolete_stages'] ?? [],true)) $state='obsolete';
        elseif($stage || isset($spec['obsolete_stages'])){
            if($status==='5') $state=($h['submitted'] ?? false) ? 'done' : null;
            elseif(in_array($status,['1','2','3','4','6'],true)) $state='open';
        }
        $last=null; $reaction=null; $commentAt=null;
        if(isset($messages[$id])){
            $last=0; $reaction=$controllers===null ? null : false;
            foreach($messages[$id] as $m){
                if(!empty($m['SERVICE_TYPE']) || $m['NEW_TOPIC']==='Y') continue;
                $aid=(int)$m['AUTHOR_ID']; $last=(int)$m['ID']; $commentAt=iso8($m['POST_DATE']);
                if(isset($controllers[$aid])) $reaction=true;

            }
        }
        $assigned=iso8($r['CREATED_DATE']); $changed=iso8($r['CHANGED_DATE']);
        $activity=isset($messages[$id]) && $h!==null ? max(array_filter([$assigned,$changed,$commentAt]) ?: [null]) : null;
        $rows[]=['id'=>$id,'title'=>$r['TITLE'],'document'=>$meta['document'],'event'=>$meta['event'],
          'state'=>$state,'stage'=>$stage,'status'=>$status,'due'=>iso8($r['DEADLINE']),'closed'=>iso8($r['CLOSED_DATE']),
          'assigned'=>$assigned,'responsible'=>$names[$resp] ?? ($resp ? 'ID '.$resp : null),'responsible_id'=>$resp,
          'accomplices'=>names8($acc,$names),'assistants'=>$assistants===null ? null : names8(array_intersect($aud,array_keys($assistants)),$names),
          'leader'=>$meta['leader'] ? ($names[$meta['leader']] ?? 'ID '.$meta['leader']) : null,
          'manager'=>$managers ? names8(array_unique($managers),$names) : null,'history'=>$h,'reaction'=>$reaction,'last_comment'=>$last];
        $observations[]= ['id'=>$id,'state'=>$state,'assigned'=>$assigned,'started'=>$h['started'] ?? null,
           'history_known'=>$h!==null && ($h['started'] || ($h['creation'] && $state==='open')),'activity'=>$activity,'last_comment'=>$last];
    }
    $ob=backend8($cfg,$uid,'/observe',['group'=>$group,'rows'=>$observations,'channel'=>$spec['comments_source'] ?? $cfg['comments_source'] ?? 'unknown']);
    foreach($rows as &$row) $row+=$ob['extra'][$row['id']];
    return ['rows'=>$rows,'history'=>$ob['history'],'checked'=>$ob['at']];
}
