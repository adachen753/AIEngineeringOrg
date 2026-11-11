const fs = require('node:fs');
const path = require('node:path');
const results = {};
for (const [name, target] of Object.entries({ inside: 'inside.txt', product: '../product/outside.txt', git_root: '../outside.txt', parent: '../../outside.txt' })) {
  try { fs.writeFileSync(path.resolve(target), 'scope probe'); results[name] = 'write-allowed'; }
  catch (error) { results[name] = error.code; }
}
try { results.product_read = fs.readFileSync('../product/source.txt', 'utf8').trim(); }
catch (error) { results.product_read = error.code; }
console.log(JSON.stringify(results));
