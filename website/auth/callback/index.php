<?php
/**
 * Chatty OAuth Callback Proxy
 *
 * Universal callback proxy for all OAuth providers (Google, Intuit/QuickBooks,
 * OpenAI). Receives the provider's callback and redirects the auth code to the
 * originating Chatty instance. The instance's callback URL is encoded in the
 * state parameter as: {flow_id}:{base64url(callback_url)}
 */

$ALLOWED_DOMAIN_PATTERNS = [
    '/^[a-z0-9-]+\.up\.railway\.app$/',
    '/^localhost$/',
    '/^127\.0\.0\.1$/',
];

// ── Read query parameters ───────────────────────────────────────────

$code  = $_GET['code']  ?? '';
$state = $_GET['state'] ?? '';
$error = $_GET['error'] ?? '';

if ($error) {
    $desc = htmlspecialchars($_GET['error_description'] ?? $error, ENT_QUOTES, 'UTF-8');
    http_response_code(400);
    die("<!doctype html><html><head><meta charset='utf-8'><title>Connection failed</title>
    <style>body{font-family:system-ui;background:#0f172a;color:#f1f5f9;display:flex;align-items:center;justify-content:center;height:100vh;margin:0}
    .c{text-align:center;max-width:420px}h1{color:#ef4444;margin:0 0 .75rem}p{color:#cbd5e1}</style></head>
    <body><div class='c'><h1>Connection failed</h1><p>$desc</p><p>Close this window and try again.</p></div></body></html>");
}

if (!$code || !$state) {
    http_response_code(400);
    die('Missing code or state parameter.');
}

// ── Decode state ────────────────────────────────────────────────────

$colon = strpos($state, ':');
if ($colon === false || $colon === 0) {
    http_response_code(400);
    die('Malformed state parameter.');
}

$flow_id     = substr($state, 0, $colon);
$encoded_url = substr($state, $colon + 1);

if (!$flow_id || !$encoded_url) {
    http_response_code(400);
    die('Malformed state parameter.');
}

// base64url decode (RFC 4648 section 5)
$callback_url = base64_decode(strtr($encoded_url, '-_', '+/'));
if (!$callback_url) {
    http_response_code(400);
    die('Invalid encoded callback URL.');
}

// ── Validate the callback URL ───────────────────────────────────────

$parsed = parse_url($callback_url);
if (!$parsed || empty($parsed['host']) || empty($parsed['scheme']) || empty($parsed['path'])) {
    http_response_code(400);
    die('Invalid callback URL.');
}

$host   = strtolower($parsed['host']);
$scheme = strtolower($parsed['scheme']);
$path   = $parsed['path'];

// Scheme check: https required, except localhost
$is_local = ($host === 'localhost' || $host === '127.0.0.1');
if ($scheme !== 'https' && !($is_local && $scheme === 'http')) {
    http_response_code(400);
    die('Callback URL must use HTTPS.');
}

// Path check
if (!str_ends_with($path, '/api/oauth/callback')) {
    http_response_code(400);
    die('Invalid callback path.');
}

// Domain allowlist check
$domain_ok = false;
foreach ($ALLOWED_DOMAIN_PATTERNS as $pattern) {
    if (preg_match($pattern, $host)) {
        $domain_ok = true;
        break;
    }
}
if (!$domain_ok) {
    http_response_code(403);
    die('Callback domain not allowed.');
}

// ── Build redirect ──────────────────────────────────────────────────

$params = ['code' => $code, 'state' => $flow_id];

// Forward extra params (scope, realmId, etc.)
foreach ($_GET as $key => $val) {
    if (!in_array($key, ['code', 'state', 'error', 'error_description'])) {
        $params[$key] = $val;
    }
}

$redirect = $callback_url . '?' . http_build_query($params);

header('Cache-Control: no-store');
header('Location: ' . $redirect, true, 302);
exit;
