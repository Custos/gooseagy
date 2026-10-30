// Exercise the distributed plugin with fake app handles; never contact a relay.
import assert from "node:assert/strict";
import { readFile, readdir, mkdtemp, rm } from "node:fs/promises";
import { tmpdir, homedir } from "node:os";
import { resolve, join } from "node:path";
import { spawn } from "node:child_process";
import { createServer } from "node:http";
import { randomBytes } from "node:crypto";
import { pathToFileURL } from "node:url";
const root = resolve(import.meta.dirname, "..");
const temp = await mkdtemp(join(tmpdir(), "buzz-plugin-contract-"));
const live = process.argv.includes("--live");
const data = new Map();
globalThis.localStorage = { getItem: k => data.get(k) ?? null, setItem: (k,v) => data.set(k,v) };
const plugin = await import(pathToFileURL(join(root,"buzz-plugin/dist/plugin.js")).href);
let type, clean, working;
const calls = [], published = [], servers = [], children = [];
const owner = "a".repeat(64), key = "c".repeat(64), channel = "contract-channel";
const event = { id: "1".repeat(64), pubkey: owner, sig: "", kind: 9, created_at: 1,
  tags: [["h",channel],["p",key]], content: live
    ? "Use Buzz's send tool to reply in this conversation with exactly PLUGIN_MCP_READY. Do not use other tools."
    : "Reply with a brief greeting." };
const events = [event];
const memories = {snapshot:()=>({status:"ready",listing:{entries:[]}}),subscribe:()=>()=>{},refresh:async()=>{},dispose:()=>{}};
const session = {read:async()=>events,agentMemories:{open:()=>memories},
 channels:{list:()=>({status:"ready",channels:[{id:channel,name:"contract",channelType:"stream",members:[]}]})},
 names:{resolve:()=>"Owner"},profiles:{ensure:async()=>{},snapshot:()=>new Map()},
 channelWrites:{startingCanvas:()=>undefined},canvas:{available:false,read:async()=>null}};
const relay = {snapshot:()=>({status:"ready",session,viewer:owner,scope:"https://local.test:"+owner})};
const host = {
 resolveDirectory: async p => p === "~" ? homedir() : temp,
 readFile: async()=>new Uint8Array(),
 serveMcp: async(handler,options)=>{
   assert.equal(options.sharedSession,true);
   const token=randomBytes(16).toString("hex");
   let closeResolve;const closed=new Promise(r=>closeResolve=r);
   const server=createServer((req,res)=>{
     if(req.headers.authorization!=="Bearer "+token){res.writeHead(404);res.end();return;}
     if(req.method!=="POST"){res.writeHead(405);res.end();return;}
     let body="";req.on("data",d=>body+=d);req.on("end",async()=>{
       const input=JSON.parse(body);calls.push(input.method+":"+(input.params?.name??""));
       if(input.id===undefined){res.writeHead(202);res.end();return;}
       try {const answer=await handler(input);res.writeHead(200,{"Content-Type":"application/json"});res.end(JSON.stringify(answer));}
       catch(e){res.writeHead(500);res.end(JSON.stringify({error:String(e)}));}
     });
   });
   await new Promise(r=>server.listen(0,"127.0.0.1",r));servers.push(server);
   return {url:`http://127.0.0.1:${server.address().port}/mcp`,headers:[{name:"Authorization",value:"Bearer "+token}],
    close:async()=>{server.close();closeResolve();},closed};
 },
 spawn: async(id,opts)=>{
   assert.equal(id,"agent");
   const env={...process.env,GOOSE_AGY_STATE_DIR:join(temp,"state")};
   delete env.GOOSE_AGY_ALLOW_ALL;
   for(const [k,v] of Object.entries(opts.env??{}))if(v===null)delete env[k];else env[k]=v;
   if(!live)env.GOOSE_AGY_COMMAND=join(root,"tests/fake_agy.py");
   const worker=process.env.GOOSE_AGY_TEST_WORKER;
   const child=spawn(worker || process.env.PYTHON || "python3",worker ? [] : [join(root,"acp_server.py")],
     {cwd:opts.cwd,env,stdio:["pipe","pipe","pipe"]});children.push(child);
   child.stdout.setEncoding("utf8").on("data",opts.onStdout);
   child.stderr.setEncoding("utf8").on("data",d=>opts.onStderr?.(d));
   return {write:d=>new Promise((r,j)=>child.stdin.write(d,e=>e?j(e):r())),end:async d=>child.stdin.end(d),
    kill:async()=>{child.kill();},exited:new Promise(r=>child.on("exit",r))};
 }
};
const agents={snapshot:()=>({status:"ready",running:[]}),subscribe:()=>()=>{},relay:()=>relay,
 core:async()=>null,tools:()=>[],register:t=>{type=t;}};
async function checkpoint(){
 for(let i=0;i<1800;i++){
   const files=await readdir(join(temp,"state/sessions"));
   const records=await Promise.all(files.filter(f=>f.endsWith(".json")).map(f=>readFile(join(temp,"state/sessions",f),"utf8").then(JSON.parse)));
   if(records.length && records.every(s=>!s.broken))return records;
   if(i===1799)throw new Error("Backend did not finish its checkpoint");
   await new Promise(r=>setTimeout(r,100));
 }
}
try{
 plugin.apply({agents,host,react:{},pluginOwner:{id:"local.gooseagy"},effect:f=>{clean=f();}});
 assert.equal(type.title,"Antigravity (Ultra)");
 await assert.rejects(type.sessionControls.run({}, {}, "compact"), /Use New session/);
 const agent={key,pubkey:key,name:"Ultra",owner,
  publish:async e=>{published.push(e);return {...event,...e,id:"2".repeat(64)};},
  query:async()=>events,remember:async()=>{}};
 await type.run({trigger:{type:"mention",event},channelId:channel,agent,config:type.defaults().config,
  signal:new AbortController().signal,current:()=>true,workingUntil:p=>{working=p;}});
 const result=await working;
 assert.equal(result.ok,true,JSON.stringify(result));
 if(live){assert.equal(published.length,1,JSON.stringify(published));assert.equal(published[0].content,"PLUGIN_MCP_READY");assert.ok(calls.some(s=>s.includes("send")),calls.join(","));}
 else { assert.equal(published.length,0); assert.ok(result.text.includes("héllo")); }
 // A final Buzz send settles app activity before the backend checkpoint. Let
 // that checkpoint complete, just as it does while the app stays open.
 const first = await checkpoint();
 if(live){
   const follow = {...event, id:"3".repeat(64), created_at:2,
     tags:[...event.tags,["e",event.id,"","reply"]],
     content:"Reply here using only Buzz's send tool with exactly PLUGIN_SECOND_READY. Do not use shell commands or other tools and do not add a free-text response afterward."};
   events.push(follow);
   working = undefined;
   await type.run({trigger:{type:"mention",event:follow},channelId:channel,agent,config:type.defaults().config,
     signal:new AbortController().signal,current:()=>true,workingUntil:p=>{working=p;}});
   assert.ok(working,"Follow-up was not accepted");
   const second = await working;
   assert.equal(second.ok,true,JSON.stringify(second));
   assert.equal(published.length,2,JSON.stringify(published));
   assert.equal(published[1].content,"PLUGIN_SECOND_READY");
   const records = await checkpoint();
   assert.equal(records.length,1,"Follow-up must reuse the thread's ACP session");
   assert.equal(records[0].conversation,first[0].conversation);
   assert.equal(records[0].history.length,2);
 }
 console.log("PASS: distributed plugin registration, native process launch, ACP session, agent-scoped Buzz reply"+(live?", two real AGY/HTTP MCP turns with conversation continuity":""));
}finally{
 clean?.();await new Promise(r=>setTimeout(r,100));for(const c of children)c.kill();for(const s of servers)s.closeAllConnections?.();for(const s of servers)s.close();
 await rm(temp,{recursive:true,force:true});
}
