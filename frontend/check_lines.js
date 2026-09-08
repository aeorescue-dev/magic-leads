const fs = require('fs');
const content = fs.readFileSync('app/dashboard/page.tsx', 'utf8');
const lines = content.split('\n');
for(let i = 1405; i <= 1415; i++) {
    console.log(i + ': [' + JSON.stringify(lines[i-1]) + ']');
}