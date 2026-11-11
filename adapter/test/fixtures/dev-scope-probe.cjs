const fs = require('node:fs');
const path = require('node:path');
const net = require('node:net');
const results = {};
for (const [name, target] of Object.entries({ product: 'dev-inside.txt', tests: '../tests/dev-inside.txt', git_root: '../dev-outside.txt', git_metadata: '../.git/dev-outside.txt', sibling: '../outside/dev-outside.txt' })) {
  try { fs.writeFileSync(path.resolve(target), 'scope probe'); results[name] = 'write-allowed'; }
  catch (error) { results[name] = error.code; }
}
const socket = net.createConnection({ host: '127.0.0.1', port: Number(process.argv[2]) });
socket.setTimeout(3000);
socket.on('connect', () => { results.raw_loopback_network = 'connected'; socket.destroy(); });
socket.on('timeout', () => { results.raw_loopback_network = 'timeout'; socket.destroy(); });
socket.on('error', error => { results.raw_loopback_network = error.code; });
socket.on('close', () => console.log(JSON.stringify(results)));
