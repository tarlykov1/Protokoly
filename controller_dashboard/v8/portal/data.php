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
function history8($logs,$responsible,$delegates=[],$names=[]) {
    $creation=false; $started=null; $submitted=false; $dates=[]; $changes=[]; $moves=0;
    foreach($logs as $l) {
        $field=$l['FIELD']; $old=(string)$l['FROM_VALUE']; $new=(string)$l['TO_VALUE'];
        $at=iso8($l['CREATED_DATE']);
        if(in_array($field,['NEW','CREATED_DATE'],true)) $creation=true;
        if($field==='STATUS') {
            if(in_array($new,['1','2','3','6','7'],true)) $submitted=false;
            $actor=(int)$l['USER_ID'];
            if($actor>0 && ($actor===$responsible || isset($delegates[$actor]))) {
                if($actor===$responsible && $new==='3' && !$started) $started=$at;
                if(in_array($new,['4','5'],true)) $submitted=true;
            }
        }
        if($field==='DEADLINE') {
            $dates[]=['at'=>$at,'from'=>$old,'to'=>$new];
            if ($old!=='' && $new!=='' && $old!==$new) $moves++;
        }
        if(!in_array($field,['COMMENT','NEW'],true)) {
            $author=(int)$l['USER_ID'];
            $change=['at'=>$at,'field'=>$field,'author'=>$names[$author] ?? ($author ? 'ID '.$author : null)];
            if($field==='STATUS') $change+=['from'=>$old,'to'=>$new];
            $changes[]=$change;
        }
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
// Resolve only containers linked to tasks that passed tasks8() for this user.
function messages8($tasks,$mode,$detail=false,&$channels=[],&$reasons=[]) {
    $out=[]; $channels=[]; $reasons=[];
    $mode=$mode ?? 'auto';
    if(!in_array($mode,['auto','forum','chat'],true) || !$tasks) return [];
    $chats=[]; $topics=[]; $ids=array_keys($tasks);
    try {
        if($mode!=='forum' && \Bitrix\Main\Loader::includeModule('im')) {
            $chats=related8(\Bitrix\Im\Model\ChatTable::class,'ENTITY_ID',$ids,
                ['ID','ENTITY_ID'],['=ENTITY_TYPE'=>'TASKS_TASK']);
        }
        if($mode!=='chat' && \Bitrix\Main\Loader::includeModule('forum')) {
            foreach(array_chunk($ids,200) as $chunk) {
                $keys=[];
                foreach($chunk as $task) $keys['TASK_'.$task]=$task;
                $rs=\Bitrix\Forum\TopicTable::getList(['select'=>['ID','XML_ID'],
                    'filter'=>['@XML_ID'=>array_keys($keys)]]);
                while($r=$rs->fetch()) if(isset($keys[$r['XML_ID']]))
                    $topics[$keys[$r['XML_ID']]][]=(int)$r['ID'];
            }
        }
    } catch(Throwable $e) { return []; }
    $forum=[];
    foreach($tasks as $id=>$task) {
        $f=$topics[$id] ?? []; $c=$chats[$id] ?? [];
        $linked=(int)($task['FORUM_TOPIC_ID'] ?? 0);
        if(count($f)>1 || count($c)>1 || ($mode!=='chat' && $linked && $f!==[$linked]) || ($f && $c)) {
            $reasons[$id]='ambiguous'; continue;
        }
        if($f) {
            $forum[$id]=$f[0];
        } elseif($c) {
            try { $items=chatMessages8((int)$c[0]['ID'],$detail); }
            catch(Throwable $e) { $items=null; }
            if(is_array($items)) { $out[$id]=$items; $channels[$id]='chat'; }
        }
    }
    if(!$forum) return $out;
    $fields=['TOPIC_ID','ID','AUTHOR_ID','POST_DATE','SERVICE_TYPE','NEW_TOPIC'];
    if($detail) $fields[]='POST_MESSAGE';
    try {
        $byTopic=related8(MessageTable::class,'TOPIC_ID',$forum,$fields,
            ['=APPROVED'=>'Y'],['ID'=>'ASC']);
        foreach($forum as $id=>$topic) {
            $out[$id]=$byTopic[$topic] ?? [];
            $channels[$id]='forum';
        }
    } catch(Throwable $e) { /* Keep independently verified chat results. */ }
    return $out;
}
function humanComment8($row) {
    return (int)($row['AUTHOR_ID'] ?? 0)>0 && empty($row['SERVICE_TYPE']) && ($row['NEW_TOPIC'] ?? '')==='N';
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
    $channels=[]; $reasons=[];
    $messages=messages8($tasks,$spec['comments_source'] ?? $cfg['comments_source'] ?? null,false,$channels,$reasons);
    $knownChannels=array_unique(array_values($channels));
    $observeChannel=count($knownChannels)===1 ? reset($knownChannels) : 'unknown';
    $users=array_column($tasks,'RESPONSIBLE_ID');
    foreach($members as $list) foreach($list as $m) $users[]=$m['USER_ID'];
    foreach($logs as $events) foreach($events ?? [] as $event) $users[]=(int)$event['USER_ID'];
    foreach($seed as $r) if(ctype_digit((string)$r['leader'])) $users[]=$r['leader'];
    [$names,$departments]=employees8($users);
    $heads=[]; $org=(int)COption::GetOptionString('intranet','iblock_structure','0');
    $deptIds=[]; foreach($departments as $list) foreach($list as $d) $deptIds[]=$d;
    if($org && $deptIds) {
        $rs=CIBlockSection::GetList([],['IBLOCK_ID'=>$org,'ID'=>array_unique($deptIds)],false,['ID','UF_HEAD']);
        while($r=$rs->Fetch()) if(!empty($r['UF_HEAD'])) $heads[$r['ID']]=(int)$r['UF_HEAD'];
        $names+=employees8(array_values($heads))[0];
    }
    try { $assistants=assistantPairs8($cfg); } catch(Throwable $e) { $assistants=null; }
    $rows=[]; $observations=[];
    $stages=related8(StagesTable::class,'ID',array_filter(array_column($tasks,'STAGE_ID')),['ID','TITLE']);
    foreach($tasks as $id=>$r){
        $meta=$seed[$id]; $resp=(int)$r['RESPONSIBLE_ID']; $acc=[]; $aud=[];
        foreach($members[$id] ?? [] as $m) {
            if($m['TYPE']==='A') $acc[]=(int)$m['USER_ID'];
            if($m['TYPE']==='U') $aud[]=(int)$m['USER_ID'];
        }
        $managers=[]; foreach($departments[$resp] ?? [] as $d) if(isset($heads[$d]) && $heads[$d]!==$resp) $managers[]=$heads[$d];
        $h=array_key_exists($id,$logs) && $logs[$id]===null ? null : history8($logs[$id] ?? [],$resp,$assistants[$resp] ?? [],$names);
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
                if(!humanComment8($m)) continue;
                $aid=(int)$m['AUTHOR_ID']; $last=(int)$m['ID']; $commentAt=iso8($m['POST_DATE']);
                if(isset($controllers[$aid])) $reaction=true;

            }
        }
        $assigned=iso8($r['CREATED_DATE']); $changed=iso8($r['CHANGED_DATE']);
        $activity=isset($messages[$id]) && $h!==null ? max(array_filter([$assigned,$changed,$commentAt]) ?: [null]) : null;
        $rows[]=['id'=>$id,'title'=>$r['TITLE'],'document'=>$meta['document'],'event'=>$meta['event'],
          'state'=>$state,'stage'=>$stage,'status'=>$status,'due'=>iso8($r['DEADLINE']),'closed'=>iso8($r['CLOSED_DATE']),
          'assigned'=>$assigned,'responsible'=>$names[$resp] ?? ($resp ? 'ID '.$resp : null),'responsible_id'=>$resp,
          'observed_by_controller'=>$controllers===null ? null : (bool)array_intersect($aud,array_keys($controllers)),
          'accomplices'=>names8($acc,$names),'assistants'=>$assistants===null ? null : names8(array_intersect(array_unique(array_merge($acc,$aud)),array_keys($assistants[$resp] ?? [])),$names),
          'leader'=>$meta['leader'] ? ($names[$meta['leader']] ?? 'ID '.$meta['leader']) : null,
          'manager'=>$managers ? names8(array_unique($managers),$names) : null,'history'=>$h,'reaction'=>$reaction,'last_comment'=>$last,
          'comments_source'=>$channels[$id] ?? null,'comments_status'=>$reasons[$id] ?? (isset($channels[$id]) ? 'ready' : 'unavailable')];
        $observations[]= ['id'=>$id,'state'=>$state,'assigned'=>$assigned,'started'=>$h['started'] ?? null,
           'history_known'=>$h!==null && ($h['started'] || ($h['creation'] && $state==='open')),'activity'=>$activity,'last_comment'=>($channels[$id] ?? null)===$observeChannel ? $last : null];
    }
    $ob=backend8($cfg,$uid,'/observe',['group'=>$group,'rows'=>$observations,'channel'=>$observeChannel]);
    foreach($rows as &$row) $row+=$ob['extra'][$row['id']];
    return ['rows'=>$rows,'history'=>$ob['history'],'checked'=>$ob['at']];
}
