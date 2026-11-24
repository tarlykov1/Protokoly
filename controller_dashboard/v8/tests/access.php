<?php
namespace Bitrix\Socialnetwork {
    class UserToGroupTable {
        public static function getList($q) {
            $f=$q['filter'];
            if($f['=USER_ID']!==17 || $f['@ROLE']!==['A','E','K'] || $f['@GROUP_ID']!==[1,2]) throw new \RuntimeException();
            return new class {private $rows=[['GROUP_ID'=>2]];function fetch(){return array_pop($this->rows);}};
        }
    }
}
namespace {
    require __DIR__.'/../portal/common.php';
    $user=new class {
        function GetID(){return 17;}
        function IsAdmin(){return ($GLOBALS['argv'][1] ?? '')==='admin';}
    };
    $groups=[1=>'МЕМО',2=>'Протокол'];
    $allowed=access8($user,$groups,$argv[1]==='other' ? [] : [17=>true]);
    if($argv[1]==='member' && array_keys($allowed)!==[2]) exit(1);
    if($argv[1]==='admin' && $allowed!==$groups) exit(1);
    if($argv[1]==='other') exit(1);
    echo "OK";
}
