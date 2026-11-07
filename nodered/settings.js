// Node-RED settings for the Smart Classroom server (Laptop 1).
// Start from this folder with:  npm start   (editor http://localhost:1880, dashboard http://localhost:1880/dashboard)
// Configuration comes from ../.env (see ../.env.example); real environment variables win over the file.
const fs = require('fs');
const path = require('path');

const envFile = path.join(__dirname, '..', '.env');
if (fs.existsSync(envFile)) {
    for (const line of fs.readFileSync(envFile, 'utf8').split(/\r?\n/)) {
        const m = line.match(/^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*?)\s*$/);
        if (m && !line.trim().startsWith('#') && process.env[m[1]] === undefined) process.env[m[1]] = m[2].replace(/^['"]|['"]$/g, '');
    }
}
// Defaults used by flows.json (${...} placeholders). Node-RED always talks to the broker on its own machine.
process.env.SC_NODERED_MQTT_HOST = process.env.SC_NODERED_MQTT_HOST || '127.0.0.1';
process.env.SC_MQTT_PORT = process.env.SC_MQTT_PORT || '1883';
process.env.SC_DB_PATH = process.env.SC_DB_PATH || path.join(__dirname, '..', 'storage', 'smartclass.db');
process.env.SC_SERVER_USERNAME = process.env.SC_SERVER_USERNAME || '';
process.env.SC_SERVER_PASSWORD = process.env.SC_SERVER_PASSWORD || '';
fs.mkdirSync(path.dirname(process.env.SC_DB_PATH), { recursive: true });
// Broker credentials: written to flows_cred.json from .env at every start (git-ignored, never committed).
// 'sc_broker' is the id of the mqtt-broker config node in flows.json.
fs.writeFileSync(path.join(__dirname, 'flows_cred.json'), JSON.stringify({
    sc_broker: { user: process.env.SC_SERVER_USERNAME, password: process.env.SC_SERVER_PASSWORD },
}, null, 2));

// ---- Editor security ----
// With SC_EDITOR_PASSWORD set (tools/init_env.py generates it) the flow editor and admin API require a login.
// Without a real password the editor/admin API answer ONLY requests from this computer (127.0.0.1 / ::1).
// The dashboard (/dashboard) stays readable on the LAN so Laptop 2 or a projector PC can view it.
const editorUser = process.env.SC_EDITOR_USERNAME || 'admin';
const editorPassword = process.env.SC_EDITOR_PASSWORD || '';
const editorPasswordSet = editorPassword.length >= 8 && !/^change-me/.test(editorPassword);
const adminAuth = editorPasswordSet ? {
    type: 'credentials',
    users: [{ username: editorUser, password: require('bcryptjs').hashSync(editorPassword, 10), permissions: '*' }],
} : undefined;
const loopbackOnly = (req, res, next) => {
    const ip = (req.socket && req.socket.remoteAddress) || '';
    if (ip === '127.0.0.1' || ip === '::1' || ip === '::ffff:127.0.0.1') return next();
    res.status(403).send('Node-RED editor: set SC_EDITOR_PASSWORD (python tools/init_env.py --role server) to allow LAN access.');
};
if (!editorPasswordSet) console.log('[smartclass] SC_EDITOR_PASSWORD not set: editor restricted to localhost');

module.exports = {
    adminAuth,
    httpAdminMiddleware: editorPasswordSet ? undefined : loopbackOnly,
    flowFile: 'flows.json',
    flowFilePretty: true,
    credentialSecret: false,          // broker credentials are ${...} placeholders, never stored in the repo
    uiPort: Number(process.env.SC_NODERED_PORT || 1880),
    uiHost: process.env.SC_NODERED_BIND || '0.0.0.0',
    diagnostics: { enabled: false },
    telemetry: { enabled: false },
    runtimeState: { enabled: false },
    logging: { console: { level: 'info', metrics: false, audit: false } },
    contextStorage: { default: { module: 'memory' } },
    editorTheme: { projects: { enabled: false }, tours: false },
    functionExternalModules: false,
};
