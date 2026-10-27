// Real-server acceptance tests in an isolated, disposable database.
const {chromium}=require('playwright');
const {spawn,spawnSync}=require('node:child_process');
const fs=require('node:fs');
const path=require('node:path');
const os=require('node:os');
const root=path.resolve(__dirname,'../..');
const python=process.env.PYTHON_EXECUTABLE || path.join(root,'.venv',process.platform==='win32'?'Scripts/python.exe':'bin/python');
const work=fs.mkdtempSync(path.join(os.tmpdir(),'mini-dbms-leaflet-'));
const port=Number(process.env.TEST_PORT || 18821);
let server,browser;
(async()=>{
 const prepared=spawnSync(python,['scripts/setup_lima.py','--data-dir',path.join(work,'database')],{cwd:root,encoding:'utf8'});
 if(prepared.status!==0)throw new Error(prepared.error?.message || prepared.stderr || prepared.stdout);
 server=spawn(python,['-m','api','--spatial','--allow-writes','--data-dir',path.join(work,'database'),'--port',String(port)],{cwd:root,stdio:'ignore'});
 const url=`http://127.0.0.1:${port}`;
 let ready=false;
 for(let i=0;i<100;i++){
  try{ready=(await fetch(url+'/api/health')).ok;}catch{}
  if(ready)break;
  await new Promise(resolve=>setTimeout(resolve,100));
 }
 if(!ready)throw new Error('The test server did not start');
 browser=await chromium.launch({headless:true,executablePath:process.env.BROWSER_EXECUTABLE_PATH || undefined});
 const page=await browser.newPage({viewport:{width:1500,height:1000}});
 await page.goto(url);
 await page.getByLabel('Tabla espacial',{exact:true}).selectOption('lugares_lima');
 await page.waitForFunction(()=>document.querySelectorAll('[data-point-id]').length===20);
 await page.getByRole('button',{name:'Ver puntos',exact:true}).click();
 // Street availability depends on the external provider. Query/mutation checks
 // use the real backend and do not mock API responses or records.
 const checks=await require('./leaflet-actions.cjs')(page,path.join(work,'browser-results.json'));
 console.log(`${checks.length} browser checks passed. Report: ${path.join(work,'browser-results.json')}`);
})().catch(error=>{console.error(error.message);process.exitCode=1;}).finally(async()=>{
 if(browser)await browser.close();
 if(server){server.kill('SIGINT');await new Promise(resolve=>{server.once('exit',resolve);setTimeout(resolve,3000);});}
});
