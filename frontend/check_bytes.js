const fs = require('fs');
const content = fs.readFileSync('app/dashboard/page.tsx', 'utf8');
const lines = content.split('\n');
for(let i = 1440; i <= 1450; i++) {
    const line = lines[i-1];
    const bytes = Buffer.from(line, 'utf8');
    console.log(i + ': [' + Array.from(bytes).join(' ') + '] ' + JSON.stringify(line));
}