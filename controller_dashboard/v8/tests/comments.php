<?php
namespace Bitrix\Main {
    class Loader {
        public static function includeModule($name) { return true; }
    }
}
namespace Fixture {
    class Rows {
        private $rows;
        public function __construct($rows) { $this->rows=$rows; }
        public function fetch() { return array_shift($this->rows); }
    }
}
namespace Bitrix\Forum {
    class TopicTable {
        public static function getList($q) {
            $topics=[];
            foreach([1=>11,2=>12,3=>13,5=>15] as $task=>$id) {
                $xml='TASK_'.$task;
                if(in_array($xml,$q['filter']['@XML_ID'],true)) $topics[]=['ID'=>$id,'XML_ID'=>$xml];
            }
            return new \Fixture\Rows($topics);
        }
    }
    class MessageTable {
        public static function getList($q) {
            if($q['filter']['=APPROVED']!=='Y') throw new \LogicException('No moderation filter');
            $rows=[];
            if(in_array(11,$q['filter']['@TOPIC_ID'],true)) {
                $r=['ID'=>100,'TOPIC_ID'=>11,'AUTHOR_ID'=>42,'POST_DATE'=>'2026-11-25','SERVICE_TYPE'=>0,'NEW_TOPIC'=>'N'];
                if(in_array('POST_MESSAGE',$q['select'],true)) $r['POST_MESSAGE']='Текст комментария';
                $rows[]=$r;
            }
            return new \Fixture\Rows($rows);
        }
    }
}
namespace Bitrix\Im\Model {
    class ChatTable {
        public static function getList($q) {
            if($q['filter']['=ENTITY_TYPE']!=='TASKS_TASK') throw new \LogicException('No task link');
            $rows=[];
            foreach([3,4,6] as $id) if(in_array($id,$q['filter']['@ENTITY_ID'],true)) $rows[]=['ID'=>100+$id,'ENTITY_ID'=>$id];
            return new \Fixture\Rows($rows);
        }
    }
}
namespace Bitrix\Im {
    class Dialog {
        public static function hasAccess($dialog) {return $dialog==='chat104';}
    }
    class Chat {
        public static function getMessages($chat,$user,$options) {
            if($chat!==104) throw new \LogicException('Unexpected chat read');
            return ['messages'=>[['id'=>400,'author_id'=>56,'date'=>'2026-11-25','text'=>'Ответ']]];
        }
    }
}
namespace {
    require __DIR__.'/../portal/data.php';
    $tasks=[1=>['FORUM_TOPIC_ID'=>11],2=>['FORUM_TOPIC_ID'=>12],3=>['FORUM_TOPIC_ID'=>13],
        4=>[],5=>['FORUM_TOPIC_ID'=>999],6=>[],7=>[]];
    $channels=[]; $reasons=[];
    $m=messages8($tasks,null,true,$channels,$reasons);
    if($channels!=[1=>'forum',2=>'forum',4=>'chat'] || $reasons!=[3=>'ambiguous',5=>'ambiguous']) exit(1);
    if(!humanComment8($m[1][0]) || $m[1][0]['POST_MESSAGE']!=='Текст комментария' || $m[2]!==[]) exit(1);
    if($m[4][400]['POST_MESSAGE']!=='Ответ' || isset($m[3]) || isset($m[5]) || isset($m[6]) || isset($m[7])) exit(1);
    if(array_key_exists('POST_MESSAGE',messages8($tasks,'auto')[1][0])) exit(1);
    if(!isset(messages8($tasks,'forum')[3]) || isset(messages8($tasks,'forum')[4])) exit(1);
    if(humanComment8(['AUTHOR_ID'=>0,'NEW_TOPIC'=>'N']) || humanComment8(['AUTHOR_ID'=>42,'NEW_TOPIC'=>'Y']) ||
       humanComment8(['AUTHOR_ID'=>42,'NEW_TOPIC'=>'N','SERVICE_TYPE'=>1])) exit(1);
    echo "OK\n";
}
