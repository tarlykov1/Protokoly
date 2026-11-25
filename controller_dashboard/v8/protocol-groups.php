<?php
// CLI on the portal host. Only the list of extra protocol group IDs is writable.
if (PHP_SAPI!=='cli') {http_response_code(404); exit;}
require __DIR__.'/portal/common.php';
try {
    $base=getenv('CONTROLLER_CONFIG_DIR') ?: '/etc/controller-v8';
    $root=getenv('BITRIX_ROOT') ?: '/home/bitrix/www';
    $current=require $base.'/portal.php';
    $legacy=$root.'/controller-dashboard/config.php';
    $old=is_readable($legacy) ? require $legacy : [];
    $path=$base.'/protocol-groups.json';
    if (($argv[1] ?? '')==='--add') {
        $raw=array_slice($argv,2);
        if (!$raw) throw new RuntimeException('После --add укажите ID групп через пробел');
        foreach ($raw as $value) if (!preg_match('/^[1-9][0-9]*$/D',$value) || !filter_var($value,FILTER_VALIDATE_INT,['options'=>['min_range'=>1]]))
            throw new RuntimeException('ID группы должен быть положительным целым числом');
        $lock=fopen($path.'.lock','c');
        if (!$lock || !flock($lock,LOCK_EX)) throw new RuntimeException('Не удалось заблокировать список');
        $saved=extraProtocols8($path);
        foreach ($raw as $id) {
            if (isset($current['groups'][$id]) && $current['groups'][$id]['source']!=='protocol') throw new RuntimeException('ID уже назначен другому типу документа');
            $saved[]=(int)$id;
        }
        $saved=array_values(array_unique($saved)); sort($saved,SORT_NUMERIC);
        $tmp=tempnam($base,'.protocol-groups-');
        try {
            $json=json_encode($saved,JSON_THROW_ON_ERROR)."\n";
            if(file_put_contents($tmp,$json)!==strlen($json) || !chmod($tmp,0644) || !rename($tmp,$path))
                throw new RuntimeException('Не удалось сохранить список');
        } finally { if(is_file($tmp)) unlink($tmp); }
    } elseif (($argv[1] ?? '--list')!=='--list') throw new RuntimeException('Допустимые команды: --list, --add ID ...');
    $fromLegacy=protocolGroups8([],$old);
    $union=protocolGroups8(protocolGroups8($current['groups'],$old),['protocol_group_ids'=>extraProtocols8($path)]);
    $ids=array_keys(array_filter($union,static function($g){return $g['source']==='protocol';}));
    echo 'Прежний кабинет: '.count($fromLegacy).' групп. Подключено протокольных групп: '.count($ids)."\n";
    echo 'ID: '.implode(', ',$ids)."\n";
} catch(Throwable $e){fwrite(STDERR,$e->getMessage()."\n");exit(1);}
