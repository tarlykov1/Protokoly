<?php
require __DIR__.'/../portal/data.php';
function iso8($s){return $s;}
function event8($user,$field,$to,$from=''){return ['USER_ID'=>$user,'FIELD'=>$field,'TO_VALUE'=>$to,'FROM_VALUE'=>$from,'CREATED_DATE'=>'2026-10-26'];}
$logs=[event8(22,'STATUS','3'),event8(22,'STATUS','5'),event8(10,'DEADLINE','02.12','01.12')];
if(history8($logs,10)['submitted'] || history8($logs,10)['started']!==null) exit(1);
$logs[]=event8(10,'STATUS','3');$logs[]=event8(10,'STATUS','4');$logs[]=event8(22,'STATUS','5');
$h=history8($logs,10);
if(!$h['submitted'] || !$h['started'] || $h['moves']!==1 || count($h['dates'])!==1)exit(1);
$logs[]=event8(22,'STATUS','2');if(history8($logs,10)['submitted'])exit(1);

// Submission by a listed delegate survives acceptance by another account.
$logs=[event8(22,'STATUS','4','3'),event8(30,'STATUS','5','4')];
if(!history8($logs,10,[22=>true,23=>true])['submitted']) exit(1);
if(history8($logs,10,[23=>true])['submitted']) exit(1);
$logs[]=event8(30,'STATUS','3','5');
if(history8($logs,10,[22=>true])['submitted']) exit(1);

$submit=event8(31,'STATUS','4','3'); $close=event8(31,'STATUS','5','4');
$roster=[31=>true]; $names=[31=>'Контролёр'];
$h=history8([$submit,$close],10,[],$names,$roster);
if($h['submitted'] || $h['controllerClosure']['author']!=='Контролёр' || $h['controllerClosure']['accepted_submission']) exit(1);
if(history8([$submit],10,[],$names,$roster)['controllerClosure']!==null) exit(1);
if(history8([$close],10,[],$names,[])['controllerClosure']!==null) exit(1);
if(history8([$close,event8(31,'STATUS','3','5')],10,[],$names,$roster)['controllerClosure']!==null) exit(1);
if(!history8([event8(22,'STATUS','4','3'),$close],10,[22=>true],$names,$roster)['controllerClosure']['accepted_submission']) exit(1);
