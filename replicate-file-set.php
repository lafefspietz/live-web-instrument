<?php
$fileseturl = "https://raw.githubusercontent.com/lafefspietz/live-web-instrument/refs/heads/main/file-set.json";

if(isset($_GET["fileseturl"])){
    $fileseturl = $_GET["fileseturl"];
}

$baseurl = explode("file-set.json",$fileseturl)[0];

$json_raw = file_get_contents($fileseturl);
$file_set = json_decode($json_raw);

mkdir("data");
mkdir("plots");

foreach($file_set as $value){
    copy($baseurl.$value,$value);
}

?>
<a href = "index.html">index.html</a>
<style>
body{
    font-size:3em;
}
a{
    font-size:3em;
}
</style>
