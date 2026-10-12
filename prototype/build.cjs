const fs=require('node:fs');const path=require('node:path');
const dir=__dirname;
const fragment=fs.readFileSync(path.join(dir,'view.html'),'utf8')+'\n<script>\n'+fs.readFileSync(path.join(dir,'core.js'),'utf8')+'\n'+fs.readFileSync(path.join(dir,'ui.js'),'utf8')+'\n</script>\n';
fs.writeFileSync(path.join(dir,'g12-study.fragment.html'),fragment);
fs.writeFileSync(path.join(dir,'index.html'),'<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><link rel="icon" href="data:,"><meta name="description" content="Interactive G12 camera interface study with simulated manual exposure and adaptive rendering."><title>Digi · G12 Study</title><style>:root{color-scheme:light dark}body{margin:0;padding:20px;background:light-dark(#e7e9e5,#171a18)}@media(max-width:420px){body{padding:8px}}</style></head><body>'+fragment+'</body></html>');
console.log('Built G12 study fragment and browser preview.');
