<?php
$json_string = file_get_contents('php://input');

// 1. Establish the network connection path on Port 8000
$socket = @fsockopen("127.0.0.1", 8000, $errno, $errstr, 5.0);

if (!$socket) {
    http_response_code(503);
    echo "ERROR: Python server is offline on Port 8000.";
    exit;
}

// 2. Set transmission stream timeout ceilings
stream_set_timeout($socket, 5, 0); 
fwrite($socket, $json_string . "\n");

// 3. Read data continuously in blocks until the transmission completes
$response_payload = "";
while (!feof($socket)) {
    $chunk = fgets($socket, 8192); // Read chunks securely up to 8KB at a time
    if ($chunk === false) {
        break; 
    }
    $response_payload .= $chunk;
}
fclose($socket);

// 4. Verify that data actually moved through the pipeline
if (empty(trim($response_payload))) {
    http_response_code(504);
    echo "ERROR: Received an empty payload string from the backend server.";
    exit;
}

// 5. Success route: return the unbroken text back to the JavaScript image tag
echo $response_payload;
?>
