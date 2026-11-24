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
